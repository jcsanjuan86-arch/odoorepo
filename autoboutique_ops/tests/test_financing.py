from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.autoboutique_ops.models import extended
from odoo.addons.autoboutique_ops.models.financing import UNIT_GROUPS, officer_bonus, unit_group


@tagged("post_install", "-at_install")
class TestFinancing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["autoboutique.financing.account"]
        cls.bank = cls.env["autoboutique.financing.bank"].create({"name": "Zz Bank", "sequence": 1})
        cls.cash = cls.env.ref("autoboutique_ops.financing_bank_cash")
        cls.partner = cls.env["autoboutique.financing.partner"].create({"name": "Zz Partner", "source": "referral"})
        cls.officer = cls.env["autoboutique.financing.officer"].create({"name": "Zz Officer"})
        cls.customer = cls.env["res.partner"].create({"name": "Zz Borrower"})
        cls.today = fields.Date.context_today(cls.Account)

    def _vehicle(self, state="ready", plate="ZZZ 1001"):
        vehicle = self.env["autoboutique.vehicle"].with_context(ab_automating=True).create({
            "name": "Zz Vios", "make": "Toyota", "model": "Vios", "variant": "XLE", "model_year": 2025,
            "plate_number": plate, "selling_price": 700000, "company_id": self.env.company.id,
            "documents_verified": True, "ready_for_sale_approved": True,
        })
        self.env["autoboutique.qc"].create({
            "name": "Final QC", "vehicle_id": vehicle.id, "inspection_type": "final", "result": "pass",
        })
        self.env["autoboutique.detailing"].create({
            "name": "Detailing", "vehicle_id": vehicle.id, "state": "approved",
            "exterior_done": True, "interior_done": True, "supervisor_id": self.env.user.id,
        })
        self.env.cr.execute("UPDATE autoboutique_vehicle SET state = %s WHERE id = %s", (state, vehicle.id))
        vehicle.invalidate_recordset(["state"])
        return vehicle

    def _account(self, **values):
        return self.Account.create({"name": "Zz Borrower", "partner_id": self.partner.id, **values})

    def _table(self, report, title):
        return next(table for table in report["tables"] if table["title"] == title)

    def _value(self, table, label, column=1):
        return next(row["cells"][column] for row in table["rows"] if row["cells"][0] == label)

    def test_unit_comes_from_the_vehicle(self):
        vehicle = self._vehicle()
        account = self._account(vehicle_id=vehicle.id)
        self.assertEqual(account.unit, "VIOS XLE 2025")
        self.assertEqual(account.plate_number, "ZZZ 1001")
        self.assertEqual(self._account(unit="L300 2023").unit, "L300 2023", "A unit can be typed before the car is known")

    def test_vehicle_found_by_plate(self):
        vehicle = self._vehicle(plate="ZZP 2002")
        found = self.env["autoboutique.vehicle"].name_search("ZZP 2002")
        self.assertIn(vehicle.id, [row[0] for row in found])

    def test_plate_is_unique(self):
        self._vehicle(plate="ZZU 3003")
        with self.assertRaises(ValidationError):
            self._vehicle(plate="ZZU 3003")

    def test_bank_approval_reserves_the_car(self):
        vehicle = self._vehicle()
        account = self._account(vehicle_id=vehicle.id, customer_id=self.customer.id)
        submission = self.env["autoboutique.financing.submission"].create({
            "account_id": account.id, "bank_id": self.bank.id, "officer_id": self.officer.id,
            "date_submitted": self.today - relativedelta(days=3),
        })
        self.assertEqual(submission.aging, 3)
        submission.write({"result": "approved", "amount_approved": 550000})
        self.assertEqual(account.status, "approved")
        self.assertEqual(account.bank_id, self.bank)
        self.assertEqual(account.amount_approved, 550000)
        self.assertEqual(account.sales_application_id.state, "reserved")
        self.assertEqual(vehicle.state, "reserved")
        self.assertEqual(vehicle.customer_id, self.customer)

    def test_every_bank_declining_declines_the_account(self):
        account = self._account()
        Submission = self.env["autoboutique.financing.submission"]
        first = Submission.create({"account_id": account.id, "bank_id": self.bank.id})
        second = Submission.create({"account_id": account.id, "bank_id": self.cash.id})
        first.result = "declined"
        self.assertEqual(account.status, "for_approval", "Another bank is still pending")
        second.result = "declined"
        self.assertEqual(account.status, "decline")

    def test_lost_account_frees_the_car(self):
        vehicle = self._vehicle()
        account = self._account(vehicle_id=vehicle.id, customer_id=self.customer.id, status="approved")
        self.assertEqual(vehicle.state, "reserved")
        account.status = "cancelled_approved"
        self.assertEqual(vehicle.state, "ready")
        self.assertFalse(vehicle.customer_id)
        self.assertEqual(account.sales_application_id.state, "cancelled")

    def test_application_decision_reaches_the_account(self):
        vehicle = self._vehicle()
        application = self.env["autoboutique.sales.application"].create({
            "name": "Zz App", "vehicle_id": vehicle.id, "customer_id": self.customer.id, "selling_price": 700000,
        })
        application._ab_ensure_financing_account()
        application._ab_ensure_financing_account()
        account = application.financing_account_ids
        self.assertEqual(len(account), 1, "One account per application")
        self.assertEqual(account.name, "Zz Borrower")
        application.state = "rejected"
        self.assertEqual(account.status, "decline")

    def test_application_made_in_odoo_reaches_the_tracker(self):
        vehicle = self._vehicle()
        application = self.env["autoboutique.sales.application"].create({
            "name": "Zz Direct", "vehicle_id": vehicle.id, "customer_id": self.customer.id, "selling_price": 700000,
        })
        self.assertEqual(len(application.financing_account_ids), 1)
        self.assertEqual(application.financing_account_ids.status, "for_approval")

    def test_reservation_from_the_tracker_keeps_one_account(self):
        vehicle = self._vehicle()
        account = self._account(vehicle_id=vehicle.id, customer_id=self.customer.id, status="approved")
        self.assertEqual(account.sales_application_id.financing_account_ids, account)

    def test_release_without_details_is_flagged_until_filled(self):
        summary = "Complete the released account"
        account = self._account(status="for_release")
        account.status = "released"
        self.assertIn(summary, account.activity_ids.mapped("summary"))
        account.bank_id = self.bank
        self.assertIn(summary, account.activity_ids.mapped("summary"), "The amount is still missing")
        account.amount_approved = 500000
        self.assertNotIn(summary, account.activity_ids.mapped("summary"))

    def test_complete_release_is_not_flagged(self):
        account = self._account(status="for_release", bank_id=self.bank.id, amount_approved=500000)
        account.status = "released"
        self.assertFalse(account.activity_ids.filtered(lambda a: a.summary == "Complete the released account"))

    def test_prices_of_the_brand_new_tab_are_loaded(self):
        self.assertEqual(self.env.ref("autoboutique_ops.financing_evaluation_1").brand_new_price, 908000)
        self.assertEqual(self.env.ref("autoboutique_ops.financing_evaluation_26").unit, "Hiace")
        self.assertEqual(self.env.ref("autoboutique_ops.financing_evaluation_3").unit, "Raize",
                         "A blank unit cell repeats the row above")
        self.assertEqual(self.env.ref("autoboutique_ops.financing_quote_8").monthly_amortization, 38826)

    def test_vehicle_release_marks_the_account_released(self):
        vehicle = self._vehicle()
        application = self.env["autoboutique.sales.application"].create({
            "name": "Zz Release", "vehicle_id": vehicle.id, "customer_id": self.customer.id, "selling_price": 700000,
        })
        account = application.financing_account_ids
        account.write({"status": "approved", "bank_id": self.bank.id, "amount_approved": 500000})
        release = self.env["autoboutique.vehicle.release"].create({
            "name": "Zz Release", "vehicle_id": vehicle.id, "sales_application_id": application.id,
            "customer_id": self.customer.id,
            "sale_order_id": self.env["sale.order"].create({"partner_id": self.customer.id}).id,
            "invoice_id": self.env["account.move"].create({
                "move_type": "out_invoice", "partner_id": self.customer.id}).id,
        })
        # The payment and checklist gates have their own tests; this checks what follows them.
        with patch.object(extended.VehicleRelease, "action_approve_release", return_value=True):
            release.action_approve_release()
        self.assertEqual(account.status, "released")
        self.assertEqual(account.release_date, self.today)

    def test_release_date_is_recorded(self):
        account = self._account(status="for_release")
        account.status = "released"
        self.assertEqual(account.release_date, self.today)

    def test_officer_bonus_levels(self):
        self.assertEqual([officer_bonus(n) for n in (0, 1, 4, 5, 7, 8, 9, 10, 15)],
                         [0, 200, 800, 2500, 2500, 3500, 3500, 10000, 10000])

    def test_unit_groups(self):
        self.assertEqual(unit_group("VIOS XLE 2025"), "VIOS")
        self.assertEqual(unit_group("Honda City 2023"), "HONDA")
        self.assertIsNone(unit_group("L300 2023"))

    def test_evaluation(self):
        row = self.env["autoboutique.financing.evaluation"].create({"unit": "Vios", "brand_new_price": 1000000})
        self.assertAlmostEqual(row.evaluation_2026, 850000)
        self.assertAlmostEqual(row.approval_2026, 765000)

    def test_empty_reports_show_their_rows(self):
        self.Account.search([]).unlink()
        anchor = fields.Date.to_string(self.today)
        for tab in ("daily", "monthly", "overall", "average", "financing", "quarter"):
            with self.subTest(tab=tab):
                report = self.Account.get_report(tab, anchor)
                self.assertTrue(report["tables"])
                for table in report["tables"]:
                    for row in table["rows"]:
                        self.assertEqual(len(row["cells"]), len(table["formats"]), table["title"])
        monthly = self._table(self.Account.get_report("monthly", anchor), "Monthly Performance")
        self.assertEqual(self._value(monthly, "MANNY"), 0, "Partners appear before they have accounts")

    def test_reports_count_the_accounts(self):
        self.Account.search([]).unlink()
        anchor = fields.Date.to_string(self.today)
        self._account(status="for_approval")
        self._account(status="for_interview")
        self._account(status="hold_lacking")
        self._account(status="decline")
        self._account(status="approved", unit="VIOS XLE 2025")
        self._account(status="released", bank_id=self.bank.id, officer_id=self.officer.id, amount_approved=500000,
                      unit="VIOS XLE 2025")
        self._account(status="released", bank_id=self.cash.id, amount_approved=300000)

        daily = self.Account.get_report("daily", anchor)
        status = self._table(daily, "Application Status")
        self.assertEqual(self._value(status, "Total on Process"), 3)
        self.assertEqual(self._value(status, "Total Endorse for the day"), 7)
        self.assertEqual(self._value(status, "Total Approved Account"), 1)
        self.assertEqual(self._value(status, "VIOS XLE 2025"), 1)
        self.assertEqual(self._value(status, "Total Releases"), 2)
        self.assertEqual(self._value(status, "Decline"), 1)
        self.assertEqual(self._value(self._table(daily, "Financing Release"), "Zz Bank"), 1)
        self.assertEqual(self._value(self._table(daily, "Source of Account"), "REFERRAL"), 2)
        self.assertEqual(self._value(self._table(daily, "Bonus Earned This Month"), "Zz Officer", 2), 200)
        self.assertEqual(self._value(self._table(daily, "Bonus Earned This Month"), "TOTAL", 2), 200,
                         "A release without an account officer earns no bonus")

        monthly = self.Account.get_report("monthly", anchor)
        performance = self._table(monthly, "Monthly Performance")
        self.assertEqual(next(row["cells"] for row in performance["rows"] if row["cells"][0] == "Zz Partner"),
                         ["Zz Partner", 3, 1, 1, 2, 7, 2 / 7])

        per_unit = self._table(monthly, "Per Unit")
        vios = 1 + 3 * [label for label, _keys in UNIT_GROUPS].index("VIOS")
        self.assertEqual(per_unit["headers"][vios:vios + 3], ["On Process", "Approved", "Released"])
        self.assertEqual(per_unit["rows"][-1]["cells"][vios:vios + 3], [0, 1, 1])

        overall = self._table(self.Account.get_report("overall", anchor), "Overall Monthly")
        month = overall["rows"][self.today.month - 1]["cells"]
        self.assertEqual(month[1:], [7, 1, 1, 500000, 300000, 800000])

        average = self._table(self.Account.get_report("average", anchor), "Monthly Over All Performance")
        self.assertEqual(self._value(average, "Zz Partner", self.today.month), 2)

        financing = self.Account.get_report("financing", anchor)
        releases = financing["tables"][0]
        self.assertAlmostEqual(self._value(releases, "Zz Bank", 4), 0.625)
        self.assertAlmostEqual(self._value(financing["tables"][1], "Zz Bank", 3), 1.0)

    def test_plate_becomes_the_stock_serial(self):
        bid = self.env["autoboutique.bid"].create({"name": "Zz Lot"})
        line = self.env["autoboutique.bid.line"].create({
            "name": "Vios", "bid_id": bid.id, "make": "Toyota", "model": "Vios", "plate_number": "ZZS 4004",
            "vin": "CHASSIS1",
        })
        self.assertEqual(line._ab_serial(), "ZZS 4004")
        line.plate_number = False
        self.assertEqual(line._ab_serial(), "CHASSIS1", "Older lines keep working with their chassis number")
