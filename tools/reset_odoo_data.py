# Clears Odoo's business data so the database starts from scratch.
#
# Keeps: the Salesforce connection and settings, companies, users, employees, the chart of
# accounts, journals, taxes, warehouses, websites, QC checklist items and installed modules.
# Clears: vehicles, sales, financing (including its setup), inquiries, accounting entries,
# stock, purchase and sale orders, POS orders, payslips, sync history, unused contacts and
# products. Nothing is sent to Salesforce.
#
# Dry run (changes nothing, prints what would happen):
#   odoo-bin shell --no-http < ~/src/user/tools/reset_odoo_data.py
# Real run, after taking a backup and pausing the two Salesforce scheduled actions:
#   RESET_CONFIRM=<database name> odoo-bin shell --no-http < ~/src/user/tools/reset_odoo_data.py
import os

import psycopg2

# Deletion order does not matter: tables blocked by a reference are retried on the next pass.
WIPE_TABLES = """
    autoboutique_salesforce_log autoboutique_salesforce_job
    autoboutique_financing_submission autoboutique_financing_account autoboutique_financing_officer
    autoboutique_financing_evaluation autoboutique_financing_quote
    autoboutique_financing_partner autoboutique_financing_bank
    autoboutique_commission autoboutique_vehicle_release autoboutique_registration autoboutique_insurance
    autoboutique_document autoboutique_sales_application autoboutique_website_inquiry
    autoboutique_detailing autoboutique_mrf_line autoboutique_mrf autoboutique_repair_line autoboutique_repair
    autoboutique_qc_line autoboutique_qc autoboutique_receiving autoboutique_bid_line autoboutique_bid
    autoboutique_vehicle_stage_log autoboutique_vehicle_gallery autoboutique_vehicle
    autoboutique_vehicle_variant_color autoboutique_vehicle_variant autoboutique_vehicle_feature
    payment_transaction
    pos_payment pos_order_line pos_order pos_session
    account_partial_reconcile account_full_reconcile account_payment
    account_bank_statement_line account_bank_statement
    account_analytic_line account_move_line account_move
    stock_valuation_layer stock_landed_cost stock_scrap stock_move_line stock_move stock_picking
    stock_quant stock_lot stock_warehouse_orderpoint
    sale_order_line sale_order purchase_order_line purchase_order
    hr_payslip_line hr_payslip hr_payslip_run
""".split()

# Any row-count change in these aborts the run.
PROTECTED_TABLES = """
    res_users res_company res_groups hr_employee ir_config_parameter ir_cron ir_module_module
    account_account account_journal account_tax stock_warehouse stock_location stock_picking_type
    website website_page pos_config autoboutique_qc_checklist_item
""".split()

# References from these never make a contact or product worth keeping.
NOISE_PREFIXES = ("mail_", "discuss_", "bus_", "res_partner", "product_", "ir_", "website_visitor", "website_track", "payment_token")


def existing(tables):
    env.cr.execute("SELECT relname FROM pg_class WHERE relkind = 'r' AND relname = ANY(%s)", [list(tables)])
    return {row[0] for row in env.cr.fetchall()}


def row_counts():
    env.cr.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    counts = {}
    for (table,) in env.cr.fetchall():
        env.cr.execute('SELECT count(*) FROM "%s"' % table)
        counts[table] = env.cr.fetchone()[0]
    return counts


def wipe_tables(tables):
    remaining = list(tables)
    for _attempt in range(len(tables) + 1):
        blocked = []
        for table in remaining:
            try:
                with env.cr.savepoint(flush=False):
                    env.cr.execute('DELETE FROM "%s"' % table)
            except psycopg2.IntegrityError:
                blocked.append(table)
        if not blocked or len(blocked) == len(remaining):
            return blocked
        remaining = blocked
    return remaining


def outside_references(table, wiped):
    """Ids of `table` used by a kept table. Self-clearing references only count for HR records."""
    env.cr.execute("""
        SELECT c.conrelid::regclass::text, a.attname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
         WHERE c.contype = 'f' AND c.confrelid = %s::regclass
           AND (c.confdeltype != 'n' OR c.conrelid::regclass::text LIKE 'hr_%%')
           AND array_length(c.conkey, 1) = 1
    """, [table])
    used = set()
    for source, column in env.cr.fetchall():
        source = source.strip('"')
        if source in wiped or source == table or source.startswith(NOISE_PREFIXES):
            continue
        env.cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL' % (column, source, column))
        used.update(row[0] for row in env.cr.fetchall())
    return used


def xmlid_records(*models):
    env.cr.execute("SELECT DISTINCT model, res_id FROM ir_model_data WHERE model = ANY(%s)", [list(models)])
    return env.cr.fetchall()


