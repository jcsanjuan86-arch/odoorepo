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

    ab_purchase_user_id = fields.Many2one("res.users", string="Purchasing")
    ab_warehouse_user_id = fields.Many2one("res.users", string="Warehouse")
    ab_inspector_user_id = fields.Many2one("res.users", string="QC Inspector")
    ab_repair_user_id = fields.Many2one("res.users", string="Repair Lead")
    ab_detailing_user_id = fields.Many2one("res.users", string="Detailing Supervisor")
    ab_manager_user_id = fields.Many2one("res.users", string="Operations Manager")
    ab_accounting_user_id = fields.Many2one("res.users", string="Accounting")
    ab_documents_user_id = fields.Many2one("res.users", string="Documents Officer")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ab_purchase_user_id = fields.Many2one(related="company_id.ab_purchase_user_id", readonly=False)
    ab_warehouse_user_id = fields.Many2one(related="company_id.ab_warehouse_user_id", readonly=False)
    ab_inspector_user_id = fields.Many2one(related="company_id.ab_inspector_user_id", readonly=False)
    ab_repair_user_id = fields.Many2one(related="company_id.ab_repair_user_id", readonly=False)
    ab_detailing_user_id = fields.Many2one(related="company_id.ab_detailing_user_id", readonly=False)
    ab_manager_user_id = fields.Many2one(related="company_id.ab_manager_user_id", readonly=False)
    ab_accounting_user_id = fields.Many2one(related="company_id.ab_accounting_user_id", readonly=False)
    ab_documents_user_id = fields.Many2one(related="company_id.ab_documents_user_id", readonly=False)
