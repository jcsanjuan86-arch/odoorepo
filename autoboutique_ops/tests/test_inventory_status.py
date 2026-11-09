from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInventoryStatus(TransactionCase):
    """The CAR INVENTORY sheet, built live from the Vehicle Master."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.bank = cls.env["res.partner"].create({"name": "BDO Test Bank"})
        Vehicle = cls.env["autoboutique.vehicle"]
        cls.creta = Vehicle.create({
            "make": "Hyundai", "model": "Creta", "model_year": 2023, "color": "White", "plate_number": "INV152",
            "state": "ready", "selling_price": 758000, "downpayment": 158000, "stock_owner": "bdo",
            "location": "ab_showroom", "marketing_status": "done", "supplier_id": cls.bank.id,
            "bidder": "Test Bidder", "papers": "with", "company_id": cls.company.id,
        })
        cls.vios = Vehicle.create({
            "make": "Toyota", "model": "Vios", "model_year": 2024, "plate_number": "INV321",
            "state": "repair", "selling_price": 628000, "downpayment": 28000, "company_id": cls.company.id,
        })

    def test_amortization_matches_the_sheet(self):
        # ((758000 - 158000) * rate + (758000 - 158000)) / months
        self.assertAlmostEqual(self.creta.amortization_3y, 24078.33, places=2)
        self.assertAlmostEqual(self.creta.amortization_4y, 19966.25, places=2)
        self.assertAlmostEqual(self.creta.amortization_5y, 17699.00, places=2)
        self.assertEqual(self.creta.bank_from, "BDO Test Bank", "Filled from the supplier")

    def test_report_groups_units_by_brand_and_model(self):
        report = self.env["autoboutique.vehicle"].get_report("inventory")
        tables = {table["title"]: table for table in report["tables"]}
        owners = {row["cells"][0]: row["cells"][1] for row in tables["Inventory Of"]["rows"]}
        self.assertGreaterEqual(owners["BDO"], 1)
        self.assertGreaterEqual(owners["AUTO BOUTIQUE"], 1)

        units = tables["Units"]
        self.assertEqual(len(units["headers"]), 26)
        rows = [row["cells"] for row in units["rows"]]
        creta = next(cells for cells in rows if cells[2] == "INV152")
        self.assertEqual(creta[:6], ["BDO", "2023 HYUNDAI CRETA WHITE", "INV152", "AB SHOWROOM", "DONE", "N/A"])
        self.assertEqual(creta[15:18], ["BDO Test Bank", "Test Bidder", ""])
        self.assertEqual(creta[18], "READY")
        self.assertEqual(creta[21], "WITH PAPERS")
        sections = [row["cells"][1] for row in units["rows"] if row["kind"] == "section"]
        self.assertIn("HYUNDAI", sections)
        self.assertIn("TOYOTA", sections)
        vios = next(cells for cells in rows if cells[2] == "INV321")
        self.assertEqual(vios[18], "REPAIR", "Not ready: shows where the car is")

    def test_bid_bank_becomes_bank_from(self):
        auction = self.env["res.partner"].create({"name": "Test Auction House"})
        bid = self.env["autoboutique.bid"].create({
            "name": "BANK-LOT", "supplier_id": auction.id, "bank_id": self.bank.id, "company_id": self.company.id,
            "line_ids": [(0, 0, {"plate_number": "BNK1234", "make": "Toyota", "model": "Wigo", "model_year": 2022,
                                 "allocated_cost": 300000, "selected": True, "company_id": self.company.id})],
        })
        bid.action_approve_bid()
        receiving = self.env["autoboutique.receiving"].search([("bid_line_id", "=", bid.line_ids.id)])
        receiving.action_mark_received()
        self.assertEqual(receiving.vehicle_id.bank_from, "BDO Test Bank", "The lot's bank, not the auction house")

    def test_financing_shows_on_the_vehicle(self):
        bank = self.env["autoboutique.financing.bank"].create({"name": "Zz Inventory Bank"})
        Account = self.env["autoboutique.financing.account"]
        Account.create({"name": "Lost Buyer", "vehicle_id": self.creta.id, "bank_id": bank.id, "status": "decline"})
        self.assertFalse(self.creta.financing_bank, "A declined account is not the car's financing")
        Account.create({"name": "Buyer", "vehicle_id": self.creta.id, "bank_id": bank.id,
                        "status": "for_approval", "amount_approved": 500000})
        self.creta.invalidate_recordset(["financing_bank", "financing_status", "financing_amount"])
        self.assertEqual(self.creta.financing_bank, "Zz Inventory Bank")
        self.assertEqual(self.creta.financing_status, "for_approval")
        self.assertEqual(self.creta.financing_amount, 500000)
        self.assertEqual(self.creta._ab_status_row()[14], "Zz Inventory Bank", "FINANCING PARTNER column")
