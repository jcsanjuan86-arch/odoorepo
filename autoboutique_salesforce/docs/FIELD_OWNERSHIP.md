# Which system owns what

**Owner** = the only system where the value may be changed. The other system
holds a read-only copy or does not hold it at all.

## Vehicle (Odoo `autoboutique.vehicle` → Salesforce `Vehicle_Inventory__c`)

| Odoo field | Salesforce field | Owner | Notes |
| --- | --- | --- | --- |
| `id` | `Odoo_Vehicle_ID__c` (External ID, unique) | Odoo | Upsert key |
| `id` (as `ODOO-<id>`) | `Stock_Number__c` | Odoo on create; Salesforce afterwards | Required and unique in Salesforce. Sent only when Odoo creates the record; stock numbers already typed by agents are kept |
| `vin` | `VIN__c` | Odoo | Also used to adopt a Salesforce vehicle created by hand |
| `model_year make model variant` | `Vehicle_Name__c` | Odoo | Truncated to 120 characters |
| `make` | `Brand__c` | Odoo | |
| `model` + `variant` | `Model__c` | Odoo | |
| `model_year` | `Year__c` | Odoo | Required before publishing |
| `condition` | `Condition__c` | Odoo | Brand New / Used (default Used) |
| `mileage` | `Odometer__c` | Odoo | |
| `plate_number` | `Plate_Number__c` | Odoo | |
| `color` | `Color__c` | Odoo | New Odoo field |
| `selling_price` | `Selling_Price__c` and `Selling_Price_PHP__c` | Odoo | Required before publishing; both Salesforce price fields are kept equal |
| `state` + `publish_to_salesforce` | `Inventory_Status__c` | Odoo | Ready for Sale → Available; Reserved → Reserved; Sold / Payment / Released / Documents → Sold; unpublished or not yet ready → Inactive |
| `ready_for_sale_date` | `Available_Date__c` | Odoo | Set automatically when the vehicle reaches Ready for Sale |
| `listing_url` | `Listing_URL__c` | Odoo | |
| — | `Branch__c`, `Default_Terms__c`, `Suggested_Downpayment__c`, `Notes__c`, vehicle images | Salesforce | Never touched by Odoo |

**Never sent to Salesforce** (not in the allowlist): acquisition cost, actual
repair/detailing/vehicle cost, gross profit, supplier, bid lot, purchase order,
QC findings, repair notes and lines, MRFs, detailing costs, invoices, payments,
and all accounting data. Adding any of these requires a code change to
`_prepare_vehicle_payload` and explicit business approval.

If someone edits an Odoo-owned field in Salesforce, the next Odoo push
overwrites it. Pressing **Sync to Salesforce** forces that push immediately.

## Loan application (Salesforce `Auto_Loan_Application__c` → Odoo `autoboutique.sales.application`)

| Salesforce field | Odoo field | Owner | Notes |
| --- | --- | --- | --- |
| `Id` | `salesforce_application_id` | Salesforce | Unique per company; prevents duplicates |
| `Application_Number__c` | `salesforce_application_number`, name | Salesforce | |
| `Status__c` | `salesforce_status`; drives `state` only before Odoo approval | Salesforce until approval | Draft / Documents Pending → Draft; Submitted / Under Review / Final Review → For Approval; **Approved → Approve & Reserve in Odoo** (car Reserved, quotation drafted) when the car is Ready for Sale and not reserved for another buyer, otherwise a manager to-do; Rejected → Rejected |
| `Final_Review_Status__c` | `salesforce_final_review_status` | Salesforce | Display only |
| Borrower name, email, mobile; `Client__c` | `customer_id` (`res.partner`, `salesforce_contact_id`) | Salesforce on creation | Matched by Contact ID, then email; new partners belong to Autoboutique only |
| `Assigned_Agent__r.Email` | `sales_agent_id` | Salesforce on creation | Matched to an Odoo user; otherwise the configured fallback agent |
| `Vehicle_Price__c` | `selling_price` (on creation) | Salesforce on creation | Falls back to the vehicle's selling price |
| `Selected_Vehicle__c` | `vehicle_id` | Salesforce before approval | Only matches Autoboutique vehicles already linked to Salesforce (by Salesforce ID, Odoo ID, or VIN) |

**Not imported**: TIN, SSS, mother's maiden name, income, co-borrower data,
and other sensitive loan fields. They stay in Salesforce.

## States that only Odoo can change

* Vehicle `sold`, `payment`, `released`, `documents`, inventory moves, invoices,
  and payments. A Salesforce **Approved** loan runs Odoo's own *Approve & Reserve*
  (same checks, quotation only drafted); it never confirms the sale. Only confirming
  the sales order in Odoo marks the car Sold. A Salesforce **Released** status is
  display only: releasing needs a paid invoice and the Odoo handover checklist.
* A car already reserved for another buyer is never taken over by a Salesforce
  approval; the operations manager gets a to-do to decide.
* Once a sales application is approved, reserved, or sold in Odoo, later
  Salesforce changes update only the `salesforce_*` display fields.
* Optional draft quotations (Settings → *Create Draft Quotations*) are drafts
  only. They reserve no stock until an authorized user confirms them in Odoo.
