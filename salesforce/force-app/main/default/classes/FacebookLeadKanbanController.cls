public with sharing class FacebookLeadKanbanController {
    private static final Integer LIMIT_SIZE = 200;

    @AuraEnabled(cacheable=true)
    public static List<LeadCard> getLeads() {
        List<LeadCard> cards = new List<LeadCard>();
        for (Facebook_Inquiry__c inquiry : [
            SELECT Id, Name, Customer_Name__c, Inquiry_Status__c, Lead_Stage__c, Lead_Priority__c,
                   Channel__c,
                   Next_Action__c, Next_Follow_Up_Date__c, Payment_Intent__c, Vehicle_Interest_Text__c,
                   Vehicle_Interested__r.Name,
                   Assigned_Agent__r.Name, Existing_Client__c, Auto_Loan_Application__c
            FROM Facebook_Inquiry__c
            WHERE Lead_Stage__c != 'Closed Lost'
            ORDER BY Next_Follow_Up_Date__c ASC NULLS LAST, LastModifiedDate DESC
            LIMIT :LIMIT_SIZE
        ]) {
            cards.add(toCard(inquiry));
        }

        for (Other_Inquiry__c inquiry : [
            SELECT Id, Name, Customer_Name__c, Inquiry_Status__c, Lead_Stage__c, Lead_Priority__c,
                   Channel__c,
                   Next_Action__c, Next_Follow_Up_Date__c, Payment_Intent__c, Vehicle_Interest_Text__c,
                   Vehicle_Interested__r.Name,
                   Assigned_Agent__r.Name, Existing_Client__c, Auto_Loan_Application__c
            FROM Other_Inquiry__c
            WHERE Lead_Stage__c != 'Closed Lost'
            ORDER BY Next_Follow_Up_Date__c ASC NULLS LAST, LastModifiedDate DESC
            LIMIT :LIMIT_SIZE
        ]) {
            cards.add(toCard(inquiry));
        }
        return cards;
    }

    @AuraEnabled
    public static void updateLeadStage(Id inquiryId, String stage) {
        if (inquiryId == null || String.isBlank(stage)) {
            throw new AuraHandledException('Inquiry and stage are required.');
        }

        Schema.SObjectType inquiryType = inquiryId.getSObjectType();
        if (inquiryType == Facebook_Inquiry__c.SObjectType) {
            update new Facebook_Inquiry__c(Id = inquiryId, Lead_Stage__c = stage);
        } else if (inquiryType == Other_Inquiry__c.SObjectType) {
            update new Other_Inquiry__c(Id = inquiryId, Lead_Stage__c = stage);
        } else {
            throw new AuraHandledException('Unsupported lead type.');
        }
    }

    private static LeadCard toCard(Facebook_Inquiry__c inquiry) {
        LeadCard card = baseCard(
            inquiry.Id,
            inquiry.Name,
            inquiry.Customer_Name__c,
            inquiry.Inquiry_Status__c,
            inquiry.Lead_Stage__c,
            inquiry.Lead_Priority__c,
            inquiry.Next_Action__c,
            inquiry.Next_Follow_Up_Date__c,
            inquiry.Payment_Intent__c,
            inquiry.Vehicle_Interest_Text__c,
            inquiry.Vehicle_Interested__r == null ? null : inquiry.Vehicle_Interested__r.Name,
            inquiry.Assigned_Agent__r == null ? null : inquiry.Assigned_Agent__r.Name,
            inquiry.Existing_Client__c,
            inquiry.Auto_Loan_Application__c != null,
            inquiry.Channel__c
        );
        card.objectApiName = 'Facebook_Inquiry__c';
        card.sourceLabel = inquiry.Channel__c == 'Website' ? 'Website' : 'Facebook';
        return card;
    }

    private static LeadCard toCard(Other_Inquiry__c inquiry) {
        LeadCard card = baseCard(
            inquiry.Id,
            inquiry.Name,
            inquiry.Customer_Name__c,
            inquiry.Inquiry_Status__c,
            inquiry.Lead_Stage__c,
            inquiry.Lead_Priority__c,
            inquiry.Next_Action__c,
            inquiry.Next_Follow_Up_Date__c,
            inquiry.Payment_Intent__c,
            inquiry.Vehicle_Interest_Text__c,
            inquiry.Vehicle_Interested__r == null ? null : inquiry.Vehicle_Interested__r.Name,
            inquiry.Assigned_Agent__r == null ? null : inquiry.Assigned_Agent__r.Name,
            inquiry.Existing_Client__c,
            inquiry.Auto_Loan_Application__c != null,
            inquiry.Channel__c
        );
        card.objectApiName = 'Other_Inquiry__c';
        card.sourceLabel = String.isBlank(inquiry.Channel__c) ? 'Other' : inquiry.Channel__c;
        return card;
    }

    private static LeadCard baseCard(
        Id id,
        String name,
        String customerName,
        String status,
        String stage,
        String priority,
        String nextAction,
        Date followUpDate,
        String paymentIntent,
        String vehicleInterestText,
        String vehicleRecordName,
        String assignedAgent,
        Boolean existingClient,
        Boolean hasApplication,
        String channel
    ) {
        LeadCard card = new LeadCard();
        card.id = id;
        card.name = name;
        card.customerName = String.isBlank(customerName) ? name : customerName;
        card.status = status;
        card.stage = String.isBlank(stage) ? 'New Message' : stage;
        card.priority = String.isBlank(priority) ? 'Warm' : priority;
        card.nextAction = nextAction;
        card.followUpDate = followUpDate == null ? null : String.valueOf(followUpDate);
        card.paymentIntent = paymentIntent;
        card.vehicleName = String.isBlank(vehicleRecordName) ? vehicleInterestText : vehicleRecordName;
        card.assignedAgent = assignedAgent;
        card.existingClient = existingClient;
        card.hasApplication = hasApplication;
        card.channel = channel;
        return card;
    }

    public class LeadCard {
        @AuraEnabled public Id id;
        @AuraEnabled public String objectApiName;
        @AuraEnabled public String sourceLabel;
        @AuraEnabled public String name;
        @AuraEnabled public String customerName;
        @AuraEnabled public String status;
        @AuraEnabled public String stage;
        @AuraEnabled public String priority;
        @AuraEnabled public String nextAction;
        @AuraEnabled public String followUpDate;
        @AuraEnabled public String paymentIntent;
        @AuraEnabled public String vehicleName;
        @AuraEnabled public String assignedAgent;
        @AuraEnabled public Boolean existingClient;
        @AuraEnabled public Boolean hasApplication;
        @AuraEnabled public String channel;
    }
}