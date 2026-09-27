# Autoboutique vehicle operations for Odoo 19.0

Python rebuild of the SaaS 19.4 Studio workflow, with the whole vehicle chain automated. Every step creates the next record and assigns a to-do to the responsible person. Documents that post stock or accounting entries (purchase orders, receipts, sales orders, invoices, payments) are only **drafted**: a person confirms, validates, posts or pays them, and the vehicle then advances by itself.

## Workflow

Bid lot (many cars) → approval and native purchase order → receiving → Vehicle Master/VIN → initial QC → repair assessment → multi-item MRF → stock issue or approved purchase → repair completion → final QC → detailing approval → ready for sale → sales order → payment → vehicle release → registration, insurance, and documents.

## Automation (`models/automation.py`)

| When a person… | Odoo automatically… | To-do for |
| --- | --- | --- |
| approves a bid lot | drafts one RFQ for the selected cars (one serial-tracked product per year/make/model) and links the receivings | Purchasing: confirm RFQ |
| confirms the RFQ | links the receipt to each receiving and prefills each VIN as the serial number | Warehouse: validate receipt |
| validates the receipt | marks the car received, creates the Vehicle Master and the initial QC | QC Inspector |
| enters a QC result | initial QC or failed QC: creates the repair assessment; passed final QC: creates the detailing job | Repair Lead / Detailing |
| approves a repair assessment | creates a material request from cost lines with products | Repair Lead |
| finishes repairs and closes (or rejects) material requests | creates the final QC | QC Inspector |
| approves detailing and ticks Documents Verified + Ready For Sale Approved | moves the car to Ready for Sale (and Salesforce) | Operations Manager until both are ticked |
| approves and reserves a sales application | drafts the quotation | Sales agent: send and confirm |
| confirms the sales order | marks the car Sold and drafts the invoice | Accounting: post and collect |
| registers the payment | records the payment and creates the vehicle release | Operations Manager |
| approves the release | creates the registration | Documents Officer; also insurance to-do |
| completes registration and activates insurance, with no missing required documents | moves the car to Documents Complete | – |

Roles are set per company in **Settings → Autoboutique**; an empty role sends the to-do to whoever triggered the step. Automation that runs inside a native action (receipt validation, sales order confirmation, payment registration) never blocks that action: a failing step is rolled back, written to the record's chatter, and assigned to the Operations Manager.

The Vehicle Master still has guided workflow buttons for every stage, so staff can advance a car by hand when needed.

The Vehicle Master checks the final QC, completed repairs, closed MRFs, approved detailing, verified documents, and sale readiness approval before the `Ready for Sale` stage can be saved. Users must validate actual inventory movements and accounting entries in native Odoo apps. MRF item lines record the related purchase line or stock move and issued quantity.

## Source backup inventory

The source archive is `prime-auto-boutique.dump.zip` from Odoo Online SaaS 19.4. It contains `dump.sql` and a filestore. This module is not a direct import of that database. The SQL should never be restored to 19.0.

| SaaS 19.4 model | 19.0 model | Source rows | Status |
| --- | --- | ---: | --- |
| `x_bids` | `autoboutique.bid` | 1 | Core fields mapped |
| `x_bids_line_e0fa6` | `autoboutique.bid.line` | 2 | Core fields mapped |
| `x_vehicle_receiving` | `autoboutique.receiving` | 1 | Core fields mapped |
| `x_vehicle_master` | `autoboutique.vehicle` | 1 | Core fields mapped |
| `x_qc_inspection` | `autoboutique.qc` | 2 | Core fields mapped |
| `x_repair_assessment` | `autoboutique.repair` | 2 | Core fields mapped |
| `x_repair_cost_line` | `autoboutique.repair.line` | 1 | Core fields mapped |
| `x_material_request_for` | `autoboutique.mrf` | 1 | Header mapped; item lines are a corrected 19.0 design |
| `x_vehicle_detailing_jo` | `autoboutique.detailing` | 1 | Core fields mapped |

The following operational models are now rebuilt in Python: Sales Application, Vehicle Release, Vehicle Registration, Vehicle Insurance, Document Tracking, Sales Commission, and Management KPI Snapshot. They include company isolation, their main approval gates, and guided actions. There are 515 custom fields across 24 custom models in the source, so not every legacy field, view layout, report, attachment, calendar, chatter feature, or Salesforce integration is yet replicated.

## Migration order

1. Install and validate this module on a disposable Odoo.sh development build.
2. Create the required companies, users, products, vendors, stock lots and native purchase documents, and verify their IDs and company ownership.
3. Export source rows with stable legacy IDs; map bid and cars first, then receiving and vehicle, then QC, repair and cost lines, then MRF and detailing. Map relational IDs using the legacy ID crosswalk; never copy numeric database IDs directly.
4. Import in that order to a test database, reconcile counts, VIN uniqueness, company, linked records, stock quantities, and posted accounting balances.
5. Only after reconciliation, repeat the approved import into production with a fresh pre-import backup.

The source ZIP and its filestore stay outside the Git repository. Do not commit customer or vehicle records to Git.
