"""Odoo <-> Salesforce mapping and sync rules.

Ownership (see docs/FIELD_OWNERSHIP.md):
* Odoo owns the vehicle, its availability, inventory, cost, and release.
  Salesforce's Vehicle_Inventory__c is a published copy of an allowlist of
  listing fields.
* Salesforce owns loan applications (Auto_Loan_Application__c).  They become
  Odoo sales applications in draft / for-approval state only; reserving or
  selling a vehicle still requires the Odoo approval buttons.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

from .salesforce_client import SalesforceClient, SalesforceError, soql_quote

_logger = logging.getLogger(__name__)

PARAM = "autoboutique_salesforce.%s"
VEHICLE_OBJECT = "Vehicle_Inventory__c"
VEHICLE_EXTERNAL_ID = "Odoo_Vehicle_ID__c"
APPLICATION_OBJECT = "Auto_Loan_Application__c"
SALESFORCE_ID_RE = re.compile(r"^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$")
WEBHOOK_TOLERANCE_SECONDS = 300

# Odoo vehicle state -> Vehicle_Inventory__c.Inventory_Status__c
LISTING_STATUS = {
    "ready": "Available",
    "reserved": "Reserved",
    "sold": "Sold",
    "payment": "Sold",
    "released": "Sold",
    "documents": "Sold",
}
UNLISTED_STATUS = "Inactive"
CONDITION_LABELS = {"new": "Brand New", "used": "Used"}
STOCK_NUMBER_PREFIX = "ODOO-"

# Vehicle fields whose change must be re-published.  Anything not listed here
# (costs, supplier, repairs, MRFs, notes...) can never trigger or reach a push.
VEHICLE_TRACKED_FIELDS = {
    "name", "vin", "make", "model", "model_year", "variant", "plate_number", "mileage",
    "color", "condition", "selling_price", "state", "publish_to_salesforce", "listing_url",
    "ready_for_sale_date",
}

APPLICATION_FIELDS = [
    "Id", "Name", "Application_Number__c", "SystemModstamp", "Status__c", "Final_Review_Status__c",
    "Application_Date__c", "Borrower_First_Name__c", "Borrower_Middle_Name__c", "Borrower_Last_Name__c",
    "Borrower_Email__c", "Borrower_Mobile_Number__c", "Client__c", "Vehicle_Price__c",
    "Selected_Vehicle__c", "Selected_Vehicle__r.VIN__c", "Selected_Vehicle__r.Odoo_Vehicle_ID__c",
    "Assigned_Agent__r.Email",
]
# Salesforce loan statuses that mean the agent has submitted the file.
SUBMITTED_STATUSES = {"Submitted", "Under Review", "Final Review", "Approved"}
REJECTED_STATUSES = {"Rejected"}


class SalesforceSync(models.AbstractModel):
    _name = "autoboutique.salesforce.sync"
    _description = "Salesforce Sync Service"

    # -- configuration -----------------------------------------------------------

    @api.model
    def _settings(self):
        ICP = self.env["ir.config_parameter"].sudo()
        company_id = int(ICP.get_param(PARAM % "company_id") or 0)
        company = self.env["res.company"].sudo().browse(company_id).exists()
        enabled = ICP.get_param(PARAM % "enabled") in ("True", "1", "true")
        agent_id = int(ICP.get_param(PARAM % "default_agent_id") or 0)
        return {
            "enabled": enabled,
            "company": company,
            # Without an explicit company nothing may sync: it is the isolation boundary.
            "active": bool(enabled and company),
            "login_url": ICP.get_param(PARAM % "login_url") or "",
            "api_version": ICP.get_param(PARAM % "api_version") or "64.0",
            "client_id": ICP.get_param(PARAM % "client_id") or "",
            "client_secret": os.environ.get("AUTOBOUTIQUE_SF_CLIENT_SECRET")
                             or ICP.get_param(PARAM % "client_secret") or "",
            "webhook_secret": os.environ.get("AUTOBOUTIQUE_SF_WEBHOOK_SECRET")
                              or ICP.get_param(PARAM % "webhook_secret") or "",
            "auto_publish": ICP.get_param(PARAM % "manual_publish_only") not in ("True", "1", "true"),
            "poll": ICP.get_param(PARAM % "poll_enabled") in ("True", "1", "true"),
            "create_quotation": ICP.get_param(PARAM % "create_quotation") in ("True", "1", "true"),
            "default_agent": self.env["res.users"].sudo().browse(agent_id).exists(),
            "max_attempts": max(int(ICP.get_param(PARAM % "max_attempts") or 5), 1),
        }

    @api.model
    def _get_client(self):
        settings = self._settings()
        return SalesforceClient(
            settings["login_url"], settings["client_id"], settings["client_secret"],
            api_version=settings["api_version"],
        )

    @api.model
    def _is_sync_company(self, company):
        settings = self._settings()
        return settings["active"] and company == settings["company"]

    # -- outbound: mapping --------------------------------------------------------

    @api.model
    def _listing_status(self, vehicle):
        if not vehicle.publish_to_salesforce:
            return UNLISTED_STATUS
        return LISTING_STATUS.get(vehicle.state, UNLISTED_STATUS)

    @api.model
    def _prepare_vehicle_payload(self, vehicle):
        """Build the Vehicle_Inventory__c body.

        This allowlist is the only place Odoo data leaves for Salesforce.  Costs,
        gross profit, supplier, repair, MRF and accounting data are deliberately
        absent; add a field here only after the business approves sharing it.
        """
        price = vehicle.selling_price or None
        title = " ".join(str(part) for part in (
            vehicle.model_year or "", vehicle.make, vehicle.model, vehicle.variant or "") if part)
        return {
            # Stock_Number__c is required and unique in Salesforce.  It is only
            # sent when Odoo creates the record (see _push_vehicle), so stock
            # numbers agents typed on existing records are never overwritten.
            "Stock_Number__c": "%s%d" % (STOCK_NUMBER_PREFIX, vehicle.id),
            # Text lengths match the Salesforce fields, which reject longer values.
            "VIN__c": (vehicle.vin or "")[:40] or None,
            "Vehicle_Name__c": title[:120] or None,
            "Brand__c": (vehicle.make or "")[:80] or None,
            "Model__c": " ".join(filter(None, [vehicle.model, vehicle.variant]))[:80] or None,
            "Year__c": vehicle.model_year or None,
            "Condition__c": CONDITION_LABELS.get(vehicle.condition, "Used"),
            "Odometer__c": vehicle.mileage or None,
            "Plate_Number__c": (vehicle.plate_number or "")[:20] or None,
            "Color__c": (vehicle.color or "")[:40] or None,
            # The org has two price fields in use; keep both consistent.
            "Selling_Price__c": price,
            "Selling_Price_PHP__c": price,
            "Inventory_Status__c": self._listing_status(vehicle),
            "Available_Date__c": fields.Date.to_string(vehicle.ready_for_sale_date) or None,
            "Listing_URL__c": vehicle.listing_url or None,
        }

    @api.model
    def _check_required(self, vehicle):
        """Fail early, with a clear message, on fields Salesforce requires."""
        missing = [label for label, value in (
            ("Selling Price", vehicle.selling_price), ("Year", vehicle.model_year)) if not value]
        if missing:
            raise SalesforceError(
                "Set %s on the vehicle before it can be published to Salesforce." % " and ".join(missing),
                code="MISSING_REQUIRED")

    @staticmethod
    def _payload_hash(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    # -- outbound: push -----------------------------------------------------------

    @api.model
    def _vehicle_needs_push(self, vehicle):
        return bool(vehicle.publish_to_salesforce or vehicle.salesforce_vehicle_id)

    @api.model
    def _enqueue_vehicles(self, vehicles, force=False):
        """Queue pushes for the vehicles that belong to the Salesforce company."""
        settings = self._settings()
        if not settings["active"]:
            return self.env["autoboutique.salesforce.job"]
        jobs = self.env["autoboutique.salesforce.job"]
        for vehicle in vehicles.sudo():
            if vehicle.company_id != settings["company"] or not self._vehicle_needs_push(vehicle):
                continue
            jobs |= jobs._enqueue("vehicle_push", vehicle.company_id, vehicle=vehicle, force=force)
            if vehicle.salesforce_sync_status != "queued":
                vehicle.salesforce_sync_status = "queued"
        return jobs

    @api.model
    def _push_vehicle(self, vehicle, force=False, job=None):
        """Create or update the vehicle's Vehicle_Inventory__c record.  Idempotent."""
        vehicle = vehicle.sudo()
        Log = self.env["autoboutique.salesforce.log"]
        settings = self._settings()
        if not vehicle.exists():
            return False
        if vehicle.company_id != settings["company"] or not settings["active"]:
            # Hard stop: never publish another company's vehicle, whatever queued it.
            Log._record(vehicle.company_id, "outbound", "vehicle_push", "skipped",
                        "Vehicle is not in the Salesforce company.", vehicle_id=vehicle.id,
                        job_id=job.id if job else False)
            return False
        if not self._vehicle_needs_push(vehicle):
            vehicle.salesforce_sync_status = "not_synced"
            return False

        payload = self._prepare_vehicle_payload(vehicle)
        digest = self._payload_hash(payload)
        if not force and vehicle.salesforce_vehicle_id and digest == vehicle.salesforce_sync_hash:
            vehicle.salesforce_sync_status = "synced"
            Log._record(vehicle.company_id, "outbound", "vehicle_push", "skipped", "No changes to send.",
                        vehicle_id=vehicle.id, job_id=job.id if job else False,
                        salesforce_record_id=vehicle.salesforce_vehicle_id)
            return vehicle.salesforce_vehicle_id

        self._check_required(vehicle)
        client = self._get_client()
        external_id = str(vehicle.id)
        update_payload = {k: v for k, v in payload.items() if k != "Stock_Number__c"}
        record_id, created = False, False
        if vehicle.salesforce_vehicle_id:
            try:
                record_id = client.update(VEHICLE_OBJECT, vehicle.salesforce_vehicle_id, update_payload)
            except SalesforceError as exc:
                if exc.code not in ("NOT_FOUND", "ENTITY_IS_DELETED"):
                    raise
                # Deleted in Salesforce while still published in Odoo: recreate below.
        else:
            record_id = self._link_existing_by_vin(client, vehicle, external_id, update_payload)
        if not record_id:
            record_id, created = client.upsert(VEHICLE_OBJECT, VEHICLE_EXTERNAL_ID, external_id, payload)
        if not record_id:  # older API versions answer an upsert-update with 204 and no body
            rows = client.query("SELECT Id FROM %s WHERE %s = %s LIMIT 1" % (
                VEHICLE_OBJECT, VEHICLE_EXTERNAL_ID, soql_quote(external_id)))
            record_id = rows[0]["Id"] if rows else False

        vehicle.write({
            "salesforce_vehicle_id": record_id,
            "salesforce_sync_hash": digest,
            "salesforce_sync_status": "synced",
            "salesforce_listing_status": payload["Inventory_Status__c"],
            "salesforce_last_sync_at": fields.Datetime.now(),
            "salesforce_last_error": False,
        })
        Log._record(vehicle.company_id, "outbound", "vehicle_push", "success",
                    "Created in Salesforce." if created else "Updated in Salesforce.",
                    vehicle_id=vehicle.id, job_id=job.id if job else False, salesforce_record_id=record_id)
        return record_id

    @api.model
    def _link_existing_by_vin(self, client, vehicle, external_id, payload):
        """Adopt the Vehicle_Inventory__c that already carries this VIN.

        Prevents a second Salesforce record for a car that agents already
        listed by hand.  Returns the adopted record ID, or False when there is
        no match and the caller should create the record.
        """
        if not vehicle.vin:
            return False
        rows = client.query("SELECT Id, %s FROM %s WHERE VIN__c = %s LIMIT 2" % (
            VEHICLE_EXTERNAL_ID, VEHICLE_OBJECT, soql_quote(vehicle.vin)))
        if not rows:
            return False
        if len(rows) > 1:
            raise SalesforceError(
                "VIN %s exists on more than one Salesforce vehicle. Merge them in Salesforce, "
                "then sync again." % vehicle.vin, code="DUPLICATE_VIN")
        linked = rows[0].get(VEHICLE_EXTERNAL_ID)
        if linked and linked != external_id:
            raise SalesforceError(
                "VIN %s is already linked to another Odoo vehicle (ID %s)." % (vehicle.vin, linked),
                code="VIN_LINKED_ELSEWHERE")
        client.update(VEHICLE_OBJECT, rows[0]["Id"], dict(payload, **{VEHICLE_EXTERNAL_ID: external_id}))
        return rows[0]["Id"]

    # -- inbound: loan applications -----------------------------------------------

    @api.model
    def _enqueue_applications(self, salesforce_ids):
        settings = self._settings()
        if not settings["active"]:
            return self.env["autoboutique.salesforce.job"]
        Job = self.env["autoboutique.salesforce.job"]
        jobs = Job
        for sf_id in salesforce_ids:
            if SALESFORCE_ID_RE.match(sf_id or ""):
                jobs |= Job._enqueue("application_pull", settings["company"], salesforce_record_id=sf_id)
        return jobs

    @api.model
    def _pull_loan_application(self, salesforce_id, job=None):
        """Create or update the Odoo sales application for one loan application."""
        if not SALESFORCE_ID_RE.match(salesforce_id or ""):
            raise SalesforceError("Invalid Salesforce ID %r." % salesforce_id, code="INVALID_ID")
        rows = self._get_client().query("SELECT %s FROM %s WHERE Id = %s" % (
            ", ".join(APPLICATION_FIELDS), APPLICATION_OBJECT, soql_quote(salesforce_id)))
        if not rows:
            self._log_inbound("skipped", "Loan application no longer exists in Salesforce.",
                              salesforce_id, job=job)
            return False
        return self._apply_loan_application(rows[0], job=job)

    @api.model
    def _apply_loan_application(self, data, job=None):
        settings = self._settings()
        company = settings["company"]
        if not settings["active"]:
            return False
        sf_id = data["Id"]
        Application = self.env["autoboutique.sales.application"].sudo().with_company(company)
        application = Application.search([
            ("salesforce_application_id", "=", sf_id), ("company_id", "=", company.id)], limit=1)
        if application and application.salesforce_modstamp == data.get("SystemModstamp"):
            return application  # already applied this exact version

        vehicle = self._find_vehicle_for_application(data, company)
        if not vehicle:
            self._log_inbound("skipped", "Selected vehicle is not an Odoo-published Autoboutique vehicle.",
                              sf_id, job=job, application=application)
            return application or False

        partner = self._find_or_create_partner(data, company)
        values = {
            "salesforce_application_id": sf_id,
            "salesforce_application_number": data.get("Application_Number__c") or data.get("Name"),
            "salesforce_status": data.get("Status__c"),
            "salesforce_final_review_status": data.get("Final_Review_Status__c"),
            "salesforce_modstamp": data.get("SystemModstamp"),
            "salesforce_last_sync_at": fields.Datetime.now(),
            "customer_id": partner.id,
        }
        sf_status = data.get("Status__c")
        if not application:
            values.update({
                "name": "%s - %s" % (values["salesforce_application_number"] or sf_id, partner.name),
                "company_id": company.id,
                "vehicle_id": vehicle.id,
                "sales_agent_id": self._find_agent(data, company).id,
                "application_date": data.get("Application_Date__c") or fields.Date.context_today(self),
                "selling_price": data.get("Vehicle_Price__c") or vehicle.selling_price or 0.0,
                "state": "approval" if sf_status in SUBMITTED_STATUSES else "draft",
            })
            application = Application.create(values)
            message = "Created sales application."
        else:
            # Only pre-approval applications follow Salesforce; after Odoo approval
            # (approved / reserved / sold) Odoo owns the state and the vehicle link.
            if application.state in ("draft", "approval"):
                if sf_status in REJECTED_STATUSES:
                    values["state"] = "rejected"
                elif sf_status in SUBMITTED_STATUSES and application.state == "draft":
                    values["state"] = "approval"
                if application.vehicle_id != vehicle:
                    values["vehicle_id"] = vehicle.id
            application.write(values)
            message = "Updated sales application."

        if settings["create_quotation"]:
            self._ensure_quotation(application)
        self._log_inbound("success", message, sf_id, job=job, application=application)
        return application

    @api.model
    def _find_vehicle_for_application(self, data, company):
        Vehicle = self.env["autoboutique.vehicle"].sudo()
        domain_company = [("company_id", "=", company.id)]
        sf_vehicle_id = data.get("Selected_Vehicle__c")
        if not sf_vehicle_id:
            return Vehicle
        vehicle = Vehicle.search(domain_company + [("salesforce_vehicle_id", "=", sf_vehicle_id)], limit=1)
        related = data.get("Selected_Vehicle__r") or {}
        odoo_id = related.get(VEHICLE_EXTERNAL_ID)
        if not vehicle and odoo_id and str(odoo_id).isdigit():
            vehicle = Vehicle.search(domain_company + [("id", "=", int(odoo_id))], limit=1)
        if not vehicle and related.get("VIN__c"):
            vehicle = Vehicle.search(domain_company + [("vin", "=", related["VIN__c"])], limit=1)
        return vehicle

    @api.model
    def _find_or_create_partner(self, data, company):
        Partner = self.env["res.partner"].sudo()
        visible = [("company_id", "in", [company.id, False])]
        contact_id = data.get("Client__c")
        email = (data.get("Borrower_Email__c") or "").strip()
        partner = Partner.browse()
        if contact_id:
            partner = Partner.search(visible + [("salesforce_contact_id", "=", contact_id)], limit=1)
        if not partner and email:
            partner = Partner.search(visible + [("email", "=ilike", email)], limit=1)
        name = " ".join(filter(None, [
            (data.get("Borrower_First_Name__c") or "").strip(),
            (data.get("Borrower_Middle_Name__c") or "").strip(),
            (data.get("Borrower_Last_Name__c") or "").strip(),
        ])) or data.get("Name") or "Salesforce Customer"
        if not partner:
            partner = Partner.create({
                "name": name,
                "email": email or False,
                "phone": data.get("Borrower_Mobile_Number__c") or False,
                # Owned by the Salesforce company so other companies never see it.
                "company_id": company.id,
                "salesforce_contact_id": contact_id or False,
            })
        elif contact_id and not partner.salesforce_contact_id:
            partner.salesforce_contact_id = contact_id
        return partner

    @api.model
    def _find_agent(self, data, company):
        email = ((data.get("Assigned_Agent__r") or {}).get("Email") or "").strip()
        if email:
            user = self.env["res.users"].sudo().search([
                "|", ("login", "=ilike", email), ("email", "=ilike", email),
                ("company_ids", "in", company.id), ("share", "=", False),
            ], limit=1)
            if user:
                return user
        fallback = self._settings()["default_agent"]
        if fallback:
            return fallback
        raise SalesforceError(
            "No Odoo user matches the Salesforce agent %s and no fallback sales agent is configured."
            % (email or "(none)"), code="NO_AGENT")

    @api.model
    def _ensure_quotation(self, application):
        """Draft quotation only: it never reserves or delivers stock."""
        if application.sale_order_id or not application.vehicle_id.product_id:
            return application.sale_order_id
        order = self.env["sale.order"].sudo().with_company(application.company_id).create({
            "partner_id": application.customer_id.id,
            "company_id": application.company_id.id,
            "user_id": application.sales_agent_id.id,
            "origin": "Salesforce %s" % application.salesforce_application_number,
            "order_line": [(0, 0, {
                "product_id": application.vehicle_id.product_id.id,
                "product_uom_qty": 1,
                "price_unit": application.selling_price,
            })],
        })
        application.sale_order_id = order
        return order

    @api.model
    def _log_inbound(self, status, message, sf_id, job=None, application=None):
        company = self._settings()["company"]
        self.env["autoboutique.salesforce.log"]._record(
            company, "inbound", "application_pull", status, message,
            sales_application_id=application.id if application else False,
            vehicle_id=application.vehicle_id.id if application else False,
            job_id=job.id if job else False, salesforce_record_id=sf_id,
        )

    # -- inbound: webhook & polling -----------------------------------------------

    @api.model
    def _verify_webhook_signature(self, body, timestamp, signature, now=None):
        """Check ``hex(HMAC-SHA256(secret, "<timestamp>." + body))``.

        Returns (ok, reason).  Rejects missing secrets, stale or future
        timestamps (replay protection), and bad signatures in constant time.
        """
        secret = self._settings()["webhook_secret"]
        if not secret:
            return False, "not_configured"
        if not timestamp or not signature:
            return False, "missing_headers"
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False, "bad_timestamp"
        now = int(time.time()) if now is None else now
        if abs(now - ts) > WEBHOOK_TOLERANCE_SECONDS:
            return False, "stale_timestamp"
        if isinstance(body, str):
            body = body.encode()
        expected = hmac.new(secret.encode(), b"%d." % ts + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.strip().lower()):
            return False, "bad_signature"
        return True, "ok"

    @api.model
    def _poll_loan_applications(self):
        ICP = self.env["ir.config_parameter"].sudo()
        watermark = ICP.get_param(PARAM % "application_watermark") or "2000-01-01T00:00:00Z"
        rows = self._get_client().query(
            "SELECT Id, SystemModstamp FROM %s WHERE Selected_Vehicle__c != null "
            "AND SystemModstamp > %s ORDER BY SystemModstamp LIMIT 200" % (APPLICATION_OBJECT, watermark))
        self._enqueue_applications([row["Id"] for row in rows])
        if rows:
            # The API returns UTC like 2026-09-01T02:36:56.000+0000; SOQL literals need ...:56Z.
            ICP.set_param(PARAM % "application_watermark", rows[-1]["SystemModstamp"][:19] + "Z")
        return len(rows)

    @api.model
    def _cron_sweep(self):
        """Scheduled safety net: re-queue changed vehicles and poll Salesforce."""
        settings = self._settings()
        if not settings["active"]:
            return
        # Vehicles in error wait for an edit or a manual sync instead of failing every hour.
        vehicles = self.env["autoboutique.vehicle"].sudo().search([
            ("company_id", "=", settings["company"].id),
            ("salesforce_sync_status", "!=", "error"),
            "|", ("publish_to_salesforce", "=", True), ("salesforce_vehicle_id", "!=", False),
        ])
        changed = vehicles.filtered(
            lambda v: v.salesforce_sync_hash != self._payload_hash(self._prepare_vehicle_payload(v)))
        self._enqueue_vehicles(changed)
        if settings["poll"]:
            try:
                self._poll_loan_applications()
            except SalesforceError as exc:
                _logger.warning("salesforce_poll_failed error=%s", exc)

    # -- UI entry point -----------------------------------------------------------

    @api.model
    def _sync_vehicle_now(self, vehicle):
        """Manual button: push immediately, and record failures instead of rolling back."""
        if not self._is_sync_company(vehicle.company_id):
            raise UserError("Salesforce sync is disabled or this vehicle's company is not the Salesforce company.")
        try:
            with self.env.cr.savepoint():
                self.sudo()._push_vehicle(vehicle, force=True)
        except SalesforceError as exc:
            self.env.invalidate_all()
            vehicle.sudo().write({"salesforce_sync_status": "error", "salesforce_last_error": str(exc)})
            self.env["autoboutique.salesforce.log"]._record(
                vehicle.company_id, "outbound", "vehicle_push", "error", str(exc), vehicle_id=vehicle.id)
            return False, str(exc)
        return True, "Vehicle synced to Salesforce."
