"""End-to-end workflow automation for the Autoboutique vehicle chain.

Every hand-off creates the next record and a to-do for the responsible person
(Settings > Autoboutique Automation). Documents that post stock or accounting
entries (purchase orders, receipts, sales orders, invoices, payments) are only
ever *drafted*; people confirm them, and the vehicle then advances by itself.

Automation that runs inside a native action (validating a receipt, confirming
a sale, registering a payment) never blocks that action: failures are rolled
back to a savepoint, written to the record's chatter, and assigned to the
operations manager.
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

TODO = "mail.mail_activity_data_todo"


def _responsible(record, role):
    company = record.company_id if "company_id" in record._fields and record.company_id else record.env.company
    return company.sudo()[f"ab_{role}_user_id"] or record.env.user


def schedule_todo(record, role, summary, note="", days=1):
    """Assign one open to-do per record and summary to the role's user."""
    for rec in record:
        user = _responsible(rec, role)
        if rec.activity_ids.filtered(lambda a: a.summary == summary):
            continue
        rec.sudo().activity_schedule(
            TODO,
            date_deadline=fields.Date.add(fields.Date.context_today(rec), days=days),
            summary=summary, note=note, user_id=user.id,
        )


def close_todo(record, summary):
    activities = record.sudo().activity_ids.filtered(lambda a: a.summary == summary)
    if activities:
        activities.action_feedback(feedback="Completed automatically.")


def run_safely(record, label, func):
    """Run an automation step without ever blocking the user's own action."""
    try:
        with record.env.cr.savepoint():
            return func()
    except Exception as exc:  # noqa: BLE001 - reported to the manager instead of raised
        _logger.warning("autoboutique_automation_failed step=%r record=%s: %s", label, record, exc)
        record.env.invalidate_all()
        message = "Automation could not %s: %s" % (label, exc)
        for rec in record:
            rec.sudo().message_post(body=message)
        schedule_todo(record, "manager", "Automation needs attention: %s" % label, note=str(exc))
        return None


class AutomationMixin(models.AbstractModel):
    _name = "autoboutique.automation.mixin"
    _description = "Autoboutique Automation"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    def _ab_todo(self, role, summary, note="", days=1):
        schedule_todo(self, role, summary, note=note, days=days)

    def _ab_done(self, summary):
        close_todo(self, summary)


# --- Bid lot -> RFQ -------------------------------------------------------------

class Bid(models.Model):
    _name = "autoboutique.bid"
    _inherit = ["autoboutique.bid", "autoboutique.automation.mixin"]

    purchase_order_id = fields.Many2one("purchase.order", string="Vehicle RFQ", readonly=True, copy=False)

    def action_approve_bid(self):
        for bid in self:
            if not bid.supplier_id:
                raise ValidationError("Set the supplier first: the vehicle RFQ is created automatically on approval.")
        result = super().action_approve_bid()
        for bid in self:
            bid._ab_create_rfq()
        return result

    def _ab_create_rfq(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.selected and not line.purchase_order_line_id)
        if not lines:
            return
        Receiving = self.env["autoboutique.receiving"]
        receivings = {line.id: Receiving.search([("bid_line_id", "=", line.id)], limit=1) for line in lines}
        order = self.env["purchase.order"].with_company(self.company_id).create({
            "partner_id": self.supplier_id.id,
            "company_id": self.company_id.id,
            "origin": self.name,
            "order_line": [(0, 0, {
                "product_id": (receivings[line.id].product_id or line._ab_vehicle_product()).id,
                "product_qty": 1,
                "price_unit": line.allocated_cost,
                "name": line._ab_description(),
            }) for line in lines],
        })
        for line, order_line in zip(lines, order.order_line.sorted("id")):
            line.purchase_order_line_id = order_line
            receivings[line.id].write({"purchase_order_id": order.id, "product_id": order_line.product_id.id})
        self.purchase_order_id = order
        self.message_post(body="Draft RFQ %s created for %d car(s)." % (order.name, len(lines)))
        schedule_todo(order, "purchase", "Confirm vehicle RFQ",
                      note="Created from bid lot %s. Confirming it prepares the receipt with each VIN." % self.name)


