from odoo import api, models, tools


class IrUiMenu(models.Model):
    """Keep the vehicle-operation app out of non-vehicle companies."""

    _inherit = "ir.ui.menu"

    @api.model
    @tools.ormcache(
        "self.env.uid", "debug", "self.env.lang", "self.env.company.id"
    )
    def load_menus(self, debug):
        """Cache the menu payload separately for each active company."""
        return super().load_menus.__wrapped__(self, debug)

    @api.model
    @tools.ormcache("self.env.uid", "self.env.lang", "self.env.company.id")
    def load_menus_root(self):
        """Cache the app-launcher roots separately for each active company."""
        return super().load_menus_root.__wrapped__(self)

    @api.model
    @tools.ormcache(
        "self.env.uid", "debug", "self.env.lang", "self.env.company.id"
    )
    def load_web_menus(self, debug):
        """Odoo 19 web clients load their launcher from this menu payload.

        The active company must be part of the cache key, otherwise a user who
        first opens Overruns keeps its filtered app list after switching to
        Autoboutique.
        """
        return super().load_web_menus.__wrapped__(self, debug)

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
