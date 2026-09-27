from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    salesforce_contact_id = fields.Char("Salesforce Contact ID", copy=False, index="btree_not_null")
