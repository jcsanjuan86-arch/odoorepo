@IsTest
private class FacebookLeadKanbanControllerTest {
    @IsTest
    static void returnsAndMovesLeadCards() {
        Facebook_Inquiry__c inquiry = new Facebook_Inquiry__c(
            Facebook_User_ID__c = 'fb-test-001',
            Customer_Name__c = 'Test Buyer',
            Channel__c = 'Facebook Messenger',
            Inquiry_Status__c = 'In Progress',
            Lead_Stage__c = 'Needs Qualification',
            Lead_Priority__c = 'Hot',
            Next_Action__c = 'Call Customer',
            Payment_Intent__c = 'Financing',
            Vehicle_Interest_Text__c = 'Toyota Vios automatic white',
            Existing_Client__c = false
        );
        insert inquiry;

        Other_Inquiry__c otherInquiry = new Other_Inquiry__c(
            Customer_Name__c = 'Walk In Buyer',
            Channel__c = 'Walk In',
            Inquiry_Status__c = 'Qualified Lead',
            Qualified_Lead__c = true,
            Lead_Stage__c = 'Contacted',
            Lead_Priority__c = 'Warm',
            Next_Action__c = 'Send Vehicle Details',
            Payment_Intent__c = 'Cash',
            Vehicle_Interest_Text__c = 'Honda City cash buyer',
            Existing_Client__c = false
        );
        insert otherInquiry;

        Test.startTest();
        List<FacebookLeadKanbanController.LeadCard> cards = FacebookLeadKanbanController.getLeads();
        FacebookLeadKanbanController.updateLeadStage(inquiry.Id, 'Vehicle Selected');
        FacebookLeadKanbanController.updateLeadStage(otherInquiry.Id, 'Vehicle Selected');
        Test.stopTest();

        System.assert(cards.size() >= 2, 'Kanban should return active Facebook and other inquiries.');

        Boolean sawFacebook = false;
        Boolean sawOther = false;
        for (FacebookLeadKanbanController.LeadCard card : cards) {
            if (card.id == inquiry.Id) {
                sawFacebook = true;
                System.assertEquals('Facebook_Inquiry__c', card.objectApiName);
                System.assertEquals('Facebook', card.sourceLabel);
                System.assertEquals('Toyota Vios automatic white', card.vehicleName);
            }
            if (card.id == otherInquiry.Id) {
                sawOther = true;
                System.assertEquals('Other_Inquiry__c', card.objectApiName);
                System.assertEquals('Walk In', card.sourceLabel);
                System.assertEquals('Honda City cash buyer', card.vehicleName);
            }
        }
        System.assert(sawFacebook, 'Kanban should include the Facebook inquiry.');
        System.assert(sawOther, 'Kanban should include the Other inquiry.');

        Facebook_Inquiry__c updated = [
            SELECT Lead_Stage__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiry.Id
        ];
        System.assertEquals('Vehicle Selected', updated.Lead_Stage__c);

        Other_Inquiry__c updatedOther = [
            SELECT Lead_Stage__c
            FROM Other_Inquiry__c
            WHERE Id = :otherInquiry.Id
        ];
        System.assertEquals('Vehicle Selected', updatedOther.Lead_Stage__c);
    }

    @IsTest
    static void rejectsBlankInput() {
        Test.startTest();
        try {
            FacebookLeadKanbanController.updateLeadStage(null, null);
            System.assert(false, 'Expected an AuraHandledException.');
        } catch (AuraHandledException expected) {
            System.assertNotEquals(null, expected.getMessage());
        }
        Test.stopTest();
    }
}