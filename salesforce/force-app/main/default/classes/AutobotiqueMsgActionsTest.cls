@IsTest
private class AutobotiqueMsgActionsTest {
    @IsTest
    static void buildsAutobotiqueInquiryAndApplication() {
        Contact contact = new Contact(
            FirstName = 'Mark',
            LastName = 'Marcelo',
            MobilePhone = '09171234567',
            Email = 'mark.marcelo@example.com'
        );
        insert contact;

        Case caseRecord = new Case(
            Subject = 'Facebook inquiry',
            Status = 'New',
            Priority = 'Medium',
            Origin = 'Facebook',
            ContactId = contact.Id
        );
        insert caseRecord;

        Vehicle_Inventory__c vehicle = new Vehicle_Inventory__c(
            Stock_Number__c = 'TEST-CONVERT-001',
            Vehicle_Name__c = '2024 Toyota Vios 1.3 XLE CVT',
            Brand__c = 'Toyota',
            Model__c = 'Vios 1.3 XLE CVT',
            Year__c = 2024,
            Condition__c = 'Used',
            Inventory_Status__c = 'Available',
            Selling_Price__c = 735000,
            Selling_Price_PHP__c = 735000,
            Suggested_Downpayment_PHP__c = 147000,
            Default_Terms__c = '48'
        );
        insert vehicle;

        AutobotiqueMessagingActionsController.ActionResult inquiryResult =
            AutobotiqueMessagingActionsController.ensureFacebookInquiryForTest(
            contact.Id,
            caseRecord.Id,
            'Mark Marcelo',
            'fb-test-mark'
        );

        Facebook_Inquiry__c inquiry = [
            SELECT Id, Contact__c, Case__c, Channel__c, Lead_Stage__c, Customer_Name__c,
                Assigned_Agent__c, Payment_Intent__c, Vehicle_Interested__c, Auto_Loan_Application__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiryResult.recordId
            LIMIT 1
        ];
        inquiry.Vehicle_Interested__c = vehicle.Id;
        update inquiry;

        AutobotiqueMessagingActionsController.ActionResult qualifyResult =
            AutobotiqueMessagingActionsController.qualifyLead(inquiry.Id);
        AutobotiqueMessagingActionsController.ActionResult convertResult =
            AutobotiqueMessagingActionsController.convertLead(inquiry.Id);

        inquiry = [
            SELECT Id, Contact__c, Case__c, Channel__c, Lead_Stage__c, Customer_Name__c,
                Assigned_Agent__c, Payment_Intent__c, Vehicle_Interested__c, Auto_Loan_Application__c,
                Qualified_Lead__c, Inquiry_Status__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiry.Id
            LIMIT 1
        ];

        AutobotiqueMessagingActionsController.ActionResult applicationResult =
            AutobotiqueMessagingActionsController.createLoanApplicationFromInquiry(inquiry.Id);

        Auto_Loan_Application__c application = [
            SELECT Id, Borrower_First_Name__c, Borrower_Last_Name__c, Status__c
            FROM Auto_Loan_Application__c
            WHERE Id = :applicationResult.recordId
            LIMIT 1
        ];

        AutobotiqueMessagingActionsController.ActionResult existingInquiry =
            AutobotiqueMessagingActionsController.existingFacebookInquiryForTest(inquiry.Id);
        inquiry.Auto_Loan_Application__c = application.Id;
        AutobotiqueMessagingActionsController.ActionResult existingApplication =
            AutobotiqueMessagingActionsController.createLoanApplicationForTest(inquiry);
        insert new List<Application_Document__c>{
            new Application_Document__c(
                Auto_Loan_Application__c = application.Id,
                Document_Type__c = 'Government ID 1',
                Document_Status__c = 'Missing',
                Required__c = true
            ),
            new Application_Document__c(
                Auto_Loan_Application__c = application.Id,
                Document_Type__c = 'Bank Statement',
                Document_Status__c = 'Missing',
                Required__c = true
            )
        };
        AutobotiqueMessagingActionsController.ActionResult uploadResult =
            AutobotiqueMessagingActionsController.createUploadRequest(inquiry.Id);
        AutobotiqueMessagingActionsController.ActionResult applicationUploadResult =
            AutobotiqueMessagingActionsController.createUploadRequestFromApplication(application.Id);

        Applicant_Upload__c upload = [
            SELECT Id, Public_Upload_URL__c, Upload_Status__c
            FROM Applicant_Upload__c
            WHERE Id = :uploadResult.recordId
            LIMIT 1
        ];
        List<Applicant_Upload__c> applicationUploads = [
            SELECT Id, Public_Upload_URL__c
            FROM Applicant_Upload__c
            WHERE Auto_Loan_Application__c = :application.Id
        ];

        System.assertEquals(contact.Id, inquiry.Contact__c, 'Inquiry should link the customer contact when available.');
        System.assertEquals('Facebook Messenger', inquiry.Channel__c, 'Inquiry should be routed as Facebook Messenger.');
        System.assertEquals(inquiry.Id, qualifyResult.recordId, 'Qualify should return the inquiry.');
        System.assertEquals(inquiry.Id, convertResult.recordId, 'Convert should return the inquiry.');
        System.assertEquals(true, inquiry.Qualified_Lead__c, 'Inquiry should be qualified before application.');
        System.assertEquals('Converted', inquiry.Inquiry_Status__c, 'Inquiry should be converted before application.');
        System.assertEquals('Converted to Application', inquiry.Lead_Stage__c, 'Lead stage should be converted before application.');
        System.assertEquals('Mark', application.Borrower_First_Name__c, 'Application should prefill borrower first name.');
        System.assertEquals('Marcelo', application.Borrower_Last_Name__c, 'Application should prefill borrower last name.');
        System.assertEquals('Draft', application.Status__c, 'New applications should start as draft.');
        System.assertEquals(inquiry.Id, existingInquiry.recordId, 'Existing inquiry should be reused.');
        System.assertEquals(application.Id, existingApplication.recordId, 'Existing application should be reused.');
        System.assertEquals('Link Sent', upload.Upload_Status__c, 'Upload request should be ready to send.');
        System.assert(upload.Public_Upload_URL__c.contains('requestId=') || upload.Public_Upload_URL__c.contains('Applicant_Upload__c'), 'Upload link should point to the customer page or the internal fallback record.');
        System.assert(applicationUploads.size() > 1, 'Generating one customer link should create upload rows for the application document checklist.');
        for (Applicant_Upload__c checklistUpload : applicationUploads) {
            System.assertEquals(upload.Public_Upload_URL__c, checklistUpload.Public_Upload_URL__c, 'Each document row should share the same customer upload link.');
        }
        System.assertEquals(uploadResult.publicUploadReady, applicationUploadResult.publicUploadReady, 'Lead and application upload actions should use the same public-site guard.');

        String carsMessage = AutobotiqueMessagingActionsController.getAvailableCarsMessage(3);
        System.assert(carsMessage.contains('Autobotique'), 'Cars message should be branded.');
        System.assert(carsMessage.contains('Toyota Vios'), 'Cars message should include available inventory.');
        System.assert(carsMessage.contains('PHP'), 'Cars message should show PHP pricing.');
    }

