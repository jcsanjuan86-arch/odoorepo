from odoo.tests.common import TransactionCase, tagged

ROLES = [
    "group_role_operations", "group_role_qaqc", "group_role_purchaser", "group_role_document_controller",
    "group_role_accounting_staff", "group_role_finance_supervisor", "group_role_accounting_head",
    "group_role_sales_head",
]


@tagged("post_install", "-at_install")
class TestRoles(TransactionCase):

    def test_every_role_sees_the_vehicle_master(self):
        vehicle_menu = self.env.ref("autoboutique_ops.menu_vehicles")
        for xmlid in ROLES:
            with self.subTest(role=xmlid):
                role = self.env.ref("autoboutique_ops." + xmlid)
                user = self.env["res.users"].create({
                    "name": xmlid, "login": xmlid + "@example.com",
                    "company_id": self.env.company.id, "company_ids": [(6, 0, self.env.company.ids)],
                    "group_ids": [(6, 0, role.ids)],
                })
                self.assertTrue(user._is_internal())
                Vehicle = self.env["autoboutique.vehicle"].with_user(user)
                Vehicle.check_access("read")
                Vehicle.search([])
                visible = self.env["ir.ui.menu"].with_user(user)._visible_menu_ids()
                self.assertIn(vehicle_menu.id, visible, "Vehicle Master is in the user's menu")
