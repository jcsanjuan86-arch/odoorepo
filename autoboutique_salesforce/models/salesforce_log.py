import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SalesforceLog(models.Model):
    _name = "autoboutique.salesforce.log"
    _description = "Salesforce Sync History"
    _order = "id desc"

    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    direction = fields.Selection(
        [("outbound", "Odoo → Salesforce"), ("inbound", "Salesforce → Odoo")],
        required=True, readonly=True)
    operation = fields.Char(required=True, readonly=True)
    status = fields.Selection(
        [("success", "Success"), ("skipped", "Skipped"), ("error", "Error")],
        required=True, readonly=True)
    message = fields.Text(readonly=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", index=True, readonly=True, ondelete="cascade")
    sales_application_id = fields.Many2one(
        "autoboutique.sales.application", index=True, readonly=True, ondelete="set null")
    job_id = fields.Many2one("autoboutique.salesforce.job", readonly=True, ondelete="set null")
    salesforce_record_id = fields.Char(readonly=True)

    @api.model
    def _record(self, company, direction, operation, status, message="", **links):
        """Write one history row and a matching structured server log line."""
        log_method = _logger.warning if status == "error" else _logger.info
        log_method(
            "salesforce_sync direction=%s operation=%s status=%s company=%s vehicle=%s sf_id=%s msg=%s",
            direction, operation, status, company.id, links.get("vehicle_id"),
            links.get("salesforce_record_id"), (message or "")[:300],
        )
        return self.sudo().create(dict(
            links, company_id=company.id, direction=direction, operation=operation,
            status=status, message=message,
        ))

    @api.autovacuum
    def _gc_old_logs(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=180)
        self.sudo().search([("create_date", "<", cutoff)]).unlink()
