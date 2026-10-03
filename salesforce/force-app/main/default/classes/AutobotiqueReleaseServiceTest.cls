@IsTest
private class AutobotiqueReleaseServiceTest {

    private static User newUser(String alias) {
        Profile admin = [SELECT Id FROM Profile WHERE Name = 'System Administrator' LIMIT 1];
        User user = new User(
            Alias = alias, Email = alias + '.release.test@example.com', EmailEncodingKey = 'UTF-8',
            LastName = 'Release Test ' + alias, LanguageLocaleKey = 'en_US', LocaleSidKey = 'en_US',
            ProfileId = admin.Id, TimeZoneSidKey = 'Asia/Manila',
            Username = alias + '.release.' + String.valueOf(Crypto.getRandomInteger()).replace('-', '') + '@example.com'
        );
        insert user;
        return user;
    }

    private static User integrationUser() {
        User user = newUser('odooint');
        insert new PermissionSetAssignment(
            AssigneeId = user.Id, PermissionSetId = [SELECT Id FROM PermissionSet WHERE Name = 'Odoo_Integration'].Id
        );
        return user;
    }

    private static Id application() {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Stock_Number__c = 'TEST-RELEASE-001', Vehicle_Name__c = '2023 MG ZS', Brand__c = 'MG', Model__c = 'ZS',
            Year__c = 2023, Condition__c = 'Used', Inventory_Status__c = 'Available',
            Selling_Price__c = 818000, Selling_Price_PHP__c = 818000
        );
        insert car;
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Name = 'Release Test', Status__c = 'Draft', Applicant_Type__c = 'Employed', Payment_Option__c = 'Cash',
            Borrower_First_Name__c = 'Ana', Borrower_Last_Name__c = 'Cruz', Borrower_Mobile_Number__c = '09182223344',
            Selected_Vehicle__c = car.Id, Assigned_Agent__c = UserInfo.getUserId(), Application_Date__c = Date.today()
        );
        insert application;
        return application.Id;
    }

    private static AutobotiqueReleaseService.Result call(Map<String, Object> body) {
        RestContext.request = new RestRequest();
        RestContext.request.requestURI = '/services/apexrest/autobotique/release';
        RestContext.request.httpMethod = 'POST';
        RestContext.request.requestBody = Blob.valueOf(JSON.serialize(body));
        RestContext.response = new RestResponse();
        return AutobotiqueReleaseService.release();
    }

    @IsTest
    static void integrationUserReleasesTheApplication() {
        User odoo;
        System.runAs(new User(Id = UserInfo.getUserId())) {
            odoo = integrationUser();
        }
        Id applicationId = application();
        AutobotiqueReleaseService.Result result;
        Test.startTest();
        System.runAs(odoo) {
            result = call(new Map<String, Object>{
                'applicationId' => applicationId, 'plateNumber' => 'NIC 7909', 'odometer' => 42000
            });
        }
        Test.stopTest();
        Auto_Loan_Application__c saved = [
            SELECT Status__c, Vehicle_Plate_Number__c, Vehicle_Odometer__c FROM Auto_Loan_Application__c WHERE Id = :applicationId
        ];
        System.assertEquals(true, result.ok, result.message);
        System.assertEquals('Released', saved.Status__c);
        System.assertEquals('NIC 7909', saved.Vehicle_Plate_Number__c);
        System.assertEquals(42000, saved.Vehicle_Odometer__c);
    }

    @IsTest
    static void otherUsersAndBadRequestsAreRefused() {
        Id applicationId = application();
        User odoo;
        User agent;
        System.runAs(new User(Id = UserInfo.getUserId())) {
            odoo = integrationUser();
            agent = newUser('agentx');
        }
        System.runAs(agent) {
            AutobotiqueReleaseService.Result forbidden = call(new Map<String, Object>{ 'applicationId' => applicationId });
            System.assertEquals(false, forbidden.ok);
            System.assertEquals(403, RestContext.response.statusCode);
        }
        System.assertEquals('Draft', [SELECT Status__c FROM Auto_Loan_Application__c WHERE Id = :applicationId].Status__c);

        System.runAs(odoo) {
            System.assertEquals('NOT_FOUND', call(new Map<String, Object>{ 'applicationId' => null }).errorCode);
            AutobotiqueReleaseService.Result noPlate = call(new Map<String, Object>{ 'applicationId' => applicationId });
            System.assertEquals(false, noPlate.ok, 'Salesforce still requires plate and odometer for Released.');
        }
    }
}
