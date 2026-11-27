"""Load the product and customer exports of the Disloq POS into Odoo.

Disloq keeps one stock count per product, with sizes and colours only picked at
the counter.  Odoo mirrors that: one product per Disloq SKU (barcode = SKU) with
the branch's stock, and SIZE / COLOR / DESIGN as "never create variants"
attributes that the cashier picks in the POS.

Every import can be run again: products are matched on their SKU and customers
on name + phone, so a second run updates instead of duplicating.
"""

import base64
import csv
import io
import re
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError

ROOT_CATEGORY = "Trendy Overruns"

# Disloq attribute names are typed by hand per product ("SZE", "COLRO", ...).
ATTRIBUTE_ALIASES = {
    "SIZE": {"SIZE", "SZE", "SUZE", "SIZIE", "SIZ", "S"},
    "COLOR": {"COLOR", "COLOUR", "COOR", "COLRO", "COLO", "COLOE", "COLR", "CLOR"},
}


def attribute_name(raw):
    letters = re.sub(r"[^A-Z]", "", (raw or "").upper())
    if not letters:
        return None
    for name, aliases in ATTRIBUTE_ALIASES.items():
        if letters in aliases:
            return name
    return letters


def clean(value):
    return " ".join((value or "").split())


def to_float(value):
    value = (value or "").replace(",", "").replace("₱", "").strip()
    try:
        return float(value)
    except ValueError:
        return 0.0


def digits(value):
    return re.sub(r"\D", "", value or "")


def ph_phone(raw):
    """639171098980 / 09171098980 -> +63 917 109 8980; anything else is kept as typed."""
    number = digits(raw)
    if number.startswith("63") and len(number) == 12:
        number = number[2:]
    elif number.startswith("0") and len(number) == 11:
        number = number[1:]
    if number.startswith("9") and len(number) == 10:
        return "+63 %s %s %s" % (number[:3], number[3:6], number[6:])
    return clean(raw)


