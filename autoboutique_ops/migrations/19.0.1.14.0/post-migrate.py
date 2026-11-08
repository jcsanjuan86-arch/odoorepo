from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Total Bid became computed: fill it in for the bid lots that already exist."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    bids = env["autoboutique.bid"].with_context(active_test=False).search([])
    env.add_to_compute(bids._fields["total_bid"], bids)
    env.flush_all()
