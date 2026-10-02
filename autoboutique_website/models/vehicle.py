"""Website listing data on the Vehicle Master.

The public website shows every published Autoboutique vehicle that is Ready
for Sale or Reserved. A car is published automatically when it reaches Ready
for Sale and disappears from the listing once it is sold. Listing content
(tagline, description, variants, feature rows, gallery) lives on the vehicle
itself, so there is one source of truth for stock, price and website.
"""
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

LISTED_STATES = ("ready", "reserved")


def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "vehicle"


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    website_published = fields.Boolean(
        "Published on Website", copy=False,
        help="Shown on the Autoboutique website while the car is Ready for Sale or Reserved.")
    website_title = fields.Char(
        "Website Title", help="Name shown on the website, e.g. '2023 MG ZS'. Defaults to year, make and model.")
    website_slug = fields.Char("URL Slug", copy=False, index=True)
    website_sequence = fields.Integer("Website Order", default=100)
    website_featured = fields.Boolean("Featured Unit", default=True)
    website_tagline = fields.Char("Tagline")
    website_description = fields.Html("Website Description", sanitize=True)
    website_card_image = fields.Image("Listing Photo", max_width=1600, max_height=1600)
    website_hero_image = fields.Image("Banner Photo", max_width=1920, max_height=1920)
    website_menu_image = fields.Image("Menu Cut-out", max_width=800, max_height=800,
                                      help="Transparent cut-out shown in the header's vehicle menu.")
    website_variant_ids = fields.One2many("autoboutique.vehicle.variant", "vehicle_id", string="Variants")
    website_feature_ids = fields.One2many("autoboutique.vehicle.feature", "vehicle_id", string="Feature Rows")
    website_gallery_ids = fields.One2many("autoboutique.vehicle.gallery", "vehicle_id", string="Gallery")
    website_listed = fields.Boolean(compute="_compute_website_listed", search="_search_website_listed")
    website_url = fields.Char(compute="_compute_website_url")
    wp_import_ref = fields.Integer("Sandbox Product ID", copy=False, index=True,
                                   help="Vehicle imported from the sandbox website listing.")
    wp_gallery_pending = fields.Boolean(copy=False)

    _website_slug_unique = models.UniqueIndex("(company_id, website_slug) WHERE website_slug IS NOT NULL")

    @api.depends("website_published", "state")
    def _compute_website_listed(self):
        for vehicle in self:
            vehicle.website_listed = vehicle.website_published and vehicle.state in LISTED_STATES

    def _search_website_listed(self, operator, value):
        domain = [("website_published", "=", True), ("state", "in", LISTED_STATES)]
        if (operator == "=") == bool(value):
            return domain
        return ["!", "&"] + domain

    @api.depends("website_slug")
    def _compute_website_url(self):
        for vehicle in self:
            vehicle.website_url = "/vehicles/%s" % vehicle.website_slug if vehicle.website_slug else False

    def _ab_default_title(self):
        self.ensure_one()
        return " ".join(filter(None, [str(self.model_year or ""), self.make, self.model])).strip()

    def _ab_web_title(self):
        self.ensure_one()
        return self.website_title or self._ab_default_title()

    def _ab_unique_slug(self, base):
        self.ensure_one()
        slug, n = base, 2
        while self.search_count([("website_slug", "=", slug), ("company_id", "=", self.company_id.id), ("id", "!=", self.id)]):
            slug, n = "%s-%d" % (base, n), n + 1
        return slug

    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)
        for vehicle in vehicles.filtered(lambda v: not v.website_slug):
            vehicle.website_slug = vehicle._ab_unique_slug(slugify(vehicle.website_title or vehicle._ab_default_title()))
        return vehicles

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") == "ready":
            self.filtered(lambda v: not v.website_published).write({"website_published": True})
        if "website_slug" in vals:
            for vehicle in self.filtered("website_slug"):
                clean = slugify(vehicle.website_slug)
                if clean != vehicle.website_slug:
                    vehicle.website_slug = vehicle._ab_unique_slug(clean)
        return result

    @api.constrains("state", "documents_verified", "ready_for_sale_approved")
    def _check_ready_for_sale(self):
        # Listings imported from the sandbox website have no purchase/QC history.
        return super(Vehicle, self.filtered(lambda v: not v.wp_import_ref))._check_ready_for_sale()

    def _ab_web_brand(self):
        self.ensure_one()
        return (self.make or "").strip().title() if (self.make or "").upper() != "MG" else "MG"

    def _ab_card_field(self):
        """Listing photo, falling back to the Vehicle Master photo."""
        self.ensure_one()
        return "website_card_image" if self.website_card_image else "image_1920"

    def _ab_web_price(self):
        self.ensure_one()
        return self.selling_price or 0.0

    def _ab_monthly_from(self, price, downpayment=20, term=60):
        return round(price * (1 - downpayment / 100.0) / term) if price else 0

    def action_view_on_website(self):
        self.ensure_one()
        if not self.website_slug:
            raise ValidationError("Set a URL slug first.")
        return {"type": "ir.actions.act_url", "url": self.website_url, "target": "new"}


class VehicleVariant(models.Model):
    _name = "autoboutique.vehicle.variant"
    _description = "Website Vehicle Variant"
    _order = "sequence, id"

    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Variant", required=True)
    price_label = fields.Char("Price Label", help="e.g. PHP 908,000 MSRP")
    monthly_label = fields.Char("Monthly Label", help="e.g. PHP 16,506 / mo")
    image = fields.Image(max_width=1600, max_height=1600)
    engine = fields.Char()
    suspension = fields.Char()
    brakes = fields.Char()
    transmission = fields.Char()
    color_ids = fields.One2many("autoboutique.vehicle.variant.color", "variant_id", string="Colours")


class VehicleVariantColor(models.Model):
    _name = "autoboutique.vehicle.variant.color"
    _description = "Website Vehicle Colour"
    _order = "sequence, id"

    variant_id = fields.Many2one("autoboutique.vehicle.variant", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Colour")
    hex_code = fields.Char("Swatch", default="#cccccc")
    image = fields.Image(max_width=1600, max_height=1600)


class VehicleFeature(models.Model):
    _name = "autoboutique.vehicle.feature"
    _description = "Website Vehicle Feature Row"
    _order = "sequence, id"

    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Heading", required=True)
    text = fields.Text()
    image = fields.Image(max_width=1920, max_height=1920)


class VehicleGallery(models.Model):
    _name = "autoboutique.vehicle.gallery"
    _description = "Website Vehicle Gallery Photo"
    _order = "sequence, id"

    vehicle_id = fields.Many2one("autoboutique.vehicle", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    image = fields.Image(max_width=1920, max_height=1920, required=True)
