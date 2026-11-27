{
    "name": "Trendy Overruns Disloq Import",
    "version": "19.0.1.1.2",
    "summary": "Load products, branch stock, variant codes and customers exported from Disloq into Odoo POS",
    "author": "Trendy Overruns Boutique",
    "category": "Sales/Point of Sale",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/disloq_import_views.xml",
        "views/product_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "trendy_overruns_import/static/src/pos/variant_code.js",
        ],
    },
    "installable": True,
}
