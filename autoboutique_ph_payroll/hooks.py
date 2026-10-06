# Accounts added to every company on the Philippine chart of accounts.
PAYABLE_ACCOUNTS = {
    "200310": ("SSS Contributions Payable", "liability_current"),
    "200311": ("PhilHealth Contributions Payable", "liability_current"),
    "200312": ("Pag-IBIG Contributions Payable", "liability_current"),
    "200313": ("Salaries Payable", "liability_current"),
    "200314": ("Withholding Tax on Compensation Payable", "liability_current"),
}

# Salary rule -> (debit account, credit account). Deductions are negative on the payslip,
# so their "debit" account is credited.
RULE_ACCOUNTS = {
    "rule_ph_basic": ("623000", False),
    "rule_ph_premium": ("623001", False),
    "rule_ph_taxable_allowance": ("623006", False),
    "rule_ph_deminimis": ("623005", False),
    "rule_ph_sss_employee": ("200310", False),
    "rule_ph_philhealth_employee": ("200311", False),
    "rule_ph_pagibig_employee": ("200312", False),
    "rule_ph_withholding_tax": ("200314", False),
    "rule_ph_sss_loan": ("200310", False),
    "rule_ph_pagibig_loan": ("200312", False),
    "rule_ph_cash_advance": ("110102", False),
    "rule_ph_net": (False, "200313"),
    "rule_ph_sss_employer": ("623002", "200310"),
    "rule_ph_sss_ec": ("623002", "200310"),
    "rule_ph_philhealth_employer": ("623004", "200311"),
    "rule_ph_pagibig_employer": ("623003", "200312"),
    "rule_ph_13th_month": ("623007", False),
    "rule_ph_13th_month_net": (False, "200313"),
}


def _setup_ph_payroll_accounts(env):
    env["res.company"].search([])._l10n_ph_payroll_setup()
