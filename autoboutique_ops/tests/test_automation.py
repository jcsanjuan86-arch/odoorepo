from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

VIN = "AUTOVIN0000000001"


@tagged("post_install", "-at_install")
class TestVehicleAutomation(TransactionCase):
    """Drives one car from bid lot to handover using only the steps people perform:
    approve, confirm, validate, enter results, tick approvals, post, pay."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.supplier = cls.env["res.partner"].create({"name": "Automation Test Auction"})
        cls.customer = cls.env["res.partner"].create({"name": "Automation Test Buyer", "email": "buyer@example.com"})
        cls.inspector = cls.env["res.users"].create({
            "name": "Automation Inspector", "login": "ab.automation.inspector@example.com",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.company.ab_inspector_user_id = cls.inspector

    # -- helpers ---------------------------------------------------------------

    def _todo(self, record, summary):
        return record.activity_ids.filtered(lambda a: a.summary == summary)

    def _inspect(self, qc, result):
        """Tick every inspection point, then record the result."""
        qc._ab_mark_unchecked_ok()
        qc.result = result

    def _approved_bid(self):
        bid = self.env["autoboutique.bid"].create({
            "name": "AUTO-BID-001", "supplier_id": self.supplier.id, "company_id": self.company.id,
            "line_ids": [(0, 0, {
                "name": "2024 Toyota Vios", "vin": VIN, "make": "Toyota", "model": "Vios",
                "model_year": 2024, "allocated_cost": 500000, "selected": True, "company_id": self.company.id,
            })],
        })
        bid.action_approve_bid()
        return bid

    def _receive(self, bid):
        order = bid.purchase_order_id
        order.button_confirm()
        receiving = self.env["autoboutique.receiving"].search([("bid_line_id", "in", bid.line_ids.ids)])
        move = receiving.receipt_id.move_ids
        if not move.move_line_ids:
            move.quantity = 1
        move_line = move.move_line_ids
        if not move_line.lot_id and not move_line.lot_name:
            move_line.lot_name = VIN
        move_line.quantity = 1
        move.picked = True
        receiving.receipt_id.button_validate()
        return receiving

    def _ready_vehicle(self):
        receiving = self._receive(self._approved_bid())
        vehicle = receiving.vehicle_id
        self._inspect(vehicle.qc_ids, "pass")
        vehicle.repair_ids.state = "approved"
        vehicle.repair_ids.state = "done"
        self._inspect(vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final"), "pass")
        vehicle.detailing_ids.write({
            "exterior_done": True, "interior_done": True, "supervisor_id": self.env.user.id, "state": "approved",
        })
        vehicle.write({"documents_verified": True, "ready_for_sale_approved": True, "selling_price": 700000})
        return vehicle

    # -- tests -----------------------------------------------------------------

    def test_bid_to_ready_for_sale(self):
        bid = self._approved_bid()
        order = bid.purchase_order_id
        self.assertEqual(order.state, "draft", "The RFQ is only drafted")
        self.assertEqual(order.partner_id, self.supplier)
        self.assertEqual(order.order_line.price_unit, 500000)
        self.assertEqual(order.order_line.product_id.tracking, "serial")
        self.assertTrue(self._todo(order, "Confirm vehicle RFQ"))
        receiving = self.env["autoboutique.receiving"].search([("bid_line_id", "in", bid.line_ids.ids)])
        self.assertEqual(receiving.purchase_order_id, order)

        order.button_confirm()
        self.assertEqual(receiving.receipt_id, order.picking_ids)
        prefilled = receiving.receipt_id.move_ids.move_line_ids
        if prefilled:
            self.assertEqual(prefilled.lot_name, VIN, "The VIN is prefilled as the serial number")
        self.assertTrue(self._todo(receiving, "Receive car and validate receipt"))

        receiving = self._receive(bid)
        vehicle = receiving.vehicle_id
        self.assertEqual(receiving.state, "received")
        self.assertEqual(vehicle.lot_id.name, VIN)
        self.assertEqual(vehicle.state, "qc")
        initial = vehicle.qc_ids
        self.assertEqual(self._todo(initial, "Record initial QC result").user_id, self.inspector)

        self._inspect(initial, "pass")
        self.assertTrue(initial.processed)
        self.assertEqual(vehicle.state, "repair")
        self.assertEqual(len(vehicle.repair_ids), 1)

        vehicle.repair_ids.state = "approved"
        vehicle.repair_ids.state = "done"
        final = vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final")
        self.assertEqual(final.result, "pending", "Final QC is created when repairs are done")

        self._inspect(final, "pass")
        self.assertEqual(vehicle.state, "detailing")
        job = vehicle.detailing_ids
        self.assertTrue(self._todo(job, "Complete and approve detailing"))

        job.write({"exterior_done": True, "interior_done": True, "supervisor_id": self.env.user.id, "state": "approved"})
        self.assertEqual(vehicle.state, "detailing", "Waits for the manager's approval")
        self.assertTrue(self._todo(vehicle, "Verify documents and approve for sale"))

        vehicle.write({"documents_verified": True, "ready_for_sale_approved": True})
        self.assertEqual(vehicle.state, "ready")
        self.assertFalse(self._todo(vehicle, "Verify documents and approve for sale"))

    def test_repair_parts_create_material_request(self):
        receiving = self._receive(self._approved_bid())
        vehicle = receiving.vehicle_id
        self._inspect(vehicle.qc_ids, "fail")
        repair = vehicle.repair_ids
        part = self.env["product.product"].create({
            "name": "Automation Test Brake Pad", "type": "consu",
            "seller_ids": [(0, 0, {"partner_id": self.supplier.id, "price": 950, "company_id": self.company.id})],
        })
        repair.line_ids = [(0, 0, {"name": "Brake pads", "cost_type": "stock", "product_id": part.id,
                                   "quantity": 2, "company_id": self.company.id})]
        repair.state = "approved"
        mrf = vehicle.mrf_ids
        self.assertEqual(mrf.state, "submitted")
        self.assertEqual(mrf.item_ids.product_id, part)
        self.assertEqual(mrf.item_ids.quantity, 2)
        self.assertEqual(mrf.item_ids.source, "purchase", "Nothing on hand: the part is bought")
        self.assertEqual(mrf.vendor_id, self.supplier, "The vendor comes from the product's vendor list")
        # Approved from another company: the RFQ still uses the vendor price for the car's company.
        other_company = self.env["res.company"].create({"name": "Automation Parts Other Company"})
        mrf.with_context(allowed_company_ids=[other_company.id, self.company.id]).action_approve_request()
        self.assertEqual(mrf.purchase_order_id.order_line.price_unit, 950)
        mrf.purchase_order_id.button_cancel()

        repair.state = "done"
        self.assertFalse(vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final"),
                         "Final QC waits for the material request")
        mrf.state = "closed"
        self.assertTrue(vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final"))

    def test_sale_to_documents_complete(self):
        if not self.env["account.journal"].search_count([("type", "=", "sale"), ("company_id", "=", self.company.id)]):
            self.skipTest("The test company has no chart of accounts.")
        vehicle = self._ready_vehicle()
        self.assertEqual(vehicle.state, "ready")

        application = self.env["autoboutique.sales.application"].create({
            "name": "AUTO-APP-001", "vehicle_id": vehicle.id, "customer_id": self.customer.id,
            "sales_agent_id": self.env.user.id, "selling_price": 700000, "requirements_complete": True,
            "company_id": self.company.id,
        })
        application.action_approve_and_reserve()
        order = application.sale_order_id
        self.assertEqual(order.state, "draft", "The quotation is only drafted")
        self.assertEqual(vehicle.state, "reserved")
        self.assertEqual(vehicle.sale_order_id, order)

        order.action_confirm()
        self.assertEqual(vehicle.state, "sold")
        invoice = vehicle.invoice_id
        self.assertEqual(invoice.state, "draft", "The invoice is only drafted")

        invoice.action_post()
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids).create({})._create_payments()
        self.assertIn(invoice.payment_state, ("in_payment", "paid"))
        self.assertEqual(vehicle.state, "payment")
        release = vehicle.release_ids
        self.assertEqual(release.state, "draft")

        release.write({"final_qc_verified": True, "detailing_verified": True, "documents_verified": True,
                       "customer_id_checked": True, "keys_handed_over": True, "originals_handed_over": True})
        # Cars imported as listings never went through intake; the release checklist covers the documents.
        vehicle.with_context(ab_automating=True).documents_verified = False
        release.action_approve_release()
        self.assertEqual(vehicle.state, "released")
        self.assertTrue(vehicle.documents_verified, "The release checklist verifies the car's documents")
        registration = vehicle.registration_ids
        self.assertEqual(registration.status, "processing")

        registration.write({"documents_complete": True, "orcr_status": "complete", "plate_status": "complete",
                            "plate_number": "NAB 1234"})
        registration.action_complete()
        today = fields.Date.context_today(vehicle)
        other_company = self.env["res.company"].create({"name": "Automation Other Company"})
        policy = self.env["autoboutique.insurance"].create({
            "name": "Comprehensive", "vehicle_id": vehicle.id, "provider_id": self.supplier.id,
            "policy_number": "AUTO-POL-1", "effective_date": today, "expiration_date": today + timedelta(days=365),
            "status": "active", "company_id": other_company.id,
        })
        self.assertEqual(policy.company_id, vehicle.company_id, "The policy follows the car's company")
        self.assertEqual(vehicle.state, "documents")
