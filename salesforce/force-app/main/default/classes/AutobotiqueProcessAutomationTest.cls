@IsTest
private class AutobotiqueProcessAutomationTest {

    private static Vehicle_Inventory__c vehicle() {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Stock_Number__c = 'TEST-PROCESS-001', Vehicle_Name__c = '2023 MG ZS', Brand__c = 'MG',
            Model__c = 'ZS', Year__c = 2023, Condition__c = 'Used', Inventory_Status__c = 'Available',
            Selling_Price__c = 818000, Selling_Price_PHP__c = 818000
        );
        insert car;
        return car;
    }

    private static Facebook_Inquiry__c inquiry(Id contactId, Id vehicleId) {
        Facebook_Inquiry__c lead = new Facebook_Inquiry__c(
            Customer_Name__c = 'Ana Cruz', Contact__c = contactId, Vehicle_Interested__c = vehicleId,
            Facebook_User_ID__c = 'fb-process-' + String.valueOf(Crypto.getRandomInteger()),
            Channel__c = 'Facebook Messenger', Inquiry_Status__c = 'In Progress', Lead_Stage__c = 'New Message',
            Next_Action__c = 'Reply to Inquiry', Payment_Intent__c = 'Cash', Assigned_Agent__c = UserInfo.getUserId()
        );
        insert lead;
        return lead;
    }

    private static Contact contact() {
        Contact customer = new Contact(FirstName = 'Ana', LastName = 'Cruz', MobilePhone = '0918 222 3344');
        insert customer;
        return customer;
    }

    @IsTest
    static void startApplicationIsOneClick() {
        Contact customer = contact();
        Facebook_Inquiry__c lead = inquiry(customer.Id, vehicle().Id);

        Test.startTest();
        AutobotiqueMessagingActionsController.ActionResult result =
            AutobotiqueMessagingActionsController.startApplication(lead.Id);
        AutobotiqueMessagingActionsController.ActionResult again =
            AutobotiqueMessagingActionsController.startApplication(lead.Id);
        Test.stopTest();

        lead = [SELECT Qualified_Lead__c, Inquiry_Status__c, Lead_Stage__c, Auto_Loan_Application__c
                FROM Facebook_Inquiry__c WHERE Id = :lead.Id];
        System.assertEquals(true, lead.Qualified_Lead__c, 'Start Application qualifies the lead.');
        System.assertEquals('Converted', lead.Inquiry_Status__c, 'Start Application converts the lead.');
        System.assertEquals('Docs Requested', lead.Lead_Stage__c, 'The lead waits for documents next.');
        System.assertEquals(result.recordId, lead.Auto_Loan_Application__c, 'The application is linked.');
        System.assertEquals(result.recordId, again.recordId, 'A second click opens the same application.');
    }

    @IsTest
    static void websiteLeadsNameTheApplicationAfterTheWebsite() {
        Facebook_Inquiry__c lead = inquiry(contact().Id, vehicle().Id);
        update new Facebook_Inquiry__c(Id = lead.Id, Channel__c = 'Website');
        Id applicationId = AutobotiqueMessagingActionsController.startApplication(lead.Id).recordId;
        System.assertEquals('Ana Cruz - Website Inquiry',
            [SELECT Name FROM Auto_Loan_Application__c WHERE Id = :applicationId].Name);
    }

    @IsTest
    static void startApplicationExplainsWhatIsMissing() {
        Facebook_Inquiry__c lead = inquiry(null, null);
        try {
            AutobotiqueMessagingActionsController.startApplication(lead.Id);
            System.assert(false, 'Expected a missing-details error.');
        } catch (AuraHandledException expected) {
            System.assertNotEquals(null, expected.getMessage(), 'The agent gets a clear message.');
        }
    }

    @IsTest
    static void leadStageFollowsApplicationStatus() {
        Contact customer = contact();
        Facebook_Inquiry__c lead = inquiry(customer.Id, vehicle().Id);
        Id applicationId = AutobotiqueMessagingActionsController.startApplication(lead.Id).recordId;

        Test.startTest();
        update new Auto_Loan_Application__c(Id = applicationId, Status__c = 'Documents Pending');
        System.assertEquals('Follow Up Documents',
            [SELECT Next_Action__c FROM Facebook_Inquiry__c WHERE Id = :lead.Id].Next_Action__c);
        update new Auto_Loan_Application__c(Id = applicationId, Status__c = 'Rejected');
        Test.stopTest();

        lead = [SELECT Lead_Stage__c, Inquiry_Status__c FROM Facebook_Inquiry__c WHERE Id = :lead.Id];
        System.assertEquals('Closed Lost', lead.Lead_Stage__c, 'A rejected application closes the lead.');
        System.assertEquals('Closed', lead.Inquiry_Status__c);
    }

    @IsTest
    static void applicantTypeChangeSwapsChecklist() {
        Contact customer = contact();
        Facebook_Inquiry__c lead = inquiry(customer.Id, vehicle().Id);
        Id applicationId = AutobotiqueMessagingActionsController.startApplication(lead.Id).recordId;
        // The create flow builds the Employed checklist; mark one shared and one Employed-only item as uploaded.
        List<Application_Document__c> docs = [
            SELECT Id, Document_Type__c FROM Application_Document__c WHERE Auto_Loan_Application__c = :applicationId
        ];
        if (docs.isEmpty()) {
            AutobotiqueProcessAutomation.swapChecklists(new Map<Id, String>{ applicationId => 'Employed' });
            docs = [SELECT Id, Document_Type__c FROM Application_Document__c WHERE Auto_Loan_Application__c = :applicationId];
        }
        for (Application_Document__c doc : docs) {
            if (doc.Document_Type__c == 'COE' || doc.Document_Type__c == 'Facebook Link') {
                doc.Submitted_File_URL__c = 'https://example.com/file';
                doc.Document_Status__c = 'Submitted';
            }
        }
        update docs;

        Test.startTest();
        update new Auto_Loan_Application__c(Id = applicationId, Applicant_Type__c = 'OFW');
        Test.stopTest();

        Map<String, Application_Document__c> byType = new Map<String, Application_Document__c>();
        for (Application_Document__c doc : [
            SELECT Document_Type__c, Required__c FROM Application_Document__c WHERE Auto_Loan_Application__c = :applicationId
        ]) {
            byType.put(doc.Document_Type__c, doc);
        }
        System.assert(byType.containsKey('Passport'), 'OFW items are added.');
        System.assert(!byType.containsKey('Payroll Statement'), 'Missing Employed-only items are removed.');
        System.assertEquals(false, byType.get('COE').Required__c, 'An uploaded old item is kept but optional.');
        System.assertEquals(true, byType.get('Facebook Link').Required__c, 'Shared items stay required.');
        System.assertEquals(AutobotiqueProcessAutomation.CHECKLIST.get('OFW').size() + 1, byType.size());
    }

    @IsTest
    static void websiteInquiriesGoToAnOnlineAgent() {
        // Routing rules themselves are covered in AutobotiqueRouterTest.
        AutobotiqueRouter.testPool = new Set<Id>{ UserInfo.getUserId() };
        AutobotiqueRouter.testFreeCapacity = new Map<Id, Decimal>{ UserInfo.getUserId() => 5 };
        Facebook_Inquiry__c web = new Facebook_Inquiry__c(
            Customer_Name__c = 'Web Buyer', Channel__c = 'Website', Facebook_User_ID__c = 'website-1',
            Inquiry_Status__c = 'New', Lead_Stage__c = 'New Message'
        );
        Test.startTest();
        insert web;
        Test.stopTest();
        web = [SELECT Assigned_Agent__c, OwnerId FROM Facebook_Inquiry__c WHERE Id = :web.Id];
        System.assertEquals(UserInfo.getUserId(), web.Assigned_Agent__c, 'The website lead is assigned.');
        System.assertEquals(UserInfo.getUserId(), web.OwnerId);
    }

    @IsTest
    static void mobileNumbersAreNormalizedAndDuplicatesBlocked() {
        Contact first = contact();
        System.assertEquals('09182223344', [SELECT MobilePhone FROM Contact WHERE Id = :first.Id].MobilePhone);
        System.assertEquals('09182223344', AutobotiqueProcessAutomation.normalizeMobile('+63 918 222 3344'));
        System.assertEquals('09182223344', AutobotiqueProcessAutomation.normalizeMobile('9182223344'));
        System.assertEquals('(02) 8888-1234', AutobotiqueProcessAutomation.normalizeMobile('(02) 8888-1234'));
        try {
            insert new Contact(FirstName = 'Ana', LastName = 'Duplicate', MobilePhone = '+63 918 222 3344');
            System.assert(false, 'Expected the duplicate to be blocked.');
        } catch (DmlException expected) {
            System.assert(expected.getMessage().contains('Ana Cruz'), 'The message names the existing customer.');
        }
    }

    @IsTest
    static void followUpJobCreatesOneTaskPerRecord() {
        Contact customer = contact();
        Facebook_Inquiry__c due = inquiry(customer.Id, null);
        update new Facebook_Inquiry__c(Id = due.Id, Lead_Stage__c = 'Contacted', Next_Follow_Up_Date__c = Date.today());
        Facebook_Inquiry__c waiting = inquiry(null, null);
        Test.setCreatedDate(waiting.Id, Datetime.now().addMinutes(-45));

        Test.startTest();
        Integer created = AutobotiqueFollowUpJob.run();
        Integer second = AutobotiqueFollowUpJob.run();
        System.schedule('Autobotique follow-up test', '0 0 * * * ?', new AutobotiqueFollowUpJob());
        Test.stopTest();

        System.assertEquals(2, created, 'One follow-up task and one reply-now task.');
        System.assertEquals(0, second, 'Open tasks are not duplicated.');
        System.assertEquals(1, [SELECT COUNT() FROM Task WHERE WhatId = :waiting.Id AND Priority = 'High']);
        System.assertEquals(1, [SELECT COUNT() FROM Task WHERE WhatId = :due.Id AND Subject LIKE 'Autobotique follow-up:%']);
    }
}
