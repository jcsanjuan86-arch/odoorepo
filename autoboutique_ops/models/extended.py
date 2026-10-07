from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

STOCK_STATES = ("receiving", "qc", "repair", "detailing", "ready", "reserved")
SOLD_STATES = ("sold", "payment", "released", "documents")
AGING_BUCKETS = {"0-30 days": 30, "31-60 days": 60, "61-90 days": 90, "Over 90 days": float("inf")}
RECEIVABLE_BUCKETS = {"Not yet due": 0, "1-30 days late": 30, "31-60 days late": 60, "61-90 days late": 90,
                      "Over 90 days late": float("inf")}


class VehicleExtension(models.Model):
    _name = "autoboutique.vehicle"
    _inherit = ["autoboutique.vehicle", "image.mixin"]

    sales_application_ids = fields.One2many("autoboutique.sales.application", "vehicle_id")
    release_ids = fields.One2many("autoboutique.vehicle.release", "vehicle_id")
    registration_ids = fields.One2many("autoboutique.registration", "vehicle_id")
    insurance_ids = fields.One2many("autoboutique.insurance", "vehicle_id")
    document_ids = fields.One2many("autoboutique.document", "vehicle_id")
    commission_ids = fields.One2many("autoboutique.commission", "vehicle_id")
    customer_id = fields.Many2one("res.partner")
    sales_agent_id = fields.Many2one("res.users")
    selling_price = fields.Monetary(currency_field="currency_id")
    selling_price_untaxed = fields.Monetary("Price before VAT", compute="_compute_profit", currency_field="currency_id")
    gross_profit = fields.Monetary(compute="_compute_profit", currency_field="currency_id")
    margin_percent = fields.Float("Margin %", compute="_compute_profit", digits=(5, 1))
    registration_status = fields.Selection([("draft", "Draft"), ("processing", "Processing"), ("completed", "Completed")], compute="_compute_document_rollups")
    insurance_status = fields.Selection([("draft", "Draft"), ("active", "Active"), ("expired", "Expired")], compute="_compute_document_rollups")
    missing_document_count = fields.Integer(compute="_compute_document_rollups")

    @api.depends("selling_price", "actual_vehicle_cost", "product_id.taxes_id", "company_id.account_sale_tax_id")
    def _compute_profit(self):
        # Listing prices include VAT; costs do not. Compare like with like.
        for vehicle in self:
            company = vehicle.company_id or self.env.company
            taxes = vehicle.product_id.taxes_id.filtered(lambda tax: tax.company_id == company) \
                or company.account_sale_tax_id
            untaxed = vehicle.selling_price
            if taxes and vehicle.selling_price:
                untaxed = taxes.compute_all(vehicle.selling_price, currency=company.currency_id,
                                            product=vehicle.product_id)["total_excluded"]
            vehicle.selling_price_untaxed = untaxed
            vehicle.gross_profit = untaxed - vehicle.actual_vehicle_cost
            vehicle.margin_percent = 100.0 * vehicle.gross_profit / untaxed if untaxed else 0.0

    @api.depends("registration_ids.status", "insurance_ids.status", "document_ids.status", "document_ids.required")
    def _compute_document_rollups(self):
        for vehicle in self:
            vehicle.missing_document_count = len(vehicle.document_ids.filtered(
                lambda document: document.required and document.status != "completed"
            ))
            vehicle.registration_status = vehicle.registration_ids[:1].status if vehicle.registration_ids else False
            vehicle.insurance_status = vehicle.insurance_ids[:1].status if vehicle.insurance_ids else False

    # -- Stage history (turnaround) --------------------------------------------

    stage_log_ids = fields.One2many("autoboutique.vehicle.stage.log", "vehicle_id", string="Stage History")

    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)
        vehicles._ab_log_stage()
        return vehicles

    def write(self, vals):
        before = {vehicle.id: vehicle.state for vehicle in self} if "state" in vals else {}
        result = super().write(vals)
        if before:
            self.filtered(lambda vehicle: vehicle.state != before[vehicle.id])._ab_log_stage()
        return result

    def _ab_log_stage(self):
        if self:
            self.env["autoboutique.vehicle.stage.log"].sudo().create(
                [{"vehicle_id": vehicle.id, "state": vehicle.state} for vehicle in self])

    def _ab_backfill_stage_log(self):
        """Rebuild the stage history of cars that existed before it was recorded, from the
        dates their receiving, QC, repair, detailing, sale, release and registration records hold."""
        Log = self.env["autoboutique.vehicle.stage.log"].sudo()
        order = list(STOCK_STATES + SOLD_STATES)
        for vehicle in self.filtered(lambda v: not v.stage_log_ids):
            received = vehicle.receiving_id.received_date
            reservation = vehicle.sales_application_ids.filtered("reservation_date").mapped("reservation_date")
            registration = vehicle.registration_ids.filtered("completed_date").mapped("completed_date")
            guesses = {
                "receiving": fields.Datetime.to_datetime(received) if received else vehicle.create_date,
                "qc": min(vehicle.qc_ids.mapped("create_date"), default=None),
                "repair": min(vehicle.repair_ids.mapped("create_date"), default=None),
                "detailing": min(vehicle.detailing_ids.mapped("create_date"), default=None),
                "ready": max(vehicle.detailing_ids.mapped("write_date"), default=None),
                "reserved": min(reservation, default=None),
                "sold": vehicle.sale_order_id.date_order,
                "payment": fields.Datetime.to_datetime(vehicle.invoice_id.invoice_date) if vehicle.invoice_id.invoice_date else None,
                "released": fields.Datetime.to_datetime(vehicle.release_date) if vehicle.release_date else None,
                "documents": fields.Datetime.to_datetime(min(registration)) if registration else None,
            }
            values, last = [], None
            for state in order[:order.index(vehicle.state) + 1]:
                date_in = guesses[state]
                if state == vehicle.state:
                    # The current stage is always recorded, never before the stage that preceded it.
                    date_in = max(filter(None, (date_in, last, vehicle.create_date if last is None else None)))
                if date_in and (last is None or date_in >= last):
                    values.append({"vehicle_id": vehicle.id, "state": state, "date_in": date_in})
                    last = date_in
            Log.create(values)


