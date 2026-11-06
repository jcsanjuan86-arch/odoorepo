"""Financing tracker: bank applications from endorsement to release.

An account follows one borrower and unit. Approval reserves the car through its
sales application, the vehicle release marks it Released, and a lost account
frees the car again. The reports reproduce the tabs of the former spreadsheet
and are always calculated from the accounts, so nobody keeps counts by hand.
"""
import calendar
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .automation import TODO, run_safely

STATUSES = [
    ("checking_docs", "Checking Docs"),
    ("hold_lacking", "Hold / With Lacking"),
    ("for_interview", "For Interview"),
    ("for_ci", "For CI"),
    ("for_cam", "For CAM"),
    ("for_approval", "For Approval"),
    ("approved", "Approved"),
    ("for_release", "For Release"),
    ("released", "Released"),
    ("decline", "Decline"),
    ("cmap_low", "CMAP Too Low"),
    ("cancelled", "Cancelled"),
    ("cancelled_approved", "Cancelled but Approved"),
    ("cancelled_unresponsive", "Cancelled Unresponsive"),
]
LACKING = ("checking_docs", "hold_lacking")
INTERVIEW = ("for_interview", "for_ci", "for_cam")
ON_PROCESS = LACKING + INTERVIEW + ("for_approval",)
APPROVED = ("approved", "for_release")
LOST = ("decline", "cmap_low", "cancelled", "cancelled_approved", "cancelled_unresponsive")

SOURCES = [("inhouse", "Inhouse"), ("partners", "Partners"), ("referral", "Referral"), ("sa", "SA")]

# Column groups of the Monthly Performance tab. Words are matched against the unit text.
UNIT_GROUPS = [
    ("NISSAN", {"NISSAN", "NAVARA", "ALMERA", "TERRA", "URVAN", "NV350", "JUKE", "PATROL"}),
    ("XPANDER", {"XPANDER"}),
    ("HONDA", {"HONDA", "CITY", "CIVIC", "BRV", "BR-V", "HRV", "HR-V", "CRV", "CR-V", "BRIO", "JAZZ", "MOBILIO"}),
    ("VIOS", {"VIOS"}),
    ("MIRAGE", {"MIRAGE"}),
    ("WIGO", {"WIGO"}),
    ("APV/HYBRID", {"APV", "HYBRID"}),
]

# Account Officer bonus of the daily report: a fixed amount from each level of releases
# and, below the first level, an amount per release.
BONUS_PER_RELEASE = 200
BONUS_LEVELS = [(10, 10000), (8, 3500), (5, 2500)]
MONTHLY_RELEASE_TARGET = 20

# TFS evaluation of a used car, as a share of the brand-new price.
EVALUATION_RATES = {"2026": 0.85, "2025": 0.80, "2024": 0.753, "2023": 0.65}
POSSIBLE_APPROVAL_RATE = 0.90


def officer_bonus(releases):
    for level, amount in BONUS_LEVELS:
        if releases >= level:
            return amount
    return releases * BONUS_PER_RELEASE


def unit_group(unit):
    words = set((unit or "").upper().split())
    return next((label for label, keys in UNIT_GROUPS if words & keys), None)


def _month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _ratio(part, whole):
    return part / whole if whole else 0.0


class FinancingBank(models.Model):
    _name = "autoboutique.financing.bank"
    _description = "Financing Bank"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_cash = fields.Boolean("Cash Buyer", help="Counted as Cash, not as a financed release, in the reports.")
    active = fields.Boolean(default=True)


class FinancingOfficer(models.Model):
    _name = "autoboutique.financing.officer"
    _description = "Account Officer"
    _order = "name"

    name = fields.Char(required=True)
    bank_id = fields.Many2one("autoboutique.financing.bank")
    active = fields.Boolean(default=True)


class FinancingPartner(models.Model):
    _name = "autoboutique.financing.partner"
    _description = "Financing Partner"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    team = fields.Char()
    source = fields.Selection(SOURCES, default="partners", required=True)
    user_id = fields.Many2one("res.users", string="Odoo User",
                              help="Accounts of this sales agent are assigned to this partner automatically.")
    active = fields.Boolean(default=True)


