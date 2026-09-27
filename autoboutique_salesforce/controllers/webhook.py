import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
MAX_IDS = 200
ACCEPTED_OBJECTS = {"Auto_Loan_Application__c"}


class SalesforceWebhook(http.Controller):
    """Inbound change notifications from Salesforce.

    The body only says *which* records changed.  Odoo then fetches each record
    through the authenticated REST API, so a forged or replayed body can at
    worst trigger a harmless re-read -- and the HMAC check stops even that.
    """

    @http.route("/autoboutique_salesforce/webhook", type="http", auth="none", methods=["POST"],
                csrf=False, save_session=False, readonly=False)
    def salesforce_webhook(self, **_kwargs):
        body = request.httprequest.get_data(cache=False)
        if len(body) > MAX_BODY_BYTES:
            return self._reply(413, "payload_too_large")
        sync = request.env["autoboutique.salesforce.sync"].sudo()
        ok, reason = sync._verify_webhook_signature(
            body,
            request.httprequest.headers.get("X-Autoboutique-Timestamp"),
            request.httprequest.headers.get("X-Autoboutique-Signature"),
        )
        if not ok:
            _logger.warning("salesforce_webhook_rejected reason=%s remote=%s",
                            reason, request.httprequest.remote_addr)
            return self._reply(503 if reason == "not_configured" else 401, "rejected")
        if not sync._settings()["active"]:
            return self._reply(503, "sync_disabled")
        try:
            payload = json.loads(body)
            sobject = payload["object"]
            ids = payload["ids"]
        except (ValueError, KeyError, TypeError):
            return self._reply(400, "invalid_payload")
        if sobject not in ACCEPTED_OBJECTS or not isinstance(ids, list) or len(ids) > MAX_IDS:
            return self._reply(400, "invalid_payload")
        jobs = sync._enqueue_applications([str(i) for i in ids])
        _logger.info("salesforce_webhook_accepted object=%s received=%s queued=%s", sobject, len(ids), len(jobs))
        return self._reply(202, "queued", queued=len(jobs))

    @staticmethod
    def _reply(status, message, **extra):
        return request.make_json_response(dict(extra, status=message), status=status)
