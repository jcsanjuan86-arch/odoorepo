from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import SAMPLE_VIN, SalesforceCase

ALLOWED_FIELDS = {
    "Stock_Number__c", "VIN__c", "Vehicle_Name__c", "Brand__c", "Model__c", "Year__c", "Condition__c",
    "Odometer__c", "Plate_Number__c", "Color__c", "Selling_Price__c", "Selling_Price_PHP__c",
    "Inventory_Status__c", "Available_Date__c", "Listing_URL__c",
}


@tagged("post_install", "-at_install")
class TestVehicleMapping(SalesforceCase):
    def test_payload_is_the_listing_allowlist(self):
        vehicle = self._vehicle(vin=SAMPLE_VIN, variant="1.3 XLE CVT", mileage=18500, color="Pearl White",
                                plate_number="NAB 1234", selling_price=748000, acquisition_cost=512345,
                                listing_url="https://autoboutique.ph/cars/vios")
        payload = self.env["autoboutique.salesforce.sync"]._prepare_vehicle_payload(vehicle)
        self.assertEqual(set(payload), ALLOWED_FIELDS)
        self.assertEqual(payload["Stock_Number__c"], "ODOO-%d" % vehicle.id)
        self.assertEqual(payload["VIN__c"], SAMPLE_VIN)
        self.assertEqual(payload["Brand__c"], "Toyota")
        self.assertEqual(payload["Model__c"], "Vios 1.3 XLE CVT")
        self.assertEqual(payload["Vehicle_Name__c"], "2024 Toyota Vios 1.3 XLE CVT")
        self.assertEqual(payload["Condition__c"], "Used")
        self.assertEqual(payload["Odometer__c"], 18500)
        self.assertEqual(payload["Selling_Price__c"], 748000)
        self.assertEqual(payload["Selling_Price_PHP__c"], 748000)

    def test_costs_and_internal_data_never_leave_odoo(self):
        vehicle = self._vehicle(vin=SAMPLE_VIN, selling_price=748000, acquisition_cost=512345)
        payload = self.env["autoboutique.salesforce.sync"]._prepare_vehicle_payload(vehicle)
        self.assertNotIn(512345, payload.values())
        for forbidden in ("cost", "profit", "supplier", "repair", "mrf", "notes", "invoice"):
            self.assertFalse([key for key in payload if forbidden in key.lower()], forbidden)

    def test_listing_status_follows_odoo_state(self):
        sync = self.env["autoboutique.salesforce.sync"]
        vehicle = self._vehicle(vin=SAMPLE_VIN)
        self.assertEqual(sync._listing_status(vehicle), "Inactive")  # not published
        self._make_ready(vehicle)
        self.assertTrue(vehicle.publish_to_salesforce, "Ready for Sale auto-publishes")
        self.assertEqual(sync._listing_status(vehicle), "Available")
        for state, expected in [("reserved", "Reserved"), ("sold", "Sold"), ("released", "Sold")]:
            vehicle.state = state
            self.assertEqual(sync._listing_status(vehicle), expected)
        vehicle.publish_to_salesforce = False
        self.assertEqual(sync._listing_status(vehicle), "Inactive")

    def test_ready_for_sale_sets_available_date_and_pushes(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self.assertTrue(vehicle.ready_for_sale_date)
        self.assertEqual(vehicle.salesforce_sync_status, "queued")
        self._run_jobs()
        self.assertEqual(vehicle.salesforce_sync_status, "synced")
        row = self.fake.vehicles[vehicle.salesforce_vehicle_id]
        self.assertEqual(row["Inventory_Status__c"], "Available")
        self.assertEqual(row["Odoo_Vehicle_ID__c"], str(vehicle.id))
        self.assertEqual(vehicle.salesforce_listing_status, "Available")
        self.assertTrue(vehicle.salesforce_log_ids.filtered(lambda log: log.status == "success"))

    @mute_logger("odoo.addons.autoboutique_salesforce.models.salesforce_log")
    def test_missing_required_salesforce_fields_fail_clearly(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN, selling_price=0))
        self._run_jobs()
        self.assertEqual(vehicle.salesforce_sync_status, "error")
        self.assertIn("Selling Price", vehicle.salesforce_last_error)
        self.assertFalse(self.fake.vehicles)
        vehicle.selling_price = 748000  # fixing the data re-queues the push
        self._run_jobs()
        self.assertEqual(vehicle.salesforce_sync_status, "synced")

    def test_internal_changes_do_not_trigger_a_push(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        vehicle.acquisition_cost = 999999
        self.assertFalse(self._jobs(vehicle_id=vehicle.id, state="pending"))
