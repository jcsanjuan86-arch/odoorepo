def post_init_hook(env):
    """Keep Autoboutique and Trendy Overruns as separate public websites.

    Domains are deliberately not set here: the owner can attach the final
    domains in Website > Configuration > Websites without hard-coding a
    temporary Odoo.sh URL into production data.
    """
    env["website"].autoboutique_sync_websites()
