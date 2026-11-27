{
    "name": "Trendy Overruns Disloq Import",
    "version": "19.0.1.0.1",
    "summary": "Load products, branch stock and customers exported from Disloq into Odoo POS",
    "author": "Trendy Overruns Boutique",
    "category": "Sales/Point of Sale",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/disloq_import_views.xml",
    ],
    "installable": True,
}
