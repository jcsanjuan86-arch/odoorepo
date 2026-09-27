@IsTest
private class FinalApplicationReviewControllerTest {
    @IsTest
    static void finalReviewerCompletesApplicationWhenRequirementsAreDone() {
        Vehicle_Inventory__c vehicle = buildVehicle('FR-001');
        insert vehicle;

        Auto_Loan_Application__c application = buildApplication('Complete Review Test', vehicle.Id);
        insert application;
        // Clear the automatic document checklist so the test checks a single known requirement.
        delete [SELECT Id FROM Application_Document__c WHERE Auto_Loan_Application__c = :application.Id];

        Application_Document__c document = new Application_Document__c(
            Auto_Loan_Application__c = application.Id,
            Document_Type__c = 'Government ID 1',
            Document_Status__c = 'Submitted',
            Required__c = true,
            Submitted_File_URL__c = 'https://example.com/government-id.pdf'
        );
        insert document;

        Test.startTest();
        List<FinalApplicationReviewController.ApplicationSummary> queue =
            FinalApplicationReviewController.getFinalApplications();
        FinalApplicationReviewController.ReviewDetail detail =
            FinalApplicationReviewController.getReviewDetail(application.Id);
        FinalApplicationReviewController.startFinalReview(application.Id);

        Boolean blocked = false;
        try {
            FinalApplicationReviewController.completeFinalReview(application.Id, 'Ready for approval.');
        } catch (AuraHandledException expected) {
            blocked = true;
        }

        FinalApplicationReviewController.markDocument(document.Id, 'Done', 'Valid ID.');
        FinalApplicationReviewController.completeFinalReview(application.Id, 'All requirements checked.');
        Test.stopTest();

        System.assert(!queue.isEmpty(), 'Final review queue should include the test application.');
        System.assertEquals(1, detail.documents.size(), 'Requirement list should be visible.');
        System.assert(blocked, 'Application should not complete final review while documents are unchecked.');

        Auto_Loan_Application__c reviewed = [
            SELECT Status__c, Final_Review_Status__c, Final_Reviewer__c, Final_Review_Completed_Date__c
            FROM Auto_Loan_Application__c
            WHERE Id = :application.Id
        ];
        System.assertEquals('Approved', reviewed.Status__c);
        System.assertEquals('Complete', reviewed.Final_Review_Status__c);
        System.assertEquals(UserInfo.getUserId(), reviewed.Final_Reviewer__c);
        System.assertNotEquals(null, reviewed.Final_Review_Completed_Date__c);

        Application_Document__c checkedDocument = [
            SELECT Document_Status__c, Final_Check_Status__c, Final_Checked_By__c
            FROM Application_Document__c
            WHERE Id = :document.Id
        ];
        System.assertEquals('Approved', checkedDocument.Document_Status__c);
        System.assertEquals('Done', checkedDocument.Final_Check_Status__c);
        System.assertEquals(UserInfo.getUserId(), checkedDocument.Final_Checked_By__c);
    }

    @IsTest
    static void finalReviewerReturnsApplicationToAssignedAgent() {
        Vehicle_Inventory__c vehicle = buildVehicle('FR-002');
        insert vehicle;

        Auto_Loan_Application__c application = buildApplication('Return Review Test', vehicle.Id);
        insert application;

        Test.startTest();
        FinalApplicationReviewController.returnToAgent(application.Id, 'Missing payslip and proof of billing.');
        Test.stopTest();

        Auto_Loan_Application__c returnedApplication = [
            SELECT Status__c, Final_Review_Status__c, Returned_To_Agent__c,
                Returned_To_Agent_Date__c, Final_Review_Notes__c, OwnerId
            FROM Auto_Loan_Application__c
            WHERE Id = :application.Id
        ];
        System.assertEquals('Returned to Agent', returnedApplication.Status__c);
        System.assertEquals('Returned to Agent', returnedApplication.Final_Review_Status__c);
        System.assertEquals(true, returnedApplication.Returned_To_Agent__c);
        System.assertNotEquals(null, returnedApplication.Returned_To_Agent_Date__c);
        System.assert(returnedApplication.Final_Review_Notes__c.contains('Missing payslip'));
        System.assertEquals(UserInfo.getUserId(), returnedApplication.OwnerId);

        System.assertEquals(1, [
            SELECT COUNT()
            FROM Task
            WHERE WhatId = :application.Id
            AND OwnerId = :UserInfo.getUserId()
            AND Status = 'Not Started'
        ]);
    }

    private static Auto_Loan_Application__c buildApplication(String name, Id vehicleId) {
        return new Auto_Loan_Application__c(
            Name = name,
            Status__c = 'Submitted',
            Applicant_Type__c = 'Employed',
            Assigned_Agent__c = UserInfo.getUserId(),
            Selected_Vehicle__c = vehicleId,
            Payment_Option__c = 'Financing',
            Application_Date__c = Date.today(),
            Borrower_First_Name__c = 'Final',
            Borrower_Last_Name__c = 'Applicant',
            Borrower_Email__c = 'final.applicant@example.com',
            Borrower_Mobile_Number__c = '09171234567',
            Vehicle_Brand__c = 'Toyota',
            Vehicle_Model__c = 'Vios',
            Vehicle_Year__c = 2024,
            Vehicle_Type__c = 'Used',
            Vehicle_Price_PHP__c = 700000,
            Downpayment_PHP__c = 100000,
            Loan_Amount_PHP__c = 600000,
            Terms__c = '48'
        );
    }

    private static Vehicle_Inventory__c buildVehicle(String stockNumber) {
        return new Vehicle_Inventory__c(
            Vehicle_Name__c = '2024 Toyota Vios Final Review',
            Brand__c = 'Toyota',
            Model__c = 'Vios',
            Year__c = 2024,
            Condition__c = 'Used',
            Inventory_Status__c = 'Available',
            Stock_Number__c = stockNumber,
            Selling_Price__c = 700000,
            Selling_Price_PHP__c = 700000,
            Suggested_Downpayment_PHP__c = 100000,
            Branch__c = 'Autobotique Quezon City'
        );
    }
}