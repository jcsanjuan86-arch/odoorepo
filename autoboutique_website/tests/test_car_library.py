from odoo.tests.common import TransactionCase, tagged

RED = b"iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAQSURBVBhXY/jPwPCfARkAAB7zAf+x9MCaAAAAAElFTkSuQmCC"
BLUE = b"iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAQSURBVBhXY2Bg+P+fARkAABz1Af843v6+AAAAAElFTkSuQmCC"


@tagged("post_install", "-at_install")
class TestCarLibrary(TransactionCase):
    """Pick a model and colour: the car gets its photos and feature rows, no upload."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.library = cls.env["autoboutique.car.library"].create({
            "make": "Toyota", "model": "Zz Vios", "tagline": "Built to go further",
            "color_ids": [(0, 0, {"name": "Red", "image": RED}), (0, 0, {"name": "Blue", "image": BLUE})],
            "feature_ids": [(0, 0, {"name": "Safety", "text": "7 airbags"}), (0, 0, {"name": "Comfort"})],
        })
        cls.red, cls.blue = cls.library.color_ids

    def _car(self, **values):
        return self.env["autoboutique.vehicle"].create(dict({
            "make": "TOYOTA", "model": "zz vios", "model_year": 2024, "color": "red", "plate_number": "LIB1234",
            "company_id": self.env.company.id,
        }, **values))

    def test_car_matches_model_and_colour(self):
        car = self._car()
        self.assertEqual(car.library_id, self.library, "Matched ignoring case")
        self.assertEqual(car.library_color_id, self.red)
        self.assertEqual(car.website_menu_image, RED, "Cut-out without uploading")
        self.assertEqual(car.website_card_image, RED, "Cut-out doubles as the listing photo")
        self.assertEqual(car.website_tagline, "Built to go further")
        self.assertEqual(car.website_feature_ids.mapped("name"), ["Safety", "Comfort"])

    def test_changing_colour_changes_library_photos_only(self):
        car = self._car()
        car.library_color_id = self.blue
        self.assertEqual(car.website_menu_image, BLUE)
        self.assertEqual(len(car.website_feature_ids), 2, "Feature rows are not added twice")

        car.color = "Red"
        self.assertEqual(car.library_color_id, self.red, "Typing the colour picks it")
        self.assertEqual(car.website_card_image, RED)

    def test_own_photo_is_kept(self):
        car = self._car(color=False)
        self.assertEqual(car.library_id, self.library)
        self.assertFalse(car.library_color_id, "No colour typed: pick it")
        car.website_card_image = BLUE
        car.library_color_id = self.red
        self.assertEqual(car.website_menu_image, RED)
        self.assertEqual(car.website_card_image, BLUE, "The team's own shot is not replaced")
        car.action_apply_library()
        self.assertEqual(car.website_card_image, RED, "Use Library Photos replaces it on purpose")

    def test_no_library_no_change(self):
        car = self._car(model="Zz Unknown")
        self.assertFalse(car.library_id)
        self.assertFalse(car.website_menu_image)

    def test_simple_colour_and_variant_names_match(self):
        self.library.color_ids = [(0, 0, {"name": "Super White II", "image": RED}),
                                  (0, 0, {"name": "Grayish Blue Mica Metallic", "image": BLUE})]
        car = self._car(model="Zz Vios 1.3 XLE CVT", color="White")
        self.assertEqual(car.library_id, self.library, "Variant words after the model still match")
        self.assertEqual(car.library_color_id.name, "Super White II")
        self.assertEqual(self._car(plate_number="LIB5678", color="grey blue").library_color_id.name,
                         "Grayish Blue Mica Metallic")

    def test_toyota_photos_are_loaded(self):
        vios = self.env.ref("autoboutique_website.lib_toyota_vios")
        self.assertEqual(vios.name, "Toyota Vios")
        self.assertTrue(vios.color_ids and all(vios.color_ids.mapped("image")))
