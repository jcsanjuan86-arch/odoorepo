from odoo import api, fields, models
from odoo.fields import Domain

SEARCH_OPERATORS = ("ilike", "=ilike", "like", "=like", "=")


def with_variant_codes(domain, operator, value):
    if operator in SEARCH_OPERATORS and isinstance(value, str) and value.strip():
        return Domain.OR([domain, Domain("disloq_variant_codes", "ilike", value.strip())])
    return domain


class ProductTemplate(models.Model):
    _inherit = "product.template"

    disloq_code_ids = fields.One2many("trendy.overruns.variant.code", "product_tmpl_id", string="Disloq Variant Codes")
    disloq_variant_codes = fields.Char(
        string="Variant Codes", compute="_compute_disloq_variant_codes", store=True,
        help="Disloq variant SKUs (e.g. 2608060227122-14), searchable in Products, Inventory and the POS.")

    @api.depends("disloq_code_ids.code")
    def _compute_disloq_variant_codes(self):
        for template in self:
            template.disloq_variant_codes = " ".join(sorted(template.disloq_code_ids.mapped("code"))) or False

    def _search_display_name(self, operator, value):
        return with_variant_codes(super()._search_display_name(operator, value), operator, value)

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["disloq_variant_codes"]


class ProductProduct(models.Model):
    _inherit = "product.product"

    disloq_variant_codes = fields.Char(related="product_tmpl_id.disloq_variant_codes")

    def _search_display_name(self, operator, value):
        return with_variant_codes(super()._search_display_name(operator, value), operator, value)
