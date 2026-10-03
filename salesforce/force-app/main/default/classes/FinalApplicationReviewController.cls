public with sharing class FinalApplicationReviewController {
    public class ApplicationSummary {
        @AuraEnabled public Id id;
        @AuraEnabled public String name;
        @AuraEnabled public String applicationNumber;
        @AuraEnabled public String status;
        @AuraEnabled public String finalReviewStatus;
        @AuraEnabled public String assignedAgentName;
        @AuraEnabled public String clientName;
        @AuraEnabled public String vehicleName;
        @AuraEnabled public Integer requiredDocuments;
        @AuraEnabled public Integer completedDocuments;
        @AuraEnabled public Integer missingDocuments;
        @AuraEnabled public String recordUrl;
    }

    public class DocumentRow {
        @AuraEnabled public Id id;
        @AuraEnabled public String documentNumber;
        @AuraEnabled public String documentType;
        @AuraEnabled public String documentStatus;
        @AuraEnabled public Boolean required;
        @AuraEnabled public String submittedFileUrl;
        @AuraEnabled public String finalCheckStatus;
        @AuraEnabled public String finalCheckNotes;
        @AuraEnabled public String statusClass;
    }

    public class ReviewDetail {
        @AuraEnabled public ApplicationSummary application;
        @AuraEnabled public List<DocumentRow> documents;
        @AuraEnabled public String notes;
    }

    @AuraEnabled(cacheable=true)
    public static List<ApplicationSummary> getFinalApplications() {
        List<Auto_Loan_Application__c> applications = [
            SELECT Id, Name, Application_Number__c, Status__c, Final_Review_Status__c,
                Assigned_Agent__r.Name, Client__r.Name, Selected_Vehicle__r.Vehicle_Name__c
            FROM Auto_Loan_Application__c
            WHERE Status__c IN ('Submitted', 'Under Review', 'Final Review', 'Returned to Agent')
            OR Final_Review_Status__c IN ('Pending Review', 'In Review', 'Returned to Agent')
            ORDER BY LastModifiedDate DESC
            LIMIT 100
        ];
        return buildSummaries(applications);
    }

    @AuraEnabled(cacheable=true)
    public static ReviewDetail getReviewDetail(Id applicationId) {
        if (applicationId == null) {
            throw new AuraHandledException('Open an application to review.');
        }

        List<ApplicationSummary> summaries = buildSummaries([
            SELECT Id, Name, Application_Number__c, Status__c, Final_Review_Status__c,
                Assigned_Agent__r.Name, Client__r.Name, Selected_Vehicle__r.Vehicle_Name__c
            FROM Auto_Loan_Application__c
            WHERE Id = :applicationId
            LIMIT 1
        ]);

        Auto_Loan_Application__c application = [
            SELECT Final_Review_Notes__c
            FROM Auto_Loan_Application__c
            WHERE Id = :applicationId
            LIMIT 1
        ];

        ReviewDetail detail = new ReviewDetail();
        detail.application = summaries.isEmpty() ? null : summaries[0];
        detail.notes = application.Final_Review_Notes__c;
        detail.documents = new List<DocumentRow>();

        for (Application_Document__c document : [
            SELECT Id, Name, Document_Type__c, Document_Status__c, Required__c,
                Submitted_File_URL__c, Final_Check_Status__c, Final_Check_Notes__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c = :applicationId
            ORDER BY Required__c DESC, Document_Type__c
        ]) {
            detail.documents.add(toDocumentRow(document));
        }
        return detail;
    }

    @AuraEnabled
    public static void startFinalReview(Id applicationId) {
        if (applicationId == null) {
            throw new AuraHandledException('Open an application to review.');
        }

        update new Auto_Loan_Application__c(
            Id = applicationId,
            Status__c = 'Final Review',
            Final_Review_Status__c = 'In Review',
            Final_Reviewer__c = UserInfo.getUserId(),
            Returned_To_Agent__c = false
        );
    }

    @AuraEnabled
    public static void markDocument(Id documentId, String finalCheckStatus, String notes) {
        if (documentId == null) {
            throw new AuraHandledException('Select a document requirement first.');
        }
        if (String.isBlank(finalCheckStatus)) {
            throw new AuraHandledException('Choose Done or Needs Correction.');
        }
        if (finalCheckStatus != 'Done' && finalCheckStatus != 'Needs Correction' && finalCheckStatus != 'Pending') {
            throw new AuraHandledException('Unsupported final document status.');
        }

        Application_Document__c updateDocument = new Application_Document__c(
            Id = documentId,
            Final_Check_Status__c = finalCheckStatus,
            Final_Check_Notes__c = notes,
            Final_Checked_By__c = UserInfo.getUserId(),
            Final_Checked_Date__c = System.now()
        );
        if (finalCheckStatus == 'Done') {
            updateDocument.Document_Status__c = 'Approved';
        } else if (finalCheckStatus == 'Needs Correction') {
            updateDocument.Document_Status__c = 'Rejected';
        }
        update updateDocument;
    }

    @AuraEnabled
    public static void returnToAgent(Id applicationId, String notes) {
        if (applicationId == null) {
            throw new AuraHandledException('Open an application to return.');
        }
        if (String.isBlank(notes)) {
            throw new AuraHandledException('Add notes before returning this to the agent.');
        }

        Auto_Loan_Application__c application = [
            SELECT Id, Name, Assigned_Agent__c
            FROM Auto_Loan_Application__c
            WHERE Id = :applicationId
            LIMIT 1
        ];

        Auto_Loan_Application__c updateApplication = new Auto_Loan_Application__c(
            Id = application.Id,
            Status__c = 'Returned to Agent',
            Final_Review_Status__c = 'Returned to Agent',
            Final_Reviewer__c = UserInfo.getUserId(),
            Final_Review_Notes__c = notes,
            Returned_To_Agent__c = true,
            Returned_To_Agent_Date__c = System.now(),
            Next_Follow_Up_Date__c = Date.today()
        );
        if (application.Assigned_Agent__c != null) {
            updateApplication.OwnerId = application.Assigned_Agent__c;
        }
        update updateApplication;

        if (application.Assigned_Agent__c != null) {
            insert new Task(
                OwnerId = application.Assigned_Agent__c,
                WhatId = application.Id,
                Subject = 'Fix missing requirements - ' + application.Name,
                Priority = 'High',
                Status = 'Not Started',
                ActivityDate = Date.today(),
                Description = notes
            );
        }
    }

    @AuraEnabled
    public static void completeFinalReview(Id applicationId, String notes) {
        if (applicationId == null) {
            throw new AuraHandledException('Open an application to complete.');
        }

        List<String> missingRequirements = new List<String>();
        for (Application_Document__c document : [
            SELECT Document_Type__c, Document_Status__c, Required__c, Final_Check_Status__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c = :applicationId
            AND Required__c = true
            ORDER BY Document_Type__c
        ]) {
            if (document.Document_Status__c != 'Approved' || document.Final_Check_Status__c != 'Done') {
                missingRequirements.add(document.Document_Type__c);
            }
        }

        if (!missingRequirements.isEmpty()) {
            throw new AuraHandledException(
                'Cannot complete final review. Check these requirements first: ' +
                String.join(missingRequirements, ', ')
            );
        }

        update new Auto_Loan_Application__c(
            Id = applicationId,
            Status__c = 'Approved',
            Final_Review_Status__c = 'Complete',
            Final_Reviewer__c = UserInfo.getUserId(),
            Final_Review_Notes__c = notes,
            Returned_To_Agent__c = false,
            Final_Review_Completed_Date__c = System.now()
        );
    }

    private static List<ApplicationSummary> buildSummaries(List<Auto_Loan_Application__c> applications) {
        Map<Id, ApplicationSummary> summariesById = new Map<Id, ApplicationSummary>();
        for (Auto_Loan_Application__c application : applications) {
            ApplicationSummary summary = new ApplicationSummary();
            summary.id = application.Id;
            summary.name = application.Name;
            summary.applicationNumber = application.Application_Number__c;
            summary.status = application.Status__c;
            summary.finalReviewStatus = String.isBlank(application.Final_Review_Status__c)
                ? 'Pending Review'
                : application.Final_Review_Status__c;
            summary.assignedAgentName = application.Assigned_Agent__r == null ? '' : application.Assigned_Agent__r.Name;
            summary.clientName = application.Client__r == null ? '' : application.Client__r.Name;
            summary.vehicleName = application.Selected_Vehicle__r == null ? '' : application.Selected_Vehicle__r.Vehicle_Name__c;
            summary.requiredDocuments = 0;
            summary.completedDocuments = 0;
            summary.missingDocuments = 0;
            summary.recordUrl = '/lightning/r/Auto_Loan_Application__c/' + application.Id + '/view';
            summariesById.put(application.Id, summary);
        }

        if (!summariesById.isEmpty()) {
            for (AggregateResult result : [
                SELECT Auto_Loan_Application__c applicationId,
                    COUNT(Id) totalDocuments
                FROM Application_Document__c
                WHERE Auto_Loan_Application__c IN :summariesById.keySet()
                AND Required__c = true
                GROUP BY Auto_Loan_Application__c
            ]) {
                Id applicationId = (Id) result.get('applicationId');
                ApplicationSummary summary = summariesById.get(applicationId);
                summary.requiredDocuments = Integer.valueOf(String.valueOf(result.get('totalDocuments')));
            }

            for (AggregateResult result : [
                SELECT Auto_Loan_Application__c applicationId,
                    COUNT(Id) completedDocuments
                FROM Application_Document__c
                WHERE Auto_Loan_Application__c IN :summariesById.keySet()
                AND Required__c = true
                AND Document_Status__c = 'Approved'
                AND Final_Check_Status__c = 'Done'
                GROUP BY Auto_Loan_Application__c
            ]) {
                Id applicationId = (Id) result.get('applicationId');
                ApplicationSummary summary = summariesById.get(applicationId);
                summary.completedDocuments = Integer.valueOf(String.valueOf(result.get('completedDocuments')));
            }

            for (ApplicationSummary summary : summariesById.values()) {
                summary.missingDocuments = summary.requiredDocuments - summary.completedDocuments;
            }
        }
        return summariesById.values();
    }

    private static DocumentRow toDocumentRow(Application_Document__c document) {
        DocumentRow row = new DocumentRow();
        row.id = document.Id;
        row.documentNumber = document.Name;
        row.documentType = document.Document_Type__c;
        row.documentStatus = document.Document_Status__c;
        row.required = document.Required__c;
        row.submittedFileUrl = document.Submitted_File_URL__c;
        row.finalCheckStatus = String.isBlank(document.Final_Check_Status__c) ? 'Pending' : document.Final_Check_Status__c;
        row.finalCheckNotes = document.Final_Check_Notes__c;
        row.statusClass = row.finalCheckStatus == 'Done'
            ? 'status done'
            : row.finalCheckStatus == 'Needs Correction'
                ? 'status needs-correction'
                : 'status pending';
        return row;
    }
}