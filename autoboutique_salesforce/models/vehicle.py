from odoo import api, fields, models
from odoo.exceptions import AccessError

from .salesforce_sync import VEHICLE_TRACKED_FIELDS

SYNC_GROUP = "autoboutique_salesforce.group_salesforce_user"


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    # Listing attributes published to Salesforce.
    color = fields.Char()
    condition = fields.Selection([("new", "Brand New"), ("used", "Used")], default="used")
    listing_url = fields.Char("Public Listing URL")
    ready_for_sale_date = fields.Date(copy=False)

    publish_to_salesforce = fields.Boolean(copy=False)
    salesforce_vehicle_id = fields.Char("Salesforce Vehicle ID", copy=False, readonly=True, index=True)
    salesforce_sync_status = fields.Selection(
        [("not_synced", "Not Synced"), ("queued", "Queued"), ("synced", "Synced"), ("error", "Error")],
        default="not_synced", copy=False, readonly=True, index=True)
    salesforce_listing_status = fields.Char(copy=False, readonly=True,
                                            help="Inventory status last sent to Salesforce.")
    salesforce_last_sync_at = fields.Datetime("Last Successful Sync", copy=False, readonly=True)
    salesforce_last_error = fields.Text(copy=False, readonly=True)
    salesforce_sync_hash = fields.Char(copy=False, readonly=True)
    salesforce_log_ids = fields.One2many("autoboutique.salesforce.log", "vehicle_id", string="Sync History")
    salesforce_application_ids = fields.One2many(
        "autoboutique.sales.application", "vehicle_id", string="Salesforce Loan Applications",
        domain=[("salesforce_application_id", "!=", False)])
    salesforce_vehicle_url = fields.Char(compute="_compute_salesforce_urls")
    salesforce_is_sync_company = fields.Boolean(compute="_compute_salesforce_is_sync_company")

    _salesforce_vehicle_uniq = models.UniqueIndex(
        "(company_id, salesforce_vehicle_id) WHERE salesforce_vehicle_id IS NOT NULL",
        "This Salesforce vehicle is already linked to another Vehicle Master record.",
    )

    @api.depends("salesforce_vehicle_id")
    def _compute_salesforce_urls(self):
        base = (self.env["ir.config_parameter"].sudo()
                .get_param("autoboutique_salesforce.login_url") or "").rstrip("/")
        base = base.replace(".my.salesforce.com", ".lightning.force.com")
        for vehicle in self:
            vehicle.salesforce_vehicle_url = (
                "%s/lightning/r/Vehicle_Inventory__c/%s/view" % (base, vehicle.salesforce_vehicle_id)
                if base and vehicle.salesforce_vehicle_id else False)

    @api.depends("company_id")
    def _compute_salesforce_is_sync_company(self):
        sync = self.env["autoboutique.salesforce.sync"]
        for vehicle in self:
            vehicle.salesforce_is_sync_company = sync._is_sync_company(vehicle.company_id)

    def _check_salesforce_publish_rights(self, vals):
        if "publish_to_salesforce" in vals and not self.env.su and not self.env.user.has_group(SYNC_GROUP):
            raise AccessError("Only Salesforce Sync users can publish vehicles to Salesforce.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_salesforce_publish_rights(vals)
            if vals.get("state") == "ready":
                vals.setdefault("ready_for_sale_date", fields.Date.context_today(self))
        vehicles = super().create(vals_list)
        vehicles._salesforce_after_change(set().union(*vals_list) if vals_list else set())
        return vehicles

    def write(self, vals):
        self._check_salesforce_publish_rights(vals)
        if vals.get("state") == "ready" and "ready_for_sale_date" not in vals:
            undated = self.filtered(lambda v: not v.ready_for_sale_date)
            if undated:
                super(Vehicle, undated).write({"ready_for_sale_date": fields.Date.context_today(self)})
        result = super().write(vals)
        self._salesforce_after_change(set(vals))
        return result

    def _salesforce_after_change(self, changed_fields):
        if not changed_fields & VEHICLE_TRACKED_FIELDS:
            return
        sync = self.env["autoboutique.salesforce.sync"]
        settings = sync._settings()
        if not settings["active"]:
            return
        mine = self.sudo().filtered(lambda v: v.company_id == settings["company"])
        if settings["auto_publish"] and "state" in changed_fields:
            to_publish = mine.filtered(lambda v: v.state == "ready" and not v.publish_to_salesforce)
            if to_publish:
                # sudo: reaching Ready for Sale is the authorization to publish.
                to_publish.write({"publish_to_salesforce": True})  # re-enters and enqueues
        sync._enqueue_vehicles(mine)
        # Handover: mark the buyer's Salesforce application Released (again once the plate is known).
        if changed_fields & {"state", "plate_number"}:
            for vehicle in mine.filtered(lambda v: v.state in ("released", "documents")):
                for application in vehicle.salesforce_application_ids.filtered(lambda a: a.state == "sold"):
                    sync._enqueue_application_release(application)

    def action_salesforce_sync(self):
        if not self.env.user.has_group(SYNC_GROUP):
            raise AccessError("Only Salesforce Sync users can sync vehicles.")
        messages = []
        ok_all = True
        for vehicle in self:
            ok, message = self.env["autoboutique.salesforce.sync"]._sync_vehicle_now(vehicle)
            ok_all &= ok
            messages.append(message if len(self) == 1 else "%s: %s" % (vehicle.display_name, message))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if ok_all else "danger",
                "title": "Salesforce",
                "message": "\n".join(messages),
                "sticky": not ok_all,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
