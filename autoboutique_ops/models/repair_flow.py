"""Checklist -> repair -> material request -> purchase, connected end to end.

* A failed QC turns every Needs Attention checklist point into a repair line
  linked back to that point, so the repair lead prices exactly what the
  inspector flagged.
* The final QC re-opens the same points with a "re-check" remark.
* Material requests take parts from stock when enough is on hand; anything
  short is switched to To Purchase, the vendor is taken from the product's
  vendor list, and the draft RFQ lines stay linked to the request and repair.
* When the parts receipt is validated, the repair lead gets a to-do to issue
  the parts and close the request.
"""
from odoo import api, fields, models

from .automation import close_todo, run_safely, schedule_todo


class QCLine(models.Model):
    _inherit = "autoboutique.qc.line"

    repair_line_ids = fields.One2many("autoboutique.repair.line", "qc_line_id", string="Repair Lines")
    repair_status = fields.Char("Repair", compute="_compute_repair_status")

    @api.depends("repair_line_ids.repair_id.state")
    def _compute_repair_status(self):
        labels = dict(self.env["autoboutique.repair"]._fields["state"].selection)
        for line in self:
            repairs = line.repair_line_ids.repair_id
            line.repair_status = ", ".join(labels.get(state, state) for state in set(repairs.mapped("state")))


class RepairLine(models.Model):
    _inherit = "autoboutique.repair.line"

    qc_line_id = fields.Many2one("autoboutique.qc.line", string="Checklist Point", index=True, ondelete="set null")
    mrf_line_ids = fields.One2many("autoboutique.mrf.line", "repair_line_id", string="Material Request Items")


class QC(models.Model):
    _inherit = "autoboutique.qc"

    def action_process_result(self):
        result = super().action_process_result()
        for qc in self.filtered("repair_id"):
            qc._ab_create_repair_lines()
        return result

    def _ab_create_repair_lines(self):
        """One repair line per Needs Attention point that has none yet."""
        self.ensure_one()
        points = self.line_ids.filtered(lambda line: line.status == "attention" and not line.repair_line_ids)
        if not points or self.repair_id.state == "done":
            return
        self.repair_id.write({"line_ids": [(0, 0, {
            "name": " - ".join(filter(None, [point.name, point.remarks])),
            "cost_type": "labor",
            "qc_line_id": point.id,
            "company_id": self.company_id.id,
        }) for point in points]})

    def _ab_load_checklist(self):
        super()._ab_load_checklist()
        for qc in self.filtered(lambda q: q.inspection_type == "final"):
            flagged = qc.vehicle_id.qc_ids.filtered(lambda q: q.inspection_type == "initial").line_ids.filtered(
                lambda line: line.status == "attention")
            by_item = {line.item_id.id: line for line in flagged if line.item_id}
            for line in qc.line_ids.filtered(lambda line: line.item_id.id in by_item and not line.remarks):
                line.remarks = "Re-check after repair: %s" % (by_item[line.item_id.id].remarks or "flagged at initial QC")


class Repair(models.Model):
    _inherit = "autoboutique.repair"

    def _ab_create_mrf(self):
        super()._ab_create_mrf()
        for mrf in self.env["autoboutique.mrf"].search([("repair_id", "in", self.ids), ("state", "=", "submitted")]):
            mrf._ab_route_by_availability()


class MRF(models.Model):
    _inherit = "autoboutique.mrf"

    def _ab_route_by_availability(self):
        """Parts not on hand are bought; the vendor comes from the product's vendor list."""
        for mrf in self:
            short = mrf.item_ids.filtered(lambda line: line.source == "stock" and line.qty_available < line.quantity)
            if short:
                short.write({"source": "purchase"})
                mrf.message_post(body="Not enough stock for %s: switched to To Purchase." % ", ".join(
                    short.mapped("product_id.display_name")))
            mrf._ab_default_vendor()

    def _ab_default_vendor(self):
        for mrf in self.filtered(lambda m: not m.vendor_id):
            sellers = mrf.item_ids.filtered(lambda line: line.source == "purchase").product_id.seller_ids
            vendor = sellers.filtered(lambda s: s.company_id in (mrf.company_id, self.env["res.company"]))[:1].partner_id
            if vendor:
                mrf.vendor_id = vendor

    def action_approve_request(self):
        self._ab_default_vendor()
        result = super().action_approve_request()
        for mrf in self.filtered("purchase_order_id"):
            order_lines = mrf.purchase_order_id.order_line
            for item in mrf.item_ids.filtered(lambda line: line.source == "purchase" and not line.purchase_order_line_id):
                order_line = order_lines.filtered(lambda ol, item=item: ol.product_id == item.product_id)[:1]
                if order_line:
                    item.purchase_order_line_id = order_line
                    if item.repair_line_id:
                        item.repair_line_id.purchase_order_line_id = order_line
        return result


class MRFLine(models.Model):
    _inherit = "autoboutique.mrf.line"

    qty_available = fields.Float("On Hand", compute="_compute_qty_available")

    @api.depends("product_id")
    def _compute_qty_available(self):
        for line in self:
            company = line.mrf_id.company_id or line.company_id or self.env.company
            line.qty_available = line.product_id.with_company(company).qty_available if line.product_id else 0.0

    @api.onchange("product_id", "quantity")
    def _onchange_route_by_availability(self):
        if self.product_id and self.product_id.is_storable:
            self.source = "stock" if self.qty_available >= self.quantity else "purchase"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        result = super()._action_done()
        orders = self.move_ids.purchase_line_id.order_id
        if orders:
            mrfs = self.env["autoboutique.mrf"].sudo().search([
                ("purchase_order_id", "in", orders.ids), ("state", "not in", ("closed", "rejected")),
            ])
            for mrf in mrfs:
                mrf = mrf.sudo(False).with_company(mrf.company_id)
                run_safely(mrf, "notify that parts arrived", mrf._ab_parts_received)
        return result


class MRFReceipt(models.Model):
    _inherit = "autoboutique.mrf"

    def _ab_parts_received(self):
        for mrf in self:
            close_todo(mrf.purchase_order_id, "Confirm parts RFQ")
            mrf.message_post(body="Parts received on %s." % ", ".join(
                mrf.purchase_order_id.picking_ids.filtered(lambda p: p.state == "done").mapped("name")))
            schedule_todo(mrf, "repair", "Parts arrived: issue parts and close material request",
                          note="Purchase order %s was received." % mrf.purchase_order_id.name)