class FinancingEvaluation(models.Model):
    _name = "autoboutique.financing.evaluation"
    _description = "TFS Evaluation for Used Car"
    _order = "unit, variant"

    unit = fields.Char(required=True)
    variant = fields.Char()
    engine = fields.Char()
    brand_new_price = fields.Float(digits=(16, 2))
    evaluation_2026 = fields.Float("Evaluation 2026", compute="_compute_values", digits=(16, 2))
    evaluation_2025 = fields.Float("Evaluation 2025", compute="_compute_values", digits=(16, 2))
    evaluation_2024 = fields.Float("Evaluation 2024", compute="_compute_values", digits=(16, 2))
    evaluation_2023 = fields.Float("Evaluation 2023", compute="_compute_values", digits=(16, 2))
    approval_2026 = fields.Float("Possible Approval 2026", compute="_compute_values", digits=(16, 2))
    approval_2025 = fields.Float("Possible Approval 2025", compute="_compute_values", digits=(16, 2))
    approval_2024 = fields.Float("Possible Approval 2024", compute="_compute_values", digits=(16, 2))
    approval_2023 = fields.Float("Possible Approval 2023", compute="_compute_values", digits=(16, 2))

    @api.depends("brand_new_price")
    def _compute_values(self):
        for row in self:
            for year, rate in EVALUATION_RATES.items():
                evaluation = row.brand_new_price * rate
                row["evaluation_" + year] = evaluation
                row["approval_" + year] = evaluation * POSSIBLE_APPROVAL_RATE


class FinancingSubmission(models.Model):
    _name = "autoboutique.financing.submission"
    _description = "Bank Submission"
    _order = "date_submitted, id"

    account_id = fields.Many2one("autoboutique.financing.account", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="account_id.company_id", store=True, index=True)
    bank_id = fields.Many2one("autoboutique.financing.bank", required=True)
    officer_id = fields.Many2one("autoboutique.financing.officer", string="AO")
    date_submitted = fields.Date("Date", default=fields.Date.context_today, required=True)
    date_result = fields.Date("Result Date")
    aging = fields.Integer("No. of Days", compute="_compute_aging")
    result = fields.Selection([("pending", "Pending"), ("approved", "Approved"), ("declined", "Declined")],
                              default="pending", required=True)
    amount_approved = fields.Float("Amount Approved", digits=(16, 2))
    remarks = fields.Char()
    inhouse_remarks = fields.Char("Inhouse Remarks")

    @api.depends("date_submitted", "date_result")
    def _compute_aging(self):
        today = fields.Date.context_today(self)
        for submission in self:
            end = submission.date_result or today
            submission.aging = (end - submission.date_submitted).days if submission.date_submitted else 0

    @api.model_create_multi
    def create(self, vals_list):
        submissions = super().create(vals_list)
        submissions._ab_apply_result()
        return submissions

    def write(self, vals):
        result = super().write(vals)
        if {"result", "amount_approved"} & set(vals):
            self._ab_apply_result()
        return result

    def _ab_apply_result(self):
        """The bank's answer moves the account, unless it has already gone further."""
        for submission in self:
            account = submission.account_id
            if account.status not in ON_PROCESS:
                continue
            if submission.result == "approved":
                account.write({
                    "status": "approved", "bank_id": submission.bank_id.id,
                    "officer_id": (submission.officer_id or account.officer_id).id,
                    "amount_approved": submission.amount_approved or account.amount_approved,
                })
            elif submission.result == "declined" and all(
                    other.result == "declined" for other in account.submission_ids):
                account.status = "decline"


