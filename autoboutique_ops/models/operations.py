from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CompanyMixin(models.AbstractModel):
    _name = "autoboutique.company.mixin"
    _description = "Autoboutique Company Fields"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )


class Bid(models.Model):
    _name = "autoboutique.bid"
    _description = "Vehicle Bid Lot"
    _inherit = "autoboutique.company.mixin"
    _order = "id desc"

    name = fields.Char("Bid / Lot", required=True)
    supplier_id = fields.Many2one("res.partner", string="Supplier")
    bid_date = fields.Date(default=fields.Date.context_today)
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"),
         ("won", "Won"), ("lost", "Lost")], default="draft", required=True
    )
    total_bid = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    line_ids = fields.One2many("autoboutique.bid.line", "bid_id", string="Cars in Lot")
    submitted_by = fields.Many2one("res.users", readonly=True)
    submitted_on = fields.Datetime(readonly=True)
    reviewed_by = fields.Many2one("res.users", readonly=True)
    reviewed_on = fields.Datetime(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_on = fields.Datetime(readonly=True)
    rejection_reason = fields.Text()
    notes = fields.Text()

    def action_approve_bid(self):
        for bid in self:
            if not bid.line_ids.filtered("selected"):
                raise ValidationError("Select at least one car in the lot before approving the bid.")
        self.write({"state": "won", "approved_by": self.env.user.id, "approved_on": fields.Datetime.now()})


class BidLine(models.Model):
    _name = "autoboutique.bid.line"
    _description = "Car in Bid Lot"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char("Description", required=True)
    bid_id = fields.Many2one("autoboutique.bid", required=True, ondelete="cascade")
    vin = fields.Char("VIN / Chassis")
    make = fields.Char(required=True)
    model = fields.Char(required=True)
    model_year = fields.Integer("Year")
    allocated_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    selected = fields.Boolean("Selected for Purchase")
    purchase_order_line_id = fields.Many2one("purchase.order.line")
    vehicle_id = fields.Many2one("autoboutique.vehicle")

    @api.constrains("bid_id", "company_id")
    def _check_bid_company(self):
        for line in self:
            if line.bid_id.company_id != line.company_id:
                raise ValidationError("The car and its bid lot must belong to the same company.")


class Receiving(models.Model):
    _name = "autoboutique.receiving"
    _description = "Vehicle Receiving"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    bid_line_id = fields.Many2one("autoboutique.bid.line", required=True)
    purchase_order_id = fields.Many2one("purchase.order")
    receipt_id = fields.Many2one("stock.picking")
    lot_id = fields.Many2one("stock.lot", string="VIN Serial / Lot")
    product_id = fields.Many2one("product.product", string="Inventory Product")
    received_date = fields.Date(default=fields.Date.context_today)
    actual_mileage = fields.Integer()
    condition = fields.Text()
    state = fields.Selection(
        [("draft", "Draft"), ("received", "Received"),
         ("verified", "Verified")], default="draft", required=True
    )
    vehicle_id = fields.Many2one("autoboutique.vehicle")

    def action_mark_received(self):
        self.write({"state": "received"})

    def action_create_vehicle_master(self):
        for receiving in self:
            if receiving.state not in ("received", "verified"):
                raise ValidationError("Mark the car received before creating its Vehicle Master record.")
            if not receiving.receipt_id or receiving.receipt_id.state != "done":
                raise ValidationError("Link a validated Inventory Receipt before creating the Vehicle Master.")
            if receiving.vehicle_id:
                continue
            bid_line = receiving.bid_line_id
            if not bid_line.vin:
                raise ValidationError("Enter the VIN / chassis number on the bid-line first.")
            vehicle = self.env["autoboutique.vehicle"].create({
                "name": " ".join(filter(None, [bid_line.make, bid_line.model, bid_line.vin])),
                "vin": bid_line.vin,
                "make": bid_line.make,
                "model": bid_line.model,
                "model_year": bid_line.model_year,
                "mileage": receiving.actual_mileage,
                "supplier_id": receiving.bid_line_id.bid_id.supplier_id.id,
                "bid_id": bid_line.bid_id.id,
                "bid_line_id": bid_line.id,
                "receiving_id": receiving.id,
                "purchase_order_id": receiving.purchase_order_id.id,
                "product_id": receiving.product_id.id,
                "lot_id": receiving.lot_id.id,
                "acquisition_cost": bid_line.allocated_cost,
                "company_id": receiving.company_id.id,
            })
            receiving.vehicle_id = vehicle
            bid_line.vehicle_id = vehicle


class Vehicle(models.Model):
    _name = "autoboutique.vehicle"
    _description = "Vehicle Master"
    _inherit = "autoboutique.company.mixin"
    _order = "id desc"

    name = fields.Char(required=True)
    vin = fields.Char(index=True)
    make = fields.Char(required=True)
    model = fields.Char(required=True)
    model_year = fields.Integer("Year")
    variant = fields.Char()
    plate_number = fields.Char()
    mileage = fields.Integer()
    supplier_id = fields.Many2one("res.partner")
    bid_id = fields.Many2one("autoboutique.bid")
    bid_line_id = fields.Many2one("autoboutique.bid.line")
    receiving_id = fields.Many2one("autoboutique.receiving")
    purchase_order_id = fields.Many2one("purchase.order")
    purchase_order_line_id = fields.Many2one("purchase.order.line")
    product_id = fields.Many2one("product.product", string="Inventory Product")
    lot_id = fields.Many2one("stock.lot", string="VIN Serial / Lot")
    sale_order_id = fields.Many2one("sale.order", string="Sales Order")
    invoice_id = fields.Many2one("account.move", string="Customer Invoice")
    payment_received = fields.Boolean(readonly=True)
    release_date = fields.Date(readonly=True)
    registration_complete = fields.Boolean()
    insurance_complete = fields.Boolean()
    qc_ids = fields.One2many("autoboutique.qc", "vehicle_id")
    repair_ids = fields.One2many("autoboutique.repair", "vehicle_id")
    mrf_ids = fields.One2many("autoboutique.mrf", "vehicle_id")
    detailing_ids = fields.One2many("autoboutique.detailing", "vehicle_id")
    acquisition_cost = fields.Monetary(currency_field="currency_id")
    repair_actual_cost = fields.Monetary(
        string="Actual Repair Cost", compute="_compute_actual_costs", currency_field="currency_id"
    )
    detailing_actual_cost = fields.Monetary(
        string="Actual Detailing Cost", compute="_compute_actual_costs", currency_field="currency_id"
    )
    actual_vehicle_cost = fields.Monetary(
        string="Actual Vehicle Cost", compute="_compute_actual_costs", currency_field="currency_id"
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    documents_verified = fields.Boolean()
    ready_for_sale_approved = fields.Boolean()
    state = fields.Selection(
        [("receiving", "Receiving"), ("qc", "QC"),
         ("repair", "Repair"), ("detailing", "Detailing"),
         ("ready", "Ready for Sale"), ("reserved", "Reserved"),
         ("sold", "Sold"), ("payment", "Payment Received"),
         ("released", "Released"), ("documents", "Documents Complete")],
        default="receiving", required=True
    )

    @api.depends("acquisition_cost", "repair_ids.line_ids.actual_cost", "detailing_ids.actual_cost")
    def _compute_actual_costs(self):
        for vehicle in self:
            repair_cost = sum(vehicle.repair_ids.mapped("line_ids.actual_cost"))
            detailing_cost = sum(vehicle.detailing_ids.mapped("actual_cost"))
            vehicle.repair_actual_cost = repair_cost
            vehicle.detailing_actual_cost = detailing_cost
            vehicle.actual_vehicle_cost = vehicle.acquisition_cost + repair_cost + detailing_cost

    def _require_initial_qc(self):
        if not self.qc_ids.filtered(lambda q: q.inspection_type == "initial" and q.result == "pass"):
            raise ValidationError("Record a passing initial QC before moving to repair.")

    def _require_final_qc(self):
        if not self.qc_ids.filtered(lambda q: q.inspection_type == "final" and q.result == "pass"):
            raise ValidationError("Record a passing final QC before continuing.")

    def action_start_qc(self):
        self.write({"state": "qc"})

    def action_start_repair(self):
        self._require_initial_qc()
        self.write({"state": "repair"})

    def action_start_detailing(self):
        self._require_final_qc()
        if self.repair_ids.filtered(lambda r: r.state != "done"):
            raise ValidationError("Complete all repair assessments first.")
        if self.mrf_ids.filtered(lambda m: m.state != "closed"):
            raise ValidationError("Close all material requests first.")
        self.write({"state": "detailing"})

    def action_mark_ready_for_sale(self):
        self.write({"state": "ready"})

    def action_mark_reserved(self):
        if not self.sale_order_id:
            raise ValidationError("Link the confirmed Sales Order before reserving this vehicle.")
        self.write({"state": "reserved"})

    def action_mark_sold(self):
        if not self.sale_order_id:
            raise ValidationError("Link the Sales Order before marking this vehicle sold.")
        self.write({"state": "sold"})

    def action_confirm_payment(self):
        if not self.invoice_id or self.invoice_id.state != "posted":
            raise ValidationError("Link a posted customer invoice before recording payment.")
        if self.invoice_id.payment_state not in ("in_payment", "paid"):
            raise ValidationError("The linked invoice has not received payment yet.")
        self.write({"payment_received": True, "state": "payment"})

    def action_release_vehicle(self):
        if not self.payment_received:
            raise ValidationError("Record customer payment before releasing the vehicle.")
        self.write({"release_date": fields.Date.context_today(self), "state": "released"})

    def action_complete_documents(self):
        if not self.release_date:
            raise ValidationError("Release the vehicle before completing handover documents.")
        if not self.registration_complete or not self.insurance_complete or not self.documents_verified:
            raise ValidationError("Complete registration, insurance, and required documents first.")
        self.write({"state": "documents"})

    @api.constrains("vin", "company_id")
    def _check_unique_vin(self):
        for vehicle in self.filtered("vin"):
            if self.search_count([
                ("vin", "=", vehicle.vin),
                ("company_id", "=", vehicle.company_id.id),
                ("id", "!=", vehicle.id),
            ]):
                raise ValidationError("VIN must be unique within a company.")

    @api.constrains("state", "documents_verified", "ready_for_sale_approved")
    def _check_ready_for_sale(self):
        for vehicle in self:
            if vehicle.state != "ready":
                continue
            if not vehicle.documents_verified or not vehicle.ready_for_sale_approved:
                raise ValidationError("Verify documents and approve sale readiness first.")
            if not vehicle.qc_ids.filtered(
                lambda q: q.inspection_type == "final" and q.result == "pass"
            ):
                raise ValidationError("A passing final QC is required.")
            if vehicle.repair_ids.filtered(lambda r: r.state != "done"):
                raise ValidationError("Complete all repair assessments first.")
            if vehicle.mrf_ids.filtered(lambda m: m.state != "closed"):
                raise ValidationError("Close all material requests first.")
            if not vehicle.detailing_ids.filtered(lambda d: d.state == "approved"):
                raise ValidationError("Approved detailing is required.")


class QC(models.Model):
    _name = "autoboutique.qc"
    _description = "Vehicle QC Inspection"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    inspection_date = fields.Date(default=fields.Date.context_today)
    inspection_type = fields.Selection(
        [("initial", "Initial"), ("final", "Final")], required=True, default="initial"
    )
    result = fields.Selection(
        [("pending", "Pending"), ("pass", "Pass"), ("fail", "Fail")],
        default="pending", required=True
    )
    findings = fields.Text()
    repair_id = fields.Many2one("autoboutique.repair")
    inspector_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    mileage = fields.Integer()
    repair_required = fields.Boolean()

    def action_process_result(self):
        for qc in self:
            if qc.result == "pending":
                raise ValidationError("Record a QC result before processing the inspection.")
            if qc.result == "pass":
                qc.vehicle_id.state = "qc"
                continue
            qc.repair_required = True
            qc.vehicle_id.state = "repair"
            if not qc.repair_id:
                qc.repair_id = self.env["autoboutique.repair"].create({
                    "name": "Repair - %s" % qc.vehicle_id.name,
                    "vehicle_id": qc.vehicle_id.id,
                    "qc_id": qc.id,
                    "company_id": qc.company_id.id,
                })


class Repair(models.Model):
    _name = "autoboutique.repair"
    _description = "Vehicle Repair Assessment"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    qc_id = fields.Many2one("autoboutique.qc")
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"),
         ("in_progress", "In Progress"), ("done", "Done")],
        default="draft", required=True
    )
    line_ids = fields.One2many("autoboutique.repair.line", "repair_id")
    notes = fields.Text()
    estimated_total = fields.Monetary(compute="_compute_cost_totals", currency_field="currency_id")
    actual_total = fields.Monetary(compute="_compute_cost_totals", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    @api.depends("line_ids.estimated_cost", "line_ids.actual_cost")
    def _compute_cost_totals(self):
        for repair in self:
            repair.estimated_total = sum(repair.line_ids.mapped("estimated_cost"))
            repair.actual_total = sum(repair.line_ids.mapped("actual_cost"))


class RepairLine(models.Model):
    _name = "autoboutique.repair.line"
    _description = "Repair Cost Line"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    repair_id = fields.Many2one("autoboutique.repair", required=True, ondelete="cascade")
    vehicle_id = fields.Many2one("autoboutique.vehicle", related="repair_id.vehicle_id", store=True)
    cost_type = fields.Selection(
        [("stock", "Stock Part"), ("purchase", "External Part"),
         ("labor", "Internal Labor"), ("service", "External Service"),
         ("fee", "Fixed Service Fee")], required=True
    )
    product_id = fields.Many2one("product.product")
    quantity = fields.Float(default=1)
    estimated_cost = fields.Monetary(currency_field="currency_id")
    actual_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    consumed = fields.Boolean("Stock Actually Consumed")
    stock_move_id = fields.Many2one("stock.move")
    purchase_order_line_id = fields.Many2one("purchase.order.line")
    vendor_bill_id = fields.Many2one("account.move")


class MRF(models.Model):
    _name = "autoboutique.mrf"
    _description = "Vehicle Material Request"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    repair_id = fields.Many2one("autoboutique.repair", required=True)
    requested_by = fields.Many2one("res.users", default=lambda self: self.env.user)
    approved_by = fields.Many2one("res.users")
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"),
         ("approved", "Approved"), ("issued", "Issued"),
         ("closed", "Closed"), ("rejected", "Rejected")],
        default="draft", required=True
    )
    item_ids = fields.One2many("autoboutique.mrf.line", "mrf_id", string="Items")
    vendor_id = fields.Many2one("res.partner")
    purchase_order_id = fields.Many2one("purchase.order", readonly=True)
    notes = fields.Text()

    @api.constrains("vehicle_id", "repair_id")
    def _check_repair_vehicle(self):
        for mrf in self:
            if mrf.repair_id.vehicle_id != mrf.vehicle_id:
                raise ValidationError("The MRF and repair must reference the same vehicle.")

    def action_approve_request(self):
        for mrf in self:
            if not mrf.item_ids:
                raise ValidationError("Add at least one requested part.")
            mrf.approved_by = self.env.user
            mrf.state = "approved"
            purchase_items = mrf.item_ids.filtered(lambda line: line.source == "purchase")
            if purchase_items:
                if not mrf.vendor_id:
                    raise ValidationError("Select a vendor before creating a draft RFQ for purchase items.")
                order = self.env["purchase.order"].create({
                    "partner_id": mrf.vendor_id.id,
                    "company_id": mrf.company_id.id,
                    "origin": "%s / %s" % (mrf.name, mrf.vehicle_id.name),
                    "order_line": [(0, 0, {
                        "product_id": line.product_id.id,
                        "product_qty": line.quantity,
                        "price_unit": line.product_id.standard_price,
                        "name": line.product_id.display_name,
                    }) for line in purchase_items],
                })
                mrf.purchase_order_id = order


