"""Set up the two company-specific Odoo websites on module installation."""


def _company(env, name):
    return env["res.company"].search([("name", "=ilike", name)], limit=1)


def _website_for_company(env, company, name):
    website_model = env["website"]
    website = website_model.search([("company_id", "=", company.id)], limit=1)
    if not website:
        website = website_model.create({"name": name, "company_id": company.id})
    return website


def post_init_hook(env):
    """Keep Autoboutique and Trendy Overruns as separate public websites.

    Domains are deliberately not set here: the owner can attach the final
    domains in Website > Configuration > Websites without hard-coding a
    temporary Odoo.sh URL into production data.
    """
    autoboutique = _company(env, "Autoboutique")
    overruns = _company(env, "Overruns")
    if not autoboutique or not overruns:
        return

    autoboutique_site = _website_for_company(env, autoboutique, "Autoboutique")
    _website_for_company(env, overruns, "Trendy Overruns Boutique")

    page_xmlids = [
        "page_home", "page_vehicles", "page_financing", "page_services",
        "page_release", "page_faqs", "page_about",
    ]
    menu_xmlids = [
        "menu_vehicles", "menu_financing", "menu_services", "menu_release",
        "menu_faqs", "menu_about",
    ]
    for xmlid in page_xmlids:
        env.ref(f"autoboutique_website.{xmlid}").write({
            "website_id": autoboutique_site.id,
            "is_published": True,
        })
    for xmlid in menu_xmlids:
        env.ref(f"autoboutique_website.{xmlid}").write({
            "website_id": autoboutique_site.id,
        })
