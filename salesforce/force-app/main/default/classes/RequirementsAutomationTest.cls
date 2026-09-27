@IsTest
private class RequirementsAutomationTest {
    private static Auto_Loan_Application__c application(String mobile) {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Vehicle_Name__c = '2024 Toyota Vios Requirements', Brand__c = 'Toyota', Model__c = 'Vios',
            Year__c = 2024, Condition__c = 'Used', Inventory_Status__c = 'Available',
            Stock_Number__c = 'REQ-' + Math.abs(Crypto.getRandomInteger()), Selling_Price__c = 700000
        );
        insert car;
        // Applicant Type Employed: the Create_Application_Documents flow adds the checklist.
        Auto_Loan_Application__c app = new Auto_Loan_Application__c(
            Name = 'Requirements Test', Status__c = 'Documents Pending', Applicant_Type__c = 'Employed',
            Payment_Option__c = 'Cash', Selected_Vehicle__c = car.Id,
            Borrower_First_Name__c = 'Req', Borrower_Last_Name__c = 'Applicant', Borrower_Mobile_Number__c = mobile
        );
        insert app;
        return app;
    }

    private static List<Application_Document__c> requirements(Id applicationId) {
        return [
            SELECT Id, Document_Type__c, Document_Status__c, Final_Check_Status__c
            FROM Application_Document__c WHERE Auto_Loan_Application__c = :applicationId AND Required__c = true
        ];
    }

    /** Like the Requirements page: only the file link is written. */
    private static void upload(List<Application_Document__c> documents, String version) {
        List<Application_Document__c> changes = new List<Application_Document__c>();
        for (Application_Document__c document : documents) {
            changes.add(new Application_Document__c(
                Id = document.Id, Submitted_File_URL__c = 'https://example.com/' + document.Id + '/' + version));
        }
        update changes;
    }

    private static String status(Id applicationId) {
        return [SELECT Status__c FROM Auto_Loan_Application__c WHERE Id = :applicationId].Status__c;
    }

    @IsTest
    static void allRequiredUploadsSendTheApplicationToFinalReview() {
        Auto_Loan_Application__c app = application('09171234567');
        List<Application_Document__c> docs = requirements(app.Id);
        Assert.isFalse(docs.isEmpty(), 'The checklist flow creates required documents');

        Test.startTest();
        upload(new List<Application_Document__c>{ docs[0] }, 'v1');
        Assert.areEqual('Documents Pending', status(app.Id), 'Partial uploads keep it with the agent');
        upload(docs, 'v1');
        Test.stopTest();

        Assert.areEqual('Final Review', status(app.Id));
        for (Application_Document__c doc : requirements(app.Id)) {
            Assert.areEqual('Submitted', doc.Document_Status__c);
            Assert.areEqual('Pending', doc.Final_Check_Status__c);
        }
    }

    @IsTest
    static void needsCorrectionReturnsToAgentAndReuploadGoesBack() {
        Auto_Loan_Application__c app = application('09171234567');
        List<Application_Document__c> docs = requirements(app.Id);
        upload(docs, 'v1');
        Assert.areEqual('Final Review', status(app.Id));

        Test.startTest();
        FinalApplicationReviewController.markDocument(docs[0].Id, 'Needs Correction', 'Photo is blurry.');
        Assert.areEqual('Returned to Agent', status(app.Id));
        List<Task> fixTasks = [SELECT Description FROM Task WHERE WhatId = :app.Id AND Subject LIKE 'Fix requirement:%'];
        Assert.areEqual(1, fixTasks.size());
        Assert.areEqual('Photo is blurry.', fixTasks[0].Description, 'The checker note reaches the agent');

        upload(new List<Application_Document__c>{ docs[0] }, 'v2');
        Test.stopTest();

        Application_Document__c fixed = [SELECT Document_Status__c, Final_Check_Status__c FROM Application_Document__c WHERE Id = :docs[0].Id];
        Assert.areEqual('Submitted', fixed.Document_Status__c);
        Assert.areEqual('Pending', fixed.Final_Check_Status__c, 'A new file resets the checker verdict');
        Assert.areEqual('Final Review', status(app.Id), 'Corrected applications go back to the checker');
    }

    @IsTest
    static void blockedMoveBecomesATaskInsteadOfAnError() {
        Auto_Loan_Application__c app = application(null); // Final Review requires a mobile number
        List<Application_Document__c> docs = requirements(app.Id);

        Test.startTest();
        upload(docs, 'v1');
        Test.stopTest();

        Assert.areEqual('Documents Pending', status(app.Id));
        Assert.areEqual(1, [SELECT COUNT() FROM Task WHERE WhatId = :app.Id
                            AND Subject LIKE 'Complete the application so it can go to Final Review%']);
    }

    @IsTest
    static void requirementsPageListsAndAttachesFiles() {
        Auto_Loan_Application__c app = application('09171234567');
        List<Application_Document__c> docs = requirements(app.Id);

        List<ApplicationRequirementsController.ApplicationRow> queue = ApplicationRequirementsController.getQueue(true);
        Assert.areEqual(1, queue.size());
        Assert.areEqual(docs.size(), queue[0].required);
        Assert.areEqual(0, queue[0].uploaded);
        Assert.areEqual(1, ApplicationRequirementsController.getQueue(false).size());

        ContentVersion file = new ContentVersion(
            Title = 'Government ID', PathOnClient = 'id.pdf', VersionData = Blob.valueOf('id'),
            FirstPublishLocationId = docs[0].Id
        );
        insert file;
        Id contentDocumentId = [SELECT ContentDocumentId FROM ContentVersion WHERE Id = :file.Id].ContentDocumentId;

        Test.startTest();
        ApplicationRequirementsController.attachUploadedFile(docs[0].Id, contentDocumentId);
        Test.stopTest();

        ApplicationRequirementsController.Checklist checklist = ApplicationRequirementsController.getChecklist(app.Id);
        Assert.areEqual(1, checklist.application.uploaded);
        Integer uploaded = 0;
        for (ApplicationRequirementsController.RequirementRow row : checklist.requirements) {
            if (row.label == 'Uploaded') {
                uploaded++;
                Assert.isTrue(row.fileUrl.contains(contentDocumentId));
            }
        }
        Assert.areEqual(1, uploaded);
        Assert.areEqual(1, [SELECT COUNT() FROM ContentDocumentLink
                            WHERE ContentDocumentId = :contentDocumentId AND LinkedEntityId = :app.Id],
                        'The file is also visible on the application');
    }
}
