from odoo import api, fields, models


class VariantCode(models.Model):
    """A Disloq variant SKU (e.g. 2608060227122-14): the product plus its size/colour."""

    _name = "trendy.overruns.variant.code"
    _description = "Disloq Variant Code"
    _order = "code"
    _rec_name = "code"

    code = fields.Char(required=True, index=True)
    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    value_ids = fields.Many2many(
        "product.template.attribute.value", string="Size / Colour",
        help="The attribute values the POS selects when this code is scanned.")
    label = fields.Char(compute="_compute_label", store=True)

    _code_uniq = models.Constraint("unique(code)", "Each Disloq variant code can only be used once.")

    @api.depends("value_ids.name")
    def _compute_label(self):
        for record in self:
            record.label = " / ".join(record.value_ids.mapped("name"))

    @api.model
    def pos_find(self, code):
        """POS lookup: the template and attribute values for a scanned or typed variant code."""
        record = self.search([("code", "=", (code or "").strip().upper())], limit=1)
        template = record.product_tmpl_id
        if not record or not (template.available_in_pos and template.sale_ok and template.active):
            return False
        return {
            "product_tmpl_id": template.id,
            "value_ids": record.value_ids.ids,
            "price_extra": sum(record.value_ids.mapped("price_extra")),
        }
