from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.autoboutique_salesforce.models.salesforce_client import SalesforceError
from odoo.addons.autoboutique_salesforce.models.salesforce_sync import SalesforceSync

VEHICLE_REQUIRED_FIELDS = ("Brand__c", "Condition__c", "Model__c", "Selling_Price__c", "Stock_Number__c",
                           "Vehicle_Name__c", "Year__c")
SAMPLE_VIN = "MHFXW42G0P2000123"
SAMPLE_SF_VEHICLE_ID = "a0Bd5000001ABCDEA1"
SAMPLE_SF_APPLICATION_ID = "a0Ad5000009XYZ1EAA"


class FakeSalesforce:
    """In-memory stand-in for SalesforceClient.

    Holds Vehicle_Inventory__c rows keyed by Salesforce ID and answers the few
    SOQL shapes the sync code issues.
    """

    def __init__(self):
        self.vehicles = {}
        self.applications = {}
        self.calls = []
        self._counter = 0

    def _new_id(self, prefix="a0B"):
        self._counter += 1
        return "%sd500000%06dAA" % (prefix, self._counter)  # 18 chars, like Salesforce

    def upsert(self, sobject, external_field, external_value, payload):
        self.calls.append(("upsert", sobject, external_value, dict(payload)))
        for record_id, row in self.vehicles.items():
            if row.get(external_field) == external_value:
                row.update(payload)
                return record_id, False
        # Same required fields as the real Vehicle_Inventory__c.
        missing = [f for f in VEHICLE_REQUIRED_FIELDS if payload.get(f) in (None, "")]
        if missing:
            raise SalesforceError("REQUIRED_FIELD_MISSING: %s" % missing, status=400,
                                  code="REQUIRED_FIELD_MISSING")
        record_id = self._new_id()
        self.vehicles[record_id] = dict(payload, **{external_field: external_value})
        return record_id, True

    def update(self, sobject, record_id, payload):
        self.calls.append(("update", sobject, record_id, dict(payload)))
        if record_id not in self.vehicles:
            raise SalesforceError("NOT_FOUND", status=404, code="NOT_FOUND")
        self.vehicles[record_id].update(payload)
        return record_id

    def query(self, soql):
        self.calls.append(("query", soql))
        if "FROM Vehicle_Inventory__c WHERE VIN__c" in soql:
            vin = soql.split("VIN__c = '")[1].split("'")[0]
            return [dict(row, Id=rid) for rid, row in self.vehicles.items() if row.get("VIN__c") == vin]
        if "FROM Vehicle_Inventory__c WHERE Odoo_Vehicle_ID__c" in soql:
            ext = soql.split("Odoo_Vehicle_ID__c = '")[1].split("'")[0]
            return [{"Id": rid} for rid, row in self.vehicles.items() if row.get("Odoo_Vehicle_ID__c") == ext]
        if "FROM Auto_Loan_Application__c WHERE Id" in soql:
            sf_id = soql.split("Id = '")[1].split("'")[0]
            return [self.applications[sf_id]] if sf_id in self.applications else []
        return []


class SalesforceCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.autoboutique = cls.env["res.company"].create({"name": "Autoboutique (test)"})
        cls.overruns = cls.env["res.company"].create({"name": "Overruns (test)"})
        cls.agent = cls.env["res.users"].create({
            "name": "Test Agent",
            "login": "agent.sf.test@example.com",
            "email": "agent.sf.test@example.com",
            "company_id": cls.autoboutique.id,
            "company_ids": [(6, 0, [cls.autoboutique.id])],
            "group_ids": [(6, 0, [cls.env.ref("autoboutique_salesforce.group_salesforce_user").id])],
        })
        ICP = cls.env["ir.config_parameter"].sudo()
        for key, value in {
            "enabled": "True",
            "company_id": str(cls.autoboutique.id),
            "login_url": "https://example.my.salesforce.com",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "webhook_secret": "webhook-test-secret",
            "default_agent_id": str(cls.agent.id),
        }.items():
            ICP.set_param("autoboutique_salesforce.%s" % key, value)

    def setUp(self):
        super().setUp()
        self.fake = FakeSalesforce()
        patcher = patch.object(SalesforceSync, "_get_client", lambda _self: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _vehicle(self, company=None, **vals):
        company = company or self.autoboutique
        values = {
            "name": "Toyota Vios %s" % (vals.get("vin") or ""),
            "make": "Toyota",
            "model": "Vios",
            "model_year": 2024,
            "selling_price": 748000,
            "company_id": company.id,
        }
        values.update(vals)
        return self.env["autoboutique.vehicle"].with_company(company).create(values)

    def _make_ready(self, vehicle):
        """Satisfy the autoboutique_ops Ready-for-Sale gates, then move to Ready."""
        company = vehicle.company_id
        self.env["autoboutique.qc"].create({
            "name": "Final QC", "vehicle_id": vehicle.id, "inspection_type": "final",
            "result": "pass", "company_id": company.id,
        })
        self.env["autoboutique.detailing"].create({
            "name": "Detailing", "vehicle_id": vehicle.id, "state": "approved",
            "exterior_done": True, "interior_done": True, "supervisor_id": self.env.user.id,
            "company_id": company.id,
        })
        vehicle.write({"documents_verified": True, "ready_for_sale_approved": True})
        vehicle.write({"state": "ready"})
        return vehicle

    def _jobs(self, **domain):
        return self.env["autoboutique.salesforce.job"].search(
            [(key, "=", value) for key, value in domain.items()])

    def _run_jobs(self):
        self.env["autoboutique.salesforce.job"]._cron_process_jobs()
