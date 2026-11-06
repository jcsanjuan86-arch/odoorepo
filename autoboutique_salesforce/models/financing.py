from odoo import api, models

# Account fields agents see on the Salesforce loan application.
PUBLISHED_FIELDS = {"status", "bank_id", "amount_approved", "release_date"}


class FinancingAccount(models.Model):
    _inherit = "autoboutique.financing.account"

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._salesforce_publish()
        return accounts

    def write(self, vals):
        result = super().write(vals)
        if PUBLISHED_FIELDS & set(vals):
            self._salesforce_publish()
        return result

    def _salesforce_publish(self):
        sync = self.env["autoboutique.salesforce.sync"]
        for application in self.sudo().sales_application_id:
            sync._enqueue_financing(application)
