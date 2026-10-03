"""Thin Salesforce REST client.

Plain Python on purpose: it knows nothing about Odoo, so it can be unit tested
with a fake HTTP session and reused by any sync code.  Authentication uses the
OAuth 2.0 client credentials flow of a Salesforce Connected App / External
Client App, which runs every call as the app's configured integration user.
"""
import logging
import threading
from urllib.parse import quote

import requests

_logger = logging.getLogger(__name__)

# Access tokens keyed by (login_url, client_id).  Client-credential tokens have
# no refresh token; on 401 we simply ask for a new one.
_TOKEN_CACHE = {}
_TOKEN_LOCK = threading.Lock()

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SalesforceError(Exception):
    """Salesforce call failure.

    ``retryable`` tells the job queue whether trying again later can succeed
    (network trouble, throttling, outages) or whether a person must fix data
    or configuration first (validation errors, missing permissions).
    """

    def __init__(self, message, status=None, code=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


def soql_quote(value):
    """Quote a string literal for SOQL."""
    return "'%s'" % str(value).replace("\\", "\\\\").replace("'", "\\'")


class SalesforceClient:
    def __init__(self, login_url, client_id, client_secret, api_version="64.0",
                 timeout=20, session=None):
        if not (login_url and client_id and client_secret):
            raise SalesforceError("Salesforce connection is not configured.", code="NOT_CONFIGURED")
        self.login_url = login_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = str(api_version).lstrip("v")
        self.timeout = timeout
        self.session = session or requests.Session()

    # -- authentication ---------------------------------------------------

    @property
    def _cache_key(self):
        return (self.login_url, self.client_id)

    def _authenticate(self):
        try:
            response = self.session.post(
                "%s/services/oauth2/token" % self.login_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SalesforceError("Salesforce login failed: %s" % exc, retryable=True) from exc
        if response.status_code != 200:
            # Never include the response body verbatim: it can echo request data.
            raise SalesforceError(
                "Salesforce login rejected (HTTP %s). Check the Connected App client ID, "
                "secret, and that the client credentials flow is enabled." % response.status_code,
                status=response.status_code, code="AUTH_FAILED",
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        body = response.json()
        token = {"access_token": body["access_token"], "instance_url": body["instance_url"].rstrip("/")}
        with _TOKEN_LOCK:
            _TOKEN_CACHE[self._cache_key] = token
        return token

    def _token(self, refresh=False):
        with _TOKEN_LOCK:
            token = None if refresh else _TOKEN_CACHE.get(self._cache_key)
        return token or self._authenticate()

    @classmethod
    def clear_token_cache(cls):
        with _TOKEN_LOCK:
            _TOKEN_CACHE.clear()

    # -- HTTP ----------------------------------------------------------------

    def request(self, method, path, json=None, params=None):
        """Call the REST API.  ``path`` is relative to /services/data/vXX.X/."""
        for attempt in (1, 2):
            token = self._token(refresh=attempt == 2)
            if path.startswith("/services/"):
                url = token["instance_url"] + path
            else:
                url = "%s/services/data/v%s/%s" % (token["instance_url"], self.api_version, path.lstrip("/"))
            try:
                response = self.session.request(
                    method, url, json=json, params=params, timeout=self.timeout,
                    headers={"Authorization": "Bearer %s" % token["access_token"],
                             "Accept": "application/json"},
                )
            except requests.RequestException as exc:
                raise SalesforceError("Salesforce request failed: %s" % exc, retryable=True) from exc
            if response.status_code == 401 and attempt == 1:
                continue  # session expired or revoked: log in again once
            return self._handle(response, method, path)
        return None  # pragma: no cover - loop always returns or raises

    @staticmethod
    def _handle(response, method, path):
        if response.status_code == 204:
            return {}
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if response.status_code < 400:
            return body
        errors = body if isinstance(body, list) else [body]
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        code = first.get("errorCode")
        message = "; ".join(
            "%s: %s" % (e.get("errorCode"), e.get("message")) for e in errors if isinstance(e, dict)
        ) or "HTTP %s" % response.status_code
        _logger.warning("salesforce_api_error method=%s path=%s status=%s code=%s",
                        method, path, response.status_code, code)
        raise SalesforceError(
            message, status=response.status_code, code=code,
            retryable=response.status_code in RETRYABLE_STATUS or code == "UNABLE_TO_LOCK_ROW",
        )

    # -- helpers -------------------------------------------------------------

    def query(self, soql):
        body = self.request("GET", "query", params={"q": soql})
        records = list(body.get("records", []))
        while body.get("nextRecordsUrl"):
            body = self.request("GET", body["nextRecordsUrl"])
            records.extend(body.get("records", []))
        return records

    def upsert(self, sobject, external_field, external_value, payload):
        """Create or update by external ID.  Returns (record_id, created)."""
        path = "sobjects/%s/%s/%s" % (sobject, external_field, quote(str(external_value), safe=""))
        body = self.request("PATCH", path, json=payload)
        return body.get("id"), bool(body.get("created"))

    def update(self, sobject, record_id, payload):
        self.request("PATCH", "sobjects/%s/%s" % (sobject, record_id), json=payload)
        return record_id

    def apex_post(self, path, payload):
        """Call a custom Apex REST endpoint (/services/apexrest/<path>)."""
        return self.request("POST", "/services/apexrest/%s" % path.lstrip("/"), json=payload)

    def create(self, sobject, payload):
        """Insert one record.  Returns its ID."""
        return self.request("POST", "sobjects/%s" % sobject, json=payload).get("id")
