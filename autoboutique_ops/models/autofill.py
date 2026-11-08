"""Type each fact once: names, products and links fill themselves from the records already tagged.

Forms fill in as soon as the source is picked (onchange), and records created without a
name get one on save, so nobody retypes a car's year, make, model, plate or customer.
"""
from odoo import api, fields, models


def _join(*parts):
    return " ".join(str(part) for part in parts if part)


def vehicle_product(env, company, year, make, model):
    """One serial-tracked, storable product per year/make/model; each car is a serial named after its plate."""
    name = _join(year, make, model).strip()
    Product = env["product.product"].with_company(company)
    product = Product.search([
        ("name", "=", name), ("tracking", "=", "serial"),
        ("company_id", "in", [company.id, False]),
    ], limit=1)
    return product or Product.sudo().create({
        "name": name, "type": "consu", "is_storable": True, "tracking": "serial",
        "company_id": company.id, "purchase_ok": True, "sale_ok": True,
        "invoice_policy": "order",
    }).sudo(False)


class BidLine(models.Model):
    _inherit = "autoboutique.bid.line"

    name = fields.Char("Description", required=False,
                       help="Filled from Year, Make and Model; change it only to add details.")

    def _ab_auto_name(self, vals):
        return _join(vals.get("model_year"), vals.get("make"), vals.get("model"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name"):
                vals["name"] = self._ab_auto_name(vals) or "Car"
        return super().create(vals_list)

    @api.onchange("model_year", "make", "model")
    def _onchange_ab_name(self):
        for line in self:
            line.name = _join(line.model_year, line.make, line.model) or line.name

    def _ab_vehicle_product(self):
        return vehicle_product(self.env, self.company_id, self.model_year, self.make, self.model)


class Receiving(models.Model):
    _inherit = "autoboutique.receiving"

    name = fields.Char(required=False)
    plate_number = fields.Char(related="bid_line_id.plate_number", readonly=False,
                               help="Enter it here or on the receipt's serial number; either one is enough.")

    @api.model_create_multi
    def create(self, vals_list):
        lines = self.env["autoboutique.bid.line"]
        for vals in vals_list:
            if not vals.get("name") and vals.get("bid_line_id"):
                vals["name"] = "Receipt - %s" % lines.browse(vals["bid_line_id"]).name
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if "plate_number" in vals:
            # The plate was the only thing missing: finish what receiving the car started.
            for receiving in self.filtered(lambda r: r.state in ("received", "verified") and not r.vehicle_id
                                           and r.receipt_id.state == "done" and r.plate_number):
                receiving._ab_done("Enter plate number and create Vehicle Master")
                receiving.action_create_vehicle_master()
                receiving.vehicle_id._ab_start_initial_qc()
        return result


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    name = fields.Char(required=False, help="Filled from Make, Model and Plate.")

    @api.model_create_multi
    def create(self, vals_list):
        companies = self.env["res.company"]
        for vals in vals_list:
            if not vals.get("name"):
                vals["name"] = _join(vals.get("make"), vals.get("model"), vals.get("plate_number") or vals.get("vin")) or "Car"
            if not vals.get("product_id") and vals.get("make") and vals.get("model"):
                company = companies.browse(vals.get("company_id")) or self.env.company
                vals["product_id"] = vehicle_product(
                    self.env, company, vals.get("model_year"), vals["make"], vals["model"]).id
        return super().create(vals_list)

    @api.onchange("make", "model", "plate_number")
    def _onchange_ab_name(self):
        for vehicle in self:
            vehicle.name = _join(vehicle.make, vehicle.model, vehicle.plate_number or vehicle.vin) or vehicle.name


class SalesApplication(models.Model):
    _inherit = "autoboutique.sales.application"

    name = fields.Char(required=False)

    @api.model_create_multi
    def create(self, vals_list):
        partners, vehicles = self.env["res.partner"], self.env["autoboutique.vehicle"]
        for vals in vals_list:
            vehicle = vehicles.browse(vals.get("vehicle_id"))
            if not vals.get("selling_price") and vehicle:
                vals["selling_price"] = vehicle.selling_price
            if not vals.get("name"):
                vals["name"] = " - ".join(filter(None, [partners.browse(vals.get("customer_id")).name, vehicle.name])) or "Application"
        return super().create(vals_list)

    @api.onchange("vehicle_id")
    def _onchange_ab_price(self):
        for application in self:
            if application.vehicle_id and not application.selling_price:
                application.selling_price = application.vehicle_id.selling_price


class VehicleRelease(models.Model):
    _inherit = "autoboutique.vehicle.release"

    @api.onchange("sales_application_id")
    def _onchange_ab_application(self):
        for release in self.filtered("sales_application_id"):
            application = release.sales_application_id
            release.vehicle_id = application.vehicle_id
            release.customer_id = application.customer_id
            release.sale_order_id = application.sale_order_id or application.vehicle_id.sale_order_id
            release.invoice_id = application.vehicle_id.invoice_id or release.sale_order_id.invoice_ids[:1]


def _paper_create(model, vals_list, label):
    """Registration, insurance and document records: the vehicle brings its customer and name."""
    vehicles = model.env["autoboutique.vehicle"]
    for vals in vals_list:
        vehicle = vehicles.browse(vals.get("vehicle_id"))
        if vehicle and not vals.get("customer_id") and vehicle.customer_id:
            vals["customer_id"] = vehicle.customer_id.id
        if not vals.get("name"):
            vals["name"] = " - ".join(filter(None, [vals.get("document_type") or label, vehicle.name]))
    return vals_list


def _paper_onchange(records):
    for record in records.filtered(lambda r: r.vehicle_id and not r.customer_id):
        record.customer_id = record.vehicle_id.customer_id


class Registration(models.Model):
    _inherit = "autoboutique.registration"

    name = fields.Char(required=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_paper_create(self, vals_list, "Registration"))

    @api.onchange("vehicle_id")
    def _onchange_ab_vehicle(self):
        _paper_onchange(self)
        for record in self.filtered(lambda r: r.vehicle_id and not r.plate_number):
            record.plate_number = record.vehicle_id.plate_number


class Insurance(models.Model):
    _inherit = "autoboutique.insurance"

    name = fields.Char(required=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_paper_create(self, vals_list, "Insurance"))

    @api.onchange("vehicle_id")
    def _onchange_ab_vehicle(self):
        _paper_onchange(self)


class VehicleDocument(models.Model):
    _inherit = "autoboutique.document"

    name = fields.Char(required=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_paper_create(self, vals_list, "Document"))

    @api.onchange("vehicle_id")
    def _onchange_ab_vehicle(self):
        _paper_onchange(self)

class Commission(models.Model):
    _inherit = "autoboutique.commission"

    @api.onchange("vehicle_id")
    def _onchange_ab_vehicle(self):
        for commission in self.filtered("vehicle_id"):
            vehicle = commission.vehicle_id
            commission.selling_price = commission.selling_price or vehicle.selling_price
            commission.sale_order_id = commission.sale_order_id or vehicle.sale_order_id
            commission.invoice_id = commission.invoice_id or vehicle.invoice_id
            commission.sales_agent_id = commission.sales_agent_id or vehicle.sales_agent_id
