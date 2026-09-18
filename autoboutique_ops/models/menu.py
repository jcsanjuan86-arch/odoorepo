from odoo import api, models


class IrUiMenu(models.Model):
    """Keep the vehicle-operation app out of non-vehicle companies."""

    _inherit = "ir.ui.menu"

    @api.model
    def _visible_menu_ids(self, debug=False):
        """Hide the complete Autoboutique menu tree outside Autoboutique.

        Menus are not company-dependent in standard Odoo.  The operational
        records are already protected by company record rules; this adds the
        matching navigation rule so the vehicle app is not offered while an
        Overruns user is working in that company.
        """
        menu_ids = set(super()._visible_menu_ids(debug=debug))
        if self.env.company.name.strip().casefold() == "autoboutique":
            return menu_ids

        root_menu = self.env.ref("autoboutique_ops.menu_root", raise_if_not_found=False)
        if root_menu:
            autoboutique_menu_ids = self.search(
                [("id", "child_of", root_menu.id)]
            ).ids
            menu_ids.difference_update(autoboutique_menu_ids)
        return menu_ids
