public with sharing class AutobotiqueMessagingActionsController {
    public class ActionResult {
        @AuraEnabled public Id recordId;
        @AuraEnabled public String recordUrl;
        @AuraEnabled public String publicUrl;
        @AuraEnabled public Boolean publicUploadReady;
        @AuraEnabled public String message;
    }

    private class ConversationContext {
        Id messagingSessionId;
        Id contactId;
        Id caseId;
        Id existingInquiryId;
        String customerName;
        String facebookUserId;
    }

    @AuraEnabled
    public static ActionResult ensureFacebookInquiry(Id messagingSessionId) {
        if (messagingSessionId == null) {
            throw new AuraHandledException('Open a messaging conversation first.');
        }

        ConversationContext context = loadContext(messagingSessionId);
        return ensureFacebookInquiry(context, true);
    }

    @AuraEnabled
    public static ActionResult createLoanApplication(Id messagingSessionId) {
        if (messagingSessionId == null) {
            throw new AuraHandledException('Open a messaging conversation first.');
        }

        ConversationContext context = loadContext(messagingSessionId);
        if (context.existingInquiryId == null) {
            throw new AuraHandledException('Create the Autobotique lead for this conversation first.');
        }

        Facebook_Inquiry__c inquiry = loadInquiry(context.existingInquiryId);
        if (inquiry.Auto_Loan_Application__c == null) {
            prepareForApplication(inquiry);
        }
        return createLoanApplication(inquiry, messagingSessionId, true);
    }

    /**
     * One click from lead to application: qualifies and converts the lead (if not
     * done yet) and creates the loan application. Replaces the separate Qualify,
     * Convert and Create Loan Application steps.
     */
    @AuraEnabled
    public static ActionResult startApplication(Id inquiryId) {
        if (inquiryId == null) {
            throw new AuraHandledException('Open an Autobotique lead first.');
        }
        Facebook_Inquiry__c inquiry = loadInquiry(inquiryId);
        if (inquiry.Auto_Loan_Application__c != null) {
            return result(inquiry.Auto_Loan_Application__c, 'Opening the loan application.');
        }
        prepareForApplication(inquiry);
        ActionResult output = createLoanApplication(inquiry, null, false);
        output.message = 'Application started with the customer and vehicle filled in. Send the upload link next.';
        return output;
    }

    private static Facebook_Inquiry__c loadInquiry(Id inquiryId) {
        return [
            SELECT Id, Customer_Name__c, Contact__c, Assigned_Agent__c, Payment_Intent__c,
                Vehicle_Interested__c, Auto_Loan_Application__c, Qualified_Lead__c,
                Inquiry_Status__c, Lead_Stage__c, Next_Action__c, Channel__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiryId
            LIMIT 1
        ];
    }

    /** Qualify + convert in one step, with one clear message for everything still missing. */
    private static void prepareForApplication(Facebook_Inquiry__c inquiry) {
        List<String> missing = new List<String>();
        if (inquiry.Contact__c == null) {
            missing.add('link or create the customer Contact');
        }
        if (inquiry.Vehicle_Interested__c == null) {
            missing.add('choose the Vehicle Interested');
        }
        if (!missing.isEmpty()) {
            throw new AuraHandledException('Before starting the application, ' + String.join(missing, ' and ') + '.');
        }
        if (inquiry.Assigned_Agent__c == null) {
            inquiry.Assigned_Agent__c = UserInfo.getUserId();
        }
        if (String.isBlank(inquiry.Payment_Intent__c)) {
            inquiry.Payment_Intent__c = 'Undecided';
        }
        inquiry.Qualified_Lead__c = true;
        inquiry.Inquiry_Status__c = 'Converted';
        inquiry.Lead_Stage__c = 'Converted to Application';
        inquiry.Next_Action__c = 'Send Upload Link';
        inquiry.Next_Follow_Up_Date__c = Date.today();
        update new Facebook_Inquiry__c(
            Id = inquiry.Id, Assigned_Agent__c = inquiry.Assigned_Agent__c, Payment_Intent__c = inquiry.Payment_Intent__c,
            Qualified_Lead__c = true, Inquiry_Status__c = 'Converted', Lead_Stage__c = 'Converted to Application',
            Next_Action__c = 'Send Upload Link', Next_Follow_Up_Date__c = Date.today()
        );
    }

    @AuraEnabled
    public static ActionResult qualifyLead(Id inquiryId) {
        if (inquiryId == null) {
            throw new AuraHandledException('Open an Autobotique lead first.');
        }

        Facebook_Inquiry__c inquiry = [
            SELECT Id, Contact__c, Assigned_Agent__c, Lead_Stage__c, Next_Action__c,
                Payment_Intent__c, Vehicle_Interested__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiryId
            LIMIT 1
        ];

        if (inquiry.Contact__c == null) {
            throw new AuraHandledException('Link or create the customer Contact before qualifying the lead.');
        }
        if (inquiry.Assigned_Agent__c == null) {
            inquiry.Assigned_Agent__c = UserInfo.getUserId();
        }

        inquiry.Qualified_Lead__c = true;
        inquiry.Inquiry_Status__c = 'Qualified Lead';
        inquiry.Lead_Stage__c = inquiry.Vehicle_Interested__c == null ? 'Needs Qualification' : 'Vehicle Selected';
        inquiry.Next_Action__c = inquiry.Vehicle_Interested__c == null ? 'Send Vehicle Details' : 'Send Upload Link';
        if (String.isBlank(inquiry.Payment_Intent__c)) {
            inquiry.Payment_Intent__c = 'Undecided';
        }
        inquiry.Next_Follow_Up_Date__c = Date.today();
        update inquiry;

        return result(inquiry.Id, 'Lead qualified. Continue to application when customer is ready.');
    }

    @AuraEnabled
    public static ActionResult convertLead(Id inquiryId) {
        if (inquiryId == null) {
            throw new AuraHandledException('Open an Autobotique lead first.');
        }

        Facebook_Inquiry__c inquiry = [
            SELECT Id, Contact__c, Assigned_Agent__c, Qualified_Lead__c, Payment_Intent__c,
                Vehicle_Interested__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiryId
            LIMIT 1
        ];
        if (!inquiry.Qualified_Lead__c) {
            throw new AuraHandledException('Qualify the lead before converting it.');
        }
        if (inquiry.Contact__c == null) {
            throw new AuraHandledException('Link or create the customer Contact before converting the lead.');
        }
        if (inquiry.Vehicle_Interested__c == null) {
            throw new AuraHandledException('Select the interested vehicle before converting the lead.');
        }
        if (String.isBlank(inquiry.Payment_Intent__c)) {
            inquiry.Payment_Intent__c = 'Undecided';
        }
        if (inquiry.Assigned_Agent__c == null) {
            inquiry.Assigned_Agent__c = UserInfo.getUserId();
        }

        inquiry.Inquiry_Status__c = 'Converted';
        inquiry.Lead_Stage__c = 'Converted to Application';
        inquiry.Next_Action__c = 'Send Upload Link';
        inquiry.Next_Follow_Up_Date__c = Date.today();
        update inquiry;

        return result(inquiry.Id, 'Lead converted. You can now create the loan application.');
    }

    @AuraEnabled
    public static ActionResult createLoanApplicationFromInquiry(Id inquiryId) {
        if (inquiryId == null) {
            throw new AuraHandledException('Open an Autobotique lead first.');
        }

        return startApplication(inquiryId);
    }

    @AuraEnabled
    public static ActionResult createUploadRequest(Id inquiryId) {
        if (inquiryId == null) {
            throw new AuraHandledException('Open an Autobotique lead first.');
        }

        Facebook_Inquiry__c inquiry = [
            SELECT Id, Customer_Name__c, Contact__r.Email, Contact__r.MobilePhone,
                Auto_Loan_Application__c
            FROM Facebook_Inquiry__c
            WHERE Id = :inquiryId
            LIMIT 1
        ];
        if (inquiry.Auto_Loan_Application__c == null) {
            throw new AuraHandledException('Create the application before sending an upload link.');
        }

        return createUploadRequestForApplication(
            inquiry.Auto_Loan_Application__c,
            String.isBlank(inquiry.Customer_Name__c) ? 'Facebook Customer' : inquiry.Customer_Name__c,
            inquiry.Contact__r == null ? null : inquiry.Contact__r.Email,
            inquiry.Contact__r == null ? null : inquiry.Contact__r.MobilePhone,
            'Upload request created from Autobotique lead process.'
        );
    }

    @AuraEnabled
    public static ActionResult createUploadRequestFromApplication(Id applicationId) {
        if (applicationId == null) {
            throw new AuraHandledException('Open a loan application first.');
        }

        Auto_Loan_Application__c application = [
            SELECT Id, Name, Borrower_First_Name__c, Borrower_Last_Name__c,
                Borrower_Email__c, Borrower_Mobile_Number__c,
                Client__r.Email, Client__r.MobilePhone
            FROM Auto_Loan_Application__c
            WHERE Id = :applicationId
            LIMIT 1
        ];

        String applicantName = (
            (String.isBlank(application.Borrower_First_Name__c) ? '' : application.Borrower_First_Name__c) +
            ' ' +
            (String.isBlank(application.Borrower_Last_Name__c) ? '' : application.Borrower_Last_Name__c)
        ).trim();
        if (String.isBlank(applicantName)) {
            applicantName = application.Name;
        }

        return createUploadRequestForApplication(
            application.Id,
            applicantName,
            String.isBlank(application.Borrower_Email__c) && application.Client__r != null
                ? application.Client__r.Email
                : application.Borrower_Email__c,
            String.isBlank(application.Borrower_Mobile_Number__c) && application.Client__r != null
                ? application.Client__r.MobilePhone
                : application.Borrower_Mobile_Number__c,
            'Upload request created from the loan application page.'
        );
    }

    private static ActionResult createUploadRequestForApplication(
        Id applicationId,
        String applicantName,
        String applicantEmail,
        String mobileNumber,
        String agentNotes
    ) {
        String safeApplicantName = String.isBlank(applicantName) ? 'Autobotique Applicant' : applicantName;
        List<Application_Document__c> requirements = [
            SELECT Id, Document_Type__c
            FROM Application_Document__c
            WHERE Auto_Loan_Application__c = :applicationId
            AND Document_Type__c != null
            ORDER BY Required__c DESC, Document_Type__c
        ];

        Map<Id, Applicant_Upload__c> uploadsByDocumentId = new Map<Id, Applicant_Upload__c>();
        List<Applicant_Upload__c> applicationUploads = [
            SELECT Id, Application_Document__c, Document_Type__c, Public_Upload_URL__c
            FROM Applicant_Upload__c
            WHERE Auto_Loan_Application__c = :applicationId
        ];
        for (Applicant_Upload__c existingUpload : applicationUploads) {
            if (existingUpload.Application_Document__c != null) {
                uploadsByDocumentId.put(existingUpload.Application_Document__c, existingUpload);
            }
        }

        List<Applicant_Upload__c> uploadsToInsert = new List<Applicant_Upload__c>();
        for (Application_Document__c requirement : requirements) {
            if (!uploadsByDocumentId.containsKey(requirement.Id)) {
                uploadsToInsert.add(new Applicant_Upload__c(
                    Auto_Loan_Application__c = applicationId,
                    Application_Document__c = requirement.Id,
                    Applicant_Name__c = safeApplicantName,
                    Applicant_Email__c = applicantEmail,
                    Mobile_Number__c = mobileNumber,
                    Document_Type__c = String.isBlank(requirement.Document_Type__c) ? 'Document Requirement' : requirement.Document_Type__c,
                    Upload_Status__c = 'Link Sent',
                    Public_Upload_URL__c = URL.getOrgDomainUrl().toExternalForm() + '/lightning/o/Applicant_Upload__c/list',
                    Agent_Notes__c = agentNotes
                ));
            }
        }

        if (requirements.isEmpty() && applicationUploads.isEmpty()) {
            uploadsToInsert.add(new Applicant_Upload__c(
                Auto_Loan_Application__c = applicationId,
                Applicant_Name__c = safeApplicantName,
                Applicant_Email__c = applicantEmail,
                Mobile_Number__c = mobileNumber,
                Document_Type__c = 'Customer Document',
                Upload_Status__c = 'Link Sent',
                Public_Upload_URL__c = URL.getOrgDomainUrl().toExternalForm() + '/lightning/o/Applicant_Upload__c/list',
                Agent_Notes__c = agentNotes
            ));
        }

        if (!uploadsToInsert.isEmpty()) {
            insert uploadsToInsert;
        }

        applicationUploads = [
            SELECT Id, Public_Upload_URL__c
            FROM Applicant_Upload__c
            WHERE Auto_Loan_Application__c = :applicationId
            ORDER BY CreatedDate
        ];
        Applicant_Upload__c upload = applicationUploads[0];

        ActionResult output = result(
            upload.Id,
            buildUploadUrl(upload.Id).isPublic
                ? 'Upload request created. Copy the customer upload URL and send it in chat.'
                : 'Upload request created, but the public upload site URL is not configured yet. Do not send this internal Salesforce link to a customer.'
        );

        UrlBuildResult urlResult = buildUploadUrl(upload.Id);
        List<Applicant_Upload__c> uploadsToUpdate = new List<Applicant_Upload__c>();
        for (Applicant_Upload__c applicationUpload : applicationUploads) {
            uploadsToUpdate.add(new Applicant_Upload__c(
                Id = applicationUpload.Id,
                Public_Upload_URL__c = urlResult.url,
                Applicant_Name__c = safeApplicantName,
                Applicant_Email__c = applicantEmail,
                Mobile_Number__c = mobileNumber
            ));
        }
        update uploadsToUpdate;

        output.publicUrl = urlResult.url;
        output.publicUploadReady = urlResult.isPublic;
        return output;
    }

    @AuraEnabled(cacheable=true)
    public static String getAvailableCarsMessage(Integer maxCars) {
        Integer limitSize = maxCars == null || maxCars <= 0 || maxCars > 25 ? 25 : maxCars;
        List<String> lines = new List<String>{
            'Hi! Here are some available Autobotique units today:'
        };

        Integer counter = 1;
        for (Vehicle_Inventory__c vehicle : [
            SELECT Vehicle_Name__c, Condition__c, Branch__c, Selling_Price_PHP__c,
                Suggested_Downpayment_PHP__c, Default_Terms__c, Odometer__c, Plate_Number__c, Listing_URL__c
            FROM Vehicle_Inventory__c
            WHERE Inventory_Status__c = 'Available'
            ORDER BY LastModifiedDate DESC, Vehicle_Name__c
            LIMIT :limitSize
        ]) {
            lines.add(
                String.valueOf(counter) + '. ' + vehicle.Vehicle_Name__c +
                ' - ' + vehicle.Condition__c +
                ', PHP ' + formatMoney(vehicle.Selling_Price_PHP__c) +
                ', DP from PHP ' + formatMoney(vehicle.Suggested_Downpayment_PHP__c) +
                ', terms up to ' + (String.isBlank(vehicle.Default_Terms__c) ? '60' : vehicle.Default_Terms__c) + ' months' +
                (String.isBlank(vehicle.Branch__c) ? '' : ', ' + vehicle.Branch__c) +
                (vehicle.Odometer__c == null ? '' : ', ' + vehicle.Odometer__c.setScale(0).format() + ' km') +
                (String.isBlank(vehicle.Plate_Number__c) ? '' : ', plate ' + vehicle.Plate_Number__c) +
                (String.isBlank(vehicle.Listing_URL__c) ? '' : '\n   Photos: ' + vehicle.Listing_URL__c)
            );
            counter++;
        }

        if (counter == 1) {
            lines.add('No available units are listed right now. I can check with our team for incoming units.');
        } else {
            lines.add('Which unit would you like to view or get a sample computation for?');
        }
        return String.join(lines, '\n');
    }

    @TestVisible
    private static ActionResult ensureFacebookInquiryForTest(Id contactId, Id caseId, String customerName, String facebookUserId) {
        ConversationContext context = new ConversationContext();
        context.messagingSessionId = UserInfo.getUserId();
        context.contactId = contactId;
        context.caseId = caseId;
        context.customerName = customerName;
        context.facebookUserId = facebookUserId;
        return ensureFacebookInquiry(context, false);
    }

    @TestVisible
    private static ActionResult existingFacebookInquiryForTest(Id inquiryId) {
        ConversationContext context = new ConversationContext();
        context.existingInquiryId = inquiryId;
        return ensureFacebookInquiry(context, false);
    }

    @TestVisible
    private static ActionResult createLoanApplicationForTest(Facebook_Inquiry__c inquiry) {
        return createLoanApplication(inquiry, UserInfo.getUserId(), false);
    }

    private static ConversationContext loadContext(Id messagingSessionId) {
        MessagingSession session = [
            SELECT Id, CaseId, EndUserContactId, Facebook_Inquiry__c, Auto_Loan_Application__c
            FROM MessagingSession
            WHERE Id = :messagingSessionId
            LIMIT 1
        ];

        ConversationContext context = new ConversationContext();
        context.messagingSessionId = session.Id;
        context.caseId = session.CaseId;
        context.contactId = session.EndUserContactId;
        context.existingInquiryId = session.Facebook_Inquiry__c;
        context.customerName = 'Facebook Customer';
        context.facebookUserId = String.valueOf(session.Id);

        if (context.contactId != null) {
            Contact contact = [
                SELECT Name
                FROM Contact
                WHERE Id = :context.contactId
                LIMIT 1
            ];
            context.customerName = contact.Name;
        }

        return context;
    }

    private static ActionResult ensureFacebookInquiry(ConversationContext context, Boolean linkMessagingSession) {
        if (context.existingInquiryId != null) {
            return result(context.existingInquiryId, 'Facebook inquiry is already linked.');
        }

        Facebook_Inquiry__c activeInquiry = findActiveInquiry(context);
        if (activeInquiry != null) {
            if (linkMessagingSession) {
                update new MessagingSession(
                    Id = context.messagingSessionId,
                    Facebook_Inquiry__c = activeInquiry.Id
                );
            }
            return result(activeInquiry.Id, 'Existing active Autobotique lead found. Opening that lead instead of creating a duplicate.');
        }

        Facebook_Inquiry__c inquiry = buildInquiry(context);
        insert inquiry;

        if (linkMessagingSession) {
            update new MessagingSession(
                Id = context.messagingSessionId,
                Facebook_Inquiry__c = inquiry.Id
            );
        }

        return result(inquiry.Id, 'Autobotique lead created and linked to this conversation.');
    }

    private static Facebook_Inquiry__c findActiveInquiry(ConversationContext context) {
        if (context.contactId == null && String.isBlank(context.facebookUserId)) {
            return null;
        }

        List<Facebook_Inquiry__c> matches;
        if (context.contactId != null && !String.isBlank(context.facebookUserId)) {
            matches = [
                SELECT Id
                FROM Facebook_Inquiry__c
                WHERE Inquiry_Status__c != 'Converted'
                AND Lead_Stage__c != 'Converted to Application'
                AND Inquiry_Status__c != 'Closed'
                AND Lead_Stage__c != 'Closed Lost'
                AND (Contact__c = :context.contactId OR Facebook_User_ID__c = :context.facebookUserId)
                ORDER BY LastModifiedDate DESC
                LIMIT 1
            ];
        } else if (context.contactId != null) {
            matches = [
                SELECT Id
                FROM Facebook_Inquiry__c
                WHERE Inquiry_Status__c != 'Converted'
                AND Lead_Stage__c != 'Converted to Application'
                AND Inquiry_Status__c != 'Closed'
                AND Lead_Stage__c != 'Closed Lost'
                AND Contact__c = :context.contactId
                ORDER BY LastModifiedDate DESC
                LIMIT 1
            ];
        } else {
            matches = [
                SELECT Id
                FROM Facebook_Inquiry__c
                WHERE Inquiry_Status__c != 'Converted'
                AND Lead_Stage__c != 'Converted to Application'
                AND Inquiry_Status__c != 'Closed'
                AND Lead_Stage__c != 'Closed Lost'
                AND Facebook_User_ID__c = :context.facebookUserId
                ORDER BY LastModifiedDate DESC
                LIMIT 1
            ];
        }
        return matches.isEmpty() ? null : matches[0];
    }

    private static ActionResult createLoanApplication(Facebook_Inquiry__c inquiry, Id messagingSessionId, Boolean linkMessagingSession) {
        if (inquiry.Auto_Loan_Application__c != null) {
            return result(inquiry.Auto_Loan_Application__c, 'Loan application is already linked.');
        }

        Auto_Loan_Application__c application = buildApplication(inquiry);
        insert application;

        // From here the lead stage follows the application status (AutobotiqueProcessAutomation).
        update new Facebook_Inquiry__c(
            Id = inquiry.Id,
            Inquiry_Status__c = 'Converted',
            Lead_Stage__c = 'Docs Requested',
            Next_Action__c = 'Send Upload Link',
            Auto_Loan_Application__c = application.Id
        );

        if (linkMessagingSession) {
            update new MessagingSession(
                Id = messagingSessionId,
                Auto_Loan_Application__c = application.Id
            );
        }

        return result(application.Id, 'Loan application created from the conversation.');
    }

    private static Facebook_Inquiry__c buildInquiry(ConversationContext context) {
        return new Facebook_Inquiry__c(
            OwnerId = UserInfo.getUserId(),
            Assigned_Agent__c = UserInfo.getUserId(),
            Contact__c = context.contactId,
            Case__c = context.caseId,
            Customer_Name__c = String.isBlank(context.customerName) ? 'Facebook Customer' : context.customerName,
            Facebook_User_ID__c = String.isBlank(context.facebookUserId) ? String.valueOf(context.messagingSessionId) : context.facebookUserId,
            Meta_Conversation_ID__c = String.valueOf(context.messagingSessionId),
            Channel__c = 'Facebook Messenger',
            Inquiry_Status__c = 'In Progress',
            Lead_Stage__c = 'New Message',
            Lead_Priority__c = 'Warm',
            Next_Action__c = 'Reply to Inquiry',
            Next_Follow_Up_Date__c = Date.today(),
            Payment_Intent__c = 'Undecided',
            Qualified_Lead__c = false,
            Existing_Client__c = context.contactId != null,
            Customer_Message__c = 'Created from Salesforce Messaging conversation.'
        );
    }

    private static Auto_Loan_Application__c buildApplication(Facebook_Inquiry__c inquiry) {
        String customerName = String.isBlank(inquiry.Customer_Name__c) ? 'Facebook Customer' : inquiry.Customer_Name__c;
        List<String> nameParts = customerName.split(' ', 2);
        String firstName = nameParts.isEmpty() ? 'Facebook' : nameParts[0];
        String lastName = nameParts.size() > 1 ? nameParts[1] : 'Customer';
        String paymentOption = inquiry.Payment_Intent__c == 'Cash' ? 'Cash' : 'Financing';
        Boolean fromWebsite = inquiry.isSet('Channel__c') && inquiry.Channel__c == 'Website';

        return new Auto_Loan_Application__c(
            Name = customerName + (fromWebsite ? ' - Website Inquiry' : ' - Facebook Conversation'),
            OwnerId = UserInfo.getUserId(),
            Assigned_Agent__c = inquiry.Assigned_Agent__c == null ? UserInfo.getUserId() : inquiry.Assigned_Agent__c,
            Client__c = inquiry.Contact__c,
            Status__c = 'Draft',
            Applicant_Type__c = 'Employed',
            Payment_Option__c = paymentOption,
            Source_Channel__c = 'Online',
            Application_Date__c = Date.today(),
            Borrower_First_Name__c = firstName,
            Borrower_Last_Name__c = lastName,
            Selected_Vehicle__c = inquiry.Vehicle_Interested__c,
            Next_Follow_Up_Date__c = Date.today().addDays(1),
            Agent_Notes__c = fromWebsite ? 'Created from a website inquiry.' : 'Created from Autobotique Messaging CRM panel.'
        );
    }

    private static ActionResult result(Id recordId, String message) {
        ActionResult output = new ActionResult();
        output.recordId = recordId;
        output.recordUrl = '/lightning/r/' + String.valueOf(recordId) + '/view';
        output.message = message;
        return output;
    }

    private class UrlBuildResult {
        String url;
        Boolean isPublic;
    }

    private static UrlBuildResult buildUploadUrl(Id uploadId) {
        UrlBuildResult output = new UrlBuildResult();
        String baseUrl = System.Label.Autobotique_Upload_Base_URL;
        output.isPublic = !String.isBlank(baseUrl) && baseUrl.toLowerCase().startsWith('http');

        if (output.isPublic) {
            String cleanBaseUrl = baseUrl.endsWith('/') ? baseUrl.left(baseUrl.length() - 1) : baseUrl;
            String separator = cleanBaseUrl.contains('?') ? '&' : '?';
            output.url = cleanBaseUrl + separator + 'requestId=' + uploadId;
            return output;
        }

        output.url = URL.getOrgDomainUrl().toExternalForm() + '/lightning/r/Applicant_Upload__c/' + uploadId + '/view';
        return output;
    }

    private static String formatMoney(Decimal amount) {
        return amount == null ? '0' : amount.setScale(0).format();
    }
}