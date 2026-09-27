from odoo.tests.common import TransactionCase, tagged

from odoo.addons.autoboutique_salesforce.models.salesforce_client import (
    SalesforceClient, SalesforceError, soql_quote,
)


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body
        self.content = b"x" if body is not None else b""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.tokens_issued = 0

    def post(self, url, data=None, timeout=None):
        self.tokens_issued += 1
        return FakeResponse(200, {"access_token": "token-%d" % self.tokens_issued,
                                  "instance_url": "https://example.my.salesforce.com"})

    def request(self, method, url, json=None, params=None, timeout=None, headers=None):
        self.requests.append((method, url, headers["Authorization"]))
        return self.responses.pop(0)


@tagged("post_install", "-at_install")
class TestSalesforceClient(TransactionCase):
    def setUp(self):
        super().setUp()
        SalesforceClient.clear_token_cache()
        self.addCleanup(SalesforceClient.clear_token_cache)

    def _client(self, *responses):
        session = FakeSession(responses)
        return SalesforceClient("https://login.example.com", "id", "secret", "62.0", session=session), session

    def test_expired_session_logs_in_again_once(self):
        client, session = self._client(FakeResponse(401, [{"errorCode": "INVALID_SESSION_ID"}]),
                                       FakeResponse(200, {"records": []}))
        client.query("SELECT Id FROM Vehicle_Inventory__c")
        self.assertEqual(session.tokens_issued, 2)
        self.assertEqual(session.requests[1][2], "Bearer token-2")

    def test_throttling_is_retryable_validation_is_not(self):
        client, _session = self._client(FakeResponse(503, [{"errorCode": "SERVER_UNAVAILABLE"}]))
        with self.assertRaises(SalesforceError) as outage:
            client.query("SELECT Id FROM Vehicle_Inventory__c")
        self.assertTrue(outage.exception.retryable)

        client, _session = self._client(FakeResponse(400, [{"errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION",
                                                            "message": "bad"}]))
        with self.assertRaises(SalesforceError) as invalid:
            client.update("Vehicle_Inventory__c", "a0B000000000001AAA", {})
        self.assertFalse(invalid.exception.retryable)
        self.assertEqual(invalid.exception.code, "FIELD_CUSTOM_VALIDATION_EXCEPTION")

    def test_upsert_url_escapes_external_id(self):
        client, session = self._client(FakeResponse(201, {"id": "a0B000000000001AAA", "created": True}))
        record_id, created = client.upsert("Vehicle_Inventory__c", "Odoo_Vehicle_ID__c", "12/3", {})
        self.assertEqual((record_id, created), ("a0B000000000001AAA", True))
        self.assertTrue(session.requests[0][1].endswith("/sobjects/Vehicle_Inventory__c/Odoo_Vehicle_ID__c/12%2F3"))

    def test_soql_quote_escapes_injection(self):
        self.assertEqual(soql_quote("AB' OR Name != '"), "'AB\\' OR Name != \\''")
