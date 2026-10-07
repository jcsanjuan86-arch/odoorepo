from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give cars that existed before stage history was recorded an approximate history."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["autoboutique.vehicle"].search([])._ab_backfill_stage_log()
