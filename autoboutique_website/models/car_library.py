"""Car Library: stock photos and default website content per model and colour.

Each model (e.g. Toyota Vios) is set up once with a cut-out per colour and its
feature rows. A car on the Vehicle Master picks its model and colour (matched
automatically from make, model and colour) and gets the cut-out, listing photo,
tagline, description and feature rows without anyone uploading photos per car.
"""
from odoo import api, fields, models


def _key(value):
    return " ".join((value or "").lower().split())


class CarLibrary(models.Model):
    _name = "autoboutique.car.library"
    _description = "Car Library Model"
    _order = "make, model, variant, id"

    name = fields.Char(compute="_compute_name", store=True)
    make = fields.Char(required=True)
    model = fields.Char(required=True)
    variant = fields.Char(help="Optional, e.g. 1.3 XLE. Leave empty to use this for every variant.")
    active = fields.Boolean(default=True)
    tagline = fields.Char()
    description = fields.Html(sanitize=True)
    color_ids = fields.One2many("autoboutique.car.library.color", "library_id", string="Colours", copy=True)
    feature_ids = fields.One2many("autoboutique.car.library.feature", "library_id", string="Feature Rows", copy=True)
    image = fields.Image("Cover", related="color_ids.image", readonly=True)

    @api.depends("make", "model", "variant")
    def _compute_name(self):
        for library in self:
            library.name = " ".join(filter(None, [library.make, library.model, library.variant]))

    @api.model
    def _ab_match(self, make, model, variant=None):
        """Library entry for a car: same make and model, preferring the same variant."""
        candidates = self.search([]).filtered(
            lambda lib: _key(lib.make) == _key(make) and _key(lib.model) == _key(model))
        exact = candidates.filtered(lambda lib: variant and _key(lib.variant) == _key(variant))
        return (exact or candidates.filtered(lambda lib: not lib.variant) or candidates)[:1]


class CarLibraryColor(models.Model):
    _name = "autoboutique.car.library.color"
    _description = "Car Library Colour"
    _order = "sequence, id"

    library_id = fields.Many2one("autoboutique.car.library", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Colour", required=True)
    hex_code = fields.Char("Swatch", default="#cccccc")
    image = fields.Image("Cut-out", max_width=800, max_height=800,
                         help="Transparent PNG of the car in this colour: the header menu picture.")
    card_image = fields.Image("Listing Photo", max_width=1600, max_height=1600,
                              help="Optional. Without it the cut-out is used on the listing card.")


class CarLibraryFeature(models.Model):
    _name = "autoboutique.car.library.feature"
    _description = "Car Library Feature Row"
    _order = "sequence, id"

    library_id = fields.Many2one("autoboutique.car.library", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Heading", required=True)
    text = fields.Text()
    image = fields.Image(max_width=1920, max_height=1920)


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    library_id = fields.Many2one("autoboutique.car.library", string="Library Model",
                                 compute="_compute_library", store=True, readonly=False,
                                 help="Picked from make and model; change it to use another model's photos.")
    library_color_id = fields.Many2one("autoboutique.car.library.color", string="Library Colour",
                                       compute="_compute_library", store=True, readonly=False,
                                       domain="[('library_id', '=', library_id)]")

    @api.depends("make", "model", "variant", "color")
    def _compute_library(self):
        Library = self.env["autoboutique.car.library"]
        for vehicle in self:
            library = vehicle.library_id
            if not library or _key(library.model) != _key(vehicle.model) or _key(library.make) != _key(vehicle.make):
                library = Library._ab_match(vehicle.make, vehicle.model, vehicle.variant) or library
            colors = library.color_ids
            color = vehicle.library_color_id if vehicle.library_color_id in colors else colors[:0]
            if vehicle.color and (not color or _key(color.name) != _key(vehicle.color)):
                color = colors.filtered(lambda c: _key(c.name) == _key(vehicle.color))[:1] or color
            vehicle.library_id = library
            vehicle.library_color_id = color

    @api.onchange("library_id")
    def _onchange_library_id(self):
        if self.library_color_id and self.library_color_id.library_id != self.library_id:
            self.library_color_id = False

    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)
        vehicles.filtered("library_id")._ab_apply_library()
        return vehicles

    def write(self, vals):
        before = {vehicle.id: (vehicle.library_id, vehicle.library_color_id) for vehicle in self}
        result = super().write(vals)
        changed = self.filtered(lambda v: (v.library_id, v.library_color_id) != before[v.id])
        if changed and not self.env.context.get("ab_applying_library"):
            for vehicle in changed:
                vehicle._ab_apply_library(previous=before[vehicle.id][1])
        return result

    def _ab_apply_library(self, replace_photos=False, previous=None):
        """Copy the library's photos and content onto the car; what the team typed or shot stays.

        A photo is replaced only when it is empty or still the previous library colour's photo,
        unless replace_photos is set (the Use Library Photos button).
        """
        previous = previous or self.env["autoboutique.car.library.color"]
        old = {previous.image, previous.card_image or previous.image} - {False, None}
        for vehicle in self.with_context(ab_applying_library=True):
            library, color = vehicle.library_id, vehicle.library_color_id
            if not library:
                continue
            values = {}
            if color.image and (replace_photos or not vehicle.website_menu_image or vehicle.website_menu_image in old):
                values["website_menu_image"] = color.image
            card = color.card_image or color.image
            if card and (replace_photos or not vehicle.website_card_image or vehicle.website_card_image in old):
                values["website_card_image"] = card
            if library.tagline and not vehicle.website_tagline:
                values["website_tagline"] = library.tagline
            if library.description and not vehicle.website_description:
                values["website_description"] = library.description
            if library.feature_ids and not vehicle.website_feature_ids:
                values["website_feature_ids"] = [(0, 0, {
                    "sequence": feature.sequence, "name": feature.name, "text": feature.text, "image": feature.image,
                }) for feature in library.feature_ids]
            if values:
                vehicle.write(values)

    def action_apply_library(self):
        """Button: use the library photos again, replacing the car's cut-out and listing photo."""
        self._ab_apply_library(replace_photos=True)
        return True
