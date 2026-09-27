@IsTest
private class OdooWebhookNotifierTest {
    private static final String SECRET = 'test-webhook-secret';
    private static final String ENDPOINT = 'https://odoo.example.com/autoboutique_salesforce/webhook';

    private class OdooMock implements HttpCalloutMock {
        public HttpRequest received;
        public HttpResponse respond(HttpRequest request) {
            received = request;
            HttpResponse response = new HttpResponse();
            response.setStatusCode(202);
            response.setBody('{"status":"queued"}');
            return response;
        }
    }

    private static void configure(Boolean enabled) {
        insert new Odoo_Integration_Settings__c(
            SetupOwnerId = UserInfo.getOrganizationId(),
            Enabled__c = enabled,
            Endpoint_URL__c = ENDPOINT,
            Webhook_Secret__c = SECRET
        );
    }

    private static Vehicle_Inventory__c vehicle() {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Brand__c = 'Toyota', Model__c = 'Vios', Vehicle_Name__c = '2024 Toyota Vios',
            Year__c = 2024, Condition__c = 'Used', Selling_Price__c = 748000,
            Stock_Number__c = 'TEST-ODOO-1', VIN__c = 'MHFXW42G0P2000123', Odoo_Vehicle_ID__c = '1'
        );
        insert car;
        return car;
    }

    @IsTest
    static void signedNotificationIsSentForLinkedApplications() {
        configure(true);
        Vehicle_Inventory__c car = vehicle();
        OdooMock mock = new OdooMock();
        Test.setMock(HttpCalloutMock.class, mock);

        Test.startTest();
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Borrower_First_Name__c = 'Angela', Borrower_Last_Name__c = 'Mendoza',
            Selected_Vehicle__c = car.Id
        );
        insert application;
        Test.stopTest();

        Assert.isNotNull(mock.received, 'Odoo should be notified');
        Assert.areEqual(ENDPOINT, mock.received.getEndpoint());
        String timestamp = mock.received.getHeader('X-Autoboutique-Timestamp');
        String body = mock.received.getBody();
        Assert.areEqual(OdooWebhookNotifier.sign(timestamp, body, SECRET),
            mock.received.getHeader('X-Autoboutique-Signature'));
        Map<String, Object> payload = (Map<String, Object>) JSON.deserializeUntyped(body);
        Assert.areEqual('Auto_Loan_Application__c', payload.get('object'));
        Assert.isTrue(((List<Object>) payload.get('ids')).contains(application.Id));
    }

    @IsTest
    static void nothingIsSentWhenDisabledOrUnlinked() {
        configure(false);
        Vehicle_Inventory__c car = vehicle();
        Test.startTest();
        insert new Auto_Loan_Application__c(Borrower_Last_Name__c = 'Disabled', Selected_Vehicle__c = car.Id);
        Test.stopTest();
        Assert.areEqual(0, [SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'OdooWebhookNotifier']);

        Odoo_Integration_Settings__c config = Odoo_Integration_Settings__c.getOrgDefaults();
        config.Enabled__c = true;
        update config;
        OdooWebhookNotifier.notifyChanged(new List<Auto_Loan_Application__c>{
            new Auto_Loan_Application__c(Borrower_Last_Name__c = 'No vehicle')
        });
        Assert.areEqual(0, Limits.getQueueableJobs(), 'Applications without a vehicle are not sent');
    }
}
