from odoo import api, models

AUTOBOUTIQUE_PAGES = (
    "page_home", "page_about", "page_services", "page_release", "page_contact", "page_financing",
    "page_faqs", "page_promos", "page_promo_everyday_moves", "page_price_list", "page_payment_calculator",
    "page_lead_form",
)
AUTOBOUTIQUE_URLS = {
    "/vehicles", "/financing", "/services", "/unit-release", "/faqs", "/about", "/contact", "/promos",
    "/price-list", "/payment-calculator", "/lead-form",
}
IMAGE_MODELS = {
    "vehicle": "autoboutique.vehicle",
    "variant": "autoboutique.vehicle.variant",
    "color": "autoboutique.vehicle.variant.color",
    "feature": "autoboutique.vehicle.feature",
    "gallery": "autoboutique.vehicle.gallery",
}


class Website(models.Model):
    _inherit = "website"

    # -- helpers used by the Autoboutique page templates -------------------------

    def _ab_vehicles(self):
        """Published vehicles that are Ready for Sale or Reserved, in website order."""
        self.ensure_one()
        return self.env["autoboutique.vehicle"].sudo().search([
            ("website_listed", "=", True), ("company_id", "=", self.company_id.id),
        ], order="website_sequence, id")

    def _ab_brands(self):
        self.ensure_one()
        return sorted({vehicle._ab_web_brand() for vehicle in self._ab_vehicles() if vehicle.make})

    def _ab_img(self, record, field, size=None):
        """Public URL of a vehicle website image (served only for listed vehicles)."""
        key = next((k for k, model in IMAGE_MODELS.items() if model == record._name), None)
        url = "/ab/img/%s/%s/%s" % (key, record.id, field)
        return url + ("?size=%s" % size if size else "")

    def _ab_static(self, name):
        return "/autoboutique_website/static/src/img/site/%s" % name

    def _ab_money(self, amount):
        return "₱{:,.0f}".format(amount or 0)

    # -- page and menu assignment ----------------------------------------------

    @api.model
    def autoboutique_sync_websites(self):
        """Assign pages and menus to the correct company website.

        XML data functions run when the module is upgraded, so this also fixes
        existing databases that installed the first version of the module.
        """
        autoboutique = self.env["res.company"].search([("name", "=ilike", "Autoboutique")], limit=1)
        overruns = self.env["res.company"].search([("name", "=ilike", "Overruns")], limit=1)
        if not autoboutique or not overruns:
            return

        autoboutique_site = self.search([("company_id", "=", autoboutique.id), ("name", "=", "Autoboutique")], limit=1) \
            or self.search([("company_id", "=", autoboutique.id)], limit=1)
        if not autoboutique_site:
            autoboutique_site = self.create({"name": "Autoboutique", "company_id": autoboutique.id})
        overruns_site = self.search([("company_id", "=", overruns.id)], limit=1)
        if not overruns_site:
            overruns_site = self.create({"name": "Trendy Overruns Boutique", "company_id": overruns.id})

        pages = self.env["website.page"]
        for xmlid in AUTOBOUTIQUE_PAGES:
            pages |= self.env.ref(f"autoboutique_website.{xmlid}", raise_if_not_found=False)
        pages.write({"website_id": autoboutique_site.id, "is_published": True})

        # Older versions created extra homepages and a static /vehicles page. The
        # new home page and the /vehicles controller replace them; the old pages
        # are kept (unpublished, moved aside) rather than deleted.
        stale = self.env["website.page"].search([
            ("website_id", "=", autoboutique_site.id), ("id", "not in", pages.ids),
            ("url", "in", ["/", "/-2", "/vehicles", "/contact"]),
        ])
        for page in stale:
            page.write({"is_published": False, "url": "%s-old-%d" % (page.url.rstrip("/") or "/home", page.id)})

        self._ab_sync_menu(autoboutique_site)
        self._ab_sync_overruns(overruns_site)

    @api.model
    def _ab_sync_menu(self, site):
        """Autoboutique uses its own header; keep the Odoo menu tidy for the editor and sitemap."""
        Menu = self.env["website.menu"]
        root = site.menu_id
        root.child_id.unlink()
        for sequence, (name, url) in enumerate([
            ("Vehicles", "/vehicles"), ("Financing", "/financing"), ("Services", "/services"),
            ("Unit Release", "/unit-release"), ("Promos", "/promos"), ("Price List", "/price-list"),
            ("FAQs", "/faqs"), ("About Us", "/about"), ("Contact", "/contact"),
        ]):
            Menu.create({"name": name, "url": url, "parent_id": root.id, "website_id": site.id, "sequence": sequence})

    @api.model
    def _ab_sync_overruns(self, overruns_site):
        overruns_pages = self.env["website.page"]
        for xmlid in ("page_home", "page_branches"):
            overruns_pages |= self.env.ref(f"trendy_overruns_website.{xmlid}", raise_if_not_found=False)
        overruns_pages.write({"website_id": overruns_site.id, "is_published": True})
        overruns_home = self.env.ref("trendy_overruns_website.page_home", raise_if_not_found=False)
        if overruns_home:
            overruns_home.write({"url": "/"})
        branches_menu = self.env.ref("trendy_overruns_website.menu_branches", raise_if_not_found=False)
        if branches_menu:
            branches_menu.write({"website_id": overruns_site.id, "parent_id": overruns_site.menu_id.id})

        # Older setup attempts attached Autoboutique entries to the Overruns menu.
        overruns_site.menu_id.child_id.filtered(lambda menu: menu.url in AUTOBOUTIQUE_URLS).unlink()
        branch_items = overruns_site.menu_id.child_id.filtered(lambda menu: menu.url == "/branches").sorted("id")
        if len(branch_items) > 1:
            branch_items[1:].unlink()
