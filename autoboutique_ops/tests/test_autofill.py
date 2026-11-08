from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAutofill(TransactionCase):
    """Each fact is typed once; names, products and links follow from it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.supplier = cls.env["res.partner"].create({"name": "Autofill Auction"})
        cls.customer = cls.env["res.partner"].create({"name": "Autofill Buyer"})

    def _bid(self, plate=False):
        bid = self.env["autoboutique.bid"].create({
            "name": "AUTOFILL-LOT", "supplier_id": self.supplier.id, "company_id": self.company.id,
            "line_ids": [(0, 0, {
                "plate_number": plate, "make": "Toyota", "model": "Vios", "model_year": 2023,
                "allocated_cost": 450000, "selected": True, "company_id": self.company.id,
            })],
        })
        bid.action_approve_bid()
        return bid

    def test_bid_line_and_receiving_names_fill_themselves(self):
        bid = self._bid(plate="NBC1234")
        self.assertEqual(bid.line_ids.name, "2023 Toyota Vios")
        receiving = self.env["autoboutique.receiving"].search([("bid_line_id", "in", bid.line_ids.ids)])
        self.assertTrue(receiving.name)
        self.assertEqual(receiving.plate_number, "NBC1234")
        self.assertEqual(receiving.product_id.name, "2023 Toyota Vios", "The product is ready before the car arrives")

    def test_serial_on_receipt_becomes_the_plate(self):
        """No plate at bid time: the serial typed on the receipt is used, so it is not entered twice."""
        bid = self._bid()
        receiving = self.env["autoboutique.receiving"].search([("bid_line_id", "in", bid.line_ids.ids)])
        move = receiving.receipt_id.move_ids
        if not move.move_line_ids:
            move.quantity = 1
        move.move_line_ids.lot_name = "ABC9876"
        move.move_line_ids.quantity = 1
        move.picked = True
        receiving.receipt_id.button_validate()
        self.assertEqual(bid.line_ids.plate_number, "ABC9876")
        self.assertEqual(receiving.vehicle_id.plate_number, "ABC9876")
        self.assertEqual(receiving.vehicle_id.state, "qc")

    def test_manual_vehicle_gets_name_and_product(self):
        vehicle = self.env["autoboutique.vehicle"].create({
            "make": "Honda", "model": "City", "model_year": 2022, "plate_number": "XYZ111",
            "company_id": self.company.id,
        })
        self.assertEqual(vehicle.name, "Honda City XYZ111")
        self.assertEqual(vehicle.product_id.name, "2022 Honda City")
        self.assertEqual(vehicle.product_id.tracking, "serial")
        again = self.env["autoboutique.vehicle"].create({
            "make": "Honda", "model": "City", "model_year": 2022, "plate_number": "XYZ222",
            "company_id": self.company.id,
        })
        self.assertEqual(again.product_id, vehicle.product_id, "Same model, same product")

    def test_application_and_paperwork_take_details_from_the_car(self):
        vehicle = self.env["autoboutique.vehicle"].create({
            "make": "Mitsubishi", "model": "Xpander", "plate_number": "PQR555",
            "selling_price": 980000, "customer_id": self.customer.id, "company_id": self.company.id,
        })
        application = self.env["autoboutique.sales.application"].create({
            "vehicle_id": vehicle.id, "customer_id": self.customer.id, "company_id": self.company.id,
        })
        self.assertEqual(application.selling_price, 980000)
        self.assertEqual(application.name, "Autofill Buyer - Mitsubishi Xpander PQR555")

        registration = self.env["autoboutique.registration"].create({"vehicle_id": vehicle.id, "company_id": self.company.id})
        self.assertEqual(registration.customer_id, self.customer)
        self.assertEqual(registration.name, "Registration - Mitsubishi Xpander PQR555")

        with Form(self.env["autoboutique.registration"]) as form:
            form.vehicle_id = vehicle
            self.assertEqual(form.plate_number, "PQR555")
            self.assertEqual(form.customer_id, self.customer)

    def test_mark_received_validates_only_that_car(self):
        """Two cars in one lot: Mark Received receives one car; the other stays expected."""
        bid = self.env["autoboutique.bid"].create({
            "name": "AUTOFILL-TWO", "supplier_id": self.supplier.id, "company_id": self.company.id,
            "line_ids": [(0, 0, {
                "plate_number": plate, "make": "Toyota", "model": "Vios", "model_year": 2023,
                "allocated_cost": 450000, "selected": True, "company_id": self.company.id,
            }) for plate in ("TWO1111", "TWO2222")],
        })
        bid.action_approve_bid()
        first, second = self.env["autoboutique.receiving"].search(
            [("bid_line_id", "in", bid.line_ids.ids)], order="id")
        first.action_mark_received()
        self.assertEqual(first.state, "received")
        self.assertEqual(first.vehicle_id.plate_number, "TWO1111")
        self.assertEqual(first.vehicle_id.lot_id.name, "TWO1111")
        self.assertEqual(second.state, "expected", "The other car is not received yet")
        self.assertNotEqual(second.receipt_id.state, "done", "It waits on the backorder")

        second.action_mark_received()
        self.assertEqual(second.vehicle_id.plate_number, "TWO2222")
        self.assertEqual(second.vehicle_id.state, "qc")