def read_rows(data, filename=""):
    """Rows of the Disloq CSV, or of the goods/customers CSV inside a Disloq zip."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise UserError(_("The zip file %s has no CSV file inside.", filename))
            names.sort(key=lambda n: (not n.lower().endswith("goods.csv"), n))
            data = archive.read(names[0])
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def column(row, *names):
    for name in names:
        if name in row:
            return row[name] or ""
    return ""


def parse_products(rows):
    """{sku: {name, category, price, cost, stock, pos, attributes: {SIZE: [..], ..}}}"""
    items = {}
    for row in rows:
        sku = clean(column(row, "SKU (O)", "SKU (R)"))
        name = clean(column(row, "Item Name (R)"))
        if not sku or not name:
            continue
        item = items.setdefault(sku, {
            "name": name,
            "category": clean(column(row, "Category Name (R)")) or "Uncategorized",
            "price": 0.0,
            "cost": 0.0,
            "stock": to_float(column(row, "Stock in hand (O)")),
            "pos": column(row, "Available on POS (Y/N)").strip().upper() == "Y",
            "attributes": {},
        })
        item["price"] = item["price"] or to_float(column(row, "Retail Price (R)"))
        item["cost"] = item["cost"] or to_float(column(row, "Item Cost (R)")) or to_float(column(row, "Purchase Cost"))
        names = column(row, "Variant Name (O)").split(";")
        options = column(row, "Variant Options (O)").split(";")
        for raw_name, raw_value in zip(names, options):
            attribute, value = attribute_name(raw_name), clean(raw_value).upper()
            if attribute and value:
                values = item["attributes"].setdefault(attribute, [])
                if value not in values:
                    values.append(value)
    return items


class DisloqImport(models.TransientModel):
    _name = "trendy.overruns.disloq.import"
    _description = "Import from Disloq"

    import_type = fields.Selection(
        [("products", "Products and branch stock"), ("customers", "Customers")],
        required=True, default="products")
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Branch / Warehouse",
        help="The stock in the file is set as this branch's on-hand quantity.")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    data_file = fields.Binary(string="Disloq export (.zip or .csv)", required=True)
    filename = fields.Char()
    result = fields.Text(readonly=True)

    def action_import(self):
        self.ensure_one()
        rows = read_rows(base64.b64decode(self.data_file), self.filename or "")
        if self.import_type == "products":
            if not self.warehouse_id:
                raise UserError(_("Choose the branch / warehouse the stock belongs to."))
            self.result = self._import_products(rows)
        else:
            self.result = self._import_customers(rows)
        self.data_file = False
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------ products

    def _categories(self, names):
        Category = self.env["product.category"]
        root = Category.search([("name", "=", ROOT_CATEGORY), ("parent_id", "=", False)], limit=1) \
            or Category.create({"name": ROOT_CATEGORY})
        product_categories = {c.name: c.id for c in Category.search([("parent_id", "=", root.id)])}
        PosCategory = self.env["pos.category"]
        pos_categories = {c.name: c.id for c in PosCategory.search([])}
        for name in sorted(names):
            if name not in product_categories:
                product_categories[name] = Category.create({"name": name, "parent_id": root.id}).id
            if name not in pos_categories:
                pos_categories[name] = PosCategory.create({"name": name}).id
        return product_categories, pos_categories

    def _attribute_values(self, items):
        """{attribute name: (attribute, {value name: value id})}, creating what is missing."""
        Attribute = self.env["product.attribute"]
        wanted = {}
        for item in items.values():
            for attribute, values in item["attributes"].items():
                wanted.setdefault(attribute, set()).update(values)
        result = {}
        for name, values in wanted.items():
            attribute = Attribute.search([("name", "=", name), ("create_variant", "=", "no_variant")], limit=1) \
                or Attribute.create({"name": name, "create_variant": "no_variant", "display_type": "pills"})
            known = {v.name.upper(): v.id for v in attribute.value_ids}
            missing = sorted(values - set(known))
            if missing:
                created = self.env["product.attribute.value"].create(
                    [{"attribute_id": attribute.id, "name": value} for value in missing])
                known.update({v.name.upper(): v.id for v in created})
            result[name] = (attribute, known)
        return result

    def _import_products(self, rows):
        company = self.warehouse_id.company_id
        items = parse_products(rows)
        if not items:
            raise UserError(_("No products found. Upload the Disloq products export (goods.csv or its zip)."))

        product_categories, pos_categories = self._categories({i["category"] for i in items.values()})
        attributes = self._attribute_values(items)
        Template = self.env["product.template"].with_company(company).with_context(active_test=False)
        existing = {
            t.default_code: t
            for t in Template.search([("default_code", "in", list(items)), ("company_id", "in", [company.id, False])])
        }
        taken_barcodes = set(
            self.env["product.product"].with_context(active_test=False)
            .search([("barcode", "in", list(items))]).mapped("barcode"))

        created_count = updated = barcode_skipped = 0
        to_create = []
        for sku, item in items.items():
            lines = [
                (attributes[name][0], [attributes[name][1][v] for v in values])
                for name, values in item["attributes"].items()
            ]
            template = existing.get(sku)
            if template:
                vals = {}
                if not template.list_price and item["price"]:
                    vals["list_price"] = item["price"]
                if not template.standard_price and item["cost"]:
                    vals["standard_price"] = item["cost"]
                line_commands = []
                for attribute, value_ids in lines:
                    line = template.attribute_line_ids.filtered(lambda l, a=attribute: l.attribute_id == a)
                    if line:
                        new_ids = set(value_ids) - set(line.value_ids.ids)
                        if new_ids:
                            line_commands.append((1, line.id, {"value_ids": [(4, v) for v in new_ids]}))
                    else:
                        line_commands.append((0, 0, {"attribute_id": attribute.id, "value_ids": [(6, 0, value_ids)]}))
                if line_commands:
                    vals["attribute_line_ids"] = line_commands
                if vals:
                    template.write(vals)
                    updated += 1
                continue
            barcode = sku if sku not in taken_barcodes else False
            barcode_skipped += not barcode
            vals = {
                "name": item["name"],
                "default_code": sku,
                "barcode": barcode,
                "type": "consu",
                "is_storable": True,
                "available_in_pos": item["pos"],
                "list_price": item["price"],
                "categ_id": product_categories[item["category"]],
                "pos_categ_ids": [(6, 0, [pos_categories[item["category"]]])],
                "company_id": company.id,
                # Disloq sells at the tag price with no tax added.
                "taxes_id": [(6, 0, [])],
                "supplier_taxes_id": [(6, 0, [])],
                "attribute_line_ids": [
                    (0, 0, {"attribute_id": attribute.id, "value_ids": [(6, 0, value_ids)]})
                    for attribute, value_ids in lines
                ],
            }
            if item["cost"]:
                vals["standard_price"] = item["cost"]
            to_create.append(vals)

        for start in range(0, len(to_create), 200):
            batch = Template.create(to_create[start:start + 200])
            created_count += len(batch)
            existing.update({t.default_code: t for t in batch})

        stock_set, units, negatives = self._set_stock(items, existing)

        report = [
            _("%(branch)s: %(count)s products in the file.", branch=self.warehouse_id.name, count=len(items)),
            _("Created %(created)s new products, updated %(updated)s existing ones.", created=created_count, updated=updated),
            _("On-hand stock set for %(count)s products, %(units)s pcs in total.", count=stock_set, units=f"{units:,.0f}"),
        ]
        if negatives:
            report.append(_("%(count)s products had negative stock in Disloq and were set to 0:", count=len(negatives)))
            report += ["  • %s (%s): %s" % n for n in negatives[:30]]
            if len(negatives) > 30:
                report.append(_("  … and %s more.", len(negatives) - 30))
        if barcode_skipped:
            report.append(_("%s products got no barcode because another product already uses that SKU.", barcode_skipped))
        return "\n".join(report)

    def _set_stock(self, items, templates):
        location = self.warehouse_id.lot_stock_id
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        products = {sku: templates[sku].product_variant_id for sku in items if sku in templates}
        quants = {}
        for quant in Quant.search([
            ("location_id", "=", location.id),
            ("product_id", "in", [p.id for p in products.values()]),
            ("lot_id", "=", False), ("package_id", "=", False), ("owner_id", "=", False),
        ]):
            quants.setdefault(quant.product_id.id, quant)

        negatives, to_create = [], []
        to_apply = Quant.browse()
        units = 0.0
        for sku, item in items.items():
            product = products.get(sku)
            if not product:
                continue
            target = item["stock"]
            if target < 0:
                negatives.append((item["name"], sku, f"{target:g}"))
                target = 0.0
            units += target
            quant = quants.get(product.id)
            if quant:
                if quant.quantity != target:
                    quant.write({"inventory_quantity": target})
                    to_apply |= quant
            elif target:
                to_create.append({"product_id": product.id, "location_id": location.id, "inventory_quantity": target})
        for start in range(0, len(to_create), 500):
            to_apply |= Quant.create(to_create[start:start + 500])
        if to_apply:
            to_apply.action_apply_inventory()
        return len(products), units, negatives

    # ----------------------------------------------------------------- customers

    def _import_customers(self, rows):
        company = self.company_id
        Partner = self.env["res.partner"].with_context(active_test=False)
        known = {
            (clean(p.name).lower(), digits(p.phone)[-10:])
            for p in Partner.search([("company_id", "in", [company.id, False]), ("customer_rank", ">", 0)])
        }
        to_create, skipped, with_points = [], 0, []
        for row in rows:
            name = clean(column(row, "Customer"))
            if not name:
                skipped += 1
                continue
            left, _sep, right = column(row, "Contact").rpartition("/")
            phone = ph_phone(right)
            key = (name.lower(), digits(phone)[-10:])
            if key in known:
                skipped += 1
                continue
            known.add(key)
            points = to_float(column(row, "Points Balance"))
            branches = ", ".join(clean(b).title() for b in column(row, "Location").split(",") if clean(b))
            notes = [_("Imported from Disloq. Branches: %s", branches or "-")]
            if points:
                with_points.append((name, points))
                notes.append(_("Disloq points balance: %s", f"{points:g}"))
            vals = {
                "name": name,
                "phone": phone or False,
                "company_id": company.id,
                "customer_rank": 1,
                "comment": "<br/>".join(notes),
            }
            if "@" in left:
                vals["email"] = clean(left)
            to_create.append(vals)
        for start in range(0, len(to_create), 500):
            Partner.create(to_create[start:start + 500])

        report = [
            _("%(count)s customers in the file.", count=len(rows)),
            _("Created %(created)s customers for %(company)s; %(skipped)s were already in Odoo, repeated, or had no name.",
              created=len(to_create), company=company.name, skipped=skipped),
            _("Customers with a points balance: %s.", len(with_points)),
        ]
        report += ["  • %s: %g" % p for p in with_points[:30]]
        if len(rows) == 10000:
            report.append(_("The file has exactly 10,000 rows, which is usually Disloq's export limit; "
                            "export the remaining customers and import them too."))
        return "\n".join(report)
