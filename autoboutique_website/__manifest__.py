{
    "name": "Autoboutique Website",
    "version": "19.0.1.0.1",
    "summary": "Dedicated premium vehicle storefront for Autoboutique",
    "author": "Autoboutique",
    "category": "Website",
    "license": "LGPL-3",
    "depends": ["website_sale", "autoboutique_ops"],
    "data": [
        "views/autoboutique_pages.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "autoboutique_website/static/src/scss/autoboutique.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
