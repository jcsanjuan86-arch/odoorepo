{
    "name": "Autoboutique Website",
    "version": "19.0.2.1.1",
    "summary": "Prime Auto Boutique website with live vehicle listings from the Vehicle Master",
    "author": "Autoboutique",
    "category": "Website",
    "license": "LGPL-3",
    "depends": ["website_sale", "autoboutique_ops", "trendy_overruns_website"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "views/layout.xml",
        "views/vehicle_templates.xml",
        "views/pages.xml",
        "views/backend_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "autoboutique_website/static/src/scss/autoboutique.scss",
            "autoboutique_website/static/src/js/autoboutique.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
