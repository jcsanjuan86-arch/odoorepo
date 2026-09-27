from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .common import SAMPLE_VIN, SalesforceCase
from .test_duplicates import loan_application


@tagged("post_install", "-at_install")
class TestCompanyIsolation(SalesforceCase):
    def test_overruns_vehicle_is_never_queued_or_pushed(self):
        vehicle = self._vehicle(company=self.overruns, vin=SAMPLE_VIN, publish_to_salesforce=True)
        vehicle.write({"state": "reserved", "selling_price": 500000})
        self.assertFalse(self._jobs(vehicle_id=vehicle.id))
        # Even a job forced into the queue is refused at push time.
        job = self.env["autoboutique.salesforce.job"]._enqueue("vehicle_push", self.overruns, vehicle=vehicle)
        self._run_jobs()
        self.assertFalse(vehicle.salesforce_vehicle_id)
        self.assertFalse([c for c in self.fake.calls if c[0] in ("upsert", "update")])
        self.assertEqual(job.state, "done")
        self.assertEqual(vehicle.salesforce_log_ids.status, "skipped")

    def test_sweep_only_considers_the_salesforce_company(self):
        self._vehicle(company=self.overruns, vin="OVR-1", publish_to_salesforce=True)
        mine = self._vehicle(vin=SAMPLE_VIN, publish_to_salesforce=True)
        self.env["autoboutique.salesforce.job"].search([]).unlink()
        self.env["autoboutique.salesforce.sync"]._cron_sweep()
        self.assertEqual(self.env["autoboutique.salesforce.job"].search([]).vehicle_id, mine)

    def test_inbound_application_never_links_an_overruns_vehicle(self):
        overruns_vehicle = self._vehicle(company=self.overruns, vin=SAMPLE_VIN)
        overruns_vehicle.sudo().write({"salesforce_vehicle_id": "a0Bd50000000OVRAAA"})
        result = self.env["autoboutique.salesforce.sync"]._apply_loan_application(
            loan_application("a0Bd50000000OVRAAA"))
        self.assertFalse(result)
        self.assertFalse(self.env["autoboutique.sales.application"].search(
            [("vehicle_id", "=", overruns_vehicle.id)]))

    def test_created_records_belong_to_autoboutique(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        application = self.env["autoboutique.sales.application"].browse(
            self.env["autoboutique.salesforce.sync"]._apply_loan_application(
                loan_application(vehicle.salesforce_vehicle_id)).id)
        self.assertEqual(application.company_id, self.autoboutique)
        self.assertEqual(application.customer_id.company_id, self.autoboutique)
        logs = self.env["autoboutique.salesforce.log"].search([])
        self.assertEqual(logs.company_id, self.autoboutique)

    def test_overruns_user_cannot_see_autoboutique_sync_data(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        overruns_user = self.env["res.users"].create({
            "name": "Overruns Staff", "login": "overruns.sf.test@example.com",
            "company_id": self.overruns.id, "company_ids": [(6, 0, [self.overruns.id])],
            "group_ids": [(6, 0, [self.env.ref("autoboutique_salesforce.group_salesforce_manager").id])],
        })
        as_overruns = self.env(user=overruns_user)
        self.assertFalse(as_overruns["autoboutique.salesforce.log"].search([]))
        self.assertFalse(as_overruns["autoboutique.salesforce.job"].search([]))
        self.assertFalse(as_overruns["autoboutique.vehicle"].search([("id", "=", vehicle.id)]))

    def test_plain_user_cannot_publish(self):
        plain = self.env["res.users"].create({
            "name": "Plain", "login": "plain.sf.test@example.com",
            "company_id": self.autoboutique.id, "company_ids": [(6, 0, [self.autoboutique.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        vehicle = self._vehicle(vin=SAMPLE_VIN)
        with self.assertRaises(AccessError):
            vehicle.with_user(plain).write({"publish_to_salesforce": True})
