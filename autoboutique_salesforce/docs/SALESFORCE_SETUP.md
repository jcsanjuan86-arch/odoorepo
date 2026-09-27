# Salesforce setup

Do every step in a **Salesforce sandbox first**, connected to an Odoo.sh
development or staging build. Repeat in production only after the
[test plan](TEST_PLAN.md) passes.

The metadata lives in `salesforce/` at the repository root (an SFDX project).

## 1. Data model

The integration reuses the existing objects. Nothing that exists today is
renamed or removed.

**`Vehicle_Inventory__c`**: fields added by this project:

| Field | Type | Purpose |
| --- | --- | --- |
| `Odoo_Vehicle_ID__c` | Text(40), External ID, Unique | Odoo upsert key |
| `Available_Date__c` | Date | Date the car became Ready for Sale |
| `Listing_URL__c` | URL | Public listing page |

Existing fields that the integration writes are listed in
[FIELD_OWNERSHIP.md](FIELD_OWNERSHIP.md). `Vehicle_Inventory__c` already
requires Brand, Condition, Model, Selling Price, Stock Number, Vehicle Name, and
Year. Odoo refuses to publish a vehicle with no selling price or year and says
why on the Salesforce tab.

Recommended data cleanup before go-live: add VINs to the existing
`Vehicle_Inventory__c` records (only 2 of 10 have one today). When Odoo first
publishes a car, it adopts the Salesforce record with the same VIN instead of
creating a duplicate. Without a VIN, a hand-made Salesforce record for the same
car cannot be recognised.

**`Auto_Loan_Application__c`**: read only; no new fields. It must have
`Selected_Vehicle__c` set to reach Odoo.

**`Odoo_Integration_Settings__c`** (public hierarchy custom setting; production
orgs do not allow Protected for unmanaged metadata): webhook endpoint URL,
shared secret, and an on/off switch. Keep the org preference *Restrict access to
custom settings* on so only admins can read the secret.

**Apex**: `OdooWebhookNotifier` (queueable callout),
`AutoLoanApplicationOdooSync` (after insert/update trigger), and
`OdooWebhookNotifierTest`.

**`Odoo_Integration` permission set**: least-privilege access for the
integration user (create/edit Vehicle Inventory; read Auto Loan Applications)
plus the `Odoo_Integration` custom permission. **Assign it to whichever user is
the app's Run As user**, even a System Administrator: new fields are hidden from
existing profiles, and without it the first push fails with
`No such column 'Odoo_Vehicle_ID__c'`.

## 1a. Process rules deployed with the integration

| Area | Rule | Metadata |
| --- | --- | --- |
| Vehicle Inventory | Agents cannot create vehicles; cars come from Odoo | `Autobotique_Staff` permission set has no Create |
| Vehicle Inventory | On cars published from Odoo, only the integration can change VIN, specs, price, status, dates and listing URL. Branch, images, notes, default terms and suggested downpayment stay editable | Validation rule `Odoo_Owned_Fields_Locked`, custom permission `Odoo_Integration` |
| Vehicle Inventory, Loan Application | Each currency field and its "(PHP)" twin are kept equal | `AutobotiqueRecordDefaults`, triggers `VehicleInventoryDefaults`, `AutoLoanApplicationDefaults` |
| Loan Application | Picking a car copies its details and price, fills a blank downpayment (full price for Cash, suggested downpayment otherwise) and derives Loan = Price - Downpayment. Monthly amortization is left to the agent | same Apex |
| Loan Application | Assigned Agent defaults to the owner when the owner is a user | same Apex |
| Loan Application | Available and Reserved cars stay open to more applicants; Sold and Inactive cars cannot be selected | Validation rule `Selected_Vehicle_Not_Sold` |
| Loan Application | New applications get the required-document checklist for their applicant type | Flow `Create_Application_Documents` (activated) |
| Follow-ups | *Overdue Follow-Ups (All Agents)* and *My Follow-Ups Due Today or Overdue* list views; report *Overdue Follow-Ups by Agent* | `listViews/`, `reports/Autobotique_Loan_Reports/` |

