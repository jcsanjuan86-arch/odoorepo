@IsTest
private class AutobotiqueFinancingServiceTest {

    private static User newUser(String alias) {
        Profile admin = [SELECT Id FROM Profile WHERE Name = 'System Administrator' LIMIT 1];
        User user = new User(
            Alias = alias, Email = alias + '.financing.test@example.com', EmailEncodingKey = 'UTF-8',
            LastName = 'Financing Test ' + alias, LanguageLocaleKey = 'en_US', LocaleSidKey = 'en_US',
            ProfileId = admin.Id, TimeZoneSidKey = 'Asia/Manila',
            Username = alias + '.financing.' + String.valueOf(Crypto.getRandomInteger()).replace('-', '') + '@example.com'
        );
        insert user;
        return user;
    }

    private static User integrationUser() {
        User user = newUser('odoofin');
        insert new PermissionSetAssignment(
            AssigneeId = user.Id, PermissionSetId = [SELECT Id FROM PermissionSet WHERE Name = 'Odoo_Integration'].Id
        );
        return user;
    }

    private static Id application() {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Stock_Number__c = 'TEST-FINANCING-001', Vehicle_Name__c = '2023 MG ZS', Brand__c = 'MG', Model__c = 'ZS',
            Year__c = 2023, Condition__c = 'Used', Inventory_Status__c = 'Available',
            Selling_Price__c = 818000, Selling_Price_PHP__c = 818000
        );
        insert car;
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Name = 'Financing Test', Status__c = 'Draft', Applicant_Type__c = 'Employed', Payment_Option__c = 'Cash',
            Borrower_First_Name__c = 'Ana', Borrower_Last_Name__c = 'Cruz', Borrower_Mobile_Number__c = '09182223344',
            Selected_Vehicle__c = car.Id, Assigned_Agent__c = UserInfo.getUserId(), Application_Date__c = Date.today()
        );
        insert application;
        return application.Id;
    }

    private static AutobotiqueFinancingService.Result call(String body) {
        RestContext.request = new RestRequest();
        RestContext.request.requestURI = '/services/apexrest/autobotique/financing';
        RestContext.request.httpMethod = 'POST';
        RestContext.request.requestBody = Blob.valueOf(body);
        RestContext.response = new RestResponse();
        return AutobotiqueFinancingService.updateFinancing();
    }

    private static AutobotiqueFinancingService.Result call(Map<String, Object> body) {
        return call(JSON.serialize(body));
    }

    @IsTest
    static void integrationUserUpdatesTheFinancingFields() {
        User odoo;
        System.runAs(new User(Id = UserInfo.getUserId())) {
            odoo = integrationUser();
        }
        Id applicationId = application();
        AutobotiqueFinancingService.Result result;
        Test.startTest();
        System.runAs(odoo) {
            result = call(new Map<String, Object>{
                'applicationId' => applicationId, 'status' => 'Released', 'bank' => 'TFS',
                'amountApproved' => 550000, 'releaseDate' => '2026-11-06'
            });
        }
        Test.stopTest();
        Auto_Loan_Application__c saved = [
            SELECT Status__c, Financing_Status__c, Financing_Bank__c, Financing_Amount_Approved__c, Financing_Release_Date__c
            FROM Auto_Loan_Application__c WHERE Id = :applicationId
        ];
        System.assertEquals(true, result.ok, result.message);
        System.assertEquals('Released', saved.Financing_Status__c);
        System.assertEquals('TFS', saved.Financing_Bank__c);
        System.assertEquals(550000, saved.Financing_Amount_Approved__c);
        System.assertEquals(Date.newInstance(2026, 11, 6), saved.Financing_Release_Date__c);
        System.assertEquals('Draft', saved.Status__c, 'The loan status stays with the agent.');
    }

    @IsTest
    static void blankDetailsClearTheFields() {
        User odoo;
        System.runAs(new User(Id = UserInfo.getUserId())) {
            odoo = integrationUser();
        }
        Id applicationId = application();
        update new Auto_Loan_Application__c(Id = applicationId, Financing_Bank__c = 'TFS', Financing_Amount_Approved__c = 1);
        System.runAs(odoo) {
            System.assertEquals(true, call(new Map<String, Object>{
                'applicationId' => applicationId, 'status' => 'For Approval'
            }).ok);
        }
        Auto_Loan_Application__c saved = [
            SELECT Financing_Bank__c, Financing_Amount_Approved__c FROM Auto_Loan_Application__c WHERE Id = :applicationId
        ];
        System.assertEquals(null, saved.Financing_Bank__c);
        System.assertEquals(null, saved.Financing_Amount_Approved__c);
    }

    @IsTest
    static void otherUsersAndBadRequestsAreRefused() {
        Id applicationId = application();
        User odoo;
        User agent;
        System.runAs(new User(Id = UserInfo.getUserId())) {
            odoo = integrationUser();
            agent = newUser('agentf');
        }
        System.runAs(agent) {
            AutobotiqueFinancingService.Result forbidden = call(new Map<String, Object>{
                'applicationId' => applicationId, 'status' => 'Approved'
            });
            System.assertEquals(false, forbidden.ok);
            System.assertEquals(403, RestContext.response.statusCode);
        }
        System.assertEquals(null, [SELECT Financing_Status__c FROM Auto_Loan_Application__c WHERE Id = :applicationId].Financing_Status__c);

        System.runAs(odoo) {
            System.assertEquals('BAD_REQUEST', call('not json').errorCode);
            System.assertEquals('NOT_FOUND', call(new Map<String, Object>{ 'applicationId' => null }).errorCode);
            System.assertEquals('BAD_REQUEST', call(new Map<String, Object>{
                'applicationId' => applicationId, 'releaseDate' => 'someday'
            }).errorCode);
        }
    }
}
