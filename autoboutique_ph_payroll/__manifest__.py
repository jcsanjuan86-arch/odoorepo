{
    "name": "Philippines - Payroll (Autoboutique)",
    "version": "19.0.1.0.0",
    "summary": "SSS, PhilHealth, Pag-IBIG, BIR withholding tax and 13th month pay",
    "description": """
Philippine payroll rules for monthly-salaried employees paid semi-monthly (or monthly):

- SSS (employee, employer and EC) from the monthly salary credit
- PhilHealth premium shared 50/50
- Pag-IBIG (HDMF) employee and employer shares
- BIR withholding tax on compensation (TRAIN graduated rates, annualized)
- Overtime, rest day, holiday and night differential premiums from work entries
- 13th month pay
- Payable accounts for each Philippine company

Rates live in dated rule parameters (Payroll > Configuration > Rule Parameters),
so a new SSS or PhilHealth table is a new parameter value, not a code change.
""",
    "author": "Prime Auto Boutique",
    "category": "Human Resources/Payroll",
    "license": "OPL-1",
    "depends": ["hr_payroll", "hr_payroll_account", "l10n_ph"],
    "data": [
        "data/hr_rule_parameter_data.xml",
        "data/hr_salary_rule_category_data.xml",
        "data/hr_work_entry_type_data.xml",
        "data/hr_payroll_structure_type_data.xml",
        "data/hr_payroll_structure_data.xml",
        "data/hr_payslip_input_type_data.xml",
        "data/hr_salary_rule_data.xml",
    ],
    "post_init_hook": "_setup_ph_payroll_accounts",
    "installable": True,
}