The draft flows `Populate_Vehicle_Details_From_Inventory` and
`Assign_Autobotique_Agent` are superseded by the Apex above and must stay
inactive.

## 2. Deploy the metadata

Edit `salesforce/force-app/main/default/remoteSiteSettings/Odoo_Webhook.remoteSite-meta.xml`
It points at production Odoo, `https://jcsanjuan86-arch-odoorepo.odoo.com`.
For a sandbox, change it to the Odoo.sh staging URL.

Then, from the `salesforce/` folder:

```bash
sf project deploy validate --source-dir force-app --target-org <sandbox-alias> --test-level RunSpecifiedTests --tests OdooWebhookNotifierTest
```

```bash
sf project deploy start --source-dir force-app --target-org <sandbox-alias> --test-level RunSpecifiedTests --tests OdooWebhookNotifierTest
```

If `Auto_Loan_Application__c` has validation rules that the test's minimal
record doesn't satisfy, the test will report which ones. Add the required values
to `OdooWebhookNotifierTest`.

## 3. Integration user

1. Setup → Users → New User. Use the **Salesforce Integration** user license and
   the **Minimum Access - API Only Integrations** profile (or your org's API-only
   equivalent). Example username: `odoo.integration@autoboutique.ph`.
2. Assign the **Odoo Integration** permission set (and the *Salesforce API
   Integration* permission set license if your org requires it).

## 4. External Client App (OAuth 2.0 client credentials)

Newer orgs create **External Client Apps**. Classic **Connected Apps** use the
same settings under different menu names.

1. Setup → **External Client App Manager** → *New External Client App*
   (or App Manager → *New Connected App*).
2. Name: `Odoo Autoboutique`. Contact email: your admin mailbox.
3. Enable OAuth:
   * Callback URL: `https://login.salesforce.com/services/oauth2/success`
     (required by the form, not used by this flow).
   * Scopes: **Manage user data via APIs (api)** only.
   * Enable **Client Credentials Flow**.
   * Leave "Require secret for Web Server Flow" and PKCE at their defaults.
4. Save. Then, under *Policies* (Connected App: *Manage → Edit Policies*):
   * **Client Credentials Flow → Run As**: the integration user from step 3.
   * Permitted users: *Admin approved users are pre-authorized*, and add the
     integration user's profile or permission set.
   * IP relaxation: follow your org's policy. Odoo.sh egress IPs are not fixed,
     so do not restrict login IP ranges on the integration user's profile.
5. *Settings → OAuth Settings → Consumer Key and Secret*: copy both into Odoo
   (see [ODOO_SH.md](ODOO_SH.md)). Treat the secret like a password.

Check it from any terminal (replace values; do not paste the secret into shared chats):

```bash
curl -s -X POST https://ability-business-4807.my.salesforce.com/services/oauth2/token -d grant_type=client_credentials -d client_id=CONSUMER_KEY -d client_secret=CONSUMER_SECRET
```

A JSON response with `access_token` means the app is ready. In Odoo, the
**Test Connection** button in Settings performs the same check.

## 5. Webhook settings

Setup → Custom Settings → **Odoo Integration Settings** → *Manage* → *New*
(organization default):

| Field | Value |
| --- | --- |
| Enabled | checked |
| Endpoint URL | `https://<odoo-domain>/autoboutique_salesforce/webhook` |
| Webhook Secret | a long random value, identical to *Webhook Secret* in Odoo Settings |

Generate a secret, for example with PowerShell:

```bash
powershell -NoProfile -Command "[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))"
```

If the webhook is off or a call fails, nothing is lost: enable **Poll Loan
Applications** in Odoo and the scheduled sync fetches changes by `SystemModstamp`.

## 6. Rotating secrets

* Consumer secret: generate a new one in the app, update Odoo Settings (or the
  environment variable), then revoke the old one.
* Webhook secret: update the Odoo value and the custom setting together. Odoo
  rejects mismatched signatures with HTTP 401, and polling covers the gap.
