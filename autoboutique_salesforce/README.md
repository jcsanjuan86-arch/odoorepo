# Autoboutique Salesforce Integration (Odoo 19.0)

Keeps the Autoboutique **Vehicle Master** in Odoo and the Salesforce org
(`ability-business-4807.my.salesforce.com`) in step:

| Direction | Odoo record | Salesforce record | Trigger |
| --- | --- | --- | --- |
| Odoo → Salesforce | `autoboutique.vehicle` (Vehicle Master) | `Vehicle_Inventory__c` | Vehicle published (automatic at Ready for Sale), then every listing change or status change |
| Salesforce → Odoo | `autoboutique.sales.application` + customer `res.partner` (+ optional draft `sale.order`) | `Auto_Loan_Application__c` with a `Selected_Vehicle__c` | Signed webhook from an Apex trigger, plus scheduled polling as a safety net |

Odoo stays the source of truth for VIN availability, inventory, cost, and
release. Salesforce stays the source of truth for loan applications and agent
activity. See [docs/FIELD_OWNERSHIP.md](docs/FIELD_OWNERSHIP.md).

Only the company chosen in **Settings → Salesforce → Salesforce Company**
(Autoboutique) takes part. Overruns vehicles, customers, jobs, and history are
never sent, matched, or shown.

## How it works

* **Service class**: `models/salesforce_client.py` is a plain REST client
  (OAuth 2.0 client credentials, one automatic re-login on 401, retryable vs.
  permanent error classification). `models/salesforce_sync.py` holds all mapping
  and sync rules.
* **Queue**: every change becomes an `autoboutique.salesforce.job`. A partial
  unique index allows one pending job per vehicle / Salesforce record, so bursts
  of edits or duplicate webhooks never double-send. The *process sync queue*
  cron (every 5 min) runs each job in its own savepoint and commit, retrying
  transient failures after 1, 5, 15, 60, and 240 minutes (max attempts
  configurable).
* **Idempotency**: vehicles are keyed by `Odoo_Vehicle_ID__c` (external ID) and
  the stored Salesforce ID; a SHA-256 of the last payload skips no-op updates. A
  Salesforce vehicle that agents created by hand with the same VIN is adopted,
  not duplicated. Loan applications are keyed by their Salesforce ID with a
  database-level unique index, and `SystemModstamp` skips versions already applied.
* **Scheduled sync** (*Salesforce: scheduled sync*, interval set in
  Settings) re-queues vehicles whose payload changed and, if enabled, polls
  loan applications changed since the last watermark.
* **Webhook**: `POST /autoboutique_salesforce/webhook` accepts
  `{"object": "Auto_Loan_Application__c", "ids": [...]}` only with a valid
  `X-Autoboutique-Signature` = hex HMAC-SHA256 of `"<timestamp>." + body` and a
  timestamp within 5 minutes. The body carries IDs only; Odoo re-reads each record
  through the API.
* **History**: every push/pull writes an `autoboutique.salesforce.log` row
  (shown on the vehicle's Salesforce tab and under *Autoboutique → Salesforce →
  Sync History*) and a structured `salesforce_sync key=value` server log line.

## Security

| Group | Can |
| --- | --- |
| Salesforce Sync / User | See the Salesforce tab, publish/unpublish vehicles, press **Sync to Salesforce**, read queue and history |
| Salesforce Sync / Manager | The above, plus retry or cancel queued jobs |
| Settings administrator (`base.group_system`) | Edit the connection, secrets, and sync rules |

Credentials live in `ir.config_parameter` (administrators only) or, if set,
the `AUTOBOUTIQUE_SF_CLIENT_SECRET` / `AUTOBOUTIQUE_SF_WEBHOOK_SECRET`
environment variables, which take precedence. Nothing is hard-coded.

Staging and development databases on Odoo.sh are neutralized by
`data/neutralize.sql`: the sync is switched off, secrets are removed, pending
jobs are cancelled and production Salesforce IDs are cleared, so a copy of
production can never write to production Salesforce.

## Setup

1. Salesforce: [docs/SALESFORCE_SETUP.md](docs/SALESFORCE_SETUP.md) (new
   fields, integration user, External Client App / Connected App, webhook trigger).
2. Odoo.sh: [docs/ODOO_SH.md](docs/ODOO_SH.md).
3. Acceptance: [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

## Automated tests

`tests/` covers field mapping and the no-cost allowlist, duplicate prevention
(queue, VIN adoption, repeated pushes, repeated webhooks and loan applications),
webhook signature validation (unit and HTTP), company isolation (queueing,
pushing, sweeping, inbound matching, record rules), and the REST client
(re-login, retry classification, URL and SOQL escaping). All Salesforce calls
are faked; tests never reach the network. Odoo.sh runs them on every
development build.