    @IsTest
    static void reusesActiveLeadAndAllowsNewAfterConversion() {
        Contact contact = new Contact(
            FirstName = 'Ana',
            LastName = 'Reyes',
            MobilePhone = '09175550123',
            Email = 'ana.reyes@example.com'
        );
        insert contact;

        AutobotiqueMessagingActionsController.ActionResult first =
            AutobotiqueMessagingActionsController.ensureFacebookInquiryForTest(
                contact.Id,
                null,
                'Ana Reyes',
                'fb-ana-001'
            );
        AutobotiqueMessagingActionsController.ActionResult duplicateAttempt =
            AutobotiqueMessagingActionsController.ensureFacebookInquiryForTest(
                contact.Id,
                null,
                'Ana Reyes',
                'fb-ana-001'
            );

        System.assertEquals(first.recordId, duplicateAttempt.recordId, 'Active lead should be reused.');

        update new Facebook_Inquiry__c(
            Id = first.recordId,
            Inquiry_Status__c = 'Converted',
            Lead_Stage__c = 'Converted to Application'
        );

        AutobotiqueMessagingActionsController.ActionResult nextBuyingCycle =
            AutobotiqueMessagingActionsController.ensureFacebookInquiryForTest(
                contact.Id,
                null,
                'Ana Reyes',
                'fb-ana-001'
            );

        System.assertNotEquals(first.recordId, nextBuyingCycle.recordId, 'Converted lead should allow a new lead.');
    }

    @IsTest
    static void rejectsBlankMessagingSession() {
        try {
            AutobotiqueMessagingActionsController.ensureFacebookInquiry(null);
            System.assert(false, 'Expected blank conversation guard.');
        } catch (AuraHandledException expected) {
            System.assertNotEquals(null, expected.getMessage(), 'Expected an action error.');
        }

        try {
            AutobotiqueMessagingActionsController.createLoanApplication(null);
            System.assert(false, 'Expected blank conversation guard.');
        } catch (AuraHandledException expected) {
            System.assertNotEquals(null, expected.getMessage(), 'Expected an action error.');
        }
    }
}