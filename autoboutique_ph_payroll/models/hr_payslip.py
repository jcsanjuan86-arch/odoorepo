from math import floor

from odoo import models

PERIODS_PER_YEAR = {"monthly": 12, "semi-monthly": 24, "bi-weekly": 26, "weekly": 52}


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _l10n_ph_is_ph(self):
        self.ensure_one()
        ph_type = self.env.ref("autoboutique_ph_payroll.structure_type_ph_employee", raise_if_not_found=False)
        return bool(ph_type) and self.struct_id.type_id == ph_type

    def _l10n_ph_periods(self):
        self.ensure_one()
        return PERIODS_PER_YEAR.get(self.version_id.schedule_pay, 12)

    def _l10n_ph_period_factor(self):
        """Share of a month covered by one payslip: 0.5 when paid semi-monthly."""
        return 12 / self._l10n_ph_periods()

    def _l10n_ph_regular_pay(self):
        return sum(line.amount for line in self.worked_days_line_ids if not line.work_entry_type_id.is_extra_hours)

    def _l10n_ph_premium_pay(self):
        """Overtime, rest day, holiday and night differential hours."""
        return sum(line.amount for line in self.worked_days_line_ids if line.work_entry_type_id.is_extra_hours)

    def _l10n_ph_contributions(self):
        """SSS, PhilHealth and Pag-IBIG shares on the monthly salary, prorated to this payslip."""
        self.ensure_one()
        wage = self.version_id.wage
        sss = self._rule_parameter("l10n_ph_sss")
        msc = floor((wage + sss["msc_step"] / 2) / sss["msc_step"]) * sss["msc_step"]
        msc = min(sss["msc_max"], max(sss["msc_min"], msc))
        phic = self._rule_parameter("l10n_ph_philhealth")
        premium = min(phic["ceiling"], max(phic["floor"], wage)) * phic["rate"] / 100
        hdmf = self._rule_parameter("l10n_ph_pagibig")
        fund_salary = min(wage, hdmf["max_fund_salary"])
        hdmf_rate = hdmf["employee_rate_low"] if wage <= hdmf["low_salary_limit"] else hdmf["employee_rate"]
        monthly = {
            "sss_employee": msc * sss["employee_rate"] / 100,
            "sss_employer": msc * sss["employer_rate"] / 100,
            "sss_ec": sss["ec_low"] if msc < sss["ec_threshold"] else sss["ec_high"],
            "philhealth_employee": premium / 2,
            "philhealth_employer": premium - premium / 2,
            "pagibig_employee": fund_salary * hdmf_rate / 100,
            "pagibig_employer": fund_salary * hdmf["employer_rate"] / 100,
        }
        factor = self._l10n_ph_period_factor()
        return {key: round(amount * factor, 2) for key, amount in monthly.items()}

    def _l10n_ph_annual_tax(self, annual_taxable):
        for lower, upper, base_tax, rate in self._rule_parameter("l10n_ph_tax_brackets"):
            if annual_taxable > lower and (upper is None or annual_taxable <= upper):
                return base_tax + (annual_taxable - lower) * rate / 100
        return 0.0

    def _l10n_ph_withholding_tax(self, taxable):
        """BIR withholding on compensation: the period's taxable pay annualized on the graduated table."""
        periods = self._l10n_ph_periods()
        return round(self._l10n_ph_annual_tax(taxable * periods) / periods, 2)

    def _l10n_ph_13th_month(self):
        """1/12 of the basic pay on this year's validated payslips."""
        year_start = self.date_to.replace(month=1, day=1)
        return round(self._sum("BASIC", year_start, self.date_to) / 12, 2)


class HrPayslipWorkedDays(models.Model):
    _inherit = "hr.payslip.worked_days"

    def _compute_amount(self):
        # Odoo spreads the whole contract wage over the payslip's hours; a monthly wage
        # paid semi-monthly must only pay half of it on each payslip.
        super()._compute_amount()
        for line in self:
            payslip = line.payslip_id
            if payslip.edited or payslip.state != "draft" or payslip.wage_type == "hourly" or not payslip.struct_id:
                continue
            if payslip._l10n_ph_is_ph():
                line.amount *= payslip._l10n_ph_period_factor()


class ResCompany(models.Model):
    _inherit = "res.company"

    def _l10n_ph_payroll_setup(self):
        """Payable accounts, rule accounts and the salary journal for Philippine companies."""
        from ..hooks import PAYABLE_ACCOUNTS, RULE_ACCOUNTS

        Account = self.env["account.account"]
        for company in self.filtered(lambda c: c.chart_template == "ph"):
            accounts = {}
            for code, (name, account_type) in PAYABLE_ACCOUNTS.items():
                account = Account.with_company(company).search(
                    [("code", "=", code), ("company_ids", "in", company.id)], limit=1)
                if not account:
                    account = Account.with_company(company).create({
                        "code": code, "name": name, "account_type": account_type,
                        "company_ids": [(6, 0, company.ids)],
                    })
                accounts[code] = account
            for xmlid, (debit_code, credit_code) in RULE_ACCOUNTS.items():
                rule = self.env.ref("autoboutique_ph_payroll." + xmlid).with_company(company)
                values = {}
                for field, code in (("account_debit", debit_code), ("account_credit", credit_code)):
                    if code:
                        values[field] = (accounts.get(code) or Account.with_company(company).search(
                            [("code", "=", code), ("company_ids", "in", company.id)], limit=1)).id
                rule.write(values)
            journal = self.env["account.journal"].search(
                [("company_id", "=", company.id), ("code", "=", "SLR")], limit=1)
            if journal:
                for xmlid in ("structure_ph_regular_pay", "structure_ph_13th_month"):
                    self.env.ref("autoboutique_ph_payroll." + xmlid).with_company(company).journal_id = journal
