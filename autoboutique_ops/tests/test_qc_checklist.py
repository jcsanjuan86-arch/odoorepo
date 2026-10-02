from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

# 1x1 PNG
PIXEL = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@tagged("post_install", "-at_install")
class TestQCChecklist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.vehicle = cls.env["autoboutique.vehicle"].create({
            "name": "Checklist Test Car", "make": "Honda", "model": "City", "vin": "CHECKLISTVIN0001",
            "state": "qc", "company_id": cls.env.company.id,
        })

    def _qc(self):
        return self.env["autoboutique.qc"].create({
            "name": "Initial QC - checklist", "vehicle_id": self.vehicle.id, "inspection_type": "initial",
        })

    def _tick_all(self, qc, status="ok"):
        qc.line_ids.filtered(lambda line: not line.status).write({"status": status})

    def test_new_inspection_starts_with_every_item(self):
        qc = self._qc()
        items = self.env["autoboutique.qc.checklist.item"].search([])
        self.assertGreaterEqual(len(items), 70)
        self.assertEqual(len(qc.line_ids), len(items))
        self.assertEqual(set(qc.line_ids.mapped("section")),
                         {"pms", "engine", "underchassis", "transmission", "electrical", "aircon", "body"})
        self.assertEqual(len(qc.pms_line_ids), 9)
        self.assertEqual(qc.checklist_unchecked_count, len(items))

    def test_result_blocked_until_every_point_is_ticked(self):
        qc = self._qc()
        qc.line_ids[:-1].write({"status": "ok"})
        with self.assertRaises(ValidationError):
            qc.result = "pass"
        qc.line_ids[-1:].tick_na = True
        qc.result = "pass"
        self.assertTrue(qc.processed)

    def test_ticks_are_exclusive(self):
        line = self._qc().line_ids[0]
        line.tick_ok = True
        self.assertEqual(line.status, "ok")
        line.tick_attention = True
        self.assertEqual(line.status, "attention")
        self.assertFalse(line.tick_ok)
        line.tick_attention = False
        self.assertFalse(line.status)

    def test_needs_attention_goes_to_findings_and_repair(self):
        qc = self._qc()
        brake = qc.line_ids.filtered(lambda line: "Brake pad/rotor" in line.name)
        brake.write({"status": "attention", "remarks": "Rotors below minimum", "photo": PIXEL})
        self._tick_all(qc)
        self.assertEqual(qc.checklist_attention_count, 1)
        qc.result = "fail"
        self.assertIn("Rotors below minimum", qc.findings)
        self.assertIn("Brake pad/rotor", qc.repair_id.notes)

    def test_attention_points_become_repair_lines_and_parts_are_bought(self):
        qc = self._qc()
        brake = qc.line_ids.filtered(lambda line: "Brake pad/rotor" in line.name)
        brake.write({"status": "attention", "remarks": "Rotors below minimum"})
        self._tick_all(qc)
        qc.result = "fail"
        repair = qc.repair_id
        repair_line = repair.line_ids.filtered(lambda line: line.qc_line_id == brake)
        self.assertEqual(len(repair_line), 1, "Each flagged point becomes a repair line")
        self.assertIn("Rotors below minimum", repair_line.name)
        self.assertTrue(brake.repair_status)

        vendor = self.env["res.partner"].create({"name": "Checklist Parts Supplier"})
        rotor = self.env["product.product"].create({
            "name": "Checklist Test Brake Rotor", "type": "consu", "is_storable": True, "standard_price": 2500,
            "seller_ids": [(0, 0, {"partner_id": vendor.id, "price": 2500})],
        })
        repair_line.write({"cost_type": "stock", "product_id": rotor.id, "quantity": 2})
        repair.state = "approved"
        mrf = self.vehicle.mrf_ids
        item = mrf.item_ids
        self.assertEqual(item.repair_line_id, repair_line)
        self.assertEqual(item.source, "purchase", "No rotors on hand, so they are bought")
        self.assertEqual(mrf.vendor_id, vendor, "Vendor comes from the product's vendor list")
        mrf.action_approve_request()
        self.assertEqual(mrf.purchase_order_id.partner_id, vendor)
        self.assertEqual(mrf.purchase_order_id.state, "draft")
        self.assertEqual(item.purchase_order_line_id.product_id, rotor)
        self.assertEqual(repair_line.purchase_order_line_id, item.purchase_order_line_id)

        repair.state = "done"
        mrf.state = "closed"
        final = self.vehicle.qc_ids.filtered(lambda q: q.inspection_type == "final")
        recheck = final.line_ids.filtered(lambda line: line.item_id == brake.item_id)
        self.assertIn("Re-check after repair", recheck.remarks)

    def test_report_renders(self):
        qc = self._qc()
        qc.line_ids[0].write({"status": "attention", "remarks": "Missing booklet", "photo": PIXEL})
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "autoboutique_ops.action_report_qc_checklist", qc.ids)
        html = html.decode()
        self.assertIn("Used Vehicle Acceptance Checklist", html)
        self.assertIn("Missing booklet", html)
        self.assertIn("2. Mechanical", html)
