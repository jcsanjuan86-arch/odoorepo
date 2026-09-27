-- Odoo.sh runs this on staging/development copies of production.
-- A copy must never write to production Salesforce: switch the sync off,
-- drop the credentials, and forget production Salesforce record IDs so a
-- sandbox connection starts clean (upserts use the Odoo ID external key).
UPDATE ir_config_parameter
   SET value = 'False'
 WHERE key = 'autoboutique_salesforce.enabled';

DELETE FROM ir_config_parameter
 WHERE key IN ('autoboutique_salesforce.client_secret',
               'autoboutique_salesforce.webhook_secret',
               'autoboutique_salesforce.application_watermark');

UPDATE autoboutique_salesforce_job
   SET state = 'cancelled'
 WHERE state = 'pending';

UPDATE autoboutique_vehicle
   SET salesforce_vehicle_id = NULL,
       salesforce_sync_hash = NULL,
       salesforce_sync_status = 'not_synced';
