from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

from odoo.addons.website_sale.controllers.main import WebsiteSale

from ..models.website import IMAGE_MODELS

INQUIRY_FIELDS = {
    "name", "phone", "email", "message", "vehicle_interest", "body_type", "payment_option",
    "employment_status", "monthly_income", "assistance",
}
SOURCES = {"contact", "vehicle", "lead", "calculator"}


def _is_autoboutique():
    website = request.website
    return bool(website) and website.company_id.name and website.company_id.name.lower() == "autoboutique"


class AutoboutiqueWebsite(http.Controller):

    def _vehicle_or_404(self, slug):
        vehicle = request.env["autoboutique.vehicle"].sudo().search([
            ("website_slug", "=", slug), ("website_listed", "=", True),
            ("company_id", "=", request.website.company_id.id),
        ], limit=1)
        if not vehicle or not _is_autoboutique():
            raise NotFound()
        return vehicle

    @http.route(["/vehicles", "/vehicles/brand/<string:brand>"], type="http", auth="public", website=True, sitemap=True)
    def vehicles(self, brand=None, search=None, **kwargs):
        if not _is_autoboutique():
            raise NotFound()
        return request.render("autoboutique_website.vehicles_listing", {
            "active_brand": (brand or kwargs.get("brand") or "").title() if (brand or kwargs.get("brand") or "").lower() != "mg" else "MG",
            "search": search or "",
        })

    @http.route("/vehicles/<string:slug>", type="http", auth="public", website=True, sitemap=True)
    def vehicle_detail(self, slug, **kwargs):
        vehicle = self._vehicle_or_404(slug)
        return request.render("autoboutique_website.vehicle_detail", {
            "vehicle": vehicle, "sent": kwargs.get("sent"),
        })

    @http.route("/ab/img/<string:key>/<int:record_id>/<string:field>", type="http", auth="public", website=True, sitemap=False)
    def vehicle_image(self, key, record_id, field, size=None, **kwargs):
        model = IMAGE_MODELS.get(key)
        if not model or not field.startswith(("image", "website_card_image", "website_hero_image", "website_menu_image")):
            raise NotFound()
        record = request.env[model].sudo().browse(record_id).exists()
        if not record or field not in record._fields or record._fields[field].type != "binary":
            raise NotFound()
        vehicle = {
            "autoboutique.vehicle": lambda r: r,
            "autoboutique.vehicle.variant": lambda r: r.vehicle_id,
            "autoboutique.vehicle.variant.color": lambda r: r.variant_id.vehicle_id,
            "autoboutique.vehicle.feature": lambda r: r.vehicle_id,
            "autoboutique.vehicle.gallery": lambda r: r.vehicle_id,
        }[model](record)
        if not vehicle.website_published or vehicle.company_id != request.website.company_id:
            raise NotFound()
        width = height = int(size) if size and str(size).isdigit() and 64 <= int(size) <= 1920 else 0
        stream = request.env["ir.binary"]._get_image_stream_from(record, field, width=width, height=height)
        return stream.get_response(max_age=86400)

    @http.route("/autoboutique/inquiry", type="http", auth="public", methods=["POST"], website=True, csrf=True, sitemap=False)
    def inquiry(self, **post):
        if not _is_autoboutique():
            raise NotFound()
        source = post.get("source") if post.get("source") in SOURCES else "contact"
        values = {key: (post.get(key) or "").strip() or False for key in INQUIRY_FIELDS}
        if not values["name"] or not (values["phone"] or values["email"]):
            return request.redirect((post.get("redirect") or "/contact") + "?error=1#inquire")
        Inquiry = request.env["autoboutique.website.inquiry"].sudo()
        for key in ("body_type", "payment_option", "employment_status", "monthly_income", "assistance"):
            if values[key] and values[key] not in dict(Inquiry._fields[key].selection):
                values[key] = False
        vehicle = False
        if post.get("vehicle_id", "").isdigit():
            vehicle = request.env["autoboutique.vehicle"].sudo().search([
                ("id", "=", int(post["vehicle_id"])), ("website_listed", "=", True),
                ("company_id", "=", request.website.company_id.id),
            ], limit=1)
        Inquiry.create(dict(
            values, source=source, vehicle_id=vehicle.id if vehicle else False,
            consent=bool(post.get("consent")), company_id=request.website.company_id.id,
            downpayment_percent=int(post["downpayment"]) if post.get("downpayment", "").isdigit() else 0,
            term_months=int(post["term"]) if post.get("term", "").isdigit() else 0,
        ))
        redirect = post.get("redirect") or "/contact"
        if not redirect.startswith("/") or redirect.startswith("//"):
            redirect = "/contact"
        return request.redirect(redirect + "?sent=1#inquire")

    # -- old WordPress URLs ------------------------------------------------------

    @http.route(["/product/<string:slug>", "/pab_vehicle/<string:slug>", "/pabfvx_vehicle/<string:slug>"],
                type="http", auth="public", website=True, sitemap=False)
    def legacy_vehicle(self, slug, **kwargs):
        vehicle = request.env["autoboutique.vehicle"].sudo().search([
            ("website_slug", "=", slug), ("company_id", "=", request.website.company_id.id)], limit=1)
        return request.redirect(vehicle.website_url if vehicle else "/vehicles", code=301)

    @http.route(["/product-category/<string:brand>", "/pab_vehicle_category/<string:brand>",
                 "/pabfvx_category/<string:brand>"], type="http", auth="public", website=True, sitemap=False)
    def legacy_brand(self, brand, **kwargs):
        return request.redirect("/vehicles" if brand == "featured-units" else "/vehicles/brand/%s" % brand, code=301)


class AutoboutiqueShop(WebsiteSale):

    @http.route()
    def shop(self, *args, **kwargs):
        """On the Autoboutique website the shop is the vehicle listing."""
        if _is_autoboutique():
            return request.redirect("/vehicles")
        return super().shop(*args, **kwargs)
