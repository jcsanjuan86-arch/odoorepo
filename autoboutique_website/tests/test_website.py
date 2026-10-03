from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.autoboutique_website.models import sandbox_import

PIXEL = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@tagged("post_install", "-at_install")
class TestAutoboutiqueWebsite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.website = cls.env["website"].create({"name": "Autoboutique Test Site", "company_id": cls.company.id})
        cls.Vehicle = cls.env["autoboutique.vehicle"]

    def _listing(self, **values):
        return self.Vehicle.create(dict({
            "name": "2023 MG ZS", "make": "MG", "model": "ZS", "model_year": 2023, "selling_price": 818000,
            "state": "ready", "website_published": True, "wp_import_ref": 9001, "company_id": self.company.id,
        }, **values))

    def test_listing_follows_vehicle_stage(self):
        car = self._listing()
        self.assertIn(car, self.website._ab_vehicles())
        car.state = "reserved"
        self.assertIn(car, self.website._ab_vehicles(), "Reserved cars stay listed")
        car.state = "sold"
        self.assertNotIn(car, self.website._ab_vehicles(), "Sold cars leave the website")

    def test_ready_for_sale_publishes_automatically(self):
        car = self._listing(state="detailing", website_published=False)
        self.assertFalse(car.website_listed)
        car.state = "ready"
        self.assertTrue(car.website_published)
        self.assertTrue(car.website_listed)

    def test_slugs_are_unique_and_clean(self):
        first = self._listing()
        second = self._listing(wp_import_ref=9002)
        self.assertEqual(first.website_slug, "2023-mg-zs")
        self.assertEqual(second.website_slug, "2023-mg-zs-2")
        first.website_slug = "My Car / Special!"
        self.assertEqual(first.website_slug, "my-car-special")
        self.assertEqual(first.website_url, "/vehicles/my-car-special")

    def test_import_sandbox_vehicles(self):
        website = self.env["website"].search([("name", "=", "Autoboutique")], limit=1)
        if not website:
            self.website.name = "Autoboutique"
        with patch.object(sandbox_import, "_download", return_value=PIXEL):
            self.Vehicle.action_import_sandbox_vehicles()
            imported = self.Vehicle.search([("wp_import_ref", "!=", 0)])
            self.assertEqual(len(imported), 13)
            self.assertTrue(all(v.state == "ready" and v.website_published for v in imported))
            self.assertTrue(all(v.website_card_image and v.product_id for v in imported))
            vios = imported.filtered(lambda v: v.website_slug == "toyota-vios-1-3-e-cvt")
            self.assertEqual(vios.selling_price, 738000)
            self.Vehicle._cron_import_sandbox_photos()
            self.assertFalse(imported.filtered("wp_gallery_pending"))
            self.assertEqual(len(vios.website_variant_ids.color_ids), 4)
            self.assertEqual(len(vios.website_feature_ids), 6)
            self.assertTrue(vios.website_gallery_ids)
            # Running it again updates instead of duplicating.
            self.Vehicle.action_import_sandbox_vehicles()
            self.assertEqual(self.Vehicle.search_count([("wp_import_ref", "!=", 0)]), 13)

    def test_payment_choice_is_read_from_the_message(self):
        from odoo.addons.autoboutique_website.controllers.main import payment_from_message
        self.assertEqual(payment_from_message("I'd like financing with 20% down over 48 months"), "financing")
        self.assertEqual(payment_from_message("Magkano po DP? Pwede hulugan?"), "financing")
        self.assertEqual(payment_from_message("I will pay cash"), "cash")
        self.assertFalse(payment_from_message("Is the Mirage available?"))
        self.assertFalse(payment_from_message("Cash or loan, which is cheaper?"))

    def test_inquiry_creates_callback_todo(self):
        car = self._listing()
        inquiry = self.env["autoboutique.website.inquiry"].create({
            "name": "Website Buyer", "phone": "09170000000", "source": "vehicle", "vehicle_id": car.id,
        })
        self.assertTrue(inquiry.activity_ids.filtered(lambda a: a.summary == "Call back website inquiry"))