class MRFLine(models.Model):
    _name = "autoboutique.mrf.line"
    _description = "Material Request Item"
    _inherit = "autoboutique.company.mixin"

    mrf_id = fields.Many2one("autoboutique.mrf", required=True, ondelete="cascade")
    repair_line_id = fields.Many2one("autoboutique.repair.line")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(required=True, default=1)
    source = fields.Selection(
        [("stock", "From Stock"), ("purchase", "To Purchase")], required=True
    )
    purchase_order_line_id = fields.Many2one("purchase.order.line")
    stock_move_id = fields.Many2one("stock.move")
    issued_quantity = fields.Float()

    @api.constrains("quantity", "issued_quantity")
    def _check_quantities(self):
        for line in self:
            if line.quantity <= 0 or line.issued_quantity < 0 or line.issued_quantity > line.quantity:
                raise ValidationError("Requested and issued quantities are inconsistent.")


class Detailing(models.Model):
    _name = "autoboutique.detailing"
    _description = "Vehicle Detailing Job"
    _inherit = "autoboutique.company.mixin"

    name = fields.Char(required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("in_progress", "In Progress"),
         ("done", "Done"), ("approved", "Approved")],
        default="draft", required=True
    )
    exterior_done = fields.Boolean()
    interior_done = fields.Boolean()
    engine_bay_done = fields.Boolean()
    paint_done = fields.Boolean()
    supervisor_id = fields.Many2one("res.users")
    actual_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    notes = fields.Text()

    @api.constrains("state", "exterior_done", "interior_done", "supervisor_id")
    def _check_approval(self):
        for job in self:
            if job.state == "approved" and not (
                job.exterior_done and job.interior_done and job.supervisor_id
            ):
                raise ValidationError("Complete exterior and interior detailing and assign a supervisor.")