class VehicleStageLog(models.Model):
    _name = "autoboutique.vehicle.stage.log"
    _description = "Vehicle Stage History"
    _order = "date_in, id"

    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="vehicle_id.company_id", store=True, index=True)
    state = fields.Selection(selection="_selection_state", required=True)
    date_in = fields.Datetime("Entered", required=True, default=fields.Datetime.now)

    def _selection_state(self):
        return self.env["autoboutique.vehicle"]._fields["state"]._description_selection(self.env)


class SalesApplication(models.Model):
    _name = "autoboutique.sales.application"
    _description = "Vehicle Sales Application"
    _inherit = "autoboutique.company.mixin"
    _order = "id desc"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    customer_id = fields.Many2one("res.partner", required=True)
    sales_agent_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    application_date = fields.Date(default=fields.Date.context_today, required=True)
    selling_price = fields.Monetary(required=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    sale_order_id = fields.Many2one("sale.order")
    requirements_complete = fields.Boolean()
    missing_requirements = fields.Text()
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_on = fields.Datetime(readonly=True)
    reservation_date = fields.Datetime(readonly=True)
    reservation_expiry = fields.Datetime()
    rejection_reason = fields.Text()
    state = fields.Selection([
        ("draft", "Draft"), ("approval", "For Approval"), ("approved", "Approved"),
        ("reserved", "Reserved"), ("sold", "Sold"), ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ], default="draft", required=True)

    def action_approve_and_reserve(self):
        for application in self:
            if not application.requirements_complete:
                raise ValidationError("Complete customer requirements before approving the application.")
            if application.vehicle_id.state != "ready":
                raise ValidationError("Only a Ready for Sale vehicle can be reserved.")
            duplicate = self.search_count([
                ("vehicle_id", "=", application.vehicle_id.id), ("state", "=", "reserved"),
                ("id", "!=", application.id),
            ])
            if duplicate:
                raise ValidationError("This vehicle already has an active reservation.")
            application.write({
                "state": "reserved", "approved_by": self.env.user.id,
                "approved_on": fields.Datetime.now(), "reservation_date": fields.Datetime.now(),
            })
            application.vehicle_id.write({
                "state": "reserved", "customer_id": application.customer_id.id,
                "sales_agent_id": application.sales_agent_id.id, "selling_price": application.selling_price,
            })


class VehicleRelease(models.Model):
    _name = "autoboutique.vehicle.release"
    _description = "Vehicle Release"
    _inherit = "autoboutique.company.mixin"
    _order = "id desc"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    sales_application_id = fields.Many2one("autoboutique.sales.application", required=True)
    sale_order_id = fields.Many2one("sale.order", required=True)
    invoice_id = fields.Many2one("account.move", required=True)
    customer_id = fields.Many2one("res.partner", required=True)
    payment_verified = fields.Boolean(readonly=True)
    final_qc_verified = fields.Boolean()
    detailing_verified = fields.Boolean()
    documents_verified = fields.Boolean()
    customer_id_checked = fields.Boolean()
    keys_handed_over = fields.Boolean()
    originals_handed_over = fields.Boolean()
    odometer = fields.Integer()
    approved_by = fields.Many2one("res.users", readonly=True)
    release_date = fields.Datetime(readonly=True)
    notes = fields.Text()
    state = fields.Selection([("draft", "Draft"), ("approved", "Released"), ("cancelled", "Cancelled")], default="draft")

    def action_approve_release(self):
        for release in self:
            invoice = release.invoice_id
            if release.sale_order_id.state not in ("sale", "done"):
                raise ValidationError("Confirm the Sales Order before releasing the vehicle.")
            if invoice.state != "posted" or invoice.payment_state not in ("in_payment", "paid"):
                raise ValidationError("A posted customer invoice with recorded payment is required.")
            checks = [release.final_qc_verified, release.detailing_verified, release.documents_verified,
                      release.customer_id_checked, release.keys_handed_over, release.originals_handed_over]
            if not all(checks):
                raise ValidationError("Complete QC, detailing, document, ID, key, and original-document checks.")
            if self.search_count([("vehicle_id", "=", release.vehicle_id.id), ("state", "=", "approved"), ("id", "!=", release.id)]):
                raise ValidationError("This vehicle already has a completed release.")
            release.write({"state": "approved", "payment_verified": True, "approved_by": self.env.user.id, "release_date": fields.Datetime.now()})
            release.vehicle_id.write({"state": "released", "documents_verified": True, "sale_order_id": release.sale_order_id.id, "invoice_id": invoice.id, "payment_received": True, "release_date": fields.Date.context_today(self)})
            release.sales_application_id.state = "sold"


class Registration(models.Model):
    _name = "autoboutique.registration"
    _description = "Vehicle Registration"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    customer_id = fields.Many2one("res.partner")
    responsible_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    submitted_date = fields.Date()
    completed_date = fields.Date()
    orcr_status = fields.Selection([("pending", "Pending"), ("complete", "Complete")], default="pending")
    plate_status = fields.Selection([("pending", "Pending"), ("complete", "Complete")], default="pending")
    plate_number = fields.Char()
    documents_complete = fields.Boolean()
    status = fields.Selection([("draft", "Draft"), ("processing", "Processing"), ("completed", "Completed")], default="draft")

    def action_complete(self):
        for record in self:
            if not record.documents_complete or record.orcr_status != "complete" or record.plate_status != "complete":
                raise ValidationError("Complete OR/CR, plate, and document requirements first.")
            record.write({"status": "completed", "completed_date": fields.Date.context_today(self)})
            if record.plate_number:
                record.vehicle_id.plate_number = record.plate_number


class Insurance(models.Model):
    _name = "autoboutique.insurance"
    _description = "Vehicle Insurance"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    customer_id = fields.Many2one("res.partner")
    provider_id = fields.Many2one("res.partner", required=True)
    policy_number = fields.Char(required=True)
    effective_date = fields.Date(required=True)
    expiration_date = fields.Date(required=True)
    status = fields.Selection([("draft", "Draft"), ("active", "Active"), ("expired", "Expired")], default="draft")

    @api.constrains("effective_date", "expiration_date")
    def _check_dates(self):
        for policy in self:
            if policy.expiration_date and policy.effective_date and policy.expiration_date < policy.effective_date:
                raise ValidationError("Insurance expiration cannot be before its effective date.")


class VehicleDocument(models.Model):
    _name = "autoboutique.document"
    _description = "Vehicle Document"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    customer_id = fields.Many2one("res.partner")
    release_id = fields.Many2one("autoboutique.vehicle.release")
    document_type = fields.Char(required=True)
    required = fields.Boolean(default=True)
    status = fields.Selection([("missing", "Missing"), ("received", "Received"), ("submitted", "Submitted"), ("processing", "Processing"), ("completed", "Completed"), ("released", "Released")], default="missing")
    received_date = fields.Date()
    completed_date = fields.Date()
    remarks = fields.Text()


class Commission(models.Model):
    _name = "autoboutique.commission"
    _description = "Sales Commission"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    sales_agent_id = fields.Many2one("res.users", required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    sale_order_id = fields.Many2one("sale.order", required=True)
    invoice_id = fields.Many2one("account.move", required=True)
    selling_price = fields.Monetary(required=True, currency_field="currency_id")
    commission_type = fields.Selection([("percent", "Percentage"), ("fixed", "Fixed")], default="percent", required=True)
    rate = fields.Float()
    amount = fields.Monetary(compute="_compute_amount", store=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_on = fields.Datetime(readonly=True)
    paid = fields.Boolean(readonly=True)
    paid_date = fields.Date(readonly=True)
    state = fields.Selection([("draft", "Draft"), ("approved", "Approved"), ("paid", "Paid"), ("rejected", "Rejected")], default="draft")

    @api.depends("commission_type", "rate", "selling_price")
    def _compute_amount(self):
        for record in self:
            record.amount = record.selling_price * record.rate / 100 if record.commission_type == "percent" else record.rate

    def action_approve(self):
        for commission in self:
            if commission.rate < 0 or (commission.commission_type == "percent" and commission.rate > 100):
                raise ValidationError("Commission rate must be between 0 and 100 percent.")
            if commission.sale_order_id.state not in ("sale", "done") or commission.invoice_id.state != "posted":
                raise ValidationError("A confirmed Sales Order and posted invoice are required.")
            commission.write({"state": "approved", "approved_by": self.env.user.id, "approved_on": fields.Datetime.now()})

    def action_mark_paid(self):
        for commission in self:
            if commission.state != "approved" or commission.invoice_id.payment_state not in ("in_payment", "paid"):
                raise ValidationError("Approve the commission and record customer payment first.")
            commission.write({"state": "paid", "paid": True, "paid_date": fields.Date.context_today(self)})


class Dashboard(models.Model):
    _name = "autoboutique.dashboard"
    _description = "Management KPI Snapshot"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    snapshot_date = fields.Date(default=fields.Date.context_today, required=True)
    vehicles_total = fields.Integer(readonly=True)
    vehicles_ready = fields.Integer(readonly=True)
    vehicles_repair = fields.Integer(readonly=True)
    vehicles_sold = fields.Integer(readonly=True)
    total_vehicle_cost = fields.Monetary(readonly=True, currency_field="currency_id")
    sales_revenue = fields.Monetary(readonly=True, currency_field="currency_id")
    gross_profit = fields.Monetary(readonly=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    def action_refresh(self):
        Vehicle = self.env["autoboutique.vehicle"]
        for snapshot in self:
            vehicles = Vehicle.search([("company_id", "=", snapshot.company_id.id)])
            snapshot.write({
                "vehicles_total": len(vehicles),
                "vehicles_ready": len(vehicles.filtered(lambda vehicle: vehicle.state == "ready")),
                "vehicles_repair": len(vehicles.filtered(lambda vehicle: vehicle.state == "repair")),
                "vehicles_sold": len(vehicles.filtered(lambda vehicle: vehicle.state in ("sold", "payment", "released", "documents"))),
                "total_vehicle_cost": sum(vehicles.mapped("actual_vehicle_cost")),
                "sales_revenue": sum(vehicles.mapped("selling_price")),
                "gross_profit": sum(vehicles.mapped("gross_profit")),
            })

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        """Live figures for the Management Dashboard, for the companies selected in the switcher.

        Sales, applications and turnaround cover the period (default: this month); stock,
        aging, documents and cash are as of today."""
        Vehicle = self.env["autoboutique.vehicle"]
        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(date_from) or today.replace(day=1)
        date_to = fields.Date.to_date(date_to) or today
        vehicles = Vehicle.search([("company_id", "in", self.env.companies.ids)])
        stock = vehicles.filtered(lambda v: v.state in STOCK_STATES)
        sold = vehicles.filtered(lambda v: v.state in SOLD_STATES)
        state_labels = dict(Vehicle._fields["state"]._description_selection(self.env))

        def received_on(vehicle):
            return vehicle.receiving_id.received_date or vehicle.create_date.date()

        def sold_on(vehicle):
            order_date = vehicle.sale_order_id.date_order
            return vehicle.invoice_id.invoice_date or (order_date and order_date.date()) or vehicle.release_date

        sold_in_period = sold.filtered(lambda v: sold_on(v) and date_from <= sold_on(v) <= date_to)
        margins = [v.margin_percent for v in sold_in_period.filtered(lambda v: v.selling_price_untaxed)]

        # Monthly trend: the months of the period, and at least the 6 months up to its end.
        last_month = date_to.replace(day=1)
        month = min(date_from.replace(day=1), last_month - relativedelta(months=5))
        months = []
        while month <= last_month:
            months.append(month)
            month += relativedelta(months=1)
        monthly = {month: {"count": 0, "revenue": 0.0, "profit": 0.0} for month in months}
        for vehicle in sold:
            sale_date = sold_on(vehicle)
            bucket = monthly.get(sale_date.replace(day=1)) if sale_date else None
            if bucket is not None:
                bucket["count"] += 1
                bucket["revenue"] += vehicle.selling_price_untaxed
                bucket["profit"] += vehicle.gross_profit

        days_in_stock = {vehicle.id: (today - received_on(vehicle)).days for vehicle in stock}
        aging = {label: 0 for label in AGING_BUCKETS}
        for days in days_in_stock.values():
            label = next(label for label, limit in AGING_BUCKETS.items() if days <= limit)
            aging[label] += 1

        makes = {}
        for vehicle in stock:
            makes[vehicle.make] = makes.get(vehicle.make, 0) + 1
        top_makes = sorted(makes.items(), key=lambda item: -item[1])[:8]

        Application = self.env["autoboutique.sales.application"]
        applications = Application.search([("company_id", "in", self.env.companies.ids),
                                           ("application_date", ">=", date_from), ("application_date", "<=", date_to)])
        agents = {}
        for application in applications.filtered(lambda a: a.state in ("reserved", "sold")):
            agent = agents.setdefault(application.sales_agent_id.name or "Unassigned", {"count": 0, "revenue": 0.0})
            agent["count"] += 1
            agent["revenue"] += application.selling_price
        application_labels = dict(applications._fields["state"]._description_selection(self.env))
        open_states = ("draft", "approval", "approved", "reserved")

        oldest = sorted(stock, key=lambda v: -days_in_stock[v.id])[:8]
        return {
            "currency": self.env.company.currency_id.name,
            "period": {"from": fields.Date.to_string(date_from), "to": fields.Date.to_string(date_to)},
            "kpis": {
                "in_stock": len(stock),
                "ready": len(stock.filtered(lambda v: v.state == "ready")),
                "inventory_value": sum(stock.mapped("actual_vehicle_cost")),
                "avg_days_in_stock": round(sum(days_in_stock.values()) / len(stock)) if stock else 0,
                "sold": len(sold_in_period),
                "revenue": sum(sold_in_period.mapped("selling_price_untaxed")),
                "profit": sum(sold_in_period.mapped("gross_profit")),
                "avg_margin": round(sum(margins) / len(margins), 1) if margins else 0.0,
                "open_applications": Application.search_count([
                    ("company_id", "in", self.env.companies.ids), ("state", "in", open_states)]),
            },
            "pipeline": [{"state": key, "label": state_labels[key], "count": len(vehicles.filtered(lambda v, k=key: v.state == k))}
                         for key in STOCK_STATES + SOLD_STATES],
            "monthly": [{"label": month.strftime("%b %Y"), **values} for month, values in monthly.items()],
            "aging": [{"label": label, "count": count} for label, count in aging.items()],
            "costs": {
                "Acquisition": sum(stock.mapped("acquisition_cost")),
                "Repairs & parts": sum(stock.mapped("repair_actual_cost")),
                "Detailing": sum(stock.mapped("detailing_actual_cost")),
            },
            "makes": [{"label": make or "Unknown", "count": count} for make, count in top_makes],
            "agents": [{"label": name, **values} for name, values in sorted(agents.items(), key=lambda item: -item[1]["revenue"])],
            "applications": [{"state": key, "label": application_labels[key],
                              "count": len(applications.filtered(lambda a, k=key: a.state == k))} for key in open_states + ("sold",)],
            "oldest": [{"id": v.id, "name": v.name, "state": state_labels[v.state], "days": days_in_stock[v.id],
                        "cost": v.actual_vehicle_cost} for v in oldest],
            "turnaround": self._dashboard_turnaround(vehicles, date_from, date_to, state_labels),
            "documents": self._dashboard_documents(vehicles, today),
            "cash": self._dashboard_cash(today),
        }

    def _dashboard_turnaround(self, vehicles, date_from, date_to, state_labels):
        """Average days per stage: stays that ended in the period, and cars waiting there now."""
        now = fields.Datetime.now()
        period_start = fields.Datetime.to_datetime(date_from)
        period_end = fields.Datetime.to_datetime(date_to) + relativedelta(days=1)
        logs = self.env["autoboutique.vehicle.stage.log"].sudo().search(
            [("vehicle_id", "in", vehicles.ids)], order="vehicle_id, date_in, id")
        by_vehicle = {}
        for log in logs:
            by_vehicle.setdefault(log.vehicle_id.id, []).append(log)
        completed = {state: [] for state in STOCK_STATES}
        waiting = {state: [] for state in STOCK_STATES}
        cycle = []
        for history in by_vehicle.values():
            for log, following in zip(history, history[1:] + [None]):
                if log.state not in completed:
                    continue
                if following is None:
                    waiting[log.state].append((now - log.date_in).total_seconds() / 86400)
                elif period_start <= following.date_in < period_end:
                    completed[log.state].append((following.date_in - log.date_in).total_seconds() / 86400)
            entered = {log.state: log.date_in for log in history}
            if "receiving" in entered and "ready" in entered and period_start <= entered["ready"] < period_end:
                cycle.append((entered["ready"] - entered["receiving"]).total_seconds() / 86400)

        def average(values):
            return round(sum(values) / len(values), 1) if values else 0.0

        return {
            "stages": [{"state": state, "label": state_labels[state],
                        "avg_days": average(completed[state]), "done": len(completed[state]),
                        "waiting_days": average(waiting[state]), "waiting": len(waiting[state])}
                       for state in STOCK_STATES],
            "cycle_days": average(cycle),
            "cycle_cars": len(cycle),
        }

    def _dashboard_documents(self, vehicles, today):
        """Released cars whose OR/CR, plate or insurance is not done yet."""
        rows = []
        for vehicle in vehicles.filtered(lambda v: v.state == "released"):
            registration = vehicle.registration_ids[:1]
            insurance = vehicle.insurance_ids.sorted("id", reverse=True)[:1]
            rows.append({
                "id": vehicle.id,
                "name": vehicle.name,
                "customer": vehicle.customer_id.name or vehicle.sale_order_id.partner_id.name or "",
                "days": (today - vehicle.release_date).days if vehicle.release_date else 0,
                "orcr": registration.orcr_status == "complete",
                "plate": registration.plate_status == "complete",
                "insurance": insurance.status == "active",
            })
        return sorted(rows, key=lambda row: -row["days"])

    def _dashboard_cash(self, today):
        """Receivables by age, payables due and bank balance, for users with accounting access only."""
        user = self.env.user
        if not (user.has_group("account.group_account_invoice") or user.has_group("account.group_account_readonly")):
            return False
        company_ids = self.env.companies.ids
        Move = self.env["account.move"]
        open_domain = [("company_id", "in", company_ids), ("state", "=", "posted"),
                       ("payment_state", "in", ("not_paid", "partial"))]
        aging = dict.fromkeys(RECEIVABLE_BUCKETS, 0.0)
        for invoice in Move.search(open_domain + [("move_type", "=", "out_invoice")]):
            late = (today - (invoice.invoice_date_due or invoice.invoice_date or today)).days
            label = next(label for label, limit in RECEIVABLE_BUCKETS.items() if late <= limit)
            aging[label] += invoice.amount_residual_signed
        payable_overdue = payable_due_30 = 0.0
        for bill in Move.search(open_domain + [("move_type", "=", "in_invoice")]):
            due = bill.invoice_date_due or bill.invoice_date or today
            if due < today:
                payable_overdue -= bill.amount_residual_signed
            elif due <= today + relativedelta(days=30):
                payable_due_30 -= bill.amount_residual_signed
        accounts = self.env["account.journal"].search(
            [("company_id", "in", company_ids), ("type", "in", ("bank", "cash"))]).default_account_id
        [(bank_balance,)] = self.env["account.move.line"]._read_group(
            [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"), ("company_id", "in", company_ids)],
            [], ["balance:sum"])
        receivable = sum(aging.values())
        return {
            "receivable": receivable,
            "receivable_overdue": receivable - aging["Not yet due"],
            "aging": [{"label": label, "amount": amount} for label, amount in aging.items()],
            "payable_overdue": payable_overdue,
            "payable_due_30": payable_due_30,
            "bank_balance": bank_balance or 0.0,
        }
