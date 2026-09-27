from odoo import api, fields, models
from odoo.exceptions import UserError

PARAM = "autoboutique_salesforce.%s"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Settings are stored in ir.config_parameter, which only Settings
    # administrators (base.group_system) can read or write.
    salesforce_enabled = fields.Boolean(
        "Enable Salesforce Sync", config_parameter=PARAM % "enabled")
    salesforce_company_id = fields.Many2one(
        "res.company", string="Salesforce Company", config_parameter=PARAM % "company_id",
        help="Only vehicles and records of this company are ever sent to or created from Salesforce.")
    salesforce_login_url = fields.Char(
        "Salesforce My Domain URL", config_parameter=PARAM % "login_url",
        help="For example https://ability-business-4807.my.salesforce.com, or the sandbox My Domain.")
    salesforce_api_version = fields.Char(
        "API Version", config_parameter=PARAM % "api_version", default="64.0")
    salesforce_client_id = fields.Char(
        "Consumer Key", config_parameter=PARAM % "client_id")
    salesforce_client_secret = fields.Char(
        "Consumer Secret", config_parameter=PARAM % "client_secret",
        help="Ignored when the AUTOBOUTIQUE_SF_CLIENT_SECRET environment variable is set.")
    salesforce_webhook_secret = fields.Char(
        "Webhook Secret", config_parameter=PARAM % "webhook_secret",
        help="Shared HMAC secret for the inbound webhook. Ignored when the "
             "AUTOBOUTIQUE_SF_WEBHOOK_SECRET environment variable is set.")
    # Phrased negatively so the safe default (auto-publish) survives Odoo
    # deleting False-valued boolean parameters.
    salesforce_manual_publish_only = fields.Boolean(
        "Manual Publishing Only", config_parameter=PARAM % "manual_publish_only",
        help="When off, vehicles are published automatically when they reach Ready for Sale.")
    salesforce_poll_enabled = fields.Boolean(
        "Poll Loan Applications", config_parameter=PARAM % "poll_enabled",
        help="Safety net for missed webhooks: fetch recently changed loan applications on every sweep.")
    salesforce_create_quotation = fields.Boolean(
        "Create Draft Quotations", config_parameter=PARAM % "create_quotation",
        help="Also create a draft quotation for new Salesforce loan applications. "
             "Draft quotations never reserve or move stock.")
    salesforce_default_agent_id = fields.Many2one(
        "res.users", string="Fallback Sales Agent", config_parameter=PARAM % "default_agent_id",
        help="Used when the Salesforce assigned agent has no matching Odoo user.")
    salesforce_max_attempts = fields.Integer(
        "Max Retries", config_parameter=PARAM % "max_attempts", default=5)
    salesforce_sweep_interval = fields.Integer(
        "Scheduled Sync Interval (minutes)", default=60,
        compute="_compute_salesforce_sweep_interval", inverse="_inverse_salesforce_sweep_interval")

    @api.depends("company_id")
    def _compute_salesforce_sweep_interval(self):
        cron = self.env.ref("autoboutique_salesforce.ir_cron_salesforce_sweep", raise_if_not_found=False)
        for settings in self:
            settings.salesforce_sweep_interval = cron.interval_number if cron else 60

    def _inverse_salesforce_sweep_interval(self):
        cron = self.env.ref("autoboutique_salesforce.ir_cron_salesforce_sweep", raise_if_not_found=False)
        for settings in self:
            if cron and settings.salesforce_sweep_interval > 0:
                cron.sudo().write({"interval_number": settings.salesforce_sweep_interval,
                                   "interval_type": "minutes"})

    def action_salesforce_test_connection(self):
        self.ensure_one()
        self.execute()
        sync = self.env["autoboutique.salesforce.sync"]
        try:
            sync._get_client().query("SELECT Id FROM Vehicle_Inventory__c LIMIT 1")
        except Exception as exc:  # noqa: BLE001 - shown to the administrator
            raise UserError("Salesforce connection failed: %s" % exc) from exc
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": "success", "message": "Connected to Salesforce."},
        }