class BidLine(models.Model):
    _inherit = "autoboutique.bid.line"

    def _ab_description(self):
        return " ".join(filter(None, [self.name, "VIN %s" % self.vin if self.vin else ""]))

    def _ab_vehicle_product(self):
        """One serial-tracked, storable product per year/make/model; each car is a VIN lot."""
        name = " ".join(filter(None, [str(self.model_year or ""), self.make, self.model])).strip()
        Product = self.env["product.product"].with_company(self.company_id)
        product = Product.search([
            ("name", "=", name), ("tracking", "=", "serial"),
            ("company_id", "in", [self.company_id.id, False]),
        ], limit=1)
        return product or Product.create({
            "name": name, "type": "consu", "is_storable": True, "tracking": "serial",
            "company_id": self.company_id.id, "purchase_ok": True, "sale_ok": True,
            "invoice_policy": "order",
        })


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_approve(self, force=False):
        result = super().button_approve(force=force)
        for order in self:
            run_safely(order, "link vehicle receipts", order._ab_link_vehicle_receipts)
        return result

    def _ab_link_vehicle_receipts(self):
        close_todo(self, "Confirm vehicle RFQ")
        Receiving = self.env["autoboutique.receiving"]
        receivings = Receiving.search([
            "|", ("bid_line_id.purchase_order_line_id", "in", self.order_line.ids),
            ("purchase_order_id", "=", self.id),
        ])
        moves = self.picking_ids.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for receiving in receivings.filtered(lambda r: r.state in ("draft", "expected", "arrived", "checking", "confirmed")):
            order_line = receiving.bid_line_id.purchase_order_line_id
            move = moves.filtered(lambda m: m.purchase_line_id == order_line)[:1] if order_line else moves.filtered(
                lambda m: m.product_id == receiving.product_id)[:1]
            if not move:
                continue
            receiving.write({
                "receipt_id": move.picking_id.id,
                "purchase_order_id": self.id,
                "product_id": move.product_id.id,
                "state": "expected" if receiving.state == "draft" else receiving.state,
            })
            vin = receiving.bid_line_id.vin
            move_line = move.move_line_ids[:1]
            if vin and move.product_id.tracking == "serial" and move_line and not move_line.lot_id and not move_line.lot_name:
                move_line.lot_name = vin
            receiving._ab_todo("warehouse", "Receive car and validate receipt",
                               note="Receipt %s, VIN %s." % (move.picking_id.name, vin or "not set"))


# --- Receipt -> Vehicle Master -> initial QC ------------------------------------

class Receiving(models.Model):
    _name = "autoboutique.receiving"
    _inherit = ["autoboutique.receiving", "autoboutique.automation.mixin"]

    def _ab_on_receipt_done(self):
        self.ensure_one()
        picking = self.receipt_id
        if picking.state != "done":
            return
        vin = self.bid_line_id.vin
        move_lines = picking.move_line_ids.filtered(
            lambda ml: ml.lot_id and (not self.product_id or ml.product_id == self.product_id))
        lot = (move_lines.filtered(lambda ml: ml.lot_id.name == vin) or move_lines)[:1].lot_id
        values = {"state": "received", "received_date": fields.Date.context_today(self)}
        if lot and not self.lot_id:
            values["lot_id"] = lot.id
        if lot and not self.product_id:
            values["product_id"] = lot.product_id.id
        self.write(values)
        self._ab_done("Receive car and validate receipt")
        if not vin:
            self._ab_todo("warehouse", "Enter VIN and create Vehicle Master",
                          note="Add the VIN on the bid line, then press Create Vehicle Master.")
            return
        self.action_create_vehicle_master()
        self.vehicle_id._ab_start_initial_qc()


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        result = super()._action_done()
        receivings = self.env["autoboutique.receiving"].sudo().search([
            ("receipt_id", "in", self.ids),
            ("state", "not in", ("received", "verified", "rejected", "cancelled")),
        ])
        for receiving in receivings:
            receiving = receiving.sudo(False).with_company(receiving.company_id)
            run_safely(receiving, "create the Vehicle Master", receiving._ab_on_receipt_done)
        return result


