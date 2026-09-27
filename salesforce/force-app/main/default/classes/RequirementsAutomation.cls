/**
 * Moves loan applications through the document checklist automatically.
 *
 * - A new file on a requirement (agent upload or customer upload link) marks it
 *   Submitted and resets the checker's verdict to Pending.
 * - When every required document is uploaded, the application goes to Final
 *   Review and appears in the checker's queue.
 * - When the checker marks a document Needs Correction, the application goes
 *   back to the assigned agent with a task explaining what to fix.
 *
 * Automatic status changes never block the upload or the checker's action: if
 * the application cannot move (for example a validation rule needs more data),
 * the agent gets a task listing what is missing instead.
 *
 * Runs without sharing on purpose: customer uploads arrive through the public
 * upload site as a guest user, who cannot see the parent application.
 */
public without sharing class RequirementsAutomation {
    @TestVisible static final Set<String> OPEN_FOR_DOCUMENTS = new Set<String>{
        'Draft', 'Documents Pending', 'Returned to Agent'
    };
    @TestVisible static final Set<String> UPLOADED = new Set<String>{ 'Submitted', 'Approved' };

    public static void beforeSave(List<Application_Document__c> records, Map<Id, Application_Document__c> oldMap) {
        for (Application_Document__c record : records) {
            Application_Document__c old = oldMap == null ? null : oldMap.get(record.Id);
            Boolean newFile = String.isNotBlank(record.Submitted_File_URL__c)
                && (old == null || record.Submitted_File_URL__c != old.Submitted_File_URL__c);
            if (newFile) {
                record.Document_Status__c = 'Submitted';
                record.Final_Check_Status__c = 'Pending';
                record.Supervisor_Download_Ready__c = true;
            }
        }
    }

    public static void afterSave(List<Application_Document__c> records, Map<Id, Application_Document__c> oldMap) {
        Set<Id> uploadedApplications = new Set<Id>();
        List<Application_Document__c> corrections = new List<Application_Document__c>();
        for (Application_Document__c record : records) {
            Application_Document__c old = oldMap == null ? null : oldMap.get(record.Id);
            if (record.Final_Check_Status__c == 'Needs Correction'
                    && (old == null || old.Final_Check_Status__c != 'Needs Correction')) {
                corrections.add(record);
            } else if (UPLOADED.contains(record.Document_Status__c)
                    && (old == null || !UPLOADED.contains(old.Document_Status__c))) {
                uploadedApplications.add(record.Auto_Loan_Application__c);
            }
        }
        if (!corrections.isEmpty()) {
            returnToAgent(corrections);
        }
        if (!uploadedApplications.isEmpty()) {
            sendCompleteApplicationsToFinalReview(uploadedApplications);
        }
    }

    private static void sendCompleteApplicationsToFinalReview(Set<Id> applicationIds) {
        Map<Id, Integer> openRequirements = new Map<Id, Integer>();
        Map<Id, Integer> requiredCount = new Map<Id, Integer>();
        for (Application_Document__c document : [
            SELECT Auto_Loan_Application__c, Document_Status__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c IN :applicationIds AND Required__c = true
        ]) {
            Id applicationId = document.Auto_Loan_Application__c;
            requiredCount.put(applicationId, (requiredCount.containsKey(applicationId) ? requiredCount.get(applicationId) : 0) + 1);
            if (!UPLOADED.contains(document.Document_Status__c)) {
                openRequirements.put(applicationId, (openRequirements.containsKey(applicationId) ? openRequirements.get(applicationId) : 0) + 1);
            }
        }
        List<Auto_Loan_Application__c> ready = new List<Auto_Loan_Application__c>();
        for (Auto_Loan_Application__c application : [
            SELECT Id, Status__c FROM Auto_Loan_Application__c WHERE Id IN :applicationIds
        ]) {
            if (OPEN_FOR_DOCUMENTS.contains(application.Status__c)
                    && requiredCount.containsKey(application.Id)
                    && !openRequirements.containsKey(application.Id)) {
                ready.add(new Auto_Loan_Application__c(
                    Id = application.Id,
                    Status__c = 'Final Review',
                    Final_Review_Status__c = 'Pending Review',
                    Returned_To_Agent__c = false
                ));
            }
        }
        updateOrExplain(ready, 'Complete the application so it can go to Final Review',
            'All required documents are uploaded, but the application could not move to Final Review automatically:');
    }

    private static void returnToAgent(List<Application_Document__c> corrections) {
        Map<Id, List<Application_Document__c>> byApplication = new Map<Id, List<Application_Document__c>>();
        for (Application_Document__c document : corrections) {
            if (!byApplication.containsKey(document.Auto_Loan_Application__c)) {
                byApplication.put(document.Auto_Loan_Application__c, new List<Application_Document__c>());
            }
            byApplication.get(document.Auto_Loan_Application__c).add(document);
        }
        List<Auto_Loan_Application__c> updates = new List<Auto_Loan_Application__c>();
        List<Task> tasks = new List<Task>();
        for (Auto_Loan_Application__c application : [
            SELECT Id, Name, Assigned_Agent__c, OwnerId, Status__c
            FROM Auto_Loan_Application__c WHERE Id IN :byApplication.keySet()
        ]) {
            if (application.Status__c != 'Returned to Agent') {
                updates.add(new Auto_Loan_Application__c(
                    Id = application.Id,
                    Status__c = 'Returned to Agent',
                    Final_Review_Status__c = 'Returned to Agent',
                    Returned_To_Agent__c = true,
                    Returned_To_Agent_Date__c = System.now(),
                    Next_Follow_Up_Date__c = Date.today()
                ));
            }
            Id agentId = agentOf(application);
            if (agentId == null) {
                continue;
            }
            for (Application_Document__c document : byApplication.get(application.Id)) {
                tasks.add(new Task(
                    OwnerId = agentId,
                    WhatId = application.Id,
                    Subject = 'Fix requirement: ' + document.Document_Type__c + ' - ' + application.Name,
                    Priority = 'High',
                    Status = 'Not Started',
                    ActivityDate = Date.today(),
                    Description = String.isBlank(document.Final_Check_Notes__c)
                        ? 'The final checker marked this document Needs Correction.'
                        : document.Final_Check_Notes__c
                ));
            }
        }
        updateOrExplain(updates, 'Return the application to the agent',
            'A document needs correction, but the application could not be returned automatically:');
        if (!tasks.isEmpty()) {
            Database.insert(tasks, false);
        }
    }

    /** Update what can be updated; for the rest, give the agent a task with the reason. */
    private static void updateOrExplain(List<Auto_Loan_Application__c> updates, String subject, String intro) {
        if (updates.isEmpty()) {
            return;
        }
        List<Database.SaveResult> results = Database.update(updates, false);
        Map<Id, String> failures = new Map<Id, String>();
        for (Integer i = 0; i < results.size(); i++) {
            if (!results[i].isSuccess()) {
                List<String> messages = new List<String>();
                for (Database.Error error : results[i].getErrors()) {
                    messages.add(error.getMessage());
                }
                failures.put(updates[i].Id, String.join(messages, '\n'));
            }
        }
        if (failures.isEmpty()) {
            return;
        }
        List<Task> tasks = new List<Task>();
        for (Auto_Loan_Application__c application : [
            SELECT Id, Name, Assigned_Agent__c, OwnerId FROM Auto_Loan_Application__c WHERE Id IN :failures.keySet()
        ]) {
            Id agentId = agentOf(application);
            if (agentId != null) {
                tasks.add(new Task(
                    OwnerId = agentId, WhatId = application.Id, Priority = 'High', Status = 'Not Started',
                    ActivityDate = Date.today(), Subject = subject + ' - ' + application.Name,
                    Description = intro + '\n' + failures.get(application.Id)
                ));
            }
        }
        Database.insert(tasks, false);
    }

    private static Id agentOf(Auto_Loan_Application__c application) {
        if (application.Assigned_Agent__c != null) {
            return application.Assigned_Agent__c;
        }
        return application.OwnerId != null && application.OwnerId.getSObjectType() == User.SObjectType
            ? application.OwnerId : null;
    }
}