def delete_rows(table, ids):
    """Deletes row by row, so anything still referenced stays. Returns the deleted ids."""
    deleted = set()
    pending = set(ids)
    while pending:
        progress = False
        for record_id in sorted(pending):
            try:
                with env.cr.savepoint(flush=False):
                    env.cr.execute('DELETE FROM "%s" WHERE id = %%s' % table, [record_id])
                deleted.add(record_id)
                progress = True
            except psycopg2.IntegrityError:
                pass
        pending -= deleted
        if not progress:
            break
    return deleted


def clear_contacts(wiped):
    keep = outside_references("res_partner", wiped)
    keep.update(res_id for _model, res_id in xmlid_records("res.partner"))
    env.cr.execute("SELECT id FROM res_partner")
    candidates = {row[0] for row in env.cr.fetchall()} - keep
    return delete_rows("res_partner", candidates)


def clear_products(wiped):
    keep = outside_references("product_template", wiped)
    variants_in_use = outside_references("product_product", wiped)
    xmlids = xmlid_records("product.template", "product.product")
    keep.update(res_id for model, res_id in xmlids if model == "product.template")
    variants_in_use.update(res_id for model, res_id in xmlids if model == "product.product")
    env.cr.execute("SELECT product_tmpl_id FROM product_product WHERE id = ANY(%s)", [list(variants_in_use)])
    keep.update(row[0] for row in env.cr.fetchall())
    env.cr.execute("SELECT id FROM product_template")
    candidates = {row[0] for row in env.cr.fetchall()} - keep
    return delete_rows("product_template", candidates)


def clear_chatter(wiped, contacts, products):
    env.cr.execute("SELECT model FROM ir_model WHERE replace(model, '.', '_') = ANY(%s)", [list(wiped)])
    models = [row[0] for row in env.cr.fetchall()]
    for table, model_column, id_column in (
        ("mail_message", "model", "res_id"), ("mail_followers", "res_model", "res_id"),
        ("mail_activity", "res_model", "res_id"), ("ir_attachment", "res_model", "res_id"),
    ):
        env.cr.execute('DELETE FROM "%s" WHERE "%s" = ANY(%%s)' % (table, model_column), [models])
        for model, ids in (("res.partner", contacts), ("product.template", products)):
            env.cr.execute('DELETE FROM "%s" WHERE "%s" = %%s AND "%s" = ANY(%%s)' % (table, model_column, id_column),
                           [model, list(ids)])


def restart_numbering():
    env.cr.execute("""
        SELECT s.id FROM ir_sequence s
         WHERE s.code LIKE 'autoboutique%%' OR s.code IN ('sale.order', 'purchase.order')
            OR s.id IN (SELECT sequence_id FROM stock_picking_type WHERE sequence_id IS NOT NULL)
    """)
    env["ir.sequence"].sudo().browse([row[0] for row in env.cr.fetchall()]).write({"number_next": 1})


def reset():
    database = env.cr.dbname
    confirmed = os.environ.get("RESET_CONFIRM") == database
    print("Database: %s. Mode: %s" % (database, "REAL RUN" if confirmed else "dry run, nothing is saved"))

    before = row_counts()
    wiped = existing(WIPE_TABLES)
    print("Not installed, skipped: %s" % (sorted(set(WIPE_TABLES) - wiped) or "none"))

    blocked = wipe_tables(sorted(wiped))
    if blocked:
        env.cr.rollback()
        raise SystemExit("Stopped, nothing saved. Still referenced: %s" % blocked)

    contacts = clear_contacts(wiped)
    products = clear_products(wiped)
    clear_chatter(wiped, contacts, products)
    restart_numbering()
    env.cr.execute("SELECT count(*) FROM ir_config_parameter WHERE key LIKE 'autoboutique_salesforce.%'")
    settings_kept = env.cr.fetchone()[0]

    after = row_counts()
    changed = {table: (before[table], after[table]) for table in before if before[table] != after[table]}
    for table, (old, new) in sorted(changed.items()):
        print("%-50s %7d -> %d" % (table, old, new))
    print("Contacts removed: %d, kept: %d" % (len(contacts), after["res_partner"]))
    print("Products removed: %d, kept: %d" % (len(products), after["product_template"]))
    print("Salesforce settings kept: %d" % settings_kept)

    damaged = sorted(set(PROTECTED_TABLES) & set(changed))
    if damaged:
        env.cr.rollback()
        raise SystemExit("Stopped, nothing saved. Protected tables changed: %s" % damaged)
    if confirmed:
        env.cr.commit()
        print("Saved.")
    else:
        env.cr.rollback()
        print("Dry run finished, nothing saved.")


reset()