# --- Vehicle stages -------------------------------------------------------------

class Vehicle(models.Model):
    _name = "autoboutique.vehicle"
    _inherit = ["autoboutique.vehicle", "autoboutique.automation.mixin"]

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("ab_automating"):
            if {"documents_verified", "ready_for_sale_approved"} & set(vals):
                self._ab_try_ready_for_sale()
            if {"registration_complete", "insurance_complete", "documents_verified"} & set(vals):
                self._ab_try_complete_documents()
        return result

    def _ab_start_initial_qc(self):
        QC = self.env["autoboutique.qc"]
        for vehicle in self:
            qc = vehicle.qc_ids.filtered(lambda q: q.inspection_type == "initial")[:1] or QC.create({
                "name": "Initial QC - %s" % vehicle.name, "vehicle_id": vehicle.id,
                "inspection_type": "initial", "company_id": vehicle.company_id.id,
            })
            if vehicle.state == "receiving":
                vehicle.state = "qc"
            qc._ab_todo("inspector", "Record initial QC result",
                        note="Set the result to Pass or Fail; the next step is created automatically.")

    def _ab_open_repairs(self):
        self.ensure_one()
        return (self.repair_ids.filtered(lambda r: r.state != "done"),
                self.mrf_ids.filtered(lambda m: m.state not in ("closed", "rejected")))

    def _ab_check_repairs_complete(self):
        QC = self.env["autoboutique.qc"]
        for vehicle in self.filtered(lambda v: v.state == "repair"):
            repairs, mrfs = vehicle._ab_open_repairs()
            if repairs or mrfs:
                continue
            final = vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final" and q.result == "pending")[:1]
            final = final or QC.create({
                "name": "Final QC - %s" % vehicle.name, "vehicle_id": vehicle.id,
                "inspection_type": "final", "company_id": vehicle.company_id.id,
            })
            final._ab_todo("inspector", "Record final QC result")

    def _ab_start_detailing(self):
        Detailing = self.env["autoboutique.detailing"]
        for vehicle in self:
            repairs, mrfs = vehicle._ab_open_repairs()
            if repairs or mrfs:
                vehicle._ab_todo("repair", "Close repairs and material requests",
                                 note="Final QC passed but repairs or material requests are still open.")
                continue
            job = vehicle.detailing_ids.filtered(lambda d: d.state != "approved")[:1] or Detailing.create({
                "name": "Detailing - %s" % vehicle.name, "vehicle_id": vehicle.id,
                "company_id": vehicle.company_id.id,
            })
            vehicle.with_context(ab_automating=True).write({"state": "detailing"})
            job._ab_todo("detailing", "Complete and approve detailing")

    def _ab_try_ready_for_sale(self):
        for vehicle in self.filtered(lambda v: v.state == "detailing"):
            if not vehicle.detailing_ids.filtered(lambda d: d.state == "approved"):
                continue
            if vehicle.documents_verified and vehicle.ready_for_sale_approved:
                done = run_safely(vehicle, "move the car to Ready for Sale",
                                  lambda v=vehicle: v.with_context(ab_automating=True).action_mark_ready_for_sale() or True)
                if done:
                    vehicle._ab_done("Verify documents and approve for sale")
                    vehicle.message_post(body="Automatically moved to Ready for Sale.")
            else:
                vehicle._ab_todo("manager", "Verify documents and approve for sale",
                                 note="Detailing is approved. Tick Documents Verified and Ready For Sale Approved; "
                                      "the car then moves to Ready for Sale automatically.")

    def _ab_on_invoice_paid(self):
        self.ensure_one()
        self.with_context(ab_automating=True).action_confirm_payment()
        close_todo(self.invoice_id, "Post invoice and register payment")
        Release = self.env["autoboutique.vehicle.release"]
        release = Release.search([("vehicle_id", "=", self.id), ("state", "!=", "cancelled")], limit=1)
        application = self.sales_application_ids.filtered(
            lambda a: a.sale_order_id == self.sale_order_id and a.state not in ("rejected", "cancelled"))[:1]
        if not release and application:
            release = Release.create({
                "name": "Release - %s" % self.name,
                "vehicle_id": self.id,
                "sales_application_id": application.id,
                "sale_order_id": self.sale_order_id.id,
                "invoice_id": self.invoice_id.id,
                "customer_id": (self.customer_id or application.customer_id or self.invoice_id.partner_id).id,
                "company_id": self.company_id.id,
            })
        if release:
            release._ab_todo("manager", "Complete release checklist and approve release")
        else:
            self._ab_todo("manager", "Create vehicle release",
                          note="Payment is recorded but no sales application is linked to this sale.")

    def _ab_try_complete_documents(self):
        for vehicle in self.filtered(lambda v: v.state == "released"):
            if (vehicle.registration_complete and vehicle.insurance_complete and vehicle.documents_verified
                    and not vehicle.missing_document_count):
                vehicle.with_context(ab_automating=True).action_complete_documents()
                vehicle.message_post(body="Registration, insurance and documents complete.")


