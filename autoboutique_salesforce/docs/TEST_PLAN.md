# Test plan

Run on an Odoo.sh **staging** build connected to a **Salesforce sandbox**.
Automated tests (`tests/`) already run on every Odoo.sh build. This plan
checks the real Salesforce connection end to end.

## Sample data

| Item | Value |
| --- | --- |
| Company | Autoboutique |
| VIN | `MHFXW42G0P2000123` (test value) |
| Vehicle | 2024 Toyota Vios 1.3 XLE CVT, Pearl White, 18,500 km, plate `NAB 1234` |
| Selling price | PHP 748,000 |
| Acquisition cost | PHP 512,345 (must **never** appear in Salesforce) |
| Salesforce loan application | Borrower *Angela Mendoza*, `angela.mendoza@example.com`, Status *Documents Pending*, Vehicle Price 748,000, Selected Vehicle = the synced Vios, Assigned Agent = a user whose email matches an Odoo user |
| Overruns control vehicle | Any Overruns vehicle, same VIN `MHFXW42G0P2000123`, published |

## Cases

| # | Steps | Expected |
| --- | --- | --- |
| 1 | Settings → Salesforce → **Test Connection** | "Connected to Salesforce." |
| 2 | Create the sample vehicle in Autoboutique; take it through final QC, detailing, documents, and approval; press **Ready for Sale** | Salesforce tab: *Publish* on, status *Queued*, Available Date = today |
| 3 | Wait for the queue cron (≤5 min) or press **Sync to Salesforce** | Status *Synced*; a new `Vehicle_Inventory__c` with Stock Number `ODOO-<id>`, Inventory Status *Available*, Odoo Vehicle ID = the Odoo ID, price 748,000 in both price fields |
| 4 | Inspect the Salesforce record (all fields, including history) | No cost, profit, supplier, repair, MRF, or accounting values anywhere |
| 5 | Change mileage to 18,600 in Odoo | One pending job; after it runs, Odometer = 18,600; still one Salesforce record |
| 6 | Change only the acquisition cost | No job is queued |
| 7 | In Salesforce, create the sample loan application | Within a minute (webhook) a Sales Application appears in Odoo: state *Draft*, customer Angela Mendoza (company Autoboutique), agent matched, Salesforce number/status shown |
| 8 | Change the Salesforce status to *Submitted* | Same Odoo application moves to *For Approval*; no second application or partner |
| 9 | Change the Salesforce status to *Approved* | Vehicle stays *Ready for Sale* in Odoo; Salesforce Inventory Status stays *Available* |
| 10 | In Odoo, **Approve & Reserve** the application | Vehicle *Reserved*; Salesforce Inventory Status becomes *Reserved* |
| 11 | Temporarily set a wrong webhook secret in Odoo; edit the loan application | Odoo log line `salesforce_webhook_rejected reason=bad_signature`; no job. Restore the secret; with polling on, the next sweep picks the change up |
| 12 | Temporarily set a wrong consumer secret; edit the vehicle | Job retries with growing delay, then *Failed*; vehicle status *Error* with a readable message. Restore; Manager presses **Retry**; status *Synced* |
| 13 | Publish the Overruns control vehicle | No job, no Salesforce record; an Overruns user sees no Salesforce queue or history for Autoboutique |
| 14 | In Salesforce, create a vehicle by hand with VIN `MHFXW42G0P2000999`, then publish an Odoo vehicle with that VIN | Odoo adopts the existing record (same Salesforce ID, agent's stock number kept); no duplicate |
| 15 | Delete the Salesforce record of the sample vehicle, then press **Sync to Salesforce** | A single replacement record is created and linked |
| 16 | Unpublish the vehicle | Salesforce Inventory Status becomes *Inactive* (the record is not deleted) |
| 17 | Duplicate the staging database (or rebuild) | After neutralization: sync disabled, secrets empty, vehicle Salesforce IDs cleared |

Record the Odoo build, the Salesforce sandbox, the tester, and the pass/fail
result for each case before merging to production.
