/**
 * Backs the Requirements page and the checklist panel on Loan Application pages:
 * agents see which documents are missing, upload files per requirement, and read
 * the final checker's notes. Final checking itself stays on Final Applications.
 */
public with sharing class ApplicationRequirementsController {
    static final Set<String> AGENT_STATUSES = new Set<String>{
        'Draft', 'Documents Pending', 'Returned to Agent', 'Final Review', 'Submitted', 'Under Review'
    };

    public class ApplicationRow {
        @AuraEnabled public Id id;
        @AuraEnabled public String name;
        @AuraEnabled public String applicationNumber;
        @AuraEnabled public String status;
        @AuraEnabled public String clientName;
        @AuraEnabled public String vehicleName;
        @AuraEnabled public String agentName;
        @AuraEnabled public Integer required = 0;
        @AuraEnabled public Integer uploaded = 0;
        @AuraEnabled public Integer needsCorrection = 0;
        @AuraEnabled public Boolean returned;
    }

    public class RequirementRow {
        @AuraEnabled public Id id;
        @AuraEnabled public String documentType;
        @AuraEnabled public Boolean required;
        @AuraEnabled public String status;
        @AuraEnabled public String finalCheckStatus;
        @AuraEnabled public String checkerNotes;
        @AuraEnabled public String fileUrl;
        @AuraEnabled public String label;
    }

    public class Checklist {
        @AuraEnabled public ApplicationRow application;
        @AuraEnabled public List<RequirementRow> requirements = new List<RequirementRow>();
        @AuraEnabled public String reviewNotes;
    }

    /** Applications that still need documents or are with the checker. */
    @AuraEnabled
    public static List<ApplicationRow> getQueue(Boolean mineOnly) {
        Id me = UserInfo.getUserId();
        List<Auto_Loan_Application__c> applications = mineOnly == true
            ? [SELECT Id, Name, Application_Number__c, Status__c, Client__r.Name, Selected_Vehicle__r.Vehicle_Name__c,
                   Assigned_Agent__r.Name, Returned_To_Agent__c
               FROM Auto_Loan_Application__c
               WHERE Status__c IN :AGENT_STATUSES AND (Assigned_Agent__c = :me OR OwnerId = :me)
               ORDER BY Returned_To_Agent__c DESC, LastModifiedDate DESC LIMIT 100]
            : [SELECT Id, Name, Application_Number__c, Status__c, Client__r.Name, Selected_Vehicle__r.Vehicle_Name__c,
                   Assigned_Agent__r.Name, Returned_To_Agent__c
               FROM Auto_Loan_Application__c
               WHERE Status__c IN :AGENT_STATUSES
               ORDER BY Returned_To_Agent__c DESC, LastModifiedDate DESC LIMIT 100];
        return buildRows(applications);
    }

    @AuraEnabled
    public static Checklist getChecklist(Id applicationId) {
        if (applicationId == null) {
            throw new AuraHandledException('Choose an application.');
        }
        List<ApplicationRow> rows = buildRows([
            SELECT Id, Name, Application_Number__c, Status__c, Client__r.Name, Selected_Vehicle__r.Vehicle_Name__c,
                Assigned_Agent__r.Name, Returned_To_Agent__c, Final_Review_Notes__c
            FROM Auto_Loan_Application__c WHERE Id = :applicationId
        ]);
        if (rows.isEmpty()) {
            throw new AuraHandledException('Application not found or not shared with you.');
        }
        Checklist checklist = new Checklist();
        checklist.application = rows[0];
        checklist.reviewNotes = [SELECT Final_Review_Notes__c FROM Auto_Loan_Application__c WHERE Id = :applicationId].Final_Review_Notes__c;
        for (Application_Document__c document : [
            SELECT Id, Document_Type__c, Required__c, Document_Status__c, Final_Check_Status__c,
                Final_Check_Notes__c, Submitted_File_URL__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c = :applicationId
            ORDER BY Required__c DESC, Document_Type__c
        ]) {
            RequirementRow row = new RequirementRow();
            row.id = document.Id;
            row.documentType = document.Document_Type__c;
            row.required = document.Required__c;
            row.status = String.isBlank(document.Document_Status__c) ? 'Missing' : document.Document_Status__c;
            row.finalCheckStatus = String.isBlank(document.Final_Check_Status__c) ? 'Pending' : document.Final_Check_Status__c;
            row.checkerNotes = document.Final_Check_Notes__c;
            row.fileUrl = document.Submitted_File_URL__c;
            row.label = labelFor(row);
            checklist.requirements.add(row);
        }
        return checklist;
    }

    /**
     * Called after lightning-file-upload stored a file on the requirement.
     * Also links the file to the application and marks the requirement uploaded;
     * RequirementsAutomation then moves the application along when complete.
     */
    @AuraEnabled
    public static void attachUploadedFile(Id documentId, Id contentDocumentId) {
        if (documentId == null || contentDocumentId == null) {
            throw new AuraHandledException('Upload a file first.');
        }
        Application_Document__c document = [
            SELECT Id, Auto_Loan_Application__c FROM Application_Document__c WHERE Id = :documentId
        ];
        if ([SELECT COUNT() FROM ContentDocumentLink
             WHERE ContentDocumentId = :contentDocumentId AND LinkedEntityId = :document.Auto_Loan_Application__c] == 0) {
            insert new ContentDocumentLink(
                ContentDocumentId = contentDocumentId,
                LinkedEntityId = document.Auto_Loan_Application__c,
                ShareType = 'V',
                Visibility = 'AllUsers'
            );
        }
        document.Submitted_File_URL__c = URL.getOrgDomainUrl().toExternalForm()
            + '/lightning/r/ContentDocument/' + contentDocumentId + '/view';
        update document;
    }

    private static List<ApplicationRow> buildRows(List<Auto_Loan_Application__c> applications) {
        Map<Id, ApplicationRow> rows = new Map<Id, ApplicationRow>();
        for (Auto_Loan_Application__c application : applications) {
            ApplicationRow row = new ApplicationRow();
            row.id = application.Id;
            row.name = application.Name;
            row.applicationNumber = application.Application_Number__c;
            row.status = application.Status__c;
            row.clientName = application.Client__r == null ? '' : application.Client__r.Name;
            row.vehicleName = application.Selected_Vehicle__r == null ? '' : application.Selected_Vehicle__r.Vehicle_Name__c;
            row.agentName = application.Assigned_Agent__r == null ? '' : application.Assigned_Agent__r.Name;
            row.returned = application.Returned_To_Agent__c;
            rows.put(application.Id, row);
        }
        if (rows.isEmpty()) {
            return new List<ApplicationRow>();
        }
        for (Application_Document__c document : [
            SELECT Auto_Loan_Application__c, Document_Status__c, Final_Check_Status__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c IN :rows.keySet() AND Required__c = true
        ]) {
            ApplicationRow row = rows.get(document.Auto_Loan_Application__c);
            row.required++;
            if (document.Document_Status__c == 'Submitted' || document.Document_Status__c == 'Approved') {
                row.uploaded++;
            }
            if (document.Final_Check_Status__c == 'Needs Correction') {
                row.needsCorrection++;
            }
        }
        return rows.values();
    }

    private static String labelFor(RequirementRow row) {
        if (row.finalCheckStatus == 'Needs Correction') {
            return 'Needs Correction';
        }
        if (row.finalCheckStatus == 'Done') {
            return 'Checked';
        }
        if (row.status == 'Submitted' || row.status == 'Approved') {
            return 'Uploaded';
        }
        return 'Missing';
    }
}
