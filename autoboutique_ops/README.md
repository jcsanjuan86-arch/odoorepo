# Autoboutique vehicle operations for Odoo 19.0

This is the first, deliberately bounded rebuild of the SaaS 19.4 Studio workflow. It stores linked records and allows staff to advance stages manually. It does **not** create purchase orders, inventory movements, vendor bills, sales orders, or journal entries automatically. Links to these native records are references, not proof that stock or costs were posted.

## Workflow

Bid lot (many cars) → approval and native purchase order → receiving → Vehicle Master/VIN → initial QC → repair assessment → multi-item MRF → stock issue or approved purchase → repair completion → final QC → detailing approval → ready for sale → sales order → payment → vehicle release → registration, insurance, and documents.

The Vehicle Master has guided workflow buttons for the stage changes from QC through handover. They only update the workflow status after the user has created and verified the required linked records. They deliberately do not create or validate a Purchase Order, stock move, customer invoice, payment, or release automatically.

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