# --- QC, repair, materials, detailing -------------------------------------------

class QC(models.Model):
    _name = "autoboutique.qc"
    _inherit = ["autoboutique.qc", "autoboutique.automation.mixin"]

    processed = fields.Boolean("Result Processed", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda q: q.result in ("pass", "fail"))._ab_process_automatically()
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals.get("result") in ("pass", "fail") and not self.env.context.get("ab_automating"):
            self.filtered(lambda q: not q.processed)._ab_process_automatically()
        return result

    def _ab_process_automatically(self):
        for qc in self:
            run_safely(qc, "process the QC result", qc.action_process_result)

    def action_process_result(self):
        Repair = self.env["autoboutique.repair"]
        for qc in self:
            if qc.result == "pending":
                raise ValidationError("Record a QC result before processing the inspection.")
            vehicle = qc.vehicle_id
            qc = qc.with_context(ab_automating=True)
            if qc.inspection_type == "final" and qc.result == "pass":
                vehicle._ab_start_detailing()
            else:
                repair = qc.repair_id
                if not repair and qc.result == "pass":
                    repair = vehicle.repair_ids.filtered(lambda r: r.state != "done")[:1]
                repair = repair or Repair.create({
                    "name": ("Repair - %s" if qc.result == "fail" else "Reconditioning - %s") % vehicle.name,
                    "vehicle_id": vehicle.id, "qc_id": qc.id, "company_id": qc.company_id.id,
                })
                qc.write({"repair_id": repair.id, "repair_required": qc.result == "fail"})
                vehicle.with_context(ab_automating=True).write({"state": "repair"})
                repair._ab_todo("repair", "Assess repairs",
                                note="%s QC %s. Add cost lines, approve (creates the material request), "
                                     "then mark Done." % (qc.inspection_type.title(), qc.result))
            qc.write({"processed": True})
            qc._ab_done("Record initial QC result" if qc.inspection_type == "initial" else "Record final QC result")


class Repair(models.Model):
    _name = "autoboutique.repair"
    _inherit = ["autoboutique.repair", "autoboutique.automation.mixin"]

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") == "approved":
            for repair in self:
                run_safely(repair, "create the material request", repair._ab_create_mrf)
        if vals.get("state") == "done":
            for repair in self:
                repair._ab_done("Assess repairs")
                run_safely(repair.vehicle_id, "start the final QC", repair.vehicle_id._ab_check_repairs_complete)
        return result

    def _ab_create_mrf(self):
        self.ensure_one()
        MRF = self.env["autoboutique.mrf"]
        if MRF.search_count([("repair_id", "=", self.id)]):
            return
        lines = self.line_ids.filtered(lambda line: line.product_id and line.cost_type in ("stock", "purchase"))
        if not lines:
            return
        mrf = MRF.create({
            "name": "MRF - %s" % self.name,
            "vehicle_id": self.vehicle_id.id,
            "repair_id": self.id,
            "company_id": self.company_id.id,
            "state": "submitted",
            "item_ids": [(0, 0, {
                "product_id": line.product_id.id,
                "quantity": line.quantity or 1,
                "source": "stock" if line.cost_type == "stock" else "purchase",
                "repair_line_id": line.id,
                "company_id": self.company_id.id,
            }) for line in lines],
        })
        mrf._ab_todo("repair", "Approve material request")


