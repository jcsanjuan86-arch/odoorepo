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
    notes = fields.Text()


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
    qc_ids = fields.One2many("autoboutique.qc", "vehicle_id")
    repair_ids = fields.One2many("autoboutique.repair", "vehicle_id")
    mrf_ids = fields.One2many("autoboutique.mrf", "vehicle_id")
    detailing_ids = fields.One2many("autoboutique.detailing", "vehicle_id")
    acquisition_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    documents_verified = fields.Boolean()
    ready_for_sale_approved = fields.Boolean()
    state = fields.Selection(
        [("receiving", "Receiving"), ("qc", "QC"),
         ("repair", "Repair"), ("detailing", "Detailing"),
         ("ready", "Ready for Sale"), ("reserved", "Reserved"),
         ("sold", "Sold"), ("released", "Released")],
        default="receiving", required=True
    )

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
    notes = fields.Text()

    @api.constrains("vehicle_id", "repair_id")
    def _check_repair_vehicle(self):
        for mrf in self:
            if mrf.repair_id.vehicle_id != mrf.vehicle_id:
                raise ValidationError("The MRF and repair must reference the same vehicle.")


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
