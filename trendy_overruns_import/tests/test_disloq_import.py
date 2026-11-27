import base64

from odoo.tests.common import TransactionCase, tagged

from ..wizard.disloq_import import attribute_name, parse_products, ph_phone

HEADER = ('"Inventory Type (R)","Category Name (R)","Available on POS (Y/N)","SKU (O)","Item Name (R)",'
          '"Item Cost (R)","Retail Price (R)","Stock in hand (O)","Variant Name (O)","Variant Options (O)","Variant SKU (O)"\n')

PRODUCTS = HEADER + (
    '"Goods","WOMEN DENIM PANTS","Y","TO-SKU-001","!AE WOMEN BAGGY DENIM","0","699","27","SIZE;COLOR","000;LIGHT DENIM","TO-SKU-001-1"\n'
    '"Goods","WOMEN DENIM PANTS","Y","TO-SKU-001","!AE WOMEN BAGGY DENIM","0","699","27","COLOR ;SZE","light denim;2","TO-SKU-001-2"\n'
    '"Goods","MEN TSHIRT","Y","TO-SKU-002","MEN NIKE DRIFIT TEE","150","399","-4","SIZE","L","TO-SKU-002-1"\n'
    '"Goods","MEN TSHIRT","Y","TO-SKU-003","PLAIN TEE","0","199","5","","",""\n'
)

CUSTOMERS = (
    '﻿"Customer","Customer Code","Social Name","Location","Contact","Transactions Count","Total Spent","Points Balance"\n'
    '"Franco rivera ","","","OVERRUNS BOUTIQUE KATIPUNAN, OVERRUNS BOUTIQUE FAIRVIEW"," / 639171098980","0","₱0.00","0"\n'
    '"Franco rivera","","","OVERRUNS BOUTIQUE KATIPUNAN"," / 639171098980","0","₱0.00","0"\n'
    '"Lara","","","OVERRUNS BOUTIQUE LILAC"," / 639171394831","2","₱1,398.00","25"\n'
    '"","","","OVERRUNS BOUTIQUE LILAC"," / 639170000000","0","₱0.00","0"\n'
)


@tagged("post_install", "-at_install")
class TestDisloqImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.env.company.id)], limit=1)

    def run_import(self, content, **vals):
        wizard = self.env["trendy.overruns.disloq.import"].create(dict(
            vals, data_file=base64.b64encode(content.encode()), filename="goods.csv"))
        wizard.action_import()
        return wizard.result

    def on_hand(self, template):
        return sum(self.env["stock.quant"].search([
            ("product_id", "=", template.product_variant_id.id),
            ("location_id", "=", self.warehouse.lot_stock_id.id),
        ]).mapped("quantity"))

    def test_helpers(self):
        self.assertEqual(attribute_name("SZE"), "SIZE")
        self.assertEqual(attribute_name("COLOR`"), "COLOR")
        self.assertEqual(attribute_name("DESIGN"), "DESIGN")
        self.assertIsNone(attribute_name(" "))
        self.assertEqual(ph_phone("639171098980"), "+63 917 109 8980")
        self.assertEqual(ph_phone("09171098980"), "+63 917 109 8980")
        self.assertEqual(ph_phone("7720-5279"), "7720-5279")
        items = parse_products([
            {"SKU (O)": "A", "Item Name (R)": "X", "Variant Name (O)": "SIZE;COLOR", "Variant Options (O)": "S;red"},
            {"SKU (O)": "A", "Item Name (R)": "X", "Variant Name (O)": "COLRO;SIZE", "Variant Options (O)": "RED;M"},
        ])
        self.assertEqual(items["A"]["attributes"], {"SIZE": ["S", "M"], "COLOR": ["RED"]})

    def test_products_and_stock(self):
        result = self.run_import(PRODUCTS, import_type="products", warehouse_id=self.warehouse.id)
        Template = self.env["product.template"]
        denim = Template.search([("default_code", "=", "TO-SKU-001")])
        self.assertEqual(len(denim), 1)
        self.assertEqual(denim.barcode, "TO-SKU-001")
        self.assertEqual(denim.list_price, 699)
        self.assertTrue(denim.available_in_pos and denim.is_storable)
        self.assertFalse(denim.taxes_id, "Disloq prices have no tax added")
        self.assertEqual(denim.categ_id.name, "WOMEN DENIM PANTS")
        self.assertEqual(denim.pos_categ_ids.name, "WOMEN DENIM PANTS")
        self.assertEqual(len(denim.product_variant_ids), 1, "Sizes and colours are picked at the POS, not variants")
        sizes = denim.attribute_line_ids.filtered(lambda l: l.attribute_id.name == "SIZE")
        self.assertEqual(sorted(sizes.value_ids.mapped("name")), ["000", "2"])
        self.assertEqual(sizes.attribute_id.create_variant, "no_variant")
        colors = denim.attribute_line_ids.filtered(lambda l: l.attribute_id.name == "COLOR")
        self.assertEqual(colors.value_ids.mapped("name"), ["LIGHT DENIM"])
        self.assertEqual(self.on_hand(denim), 27)

        tee = Template.search([("default_code", "=", "TO-SKU-002")])
        self.assertEqual(tee.standard_price, 150)
        self.assertEqual(self.on_hand(tee), 0, "Negative Disloq stock becomes 0")
        self.assertIn("MEN NIKE DRIFIT TEE (TO-SKU-002): -4", result)
        plain = Template.search([("default_code", "=", "TO-SKU-003")])
        self.assertFalse(plain.attribute_line_ids)
        self.assertEqual(self.on_hand(plain), 5)

        # Importing again (with a recount) updates instead of duplicating.
        self.run_import(PRODUCTS.replace('"5","",', '"8","",'), import_type="products", warehouse_id=self.warehouse.id)
        self.assertEqual(Template.search_count([("default_code", "in", ["TO-SKU-001", "TO-SKU-002", "TO-SKU-003"])]), 3)
        self.assertEqual(self.on_hand(plain), 8)
        self.assertEqual(self.on_hand(denim), 27)

    def test_customers(self):
        result = self.run_import(CUSTOMERS, import_type="customers", company_id=self.env.company.id)
        Partner = self.env["res.partner"]
        franco = Partner.search([("name", "=", "Franco rivera")])
        self.assertEqual(len(franco), 1, "Same name and phone is one customer")
        self.assertEqual(franco.phone, "+63 917 109 8980")
        self.assertEqual(franco.company_id, self.env.company)
        self.assertIn("Overruns Boutique Fairview", franco.comment)
        lara = Partner.search([("name", "=", "Lara"), ("phone", "=", "+63 917 139 4831")])
        self.assertIn("points balance: 25", lara.comment)
        self.assertIn("Customers with a points balance: 1", result)
        self.run_import(CUSTOMERS, import_type="customers", company_id=self.env.company.id)
        self.assertEqual(Partner.search_count([("name", "in", ["Franco rivera", "Lara"])]), 2)