class MRF(models.Model):
    _name = "autoboutique.mrf"
    _inherit = ["autoboutique.mrf", "autoboutique.automation.mixin"]

    def action_approve_request(self):
        result = super().action_approve_request()
        for mrf in self:
            mrf._ab_done("Approve material request")
            if mrf.purchase_order_id:
                schedule_todo(mrf.purchase_order_id, "purchase", "Confirm parts RFQ",
                              note="Parts for %s (%s)." % (mrf.vehicle_id.name, mrf.name))
            mrf._ab_todo("repair", "Issue parts and close material request")
        return result

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") in ("closed", "rejected"):
            for mrf in self:
                mrf._ab_done("Issue parts and close material request")
                run_safely(mrf.vehicle_id, "start the final QC", mrf.vehicle_id._ab_check_repairs_complete)
        return result


class Detailing(models.Model):
    _name = "autoboutique.detailing"
    _inherit = ["autoboutique.detailing", "autoboutique.automation.mixin"]

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") == "approved":
            for job in self:
                job._ab_done("Complete and approve detailing")
                job.vehicle_id._ab_try_ready_for_sale()
        return result


# --- Sale -> invoice -> payment -> release -> documents -------------------------

class SalesApplication(models.Model):
    _name = "autoboutique.sales.application"
    _inherit = ["autoboutique.sales.application", "autoboutique.automation.mixin"]

    def action_approve_and_reserve(self):
        result = super().action_approve_and_reserve()
        for application in self:
            run_safely(application, "create the quotation", application._ab_create_quotation)
        return result

    def _ab_create_quotation(self):
        self.ensure_one()
        vehicle = self.vehicle_id
        order = self.sale_order_id
        if not order:
            if not vehicle.product_id:
                self._ab_todo("manager", "Link the inventory product",
                              note="The Vehicle Master has no inventory product, so no quotation could be drafted.")
                return
            order = self.env["sale.order"].with_company(self.company_id).create({
                "partner_id": self.customer_id.id,
                "company_id": self.company_id.id,
                "user_id": self.sales_agent_id.id,
                "origin": self.name,
                "order_line": [(0, 0, {
                    "product_id": vehicle.product_id.id,
                    "product_uom_qty": 1,
                    "price_unit": self.selling_price,
                    "name": " ".join(filter(None, [vehicle.name, "VIN %s" % vehicle.vin if vehicle.vin else ""])),
                })],
            })
            self.sale_order_id = order
        if not vehicle.sale_order_id:
            vehicle.with_context(ab_automating=True).sale_order_id = order
        order.sudo().activity_schedule(
            TODO, date_deadline=fields.Date.add(fields.Date.context_today(self), days=1),
            summary="Send and confirm quotation", user_id=self.sales_agent_id.id,
            note="Reserved for %s. Confirming marks the car Sold and drafts the invoice." % self.customer_id.name,
        )


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            run_safely(order, "mark the vehicle sold", order._ab_on_confirmed)
        return result

    def _ab_on_confirmed(self):
        vehicles = self.env["autoboutique.vehicle"].search([
            ("sale_order_id", "=", self.id), ("state", "in", ("ready", "reserved")),
        ])
        if not vehicles:
            return
        close_todo(self, "Send and confirm quotation")
        vehicles.with_context(ab_automating=True).write({"state": "sold"})
        invoice = self.invoice_ids.filtered(lambda move: move.state != "cancel")[:1]
        if not invoice and self.invoice_status == "to invoice":
            invoice = self._create_invoices()
        if invoice:
            vehicles.with_context(ab_automating=True).write({"invoice_id": invoice.id})
            schedule_todo(invoice, "accounting", "Post invoice and register payment",
                          note="Payment completion records the payment and prepares the vehicle release.")


