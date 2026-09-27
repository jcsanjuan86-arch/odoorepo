from odoo import fields, models


class SalesApplication(models.Model):
    _inherit = "autoboutique.sales.application"

    salesforce_application_id = fields.Char("Salesforce Loan Application ID", copy=False, readonly=True, index=True)
    salesforce_application_number = fields.Char("Salesforce Application No.", copy=False, readonly=True)
    salesforce_status = fields.Char("Salesforce Status", copy=False, readonly=True)
    salesforce_final_review_status = fields.Char("Salesforce Final Review", copy=False, readonly=True)
    salesforce_modstamp = fields.Char(copy=False, readonly=True)
    salesforce_last_sync_at = fields.Datetime(copy=False, readonly=True)

    _salesforce_application_uniq = models.UniqueIndex(
        "(company_id, salesforce_application_id) WHERE salesforce_application_id IS NOT NULL",
        "This Salesforce loan application is already linked to a sales application.",
    )
