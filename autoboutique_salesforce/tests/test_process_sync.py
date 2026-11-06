from odoo.tests.common import tagged

from .common import SAMPLE_SF_APPLICATION_ID, SAMPLE_VIN, SalesforceCase
from .test_duplicates import loan_application


@tagged("post_install", "-at_install")
class TestProcessSync(SalesforceCase):

    def _approved(self, **reviewer):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN, plate_number="NIC 7909", mileage=42000))
        self._run_jobs()
        sync = self.env["autoboutique.salesforce.sync"]
        data = dict(loan_application(vehicle.salesforce_vehicle_id, status="Approved"),
                    Final_Reviewer__r=dict({"Name": "Marjorie Franco"}, **reviewer))
        return vehicle, sync._apply_loan_application(data)

    def test_final_checker_is_recorded_as_approver(self):
        _vehicle, application = self._approved(Email="agent.sf.test@example.com")
        self.assertEqual(application.state, "reserved")
        self.assertEqual(application.approved_by, self.agent, "The Salesforce checker, not the integration user")

    def test_unknown_checker_keeps_the_reservation(self):
        _vehicle, application = self._approved(Email="nobody@example.com")
        self.assertEqual(application.state, "reserved")
        self.assertTrue(any("Marjorie Franco" in (body or "") for body in application.message_ids.mapped("body")))

    def test_handover_marks_the_application_released(self):
        vehicle, application = self._approved()
        application.state = "sold"
        vehicle.write({"state": "released"})
        jobs = self._jobs(job_type="application_release", state="pending")
        self.assertEqual(len(jobs), 1)
        self._run_jobs()
        self.assertEqual(jobs.state, "done")
        sent = self.fake.applications[SAMPLE_SF_APPLICATION_ID]
        self.assertEqual(sent["Status__c"], "Released")
        self.assertEqual(sent["Vehicle_Plate_Number__c"], "NIC 7909")
        self.assertEqual(sent["Vehicle_Odometer__c"], 42000)

    def _financing_posts(self):
        return [call[2] for call in self.fake.calls if call[:2] == ("apex_post", "autobotique/financing")]

    def test_loan_application_creates_the_tracker_account(self):
        vehicle, application = self._approved()
        account = application.financing_account_ids
        self.assertEqual(len(account), 1)
        self.assertEqual(account.status, "approved")
        self.assertEqual(account.vehicle_id, vehicle)
        self.assertEqual(account.plate_number, "NIC 7909")
        self.assertEqual(account.customer_id, application.customer_id)

    def test_partner_picked_in_salesforce_fills_the_tracker(self):
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        sync = self.env["autoboutique.salesforce.sync"]
        data = dict(loan_application(vehicle.salesforce_vehicle_id), Financing_Partner__c="CARMS")
        account = sync._apply_loan_application(data).financing_account_ids
        carms = self.env.ref("autoboutique_ops.financing_partner_carms")
        self.assertEqual(account.partner_id, carms)
        self.assertEqual(account.source, "inhouse")
        manny = self.env.ref("autoboutique_ops.financing_partner_manny")
        account.partner_id = manny
        sync._apply_loan_application(dict(data, SystemModstamp="2026-09-02T02:36:56.000+0000"))
        self.assertEqual(account.partner_id, manny, "Finance's choice is kept")

    def test_tracker_changes_reach_the_salesforce_application(self):
        _vehicle, application = self._approved()
        self._run_jobs()
        bank = self.env.ref("autoboutique_ops.financing_bank_tfs")
        application.financing_account_ids.write({"bank_id": bank.id, "amount_approved": 550000})
        self.assertEqual(len(self._jobs(job_type="financing_push", state="pending")), 1)
        self._run_jobs()
        self.assertEqual(self._financing_posts()[-1], {
            "applicationId": SAMPLE_SF_APPLICATION_ID, "status": "Approved", "bank": "TFS",
            "amountApproved": 550000, "releaseDate": None,
        })

    def test_released_account_shows_in_salesforce(self):
        _vehicle, application = self._approved()
        account = application.financing_account_ids
        account.status = "released"
        self._run_jobs()
        self.assertEqual(self._financing_posts()[-1]["status"], "Released")
        self.assertEqual(self._financing_posts()[-1]["releaseDate"], str(account.release_date))

    def test_account_without_salesforce_application_stays_in_odoo(self):
        self.env["autoboutique.financing.account"].create({"name": "Zz Walk In", "company_id": self.autoboutique.id})
        self.assertFalse(self._jobs(job_type="financing_push"))

    def test_mobile_numbers_match_salesforce_format(self):
        sync = self.env["autoboutique.salesforce.sync"]
        self.assertEqual(sync._normalize_mobile("+63 917 123 4567"), "09171234567")
        self.assertEqual(sync._normalize_mobile("917-123-4567"), "09171234567")
        self.assertEqual(sync._normalize_mobile("(02) 8888-1234"), "(02) 8888-1234")

    def _website_inquiry(self, **values):
        Inquiry = self.env["autoboutique.website.inquiry"]
        return Inquiry.create(dict({
            "name": "Ana Cruz", "phone": "+63 918 222 3344", "email": "ana@example.com",
            "message": "Is the Vios available?", "source": "vehicle", "payment_option": "financing",
            "assistance": "test_drive", "company_id": self.autoboutique.id,
        }, **values))

    def test_website_inquiry_becomes_a_salesforce_lead(self):
        if "autoboutique.website.inquiry" not in self.env:
            self.skipTest("autoboutique_website is not installed")
        vehicle = self._make_ready(self._vehicle(vin=SAMPLE_VIN))
        self._run_jobs()
        inquiry = self._website_inquiry(vehicle_id=vehicle.id)
        self.assertFalse(inquiry.activity_ids, "Salesforce agents work the lead instead of an Odoo call-back")
        self._run_jobs()
        self.assertTrue(inquiry.salesforce_inquiry_id)
        lead = self.fake.created["Facebook_Inquiry__c"][inquiry.salesforce_inquiry_id]
        self.assertEqual(lead["Channel__c"], "Website")
        self.assertEqual(lead["Vehicle_Interested__c"], vehicle.salesforce_vehicle_id)
        self.assertEqual(lead["Payment_Intent__c"], "Financing")
        self.assertEqual(lead["Lead_Priority__c"], "Hot")
        self.assertIn("Book a Test Drive", lead["Customer_Message__c"])
        contact = self.fake.created["Contact"][lead["Contact__c"]]
        self.assertEqual(contact["MobilePhone"], "09182223344")

        # The same customer again reuses the Salesforce contact.
        second = self._website_inquiry(phone="0918 222 3344", email=False)
        self._run_jobs()
        lead2 = self.fake.created["Facebook_Inquiry__c"][second.salesforce_inquiry_id]
        self.assertEqual(lead2["Contact__c"], lead["Contact__c"])
        self.assertTrue(lead2["Existing_Client__c"])
        self.assertEqual(len(self.fake.created["Contact"]), 1)

    def test_website_inquiry_from_another_company_stays_in_odoo(self):
        if "autoboutique.website.inquiry" not in self.env:
            self.skipTest("autoboutique_website is not installed")
        inquiry = self._website_inquiry(company_id=self.overruns.id)
        self.assertFalse(self._jobs(job_type="inquiry_push"))
        self.assertTrue(inquiry.activity_ids, "Without Salesforce the Odoo call-back to-do is created")
