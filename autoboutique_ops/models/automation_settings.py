from odoo import fields, models

# role -> (label, what the person is asked to do)
AUTOMATION_ROLES = {
    "purchase": ("Purchasing", "Confirm vehicle RFQs created from approved bid lots."),
    "warehouse": ("Warehouse", "Validate vehicle receipts when cars arrive."),
    "inspector": ("QC Inspector", "Record initial and final QC results."),
    "repair": ("Repair Lead", "Assess repairs and approve material requests."),
    "detailing": ("Detailing Supervisor", "Complete and approve detailing jobs."),
    "manager": ("Operations Manager", "Approve sale readiness and vehicle releases; receives automation errors."),
    "accounting": ("Accounting", "Post customer invoices and register payments."),
    "documents": ("Documents Officer", "Complete registration, insurance and handover documents."),
}


class ResCompany(models.Model):
    _inherit = "res.company"

    ab_purchase_user_id = fields.Many2one("res.users", string="Purchasing To-dos")
    ab_warehouse_user_id = fields.Many2one("res.users", string="Warehouse To-dos")
    ab_inspector_user_id = fields.Many2one("res.users", string="QC Inspector To-dos")
    ab_repair_user_id = fields.Many2one("res.users", string="Repair Lead To-dos")
    ab_detailing_user_id = fields.Many2one("res.users", string="Detailing Supervisor To-dos")
    ab_manager_user_id = fields.Many2one("res.users", string="Operations Manager To-dos")
    ab_accounting_user_id = fields.Many2one("res.users", string="Accounting To-dos")
    ab_documents_user_id = fields.Many2one("res.users", string="Documents Officer To-dos")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ab_purchase_user_id = fields.Many2one(related="company_id.ab_purchase_user_id", readonly=False, string="Purchasing To-dos")
    ab_warehouse_user_id = fields.Many2one(related="company_id.ab_warehouse_user_id", readonly=False, string="Warehouse To-dos")
    ab_inspector_user_id = fields.Many2one(related="company_id.ab_inspector_user_id", readonly=False)
    ab_repair_user_id = fields.Many2one(related="company_id.ab_repair_user_id", readonly=False)
    ab_detailing_user_id = fields.Many2one(related="company_id.ab_detailing_user_id", readonly=False)
    ab_manager_user_id = fields.Many2one(related="company_id.ab_manager_user_id", readonly=False)
    ab_accounting_user_id = fields.Many2one(related="company_id.ab_accounting_user_id", readonly=False, string="Accounting To-dos")
    ab_documents_user_id = fields.Many2one(related="company_id.ab_documents_user_id", readonly=False)
