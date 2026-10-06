from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPhPayslip(TransactionCase):
    """A ₱30,000/month employee paid semi-monthly, full attendance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "PH Payroll Test Co",
            "country_id": cls.env.ref("base.ph").id,
        })
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))
        cls.struct_type = cls.env.ref("autoboutique_ph_payroll.structure_type_ph_employee")
        cls.employee = cls.env["hr.employee"].with_company(cls.company).create({
            "name": "Juan Dela Cruz",
            "company_id": cls.company.id,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
            "date_version": date(2026, 1, 1),
            "contract_date_start": date(2026, 1, 1),
            "structure_type_id": cls.struct_type.id,
            "schedule_pay": "semi-monthly",
            "wage": 30000,
        })

    def _payslip(self, date_from, date_to, struct=None):
        payslip = self.env["hr.payslip"].with_company(self.company).create({
            "name": "Test Payslip",
            "employee_id": self.employee.id,
            "struct_id": (struct or self.env.ref("autoboutique_ph_payroll.structure_ph_regular_pay")).id,
            "date_from": date_from,
            "date_to": date_to,
        })
        payslip.compute_sheet()
        return payslip

    def _line(self, payslip, code):
        return payslip.line_ids.filtered(lambda line: line.code == code).total

    def test_semi_monthly_payslip(self):
        payslip = self._payslip(date(2026, 10, 1), date(2026, 10, 15))
        self.assertAlmostEqual(self._line(payslip, "BASIC"), 15000, 2, "Half the monthly salary per cut-off")
        # SSS: MSC 30,000 -> 5% employee, 10% employer, EC 30; half of each per cut-off
        self.assertAlmostEqual(self._line(payslip, "SSS_EE"), -750, 2)
        self.assertAlmostEqual(self._line(payslip, "SSS_ER"), 1500, 2)
        self.assertAlmostEqual(self._line(payslip, "SSS_EC"), 15, 2)
        # PhilHealth: 5% of 30,000 = 1,500 a month, shared 50/50
        self.assertAlmostEqual(self._line(payslip, "PHIC_EE"), -375, 2)
        self.assertAlmostEqual(self._line(payslip, "PHIC_ER"), 375, 2)
        # Pag-IBIG: 2% of the 10,000 cap = 200 a month each
        self.assertAlmostEqual(self._line(payslip, "HDMF_EE"), -100, 2)
        self.assertAlmostEqual(self._line(payslip, "HDMF_ER"), 100, 2)
        # Taxable 13,775 x 24 = 330,600 -> 15% over 250,000 = 12,090 a year
        self.assertAlmostEqual(self._line(payslip, "PH_TAXABLE"), 13775, 2)
        self.assertAlmostEqual(self._line(payslip, "PH_WHT"), -503.75, 2)
        self.assertAlmostEqual(self._line(payslip, "NET"), 13271.25, 2)

    def test_contribution_limits(self):
        payslip = self._payslip(date(2026, 10, 1), date(2026, 10, 15))
        self.employee.version_id.wage = 4000
        low = payslip._l10n_ph_contributions()
        self.assertAlmostEqual(low["sss_employee"], 5000 * 0.05 / 2, 2, "SSS uses the minimum salary credit")
        self.assertAlmostEqual(low["sss_ec"], 5, 2)
        self.assertAlmostEqual(low["philhealth_employee"], 10000 * 0.05 / 4, 2, "PhilHealth floor of 10,000")
        self.employee.version_id.wage = 150000
        high = payslip._l10n_ph_contributions()
        self.assertAlmostEqual(high["sss_employee"], 35000 * 0.05 / 2, 2, "SSS maximum salary credit")
        self.assertAlmostEqual(high["philhealth_employee"], 100000 * 0.05 / 4, 2, "PhilHealth ceiling of 100,000")
        self.assertAlmostEqual(high["pagibig_employee"], 100, 2, "Pag-IBIG capped at 200 a month")

    def test_annual_tax_table(self):
        payslip = self._payslip(date(2026, 10, 1), date(2026, 10, 15))
        self.assertEqual(payslip._l10n_ph_annual_tax(250000), 0)
        self.assertAlmostEqual(payslip._l10n_ph_annual_tax(400000), 22500, 2)
        self.assertAlmostEqual(payslip._l10n_ph_annual_tax(1000000), 152500, 2)
        self.assertAlmostEqual(payslip._l10n_ph_annual_tax(10000000), 2902500, 2)

    def test_13th_month(self):
        for date_from, date_to in ((date(2026, 1, 1), date(2026, 1, 15)), (date(2026, 1, 16), date(2026, 1, 31))):
            # Validated without posting: the test company has no chart of accounts.
            self._payslip(date_from, date_to).write({"state": "validated"})
        thirteenth = self._payslip(date(2026, 12, 1), date(2026, 12, 15),
                                   self.env.ref("autoboutique_ph_payroll.structure_ph_13th_month"))
        self.assertAlmostEqual(self._line(thirteenth, "PH_13TH"), 30000 / 12, 2, "One month of basic pay / 12")
