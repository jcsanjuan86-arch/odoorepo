# Odoo.sh configuration

## Branch flow

1. Push the feature branch `feature/autoboutique-salesforce` and add it as a
   **Development** branch in Odoo.sh. Every push builds a fresh database, installs
   the module, and runs its tests (`post_install` tests included).
2. Merge into **staging** only after the development build is green. Staging
   runs on a neutralized copy of production (see below).
3. Merge into **production** only after the [test plan](TEST_PLAN.md) passes on
   staging against a Salesforce sandbox. Odoo.sh upgrades the module on deploy.
   Take a manual backup first.

The module depends on `autoboutique_ops` and `sale_management`, and its Python
dependency, `requests`, is already part of Odoo.

## Install and configure

1. Apps → search *Autoboutique Salesforce Integration* → Install (or add it to
   the branch's module list).
2. Settings → Users: add staff to **Salesforce Sync / User** or **Manager**.
3. Settings → **Salesforce**:

| Setting | Value |
| --- | --- |
| Enable Salesforce Sync | on (last, once everything else is set) |
| Salesforce Company | **Autoboutique** (never Overruns) |
| Salesforce My Domain URL | production: `https://ability-business-4807.my.salesforce.com`; staging: the sandbox My Domain |
| API Version | `64.0` |
| Consumer Key / Secret | from the External Client App |
| Webhook Secret | same value as the Salesforce custom setting |
| Manual Publishing Only | off (publish automatically at Ready for Sale) |
| Poll Loan Applications | on (recommended safety net) |
| Create Draft Quotations | optional |
| Fallback Sales Agent | a real Autoboutique sales user |
| Scheduled Sync Interval | 60 minutes |
| Max Retries | 5 |

4. Press **Test Connection**.

## Secrets and environment variables

The secrets are stored as system parameters, readable only by Settings
administrators. If you manage the Odoo process environment yourself, you can
instead set `AUTOBOUTIQUE_SF_CLIENT_SECRET` and `AUTOBOUTIQUE_SF_WEBHOOK_SECRET`.
Environment values take precedence over the database. Odoo.sh does not provide a
general UI for custom environment variables, so on Odoo.sh the Settings screen is
the supported path.

## Neutralized databases (staging, development, duplicates)

`data/neutralize.sql` runs automatically whenever Odoo.sh neutralizes a copy of
production. It:

* switches the sync off,
* deletes the consumer secret, webhook secret, and polling watermark,
* cancels pending jobs,
* clears production Salesforce vehicle IDs and sync hashes.

To test on staging, point it at a **Salesforce sandbox**: enter the sandbox My
Domain URL, the sandbox app's key and secret, and a staging webhook secret, then
enable. Never enter production Salesforce credentials into staging.

## Operations

* **Autoboutique → Salesforce → Sync Queue**: pending and failed jobs. Managers
  can *Retry* or *Cancel*.
* **Sync History**: every push and pull, filterable by errors and direction.
* Vehicle → **Salesforce** tab: status, links, last error, history, and the
  **Sync to Salesforce** button.
* Server logs: search for `salesforce_sync`, `salesforce_api_error`,
  `salesforce_webhook_rejected`, `salesforce_job_crash`.
* Vehicles with a sync error are skipped by the hourly sweep until someone edits
  them or presses **Sync to Salesforce**, so one bad record doesn't fail every hour.
