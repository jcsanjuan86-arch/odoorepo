import hashlib
import hmac
import json
import time

from odoo.tests.common import HttpCase, tagged

from .common import SAMPLE_SF_APPLICATION_ID, SalesforceCase

SECRET = "webhook-test-secret"
URL = "/autoboutique_salesforce/webhook"


def sign(body, ts, secret=SECRET):
    return hmac.new(secret.encode(), b"%d." % ts + body, hashlib.sha256).hexdigest()


@tagged("post_install", "-at_install")
class TestWebhookSignature(SalesforceCase):
    def setUp(self):
        super().setUp()
        self.sync = self.env["autoboutique.salesforce.sync"]
        self.body = json.dumps({"object": "Auto_Loan_Application__c", "ids": [SAMPLE_SF_APPLICATION_ID]}).encode()
        self.ts = 1790000000

    def test_valid_signature(self):
        self.assertEqual(self.sync._verify_webhook_signature(self.body, str(self.ts), sign(self.body, self.ts),
                                                             now=self.ts + 10), (True, "ok"))

    def test_tampered_body(self):
        ok, reason = self.sync._verify_webhook_signature(self.body + b" ", str(self.ts), sign(self.body, self.ts),
                                                         now=self.ts)
        self.assertEqual((ok, reason), (False, "bad_signature"))

    def test_wrong_secret(self):
        ok, reason = self.sync._verify_webhook_signature(self.body, str(self.ts),
                                                         sign(self.body, self.ts, "guess"), now=self.ts)
        self.assertEqual((ok, reason), (False, "bad_signature"))

    def test_replayed_old_request(self):
        ok, reason = self.sync._verify_webhook_signature(self.body, str(self.ts), sign(self.body, self.ts),
                                                         now=self.ts + 301)
        self.assertEqual((ok, reason), (False, "stale_timestamp"))

    def test_missing_headers_and_missing_secret(self):
        self.assertEqual(self.sync._verify_webhook_signature(self.body, None, None)[1], "missing_headers")
        self.env["ir.config_parameter"].sudo().set_param("autoboutique_salesforce.webhook_secret", False)
        self.assertEqual(self.sync._verify_webhook_signature(self.body, str(self.ts), "x")[1], "not_configured")


@tagged("post_install", "-at_install")
class TestWebhookEndpoint(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Autoboutique (webhook test)"})
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("autoboutique_salesforce.enabled", "True")
        ICP.set_param("autoboutique_salesforce.company_id", str(cls.company.id))
        ICP.set_param("autoboutique_salesforce.webhook_secret", SECRET)

    def _post(self, body, signature=None, ts=None):
        ts = ts or int(time.time())
        return self.url_open(URL, data=body, headers={
            "Content-Type": "application/json",
            "X-Autoboutique-Timestamp": str(ts),
            "X-Autoboutique-Signature": signature or sign(body, ts),
        })

    def test_signed_notification_queues_a_pull(self):
        body = json.dumps({"object": "Auto_Loan_Application__c", "ids": [SAMPLE_SF_APPLICATION_ID]}).encode()
        response = self._post(body)
        self.assertEqual(response.status_code, 202)
        job = self.env["autoboutique.salesforce.job"].search([("salesforce_record_id", "=", SAMPLE_SF_APPLICATION_ID)])
        self.assertEqual(len(job), 1)
        self.assertEqual(job.company_id, self.company)

    def test_unsigned_notification_is_rejected(self):
        body = json.dumps({"object": "Auto_Loan_Application__c", "ids": [SAMPLE_SF_APPLICATION_ID]}).encode()
        response = self._post(body, signature="0" * 64)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.env["autoboutique.salesforce.job"].search([("salesforce_record_id", "=", SAMPLE_SF_APPLICATION_ID)]))

    def test_unexpected_object_is_rejected(self):
        body = json.dumps({"object": "User", "ids": ["005000000000001AAA"]}).encode()
        self.assertEqual(self._post(body).status_code, 400)
