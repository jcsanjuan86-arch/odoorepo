from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestManagementDashboard(TransactionCase):

    def _vehicle(self, make, state, cost):
        vehicle = self.env["autoboutique.vehicle"].with_context(ab_automating=True).create({
            "name": f"{make} test", "make": make, "model": "Test",
            "acquisition_cost": cost, "company_id": self.env.company.id,
        })
        # Put the car in the stage directly: the workflow checks are tested elsewhere.
        self.env.cr.execute("UPDATE autoboutique_vehicle SET state = %s WHERE id = %s", (state, vehicle.id))
        vehicle.invalidate_recordset(["state"])
        return vehicle

    def test_dashboard_figures(self):
        Dashboard = self.env["autoboutique.dashboard"]
        before = Dashboard.get_dashboard_data()
        self._vehicle("Zz Toyota", "ready", 500000)
        self._vehicle("Zz Toyota", "repair", 300000)
        released = self._vehicle("Zz Honda", "released", 400000)
        released.release_date = fields.Date.context_today(released)
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
        self.assertGreaterEqual(len(data["monthly"]), 6, "The trend shows at least six months")
        self.assertEqual(data["monthly"][-1]["label"], fields.Date.context_today(Dashboard).strftime("%b %Y"))
        self.assertEqual(sum(bucket["count"] for bucket in data["aging"]), data["kpis"]["in_stock"])
        pending = {row["id"]: row for row in data["documents"]}
        self.assertIn(released.id, pending, "A released car without OR/CR, plate and insurance needs follow-up")
        self.assertFalse(pending[released.id]["orcr"])
        self.assertIsInstance(data["cash"], dict, "Administrators see the cash panel")
        self.assertEqual(len(data["cash"]["aging"]), 5)

    def test_period_filter(self):
        Dashboard = self.env["autoboutique.dashboard"]
        year = Dashboard.get_dashboard_data("2026-01-01", "2026-12-31")
        self.assertEqual(year["period"], {"from": "2026-01-01", "to": "2026-12-31"})
        self.assertEqual(len(year["monthly"]), 12)
        self.assertEqual(year["monthly"][0]["label"], "Jan 2026")

    def test_stage_history_and_turnaround(self):
        vehicle = self.env["autoboutique.vehicle"].create({
            "name": "Zz Stage test", "make": "Zz", "model": "Test", "company_id": self.env.company.id,
        })
        self.assertEqual(vehicle.stage_log_ids.mapped("state"), ["receiving"], "A new car starts its history")
        vehicle.action_start_qc()
        self.assertEqual(vehicle.stage_log_ids.mapped("state"), ["receiving", "qc"])
        today = fields.Date.today()
        turnaround = self.env["autoboutique.dashboard"]._dashboard_turnaround(
            vehicle, today - relativedelta(days=1), today + relativedelta(days=1),
            dict(vehicle._fields["state"]._description_selection(self.env)))
        stages = {stage["state"]: stage for stage in turnaround["stages"]}
        self.assertEqual(stages["receiving"]["done"], 1, "Receiving ended today")
        self.assertEqual(stages["qc"]["waiting"], 1, "The car is waiting in QC")

    def test_backfill_uses_existing_dates(self):
        vehicle = self.env["autoboutique.vehicle"].with_context(ab_automating=True).create({
            "name": "Zz Backfill", "make": "Zz", "model": "Test", "company_id": self.env.company.id,
        })
        vehicle.stage_log_ids.unlink()
        self.env.cr.execute("UPDATE autoboutique_vehicle SET state = 'ready' WHERE id = %s", (vehicle.id,))
        vehicle.invalidate_recordset(["state"])
        vehicle._ab_backfill_stage_log()
        states = vehicle.stage_log_ids.mapped("state")
        self.assertEqual(states[0], "receiving")
        self.assertEqual(states[-1], "ready", "The current stage is always recorded")
