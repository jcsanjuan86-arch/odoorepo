/**
 * Process automation for Autobotique leads and loan applications.
 *
 * - The Facebook/website inquiry stage follows its loan application's status,
 *   so agents never move the lead stage by hand once an application exists.
 * - Changing the applicant type swaps the document checklist: missing items of
 *   the old type are removed, uploaded ones are kept as optional, and the new
 *   type's items are added.
 * - Website inquiries created by Odoo are assigned to the least busy agent.
 * - Contact mobile numbers are normalized to 09XXXXXXXXX and duplicates are
 *   blocked with the name of the existing customer.
 */
public without sharing class AutobotiqueProcessAutomation {

    // Application status -> [inquiry Lead_Stage__c, Next_Action__c]
    private static final Map<String, List<String>> STAGE_BY_STATUS = new Map<String, List<String>>{
        'Draft' => new List<String>{ 'Docs Requested', 'Send Upload Link' },
        'Documents Pending' => new List<String>{ 'Docs Requested', 'Follow Up Documents' },
        'Returned to Agent' => new List<String>{ 'Docs Requested', 'Follow Up Documents' },
        'Submitted' => new List<String>{ 'Docs Submitted', 'Follow Up Documents' },
        'Under Review' => new List<String>{ 'Docs Submitted', 'Follow Up Documents' },
        'Final Review' => new List<String>{ 'For Supervisor Review', 'Supervisor Review' },
        'Approved' => new List<String>{ 'Converted to Application', 'Close Lead' },
        'Released' => new List<String>{ 'Converted to Application', 'Close Lead' },
        'Rejected' => new List<String>{ 'Closed Lost', 'Close Lead' }
    };

    // Same checklists as the Create Application Documents flow (which runs on create only).
    @TestVisible
    private static final Map<String, List<String>> CHECKLIST = new Map<String, List<String>>{
        'Employed' => new List<String>{
            'COE', '3 Months Payslip', 'Payroll Statement', 'Bank Statement', 'Government ID 1',
            'Government ID 2', 'Company ID', 'Proof Of Billing', 'Spouse ID', 'Marriage Certificate',
            'TIN Number', 'Facebook Link', 'Specimen Signature 1', 'Specimen Signature 2', 'Specimen Signature 3'
        },
        'Business Owner' => new List<String>{
            'DTI Registration', 'Business Permit', 'Receipts', 'Business Photos', 'Government ID 1',
            'Government ID 2', 'Bank Statement', 'Proof Of Billing', 'Spouse ID', 'Marriage Certificate',
            'TIN Number', 'Facebook Link', 'Specimen Signature 1', 'Specimen Signature 2', 'Specimen Signature 3'
        },
        'OFW' => new List<String>{
            'Payslip', 'Passport', 'Visa', 'Employment Contract', 'Remittance Receipt', 'Authorization Letter',
            'Selfie Holding ID', 'Receiver Government ID 1', 'Receiver Government ID 2', 'Meralco Bill',
            'Facebook Link', 'Specimen Signature 1', 'Specimen Signature 2', 'Specimen Signature 3'
        }
    };

    // ------------------------------------------------------------------ applications

    public static void afterUpdateApplications(List<Auto_Loan_Application__c> records, Map<Id, Auto_Loan_Application__c> oldMap) {
        Map<Id, String> statusChanged = new Map<Id, String>();
        Map<Id, String> typeChanged = new Map<Id, String>();
        for (Auto_Loan_Application__c record : records) {
            Auto_Loan_Application__c old = oldMap.get(record.Id);
            if (record.Status__c != old.Status__c && String.isNotBlank(record.Status__c)) {
                statusChanged.put(record.Id, record.Status__c);
            }
            if (record.Applicant_Type__c != old.Applicant_Type__c && CHECKLIST.containsKey(record.Applicant_Type__c)) {
                typeChanged.put(record.Id, record.Applicant_Type__c);
            }
        }
        if (!statusChanged.isEmpty()) {
            syncInquiryStages(statusChanged);
        }
        if (!typeChanged.isEmpty()) {
            swapChecklists(typeChanged);
        }
    }

    public static void syncInquiryStages(Map<Id, String> statusByApplication) {
        List<Facebook_Inquiry__c> updates = new List<Facebook_Inquiry__c>();
        for (Facebook_Inquiry__c inquiry : [
            SELECT Id, Auto_Loan_Application__c, Lead_Stage__c, Next_Action__c, Inquiry_Status__c
            FROM Facebook_Inquiry__c
            WHERE Auto_Loan_Application__c IN :statusByApplication.keySet()
        ]) {
            List<String> target = STAGE_BY_STATUS.get(statusByApplication.get(inquiry.Auto_Loan_Application__c));
            if (target == null) {
                continue;
            }
            String inquiryStatus = target[0] == 'Closed Lost' ? 'Closed' : 'Converted';
            if (inquiry.Lead_Stage__c == target[0] && inquiry.Next_Action__c == target[1]
                    && inquiry.Inquiry_Status__c == inquiryStatus) {
                continue;
            }
            updates.add(new Facebook_Inquiry__c(
                Id = inquiry.Id, Lead_Stage__c = target[0], Next_Action__c = target[1], Inquiry_Status__c = inquiryStatus
            ));
        }
        if (!updates.isEmpty()) {
            // Never block the application save because a lead record has its own validation issue.
            Database.update(updates, false);
        }
    }

    public static void swapChecklists(Map<Id, String> typeByApplication) {
        Map<Id, List<Application_Document__c>> documentsByApplication = new Map<Id, List<Application_Document__c>>();
        for (Id applicationId : typeByApplication.keySet()) {
            documentsByApplication.put(applicationId, new List<Application_Document__c>());
        }
        for (Application_Document__c document : [
            SELECT Id, Auto_Loan_Application__c, Document_Type__c, Document_Status__c, Submitted_File_URL__c, Required__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c IN :typeByApplication.keySet()
        ]) {
            documentsByApplication.get(document.Auto_Loan_Application__c).add(document);
        }

        List<Application_Document__c> toDelete = new List<Application_Document__c>();
        List<Application_Document__c> toUpdate = new List<Application_Document__c>();
        List<Application_Document__c> toInsert = new List<Application_Document__c>();
        for (Id applicationId : typeByApplication.keySet()) {
            Set<String> wanted = new Set<String>(CHECKLIST.get(typeByApplication.get(applicationId)));
            Set<String> present = new Set<String>();
            for (Application_Document__c document : documentsByApplication.get(applicationId)) {
                present.add(document.Document_Type__c);
                if (wanted.contains(document.Document_Type__c)) {
                    if (document.Required__c != true) {
                        toUpdate.add(new Application_Document__c(Id = document.Id, Required__c = true));
                    }
                } else if (String.isBlank(document.Submitted_File_URL__c) && document.Document_Status__c == 'Missing') {
                    toDelete.add(document);
                } else if (document.Required__c == true) {
                    // Already uploaded for the old type: keep the file, but it no longer blocks the review.
                    toUpdate.add(new Application_Document__c(Id = document.Id, Required__c = false));
                }
            }
            for (String documentType : CHECKLIST.get(typeByApplication.get(applicationId))) {
                if (!present.contains(documentType)) {
                    toInsert.add(new Application_Document__c(
                        Auto_Loan_Application__c = applicationId, Document_Type__c = documentType,
                        Document_Status__c = 'Missing', Required__c = true
                    ));
                }
            }
        }
        if (!toDelete.isEmpty()) {
            // Customer upload rows for removed items go too; uploads already received are kept.
            delete [
                SELECT Id FROM Applicant_Upload__c
                WHERE Application_Document__c IN :toDelete AND Upload_Status__c = 'Link Sent'
            ];
            delete toDelete;
        }
        if (!toUpdate.isEmpty()) {
            update toUpdate;
        }
        if (!toInsert.isEmpty()) {
            insert toInsert;
            addUploadRows(toInsert);
        }
    }

    /** If the customer already has an upload link, add the new checklist items to it. */
    private static void addUploadRows(List<Application_Document__c> documents) {
        Set<Id> applicationIds = new Set<Id>();
        for (Application_Document__c document : documents) {
            applicationIds.add(document.Auto_Loan_Application__c);
        }
        Map<Id, Applicant_Upload__c> templateByApplication = new Map<Id, Applicant_Upload__c>();
        for (Applicant_Upload__c upload : [
            SELECT Auto_Loan_Application__c, Applicant_Name__c, Applicant_Email__c, Mobile_Number__c, Public_Upload_URL__c
            FROM Applicant_Upload__c
            WHERE Auto_Loan_Application__c IN :applicationIds
            ORDER BY CreatedDate
        ]) {
            if (!templateByApplication.containsKey(upload.Auto_Loan_Application__c)) {
                templateByApplication.put(upload.Auto_Loan_Application__c, upload);
            }
        }
        List<Applicant_Upload__c> rows = new List<Applicant_Upload__c>();
        for (Application_Document__c document : documents) {
            Applicant_Upload__c template = templateByApplication.get(document.Auto_Loan_Application__c);
            if (template == null) {
                continue;
            }
            rows.add(new Applicant_Upload__c(
                Auto_Loan_Application__c = document.Auto_Loan_Application__c,
                Application_Document__c = document.Id,
                Document_Type__c = document.Document_Type__c,
                Applicant_Name__c = template.Applicant_Name__c,
                Applicant_Email__c = template.Applicant_Email__c,
                Mobile_Number__c = template.Mobile_Number__c,
                Public_Upload_URL__c = template.Public_Upload_URL__c,
                Upload_Status__c = 'Link Sent',
                Agent_Notes__c = 'Added when the applicant type changed.'
            ));
        }
        if (!rows.isEmpty()) {
            insert rows;
        }
    }

    // ------------------------------------------------------------------ inquiries

    public static void beforeInsertInquiries(List<Facebook_Inquiry__c> records) {
        List<Facebook_Inquiry__c> unassigned = new List<Facebook_Inquiry__c>();
        for (Facebook_Inquiry__c inquiry : records) {
            if (inquiry.Channel__c == 'Website' && inquiry.Assigned_Agent__c == null) {
                unassigned.add(inquiry);
            }
        }
        if (unassigned.isEmpty()) {
            return;
        }
        List<Id> agents = leastBusyAgents();
        if (agents.isEmpty()) {
            return;
        }
        Integer index = 0;
        for (Facebook_Inquiry__c inquiry : unassigned) {
            Id agentId = agents[Math.mod(index++, agents.size())];
            inquiry.Assigned_Agent__c = agentId;
            inquiry.OwnerId = agentId;
        }
    }

    /** Agents ordered by open inquiries, fewest first. Users ticked "Receives Website Leads" win if any. */
    @TestVisible
    private static List<Id> leastBusyAgents() {
        Set<Id> candidates = new Set<Id>();
        for (User agent : [
            SELECT Id FROM User WHERE IsActive = true AND UserType = 'Standard' AND Autobotique_Website_Leads__c = true
        ]) {
            candidates.add(agent.Id);
        }
        if (candidates.isEmpty()) {
            for (PermissionSetAssignment assignment : [
                SELECT AssigneeId FROM PermissionSetAssignment
                WHERE PermissionSet.Name = 'Autobotique_Staff' AND Assignee.IsActive = true
                AND Assignee.UserType = 'Standard' AND (NOT Assignee.Name LIKE '%Integration%')
            ]) {
                candidates.add(assignment.AssigneeId);
            }
        }
        if (candidates.isEmpty()) {
            return new List<Id>();
        }
        Map<Id, Integer> load = new Map<Id, Integer>();
        for (Id candidate : candidates) {
            load.put(candidate, 0);
        }
        for (AggregateResult row : [
            SELECT Assigned_Agent__c agent, COUNT(Id) total FROM Facebook_Inquiry__c
            WHERE Assigned_Agent__c IN :candidates AND Inquiry_Status__c NOT IN ('Converted', 'Closed', 'Not Qualified')
            GROUP BY Assigned_Agent__c
        ]) {
            load.put((Id) row.get('agent'), (Integer) row.get('total'));
        }
        List<AgentLoad> ranked = new List<AgentLoad>();
        for (Id candidate : load.keySet()) {
            ranked.add(new AgentLoad(candidate, load.get(candidate)));
        }
        ranked.sort();
        List<Id> ordered = new List<Id>();
        for (AgentLoad entry : ranked) {
            ordered.add(entry.userId);
        }
        return ordered;
    }

    private class AgentLoad implements Comparable {
        Id userId;
        Integer openCount;
        AgentLoad(Id userId, Integer openCount) {
            this.userId = userId;
            this.openCount = openCount;
        }
        public Integer compareTo(Object other) {
            AgentLoad that = (AgentLoad) other;
            if (openCount != that.openCount) {
                return openCount - that.openCount;
            }
            return String.valueOf(userId).compareTo(String.valueOf(that.userId));
        }
    }

    // ------------------------------------------------------------------ contacts

    /** 0917 123 4567 / +63 917 123 4567 / 9171234567 -> 09171234567. Other formats are left alone. */
    public static String normalizeMobile(String value) {
        if (String.isBlank(value)) {
            return value;
        }
        String digits = value.replaceAll('[^0-9]', '');
        if (digits.length() == 12 && digits.startsWith('639')) {
            digits = '0' + digits.substring(2);
        } else if (digits.length() == 10 && digits.startsWith('9')) {
            digits = '0' + digits;
        }
        return digits.length() == 11 && digits.startsWith('09') ? digits : value;
    }

    public static void beforeSaveContacts(List<Contact> records, Map<Id, Contact> oldMap) {
        Map<String, Contact> byMobile = new Map<String, Contact>();
        for (Contact record : records) {
            Contact old = oldMap == null ? null : oldMap.get(record.Id);
            if (old != null && record.MobilePhone == old.MobilePhone) {
                continue;
            }
            record.MobilePhone = normalizeMobile(record.MobilePhone);
            if (String.isBlank(record.MobilePhone)) {
                continue;
            }
            if (byMobile.containsKey(record.MobilePhone)) {
                record.MobilePhone.addError('Another customer in this save has the same mobile number.');
                continue;
            }
            byMobile.put(record.MobilePhone, record);
        }
        if (byMobile.isEmpty()) {
            return;
        }
        for (Contact existing : [
            SELECT Id, Name, MobilePhone FROM Contact WHERE MobilePhone IN :byMobile.keySet()
        ]) {
            Contact record = byMobile.get(existing.MobilePhone);
            if (record != null && record.Id != existing.Id) {
                record.MobilePhone.addError(
                    'Customer ' + existing.Name + ' already has mobile ' + existing.MobilePhone +
                    '. Open that contact instead of creating a duplicate.'
                );
            }
        }
    }
}
