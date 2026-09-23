{
    "name": "Autoboutique Vehicle Operations",
    "version": "19.0.1.3.3",
    "summary": "Vehicle acquisition, inspection, repair, materials, and detailing",
    "author": "Prime Auto Boutique",
    "category": "Inventory",
    "license": "LGPL-3",
    "depends": ["base", "product", "purchase", "stock", "sale_management", "account"],
    "data": [
        "security/ir.model.access.csv",
        "security/company_rules.xml",
        "views/operations_views.xml",
        "views/extended_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "autoboutique_ops/static/src/js/company_switch_reload.js",
        ],
    },
    "application": True,
    "installable": True,
}
