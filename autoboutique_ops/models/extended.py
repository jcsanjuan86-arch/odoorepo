from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VehicleExtension(models.Model):
    _inherit = "autoboutique.vehicle"

    sales_application_ids = fields.One2many("autoboutique.sales.application", "vehicle_id")
    release_ids = fields.One2many("autoboutique.vehicle.release", "vehicle_id")
    registration_ids = fields.One2many("autoboutique.registration", "vehicle_id")
    insurance_ids = fields.One2many("autoboutique.insurance", "vehicle_id")
    document_ids = fields.One2many("autoboutique.document", "vehicle_id")
    commission_ids = fields.One2many("autoboutique.commission", "vehicle_id")
    customer_id = fields.Many2one("res.partner")
    sales_agent_id = fields.Many2one("res.users")
    selling_price = fields.Monetary(currency_field="currency_id")
    gross_profit = fields.Monetary(compute="_compute_profit", currency_field="currency_id")
    registration_status = fields.Selection([("draft", "Draft"), ("processing", "Processing"), ("completed", "Completed")], compute="_compute_document_rollups")
    insurance_status = fields.Selection([("draft", "Draft"), ("active", "Active"), ("expired", "Expired")], compute="_compute_document_rollups")
    missing_document_count = fields.Integer(compute="_compute_document_rollups")

    @api.depends("selling_price", "actual_vehicle_cost")
    def _compute_profit(self):
        for vehicle in self:
            vehicle.gross_profit = vehicle.selling_price - vehicle.actual_vehicle_cost

    @api.depends("registration_ids.status", "insurance_ids.status", "document_ids.status", "document_ids.required")
    def _compute_document_rollups(self):
        for vehicle in self:
            vehicle.missing_document_count = len(vehicle.document_ids.filtered(
                lambda document: document.required and document.status != "completed"
            ))
            vehicle.registration_status = vehicle.registration_ids[:1].status if vehicle.registration_ids else False
            vehicle.insurance_status = vehicle.insurance_ids[:1].status if vehicle.insurance_ids else False


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
            release.vehicle_id.write({"state": "released", "sale_order_id": release.sale_order_id.id, "invoice_id": invoice.id, "payment_received": True, "release_date": fields.Date.context_today(self)})
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
