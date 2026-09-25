from odoo import api, models


class Website(models.Model):
    _inherit = "website"

    @api.model
    def autoboutique_sync_websites(self):
        """Assign pages and menus to the correct company website.

        XML data functions run when the module is upgraded, so this also fixes
        existing databases that installed the first version of the module.
        """
        autoboutique = self.env["res.company"].search(
            [("name", "=ilike", "Autoboutique")], limit=1
        )
        overruns = self.env["res.company"].search(
            [("name", "=ilike", "Overruns")], limit=1
        )
        if not autoboutique or not overruns:
            return

        autoboutique_site = self.search(
            [("company_id", "=", autoboutique.id)], limit=1
        )
        if not autoboutique_site:
            autoboutique_site = self.create({
                "name": "Autoboutique", "company_id": autoboutique.id,
            })
        overruns_site = self.search(
            [("company_id", "=", overruns.id)], limit=1
        )
        if not overruns_site:
            overruns_site = self.create({
                "name": "Trendy Overruns Boutique", "company_id": overruns.id,
            })

        autoboutique_pages = self.env["website.page"]
        for xmlid in (
            "page_home", "page_vehicles", "page_financing", "page_services",
            "page_release", "page_faqs", "page_about",
        ):
            autoboutique_pages |= self.env.ref(
                f"autoboutique_website.{xmlid}", raise_if_not_found=False
            )
        autoboutique_pages.write({
            "website_id": autoboutique_site.id, "is_published": True,
        })

        autoboutique_menus = self.env["website.menu"]
        for xmlid in (
            "menu_vehicles", "menu_financing", "menu_services", "menu_release",
            "menu_faqs", "menu_about",
        ):
            autoboutique_menus |= self.env.ref(
                f"autoboutique_website.{xmlid}", raise_if_not_found=False
            )
        autoboutique_menus.write({
            "website_id": autoboutique_site.id,
            "parent_id": autoboutique_site.menu_id.id,
        })

        overruns_pages = self.env["website.page"]
        for xmlid in ("page_home", "page_branches"):
            overruns_pages |= self.env.ref(
                f"trendy_overruns_website.{xmlid}", raise_if_not_found=False
            )
        overruns_pages.write({
            "website_id": overruns_site.id, "is_published": True,
        })

        branches_page = self.env.ref(
            "trendy_overruns_website.page_branches", raise_if_not_found=False
        )
        if branches_page:
            branches_page.write({
                "website_id": overruns_site.id, "is_published": True,
            })
        branches_menu = self.env.ref(
            "trendy_overruns_website.menu_branches", raise_if_not_found=False
        )
        if branches_menu:
            branches_menu.write({
                "website_id": overruns_site.id,
                "parent_id": overruns_site.menu_id.id,
            })
