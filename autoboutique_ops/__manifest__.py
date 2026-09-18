{
    "name": "Autoboutique Vehicle Operations",
    "version": "19.0.1.3.1",
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
    "application": True,
    "installable": True,
}