class AccountMove(models.Model):
    _inherit = "account.move"

    def _invoice_paid_hook(self):
        result = super()._invoice_paid_hook()
        self._ab_advance_paid_vehicles()
        return result

    def _ab_advance_paid_vehicles(self):
        """Advance Sold cars whose invoice is paid or in payment. Idempotent."""
        paid = self.filtered(lambda move: move.payment_state in ("in_payment", "paid"))
        if not paid:
            return
        vehicles = self.env["autoboutique.vehicle"].sudo().search([
            ("invoice_id", "in", paid.ids), ("state", "=", "sold"),
        ])
        for vehicle in vehicles:
            vehicle = vehicle.sudo(False).with_company(vehicle.company_id)
            run_safely(vehicle, "record the payment", vehicle._ab_on_invoice_paid)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_post(self):
        # Journals without an outstanding payments account register payments
        # without a journal entry: the invoice becomes "In Payment" by matching,
        # and _invoice_paid_hook never fires. Advance the vehicles here instead.
        result = super().action_post()
        (self.invoice_ids | self.reconciled_invoice_ids)._ab_advance_paid_vehicles()
        return result


class VehiclePaymentSweep(models.Model):
    _inherit = "autoboutique.vehicle"

    @api.model
    def _cron_advance_paid_vehicles(self):
        """Safety net for payments recorded any other way (bank statements, imports...)."""
        invoices = self.sudo().search([("state", "=", "sold"), ("invoice_id", "!=", False)]).invoice_id
        invoices._ab_advance_paid_vehicles()


class VehicleRelease(models.Model):
    _name = "autoboutique.vehicle.release"
    _inherit = ["autoboutique.vehicle.release", "autoboutique.automation.mixin"]

    def action_approve_release(self):
        result = super().action_approve_release()
        for release in self:
            run_safely(release, "start registration", release._ab_after_release)
        return result

    def _ab_after_release(self):
        self._ab_done("Complete release checklist and approve release")
        vehicle = self.vehicle_id
        registration = vehicle.registration_ids[:1] or self.env["autoboutique.registration"].create({
            "name": "Registration - %s" % vehicle.name, "vehicle_id": vehicle.id,
            "customer_id": self.customer_id.id, "company_id": self.company_id.id,
            "status": "processing", "submitted_date": fields.Date.context_today(self),
        })
        registration._ab_todo("documents", "Complete OR/CR and plate registration")
        if not vehicle.insurance_ids.filtered(lambda p: p.status == "active"):
            vehicle._ab_todo("documents", "Record the insurance policy",
                             note="Add the policy under Vehicle Insurance and set it Active.")


class Registration(models.Model):
    _name = "autoboutique.registration"
    _inherit = ["autoboutique.registration", "autoboutique.automation.mixin"]

    def action_complete(self):
        result = super().action_complete()
        for registration in self:
            registration._ab_done("Complete OR/CR and plate registration")
            registration.vehicle_id.write({"registration_complete": True})
        return result


class Insurance(models.Model):
    _inherit = "autoboutique.insurance"

    @api.model_create_multi
    def create(self, vals_list):
        policies = super().create(vals_list)
        policies._ab_sync_vehicle()
        return policies

    def write(self, vals):
        result = super().write(vals)
        if "status" in vals:
            self._ab_sync_vehicle()
        return result

    def _ab_sync_vehicle(self):
        for policy in self.filtered(lambda p: p.status == "active"):
            close_todo(policy.vehicle_id, "Record the insurance policy")
            if not policy.vehicle_id.insurance_complete:
                policy.vehicle_id.write({"insurance_complete": True})


class VehicleDocument(models.Model):
    _inherit = "autoboutique.document"

    def write(self, vals):
        result = super().write(vals)
        if "status" in vals:
            self.vehicle_id._ab_try_complete_documents()
        return result
