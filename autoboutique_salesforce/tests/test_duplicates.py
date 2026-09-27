from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import SAMPLE_SF_APPLICATION_ID, SAMPLE_SF_VEHICLE_ID, SAMPLE_VIN, SalesforceCase


def loan_application(vehicle_sf_id, modstamp="2026-09-01T02:36:56.000+0000", status="Documents Pending"):
    return {
        "Id": SAMPLE_SF_APPLICATION_ID,
        "Name": "Mendoza, Angela",
        "Application_Number__c": "ALA-000044",
        "SystemModstamp": modstamp,
        "Status__c": status,
        "Final_Review_Status__c": "Pending Review",
        "Application_Date__c": "2026-08-24",
        "Borrower_First_Name__c": "Angela",
        "Borrower_Middle_Name__c": None,
        "Borrower_Last_Name__c": "Mendoza",
        "Borrower_Email__c": "angela.mendoza@example.com",
        "Borrower_Mobile_Number__c": "+63 917 000 0000",
        "Client__c": "003d5000000CLNTAAA",
        "Vehicle_Price__c": 748000,
        "Selected_Vehicle__c": vehicle_sf_id,
        "Selected_Vehicle__r": {"VIN__c": SAMPLE_VIN, "Odoo_Vehicle_ID__c": None},
        "Assigned_Agent__r": {"Email": "agent.sf.test@example.com"},
    }


