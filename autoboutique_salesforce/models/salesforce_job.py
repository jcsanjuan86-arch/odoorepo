import logging
from datetime import timedelta

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.modules import module as odoo_module

from .salesforce_client import SalesforceError

_logger = logging.getLogger(__name__)

# Minutes to wait before retry number N (1-based); the last value repeats.
BACKOFF_MINUTES = [1, 5, 15, 60, 240]


class SalesforceJob(models.Model):
    """Durable, retry-safe queue for Salesforce work.

    Each job is processed in its own savepoint and committed separately, so one
    failing vehicle never blocks or rolls back the others.  A partial unique
    index guarantees at most one pending job per vehicle / Salesforce record.
    """

    _name = "autoboutique.salesforce.job"
    _description = "Salesforce Sync Job"
    _order = "next_attempt_at, id"

    name = fields.Char(compute="_compute_name")
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    job_type = fields.Selection(
        [("vehicle_push", "Push Vehicle"), ("application_pull", "Pull Loan Application"),
         ("application_release", "Mark Application Released"), ("inquiry_push", "Push Website Inquiry")],
        required=True, readonly=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", index=True, readonly=True, ondelete="cascade")
    sales_application_id = fields.Many2one("autoboutique.sales.application", index=True, readonly=True,
                                           ondelete="cascade")
    # Website inquiries live in autoboutique_website, which this module does not depend on.
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    salesforce_record_id = fields.Char(readonly=True)
    dedupe_key = fields.Char(required=True, index=True, readonly=True)
    force = fields.Boolean(readonly=True, help="Push even if nothing changed since the last sync.")
    state = fields.Selection(
        [("pending", "Pending"), ("done", "Done"), ("failed", "Failed"), ("cancelled", "Cancelled")],
        default="pending", required=True, index=True, readonly=True)
    attempts = fields.Integer(readonly=True)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True, readonly=True)
    last_error = fields.Text(readonly=True)
    done_at = fields.Datetime(readonly=True)

    _one_pending_per_key = models.UniqueIndex(
        "(dedupe_key) WHERE state = 'pending'",
        "A pending Salesforce job already exists for this record.",
    )

    @api.depends("job_type", "vehicle_id", "salesforce_record_id", "sales_application_id", "res_model", "res_id")
    def _compute_name(self):
        labels = dict(self._fields["job_type"].selection)
        for job in self:
            target = (job.vehicle_id.display_name or job.sales_application_id.display_name
                      or job.salesforce_record_id or ("%s #%s" % (job.res_model, job.res_id) if job.res_model else ""))
            job.name = "%s %s" % (labels.get(job.job_type, ""), target)

    def _target_record(self):
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env:
            return None
        return self.env[self.res_model].sudo().browse(self.res_id).exists()

    # -- enqueueing ------------------------------------------------------------

    @api.model
    def _enqueue(self, job_type, company, vehicle=None, salesforce_record_id=None, force=False,
                 application=None, record=None):
        """Queue work once.  Re-queuing the same record reuses the pending job."""
        if vehicle:
            target = vehicle.id
        elif application:
            target = "app%s" % application.id
        elif record:
            target = "%s%s" % (record._name, record.id)
        else:
            target = salesforce_record_id
        key = "%s:%s" % (job_type, target)
        Job = self.sudo()
        existing = Job.search([("dedupe_key", "=", key), ("state", "=", "pending")], limit=1)
        if existing:
            if force and not existing.force:
                existing.force = True
            return existing
        try:
            with self.env.cr.savepoint():
                return Job.create({
                    "job_type": job_type,
                    "company_id": company.id,
                    "vehicle_id": vehicle.id if vehicle else False,
                    "sales_application_id": application.id if application else False,
                    "res_model": record._name if record else False,
                    "res_id": record.id if record else 0,
                    "salesforce_record_id": salesforce_record_id,
                    "dedupe_key": key,
                    "force": force,
                })
        except psycopg2.IntegrityError:  # a concurrent transaction queued it first
            return Job.search([("dedupe_key", "=", key), ("state", "=", "pending")], limit=1)

    # -- processing ------------------------------------------------------------

    @api.model
    def _cron_process_jobs(self, limit=100):
        sync = self.env["autoboutique.salesforce.sync"]
        if not sync._settings()["active"]:
            return
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT id FROM autoboutique_salesforce_job
             WHERE state = 'pending' AND next_attempt_at <= %s
             ORDER BY next_attempt_at, id
             LIMIT %s
               FOR UPDATE SKIP LOCKED
        """, [fields.Datetime.now(), limit])
        for job in self.sudo().browse([row[0] for row in self.env.cr.fetchall()]):
            job._run()
            if not odoo_module.current_test:
                self.env["ir.cron"]._commit_progress(1)

    def _run(self):
        self.ensure_one()
        sync = self.env["autoboutique.salesforce.sync"].sudo().with_company(self.company_id)
        try:
            with self.env.cr.savepoint():
                if self.job_type == "vehicle_push":
                    sync._push_vehicle(self.vehicle_id, force=self.force, job=self)
                elif self.job_type == "application_release":
                    sync._push_application_release(self.sales_application_id, job=self)
                elif self.job_type == "inquiry_push":
                    sync._push_website_inquiry(self._target_record(), job=self)
                else:
                    sync._pull_loan_application(self.salesforce_record_id, job=self)
        except SalesforceError as exc:
            self.env.invalidate_all()
            self._fail(str(exc), retryable=exc.retryable)
        except Exception as exc:  # noqa: BLE001 - keep the queue moving; record the bug
            _logger.exception("salesforce_job_crash job=%s", self.id)
            self.env.invalidate_all()
            self._fail("Unexpected error: %s" % exc, retryable=False)
        else:
            self.write({"state": "done", "done_at": fields.Datetime.now(), "last_error": False})

    def _fail(self, message, retryable):
        max_attempts = self.env["autoboutique.salesforce.sync"]._settings()["max_attempts"]
        attempts = self.attempts + 1
        if retryable and attempts < max_attempts:
            delay = BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1]
            self.write({"attempts": attempts, "last_error": message,
                        "next_attempt_at": fields.Datetime.now() + timedelta(minutes=delay)})
        else:
            self.write({"attempts": attempts, "last_error": message, "state": "failed"})
        if self.vehicle_id:
            self.vehicle_id.sudo().write({"salesforce_sync_status": "error", "salesforce_last_error": message})
        self.env["autoboutique.salesforce.log"]._record(
            self.company_id, "inbound" if self.job_type == "application_pull" else "outbound",
            self.job_type, "error", message, vehicle_id=self.vehicle_id.id or False,
            job_id=self.id, salesforce_record_id=self.salesforce_record_id,
        )

    # -- manual actions --------------------------------------------------------

    def _check_manager(self):
        if not self.env.user.has_group("autoboutique_salesforce.group_salesforce_manager"):
            raise AccessError("Only Salesforce Sync managers can change the sync queue.")

    def action_retry(self):
        self._check_manager()
        for job in self.filtered(lambda j: j.state in ("failed", "cancelled")):
            if job.search_count([("dedupe_key", "=", job.dedupe_key), ("state", "=", "pending")]):
                continue
            job.sudo().write({"state": "pending", "attempts": 0,
                              "next_attempt_at": fields.Datetime.now()})

    def action_cancel(self):
        self._check_manager()
        self.filtered(lambda j: j.state == "pending").sudo().write({"state": "cancelled"})

    @api.autovacuum
    def _gc_done_jobs(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=30)
        self.sudo().search([("state", "in", ("done", "cancelled")), ("write_date", "<", cutoff)]).unlink()
