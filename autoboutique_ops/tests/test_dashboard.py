from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestManagementDashboard(TransactionCase):

    def _vehicle(self, make, state, cost):
        return self.env["autoboutique.vehicle"].with_context(ab_automating=True).create({
            "name": f"{make} test", "make": make, "model": "Test", "state": state,
            "acquisition_cost": cost, "company_id": self.env.company.id,
        })

    def test_dashboard_figures(self):
        Dashboard = self.env["autoboutique.dashboard"]
        before = Dashboard.get_dashboard_data()
        self._vehicle("Zz Toyota", "ready", 500000)
        self._vehicle("Zz Toyota", "repair", 300000)
        self._vehicle("Zz Honda", "released", 400000)
        data = Dashboard.get_dashboard_data()

        self.assertEqual(data["kpis"]["in_stock"], before["kpis"]["in_stock"] + 2, "Released cars are not in stock")
        self.assertEqual(data["kpis"]["ready"], before["kpis"]["ready"] + 1)
        self.assertAlmostEqual(data["kpis"]["inventory_value"], before["kpis"]["inventory_value"] + 800000)
        self.assertAlmostEqual(data["costs"]["Acquisition"], before["costs"]["Acquisition"] + 800000)
        pipeline = {stage["state"]: stage["count"] for stage in data["pipeline"]}
        old_pipeline = {stage["state"]: stage["count"] for stage in before["pipeline"]}
        self.assertEqual(pipeline["released"], old_pipeline["released"] + 1)
        makes = {make["label"]: make["count"] for make in data["makes"]}
        self.assertEqual(makes.get("Zz Toyota"), 2)
        self.assertEqual(len(data["monthly"]), 12)
        self.assertEqual(data["monthly"][-1]["label"], fields.Date.context_today(Dashboard).strftime("%b %Y"))
        self.assertEqual(sum(bucket["count"] for bucket in data["aging"]), data["kpis"]["in_stock"])