class FinancingAccount(models.Model):
    _name = "autoboutique.financing.account"
    _description = "Financing Account"
    _inherit = ["autoboutique.company.mixin", "autoboutique.automation.mixin"]
    _order = "date desc, id desc"

    name = fields.Char("Borrower", required=True, tracking=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    customer_id = fields.Many2one("res.partner", string="Customer")
    vehicle_id = fields.Many2one("autoboutique.vehicle", string="Vehicle", tracking=True)
    plate_number = fields.Char(related="vehicle_id.plate_number", string="Plate Number")
    unit = fields.Char(compute="_compute_unit", store=True, readonly=False)
    partner_id = fields.Many2one("autoboutique.financing.partner", string="Partner", index=True)
    source = fields.Selection(SOURCES, compute="_compute_source", store=True, readonly=False, string="Source")
    bank_id = fields.Many2one("autoboutique.financing.bank", string="Financing", index=True, tracking=True)
    officer_id = fields.Many2one("autoboutique.financing.officer", string="AO", index=True)
    amount_approved = fields.Float("Amount Approved", digits=(16, 2), tracking=True)
    status = fields.Selection(STATUSES, default="for_approval", required=True, index=True, tracking=True)
    days_open = fields.Integer("No. of Days", compute="_compute_days_open")
    remarks = fields.Char()
    inhouse_remarks = fields.Char("Inhouse Remarks")
    submission_ids = fields.One2many("autoboutique.financing.submission", "account_id", string="Bank Submissions")
    submission_summary = fields.Char("Banks", compute="_compute_submission_summary")
    sales_application_id = fields.Many2one("autoboutique.sales.application", index=True, copy=False)
    invoice_id = fields.Many2one(related="vehicle_id.invoice_id", string="Customer Invoice")
    # Released tab
    release_date = fields.Date("Released Date", index=True, copy=False)
    proceed_amount = fields.Float("Proceed Amount Released", digits=(16, 2), copy=False)
    transfer_status = fields.Char("Transfer Status", copy=False)
    chattel_fee = fields.Float("Chattel Fee", digits=(16, 2), copy=False)
    chattel_date = fields.Date("Chattel Date", copy=False)
    due_date = fields.Date("Due Date", copy=False)
    no_b = fields.Char("No. B", copy=False)
    no_cb = fields.Char("No. CB", copy=False)
    email = fields.Char()
    released_remarks = fields.Char("Release Remarks", copy=False)

    @api.depends("vehicle_id", "vehicle_id.model", "vehicle_id.variant", "vehicle_id.model_year")
    def _compute_unit(self):
        for account in self:
            vehicle = account.vehicle_id
            if vehicle:
                parts = [vehicle.model, vehicle.variant, vehicle.model_year and str(vehicle.model_year)]
                account.unit = " ".join(filter(None, parts)).upper()
            else:
                account.unit = account.unit or False

    @api.depends("partner_id", "partner_id.source")
    def _compute_source(self):
        for account in self:
            account.source = account.partner_id.source or account.source or "inhouse"

    @api.depends("date", "status", "release_date")
    def _compute_days_open(self):
        today = fields.Date.context_today(self)
        for account in self:
            end = account.release_date or today
            account.days_open = (end - account.date).days if account.date else 0

    @api.depends("submission_ids.bank_id", "submission_ids.aging", "submission_ids.result")
    def _compute_submission_summary(self):
        for account in self:
            account.submission_summary = ", ".join(
                "%s %sd" % (submission.bank_id.name, submission.aging) for submission in account.submission_ids)

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._ab_on_status_change()
        return accounts

    def write(self, vals):
        before = {account.id: account.status for account in self} if "status" in vals else {}
        result = super().write(vals)
        if before:
            self.filtered(lambda account: account.status != before[account.id])._ab_on_status_change()
        return result

    def _ab_on_status_change(self):
        for account in self:
            if account.status in APPROVED:
                run_safely(account, "reserve the car", account._ab_reserve_car)
            elif account.status == "released":
                if not account.release_date:
                    account.release_date = fields.Date.context_today(account)
            elif account.status in LOST:
                run_safely(account, "free the car", account._ab_free_car)

    def _ab_reserve_car(self):
        """Approved by the bank: the car goes to this buyer through the normal reservation."""
        self.ensure_one()
        vehicle = self.vehicle_id
        if not vehicle or not self.customer_id:
            self._ab_todo("manager", "Link the vehicle and customer of the approved account",
                          note="%s is approved, so its car can be reserved once both are set." % self.name)
            return
        application = self.sales_application_id.sudo()
        if not application:
            application = self.env["autoboutique.sales.application"].sudo().create({
                "name": "Financing - %s" % self.name, "vehicle_id": vehicle.id, "customer_id": self.customer_id.id,
                "selling_price": vehicle.selling_price, "company_id": self.company_id.id, "state": "approval",
            })
            self.sales_application_id = application
        if application.state not in ("draft", "approval"):
            return
        if vehicle.state != "ready":
            self._ab_todo("manager", "The approved car is not Ready for Sale",
                          note="Reserve %s for %s when it is available." % (vehicle.name, self.name))
            return
        application.requirements_complete = True
        application.action_approve_and_reserve()

    def _ab_free_car(self):
        """Lost account: its reservation ends and the car returns to Ready for Sale."""
        self.ensure_one()
        application = self.sales_application_id.sudo()
        if application.state not in ("draft", "approval", "approved", "reserved"):
            return
        was_reserved = application.state == "reserved"
        application.state = "cancelled"
        vehicle = application.vehicle_id
        if was_reserved and vehicle.state == "reserved":
            vehicle.with_context(ab_automating=True).write({
                "state": "ready", "customer_id": False, "sales_agent_id": False, "sale_order_id": False,
            })
        self.sudo().activity_schedule(
            TODO, date_deadline=fields.Date.add(fields.Date.context_today(self), days=1),
            summary="Financing lost: follow up the customer", user_id=application.sales_agent_id.id,
            note="%s is now %s.%s" % (self.name, dict(STATUSES)[self.status], (
                " %s is back in stock; cancel its draft quotation." % vehicle.name) if was_reserved else ""),
        )

    # -- reports ---------------------------------------------------------------------

    @api.model
    def get_report(self, tab, anchor=None):
        """One tab of the tracker as tables: {title, tables: [{title, headers, formats, rows}]}."""
        day = fields.Date.to_date(anchor) if anchor else fields.Date.context_today(self)
        return {
            "daily": self._report_daily, "monthly": self._report_monthly, "overall": self._report_overall,
            "average": self._report_average, "financing": self._report_financing,
            "quarter": self._report_quarter,
        }[tab](day)

    def _accounts_between(self, field, start, end):
        return self.search([(field, ">=", start), (field, "<=", end)])

    def _released_between(self, start, end):
        return self.search([("status", "=", "released"), ("release_date", ">=", start), ("release_date", "<=", end)])

    def _partners_in(self, accounts):
        """Every active partner, in tracker order, then any archived ones with accounts here."""
        Partner = self.env["autoboutique.financing.partner"]
        return Partner.search([]) | accounts.partner_id

    @staticmethod
    def _row(cells, kind=None):
        return {"cells": cells, "kind": kind}

    def _report_daily(self, day):
        month_start = day.replace(day=1)
        current = self.search([("status", "in", ON_PROCESS + APPROVED)])
        released = self._released_between(month_start, day)
        lost = self.search([("status", "in", LOST), ("date", ">=", month_start), ("date", "<=", day)])

        def count(records, statuses):
            return len(records.filtered(lambda a: a.status in statuses))

        approved = current.filtered(lambda a: a.status in APPROVED)
        units = defaultdict(int)
        for account in approved:
            units[account.unit or "(No unit)"] += 1
        status_rows = [
            self._row(["Total on Process", count(current, ON_PROCESS)], "total"),
            self._row(["Total Endorse for the day", self.search_count([("date", "=", day)])], "total"),
            self._row(["APPLICATION STATUS", ""], "section"),
            self._row(["With Lacking", count(current, LACKING)]),
            self._row(["For interview / For CI", count(current, INTERVIEW)]),
            self._row(["For Approval", count(current, ("for_approval",))]),
            self._row(["Total Approved Account", len(approved)], "total"),
            self._row(["Per unit", ""], "section"),
            *[self._row([unit, units[unit]]) for unit in sorted(units)],
            self._row(["Total Releases", len(released)], "total"),
            self._row(["Number of Lost Account", len(lost)], "total"),
            self._row(["Decline", count(lost, ("decline", "cmap_low"))]),
            self._row(["Cancelled", count(lost, ("cancelled", "cancelled_unresponsive"))]),
            self._row(["Cancelled but approved", count(lost, ("cancelled_approved",))]),
        ]
        banks = self.env["autoboutique.financing.bank"].search([]) | released.bank_id
        bank_rows = [self._row([bank.name, len(released.filtered(lambda a: a.bank_id == bank))]) for bank in banks]
        source_rows = [self._row([label.upper(), len(released.filtered(lambda a: a.source == key))])
                       for key, label in SOURCES]
        officers = defaultdict(int)
        for account in released.filtered("officer_id"):
            officers[account.officer_id.name] += 1
        officer_rows = [self._row([name, officers[name], officer_bonus(officers[name])]) for name in sorted(officers)]
        return {"title": "As of %s" % day.strftime("%B %d, %Y"), "tables": [
            {"title": "Application Status", "headers": ["", ""], "formats": ["text", "int"], "rows": status_rows},
            {"title": "Financing Release", "headers": ["", ""], "formats": ["text", "int"], "rows": bank_rows + [
                self._row(["TOTAL", len(released)], "total")]},
            {"title": "Source of Account", "headers": ["", ""], "formats": ["text", "int"], "rows": source_rows + [
                self._row(["TOTAL", len(released)], "total")]},
            {"title": "Account Officer Bonus", "headers": ["Release Unit", "Amount"], "formats": ["text", "text"],
             "rows": [self._row(["1 to 4 account release", "%d each" % BONUS_PER_RELEASE])] + [
                 self._row(["%d releases" % level, "{:,}".format(amount)]) for level, amount in reversed(BONUS_LEVELS)]
             + [self._row(["Target this month: %d unit releases" % MONTHLY_RELEASE_TARGET, "%d released" % len(released)],
                          "total")]},
            {"title": "Bonus Earned This Month", "headers": ["Account Officer", "Releases", "Bonus"],
             "formats": ["text", "int", "money"], "rows": officer_rows + [self._row(
                 ["TOTAL", sum(officers.values()), sum(officer_bonus(number) for number in officers.values())], "total")]},
        ]}

    def _partner_counts(self, accounts):
        """Per partner: on process, cancelled / decline, approved, released."""
        counts = defaultdict(lambda: [0, 0, 0, 0])
        for account in accounts:
            column = (0 if account.status in ON_PROCESS else 2 if account.status in APPROVED
                      else 3 if account.status == "released" else 1)
            counts[account.partner_id.id][column] += 1
        return counts

    def _report_monthly(self, day):
        start, end = day.replace(day=1), _month_end(day)
        accounts = self._accounts_between("date", start, end)
        counts = self._partner_counts(accounts)
        partners = self._partners_in(accounts)
        teams, order = defaultdict(list), []
        for partner in partners:
            if partner.team not in teams:
                order.append(partner.team)
            teams[partner.team].append(partner)
        rows, unit_rows = [], []
        group_labels = [label for label, _keys in UNIT_GROUPS]
        unit_counts = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for account in accounts:
            group = unit_group(account.unit)
            if group and account.status in ON_PROCESS:
                unit_counts[account.partner_id.id][group][0] += 1
            elif group and account.status == "released":
                unit_counts[account.partner_id.id][group][1] += 1

        def partner_row(label, values):
            total = sum(values)
            return [label, *values, total, _ratio(values[3], total)]

        def unit_row(label, partner_id):
            return [label] + [n for group in group_labels for n in unit_counts[partner_id][group]]

        for team in order:
            if team:
                rows.append(self._row([team.upper()] + [""] * 6, "section"))
                unit_rows.append(self._row([team.upper()] + [""] * (2 * len(group_labels)), "section"))
            for partner in teams[team]:
                rows.append(self._row(partner_row(partner.name, counts[partner.id])))
                unit_rows.append(self._row(unit_row(partner.name, partner.id)))
        if counts.get(False):
            rows.append(self._row(partner_row("(No partner)", counts[False])))
            unit_rows.append(self._row(unit_row("(No partner)", False)))
        totals = [sum(values[i] for values in counts.values()) for i in range(4)]
        rows.append(self._row(partner_row("TOTAL", totals), "total"))
        unit_totals = [sum(unit_counts[pid][group][i] for pid in unit_counts)
                       for group in group_labels for i in range(2)]
        unit_rows.append(self._row(["TOTAL"] + unit_totals, "total"))
        return {"title": day.strftime("%B %Y").upper(), "tables": [
            {"title": "Monthly Performance",
             "headers": ["Partners", "On Process", "Cancelled / Decline", "Approved", "Released", "Total Endorsed", "%"],
             "formats": ["text", "int", "int", "int", "int", "int", "pct"], "rows": rows},
            {"title": "Per Unit", "wide": True,
             "header_groups": [{"label": "", "span": 1}] + [{"label": label, "span": 2} for label in group_labels],
             "headers": ["Partners"] + ["On Process", "Released"] * len(group_labels),
             "formats": ["text"] + ["int"] * (2 * len(group_labels)), "rows": unit_rows},
        ]}

    def _year_figures(self, year):
        """Per month: endorsed, financed releases, cash releases, financed amount, cash amount."""
        figures = [[0, 0, 0, 0.0, 0.0] for _month in range(12)]
        for account in self._accounts_between("date", date(year, 1, 1), date(year, 12, 31)):
            figures[account.date.month - 1][0] += 1
        for account in self._released_between(date(year, 1, 1), date(year, 12, 31)):
            month = figures[account.release_date.month - 1]
            if account.bank_id.is_cash:
                month[2] += 1
                month[4] += account.amount_approved
            else:
                month[1] += 1
                month[3] += account.amount_approved
        return figures

    def _report_overall(self, day):
        figures, last = self._year_figures(day.year), self._year_figures(day.year - 1)
        names = [calendar.month_name[month].upper() for month in range(1, 13)]
        rows = [self._row([names[i], *row, row[3] + row[4]]) for i, row in enumerate(figures)]
        totals = [sum(row[i] for row in figures) for i in range(5)]
        rows.append(self._row(["TOTAL", *totals, totals[3] + totals[4]], "total"))
        growth_rows = []
        for i, row in enumerate(figures):
            before, now = last[i][1] + last[i][2], row[1] + row[2]
            growth = (now - before) / before if before else "N/A"
            growth_rows.append(self._row(
                [names[i], last[i][0], last[i][1], last[i][2], before, row[0], row[1], row[2], now, growth]))
        return {"title": "OVER ALL RELEASE %d" % day.year, "tables": [
            {"title": "Overall Monthly", "wide": True,
             "headers": ["Month", "Endorsed Account", "Financing", "Cash", "Financing Amount", "Cash Amount", "Amount"],
             "formats": ["text", "int", "int", "int", "money", "money", "money"], "rows": rows},
            {"title": "Over All Release vs. Last Year", "wide": True,
             "header_groups": [{"label": "", "span": 1}, {"label": str(day.year - 1), "span": 4},
                               {"label": str(day.year), "span": 4}, {"label": "", "span": 1}],
             "headers": ["Month", "Endorsed Account", "Released Volume", "Cash", "Total",
                         "Endorsed Account", "Released Volume", "Cash", "Total", "Growth"],
             "formats": ["text"] + ["int"] * 8 + ["pct"], "rows": growth_rows},
        ]}

    def _months_elapsed(self, start, months):
        today = fields.Date.context_today(self)
        passed = (today.year - start.year) * 12 + today.month - start.month + 1
        return max(1, min(months, passed))

    def _partner_month_table(self, title, accounts, date_field, start, months):
        """Partners down, months across, with the total and the average per month elapsed."""
        grid = defaultdict(lambda: [0] * months)
        for account in accounts:
            moved = account[date_field]
            grid[account.partner_id.id][(moved.year - start.year) * 12 + moved.month - start.month] += 1
        elapsed = self._months_elapsed(start, months)
        partners = self._partners_in(accounts)

        def row(label, values):
            return [label, *values, sum(values), sum(values) / elapsed]

        rows = [self._row(row(partner.name, grid[partner.id])) for partner in partners]
        if grid.get(False):
            rows.append(self._row(row("(No partner)", grid[False])))
        rows.append(self._row(row("TOTAL", [sum(values[i] for values in grid.values()) for i in range(months)]), "total"))
        labels = [(start + relativedelta(months=i)).strftime("%B").upper() for i in range(months)]
        return {"title": title, "wide": months > 6, "headers": ["", *labels, "Total", "Average"],
                "formats": ["text"] + ["int"] * (months + 1) + ["dec"], "rows": rows}

    def _report_average(self, day):
        start = date(day.year, 1, 1)
        released = self._released_between(start, date(day.year, 12, 31))
        table = self._partner_month_table("Monthly Over All Performance", released, "release_date", start, 12)
        return {"title": "MONTHLY OVER ALL PERFORMANCE %d" % day.year, "tables": [table]}

    def _report_financing(self, day):
        start, end = day.replace(day=1), _month_end(day)
        released = self._released_between(start, end)
        endorsed = self._accounts_between("date", start, end)
        banks = self.env["autoboutique.financing.bank"].search([]) | released.bank_id | endorsed.bank_id
        total_amount = sum(released.mapped("amount_approved"))
        release_rows, process_rows = [], []
        for bank in banks:
            bank_released = released.filtered(lambda a: a.bank_id == bank)
            bank_endorsed = endorsed.filtered(lambda a: a.bank_id == bank)
            amount = sum(bank_released.mapped("amount_approved"))
            release_rows.append(self._row([bank.name, len(bank_endorsed), len(bank_released), amount,
                                           _ratio(amount, total_amount)]))
            if not bank.is_cash:
                process_rows.append(self._row([bank.name, len(bank_endorsed), _ratio(len(bank_endorsed), len(endorsed)),
                                               _ratio(len(bank_released), len(bank_endorsed))]))
        month = day.strftime("%B").upper()
        release_rows.append(self._row(["Grand Total", len(endorsed), len(released), total_amount, ""], "total"))
        process_rows.append(self._row(["Grand Total", len(endorsed), "", ""], "total"))
        return {"title": day.strftime("%B %Y").upper(), "tables": [
            {"title": "%s Releases Percentage" % month, "headers": ["Financing", "Endorsed", "Volume", "Amount", "%"],
             "formats": ["text", "int", "int", "money", "pct"], "rows": release_rows},
            {"title": "%s Process Report" % month, "headers": ["Financing", "Volume", "Endorsement %", "Efficiency"],
             "formats": ["text", "int", "pct", "pct"], "rows": process_rows},
        ]}

    def _report_quarter(self, day):
        start = date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
        end = _month_end(start + relativedelta(months=2))
        endorsed = self._accounts_between("date", start, end)
        released = self._released_between(start, end)
        counts = self._partner_counts(endorsed)
        elapsed = self._months_elapsed(start, 3)

        def row(label, values):
            return [label, *values, sum(values), values[3] / elapsed]

        rows = [self._row(row(partner.name, counts[partner.id])) for partner in self._partners_in(endorsed)]
        if counts.get(False):
            rows.append(self._row(row("(No partner)", counts[False])))
        rows.append(self._row(row("TOTAL", [sum(values[i] for values in counts.values()) for i in range(4)]), "total"))
        period = "%s TO %s %d" % (start.strftime("%B").upper(), end.strftime("%B").upper(), start.year)
        return {"title": period, "tables": [
            {"title": "Average Releases %s" % period, "wide": True,
             "headers": ["Partners", "On Process", "Cancelled / Decline", "Approved", "Released", "Total Endorsed", "Average"],
             "formats": ["text", "int", "int", "int", "int", "int", "dec"], "rows": rows},
            self._partner_month_table("Average Endorsed", endorsed, "date", start, 3),
            self._partner_month_table("Average Release", released, "release_date", start, 3),
        ]}


class SalesApplication(models.Model):
    _inherit = "autoboutique.sales.application"

    financing_account_ids = fields.One2many("autoboutique.financing.account", "sales_application_id")

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals:
            self._ab_update_financing()
        return result

    def _ab_update_financing(self):
        """A reservation, rejection or cancellation decided on the application reaches its account."""
        for application in self:
            accounts = application.sudo().financing_account_ids
            if application.state == "reserved":
                accounts.filtered(lambda a: a.status in ON_PROCESS).write({"status": "approved"})
            elif application.state in ("rejected", "cancelled"):
                status = "decline" if application.state == "rejected" else "cancelled"
                accounts.filtered(lambda a: a.status in ON_PROCESS + APPROVED).write({"status": status})

    def _ab_ensure_financing_account(self):
        """Loan applications from Salesforce appear in the tracker without anyone typing them."""
        Account = self.env["autoboutique.financing.account"].sudo()
        Partner = self.env["autoboutique.financing.partner"].sudo()
        for application in self.sudo():
            if not application.financing_account_ids:
                Account.create({
                    "name": application.customer_id.name, "customer_id": application.customer_id.id,
                    "email": application.customer_id.email, "vehicle_id": application.vehicle_id.id,
                    "date": application.application_date, "sales_application_id": application.id,
                    "partner_id": Partner.search([("user_id", "=", application.sales_agent_id.id)], limit=1).id,
                    "company_id": application.company_id.id,
                    "status": "approved" if application.state in ("approved", "reserved", "sold") else "for_approval",
                })

    def action_open_financing_account(self):
        self.ensure_one()
        self._ab_ensure_financing_account()
        return {
            "type": "ir.actions.act_window", "res_model": "autoboutique.financing.account", "view_mode": "form",
            "res_id": self.sudo().financing_account_ids[:1].id,
        }


class VehicleRelease(models.Model):
    _inherit = "autoboutique.vehicle.release"

    def action_approve_release(self):
        result = super().action_approve_release()
        for release in self:
            accounts = release.sudo().sales_application_id.financing_account_ids
            accounts.filtered(lambda a: a.status not in LOST + ("released",)).write({"status": "released"})
        return result
