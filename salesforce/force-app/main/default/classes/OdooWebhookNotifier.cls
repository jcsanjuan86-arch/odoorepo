/**
 * Tells Odoo which Auto Loan Applications changed.
 *
 * The request carries only record IDs; Odoo fetches the data itself through
 * the authenticated REST API. Each request is signed:
 *   X-Autoboutique-Timestamp: <unix seconds>
 *   X-Autoboutique-Signature: hex(HMAC-SHA256(secret, "<timestamp>." + body))
 * If a notification is lost, Odoo's scheduled polling picks the change up.
 */
public with sharing class OdooWebhookNotifier implements Queueable, Database.AllowsCallouts {
    @TestVisible private static final String OBJECT_NAME = 'Auto_Loan_Application__c';
    private final List<Id> recordIds;

    public OdooWebhookNotifier(List<Id> recordIds) {
        this.recordIds = recordIds;
    }

    public static void notifyChanged(List<Auto_Loan_Application__c> records) {
        Odoo_Integration_Settings__c config = Odoo_Integration_Settings__c.getOrgDefaults();
        if (config == null || !config.Enabled__c || String.isBlank(config.Endpoint_URL__c)
                || String.isBlank(config.Webhook_Secret__c)) {
            return;
        }
        List<Id> ids = new List<Id>();
        for (Auto_Loan_Application__c record : records) {
            if (record.Selected_Vehicle__c != null) {
                ids.add(record.Id);
            }
        }
        // A trigger batch holds at most 200 records, matching Odoo's per-request limit.
        if (ids.isEmpty() || Limits.getQueueableJobs() >= Limits.getLimitQueueableJobs()) {
            return;
        }
        System.enqueueJob(new OdooWebhookNotifier(ids));
    }

    public void execute(QueueableContext context) {
        Odoo_Integration_Settings__c config = Odoo_Integration_Settings__c.getOrgDefaults();
        String body = JSON.serialize(new Map<String, Object>{ 'object' => OBJECT_NAME, 'ids' => recordIds });
        String timestamp = String.valueOf(Datetime.now().getTime() / 1000);

        HttpRequest request = new HttpRequest();
        request.setEndpoint(config.Endpoint_URL__c);
        request.setMethod('POST');
        request.setTimeout(20000);
        request.setHeader('Content-Type', 'application/json');
        request.setHeader('X-Autoboutique-Timestamp', timestamp);
        request.setHeader('X-Autoboutique-Signature', sign(timestamp, body, config.Webhook_Secret__c));
        request.setBody(body);

        HttpResponse response = new Http().send(request);
        if (response.getStatusCode() != 202) {
            System.debug(LoggingLevel.WARN, 'Odoo webhook returned ' + response.getStatusCode()
                + '; Odoo polling will pick up these changes.');
        }
    }

    @TestVisible
    private static String sign(String timestamp, String body, String secret) {
        Blob mac = Crypto.generateMac('hmacSHA256', Blob.valueOf(timestamp + '.' + body), Blob.valueOf(secret));
        return EncodingUtil.convertToHex(mac);
    }
}