@tagged("post_install", "-at_install")
class TestDuplicatePrevention(SalesforceCase):
    def test_repeated_changes_queue_one_job(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        vehicle.write({"mileage": 100})
        vehicle.write({"color": "Red"})
        self.assertEqual(len(self._jobs(vehicle_id=vehicle.id, state="pending")), 1)

    def test_repeated_pushes_update_the_same_salesforce_record(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        first_id = vehicle.salesforce_vehicle_id
        vehicle.write({"mileage": 20000})
        self._run_jobs()
        self.env["autoboutique.salesforce.sync"]._push_vehicle(vehicle, force=True)
        self.assertEqual(vehicle.salesforce_vehicle_id, first_id)
        self.assertEqual(len(self.fake.vehicles), 1)
        self.assertEqual(self.fake.vehicles[first_id]["Odometer__c"], 20000)

    def test_unchanged_vehicle_is_not_resent(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        writes = len([c for c in self.fake.calls if c[0] in ("upsert", "update")])
        self.env["autoboutique.salesforce.sync"]._push_vehicle(vehicle)
        self.assertEqual(len([c for c in self.fake.calls if c[0] in ("upsert", "update")]), writes)

    def test_existing_salesforce_vehicle_with_same_vin_is_adopted(self):
        self.fake.vehicles[SAMPLE_SF_VEHICLE_ID] = {"VIN__c": SAMPLE_VIN, "Stock_Number__c": "12"}
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        self.assertEqual(vehicle.salesforce_vehicle_id, SAMPLE_SF_VEHICLE_ID)
        self.assertEqual(len(self.fake.vehicles), 1)
        self.assertEqual(self.fake.vehicles[SAMPLE_SF_VEHICLE_ID]["Odoo_Vehicle_ID__c"], str(vehicle.id))
        self.assertEqual(self.fake.vehicles[SAMPLE_SF_VEHICLE_ID]["Stock_Number__c"], "12",
                         "The agent's stock number is kept")

    def test_vehicle_deleted_in_salesforce_is_recreated_once(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        self.fake.vehicles.clear()
        self.env["autoboutique.salesforce.sync"]._push_vehicle(vehicle, force=True)
        self.assertEqual(len(self.fake.vehicles), 1)
        self.assertEqual(vehicle.salesforce_vehicle_id, next(iter(self.fake.vehicles)))

    @mute_logger("odoo.addons.autoboutique_salesforce.models.salesforce_log")
    def test_vin_linked_to_other_odoo_vehicle_is_an_error_not_a_duplicate(self):
        self.fake.vehicles[SAMPLE_SF_VEHICLE_ID] = {"VIN__c": SAMPLE_VIN, "Odoo_Vehicle_ID__c": "999999"}
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        self.assertEqual(vehicle.salesforce_sync_status, "error")
        self.assertIn("already linked", vehicle.salesforce_last_error)
        self.assertEqual(len(self.fake.vehicles), 1)
        self.assertEqual(self._jobs(vehicle_id=vehicle.id).state, "failed")

    def test_loan_application_is_imported_once(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN, selling_price=748000))
        self._run_jobs()
        sync = self.env["autoboutique.salesforce.sync"]
        data = loan_application(vehicle.salesforce_vehicle_id)
        first = sync._apply_loan_application(data)
        again = sync._apply_loan_application(dict(data))
        newer = sync._apply_loan_application(loan_application(
            vehicle.salesforce_vehicle_id, modstamp="2026-09-02T01:00:00.000+0000", status="Submitted"))
        self.assertEqual(first, again)
        self.assertEqual(first, newer)
        applications = self.env["autoboutique.sales.application"].search(
            [("salesforce_application_id", "=", SAMPLE_SF_APPLICATION_ID)])
        self.assertEqual(len(applications), 1)
        self.assertEqual(applications.state, "approval")
        self.assertEqual(applications.sales_agent_id, self.agent)
        self.assertEqual(len(self.env["res.partner"].search([("salesforce_contact_id", "=", "003d5000000CLNTAAA")])), 1)

    def test_documents_pending_does_not_reserve(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        application = self.env["autoboutique.salesforce.sync"]._apply_loan_application(
            loan_application(vehicle.salesforce_vehicle_id, status="Documents Pending"))
        self.assertEqual(application.state, "draft")
        self.assertEqual(vehicle.state, "ready")

    def test_salesforce_approval_reserves_but_never_sells(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        sync = self.env["autoboutique.salesforce.sync"]
        sync._apply_loan_application(loan_application(vehicle.salesforce_vehicle_id))
        application = sync._apply_loan_application(loan_application(
            vehicle.salesforce_vehicle_id, modstamp="2026-09-03T01:00:00.000+0000", status="Approved"))
        self.assertEqual(application.state, "reserved")
        self.assertTrue(application.requirements_complete)
        self.assertEqual(vehicle.state, "reserved", "Salesforce final approval reserves the car in Odoo")
        self.assertEqual(vehicle.customer_id, application.customer_id)
        self.assertNotIn(vehicle.sale_order_id.state, ("sale", "done"), "Selling still needs an Odoo confirmation")
        self._run_jobs()
        self.assertEqual(self.fake.vehicles[vehicle.salesforce_vehicle_id]["Inventory_Status__c"], "Reserved")

    def test_second_approved_buyer_does_not_take_over_a_reserved_car(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        sync = self.env["autoboutique.salesforce.sync"]
        first = sync._apply_loan_application(loan_application(vehicle.salesforce_vehicle_id, status="Approved"))
        self.assertEqual(first.state, "reserved")
        second_data = dict(loan_application(vehicle.salesforce_vehicle_id, status="Approved"),
                           Id="a0Ad5000009XYZ2EAA", Application_Number__c="ALA-000050",
                           Client__c="003d5000000CLN2AAA", Borrower_Email__c="second.buyer@example.com")
        second = sync._apply_loan_application(second_data)
        self.assertEqual(second.state, "approval", "The backup buyer waits for the manager")
        self.assertEqual(vehicle.customer_id, first.customer_id)
        self.assertTrue(second.activity_ids.filtered(
            lambda a: a.summary == "Salesforce approved a buyer for an unavailable car"))

    def test_webhook_duplicates_queue_one_pull(self):
        sync = self.env["autoboutique.salesforce.sync"]
        sync._enqueue_applications([SAMPLE_SF_APPLICATION_ID])
        sync._enqueue_applications([SAMPLE_SF_APPLICATION_ID, SAMPLE_SF_APPLICATION_ID])
        self.assertEqual(len(self._jobs(salesforce_record_id=SAMPLE_SF_APPLICATION_ID, state="pending")), 1)
