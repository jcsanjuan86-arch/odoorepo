# Philippines - Payroll (Autoboutique)

Philippine payroll for monthly-salaried employees paid semi-monthly (15th/30th) or monthly.

## Setup per employee

On the employee's contract (Payroll tab):

- **Salary Structure Type**: Philippines: Monthly-Salaried Employee
- **Pay Schedule**: half-month (semi-monthly) or month
- **Wage**: the monthly salary. Each semi-monthly payslip pays half of it.

## What each payslip computes

| Line | Rule |
|---|---|
| Basic Salary | Worked hours share of the monthly wage (half a month per cut-off) |
| Overtime / holiday / night differential | Work entries: Overtime 125%, Rest Day 130%, Special Holiday 130%, Regular Holiday 200%, Night Differential +10% |
| SSS | Monthly salary credit (₱5,000–₱35,000, steps of ₱500): employee 5%, employer 10%, EC ₱10/₱30 |
| PhilHealth | 5% of the monthly salary (floor ₱10,000, ceiling ₱100,000), shared 50/50 |
| Pag-IBIG | 2% employee and 2% employer on up to ₱10,000 (₱200 each a month) |
| Withholding tax | Taxable pay (gross less employee contributions) annualized on the TRAIN table |
| Inputs | Taxable allowance, de minimis benefits, SSS loan, Pag-IBIG loan, cash advance |

Monthly contributions are split equally across the two cut-offs.

**13th Month Pay** structure: 1/12 of the basic pay on the year's validated payslips.
The ₱90,000 exemption is not applied automatically: tax any excess at year-end annualization.

## Accounts (created for each company on the Philippine chart)

200310 SSS, 200311 PhilHealth, 200312 Pag-IBIG contributions payable, 200313 Salaries payable,
200314 Withholding tax on compensation payable. Expenses use the chart's 6230xx accounts.

## Rates

Payroll > Configuration > Rule Parameters (codes `l10n_ph_*`). Add a new dated value when
SSS, PhilHealth, Pag-IBIG or BIR publish a new table; payslips use the value valid on their end date.
