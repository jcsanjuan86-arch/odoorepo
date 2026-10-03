public without sharing class AutobotiquePublicUploadController {
    private static final Integer MAX_FILE_BYTES = 10485760;

    public Id requestId { get; private set; }
    public Applicant_Upload__c upload { get; private set; }
    public List<Applicant_Upload__c> documentUploads { get; private set; }
    public Blob uploadedFileBody { get; set; }
    public String uploadedFileName { get; set; }
    public String uploadedContentType { get; set; }
    public String selectedUploadId { get; set; }
    public String applicantEmail { get; set; }
    public String mobileNumber { get; set; }
    public String applicantNotes { get; set; }
    public Boolean submitted { get; private set; }
    public String errorMessage { get; private set; }

    public AutobotiquePublicUploadController() {
        String rawRequestId = ApexPages.currentPage().getParameters().get('requestId');
        if (String.isBlank(rawRequestId)) {
            errorMessage = 'Upload request is missing. Please ask your Autobotique agent for a new link.';
            return;
        }

        try {
            requestId = (Id) rawRequestId;
            loadUpload();
        } catch (Exception ex) {
            errorMessage = 'Upload request was not found. Please ask your Autobotique agent for a new link.';
        }
    }

    public PageReference submitUpload() {
        upload = selectedUpload();
        if (upload == null) {
            errorMessage = 'Upload request was not found. Please ask your Autobotique agent for a new link.';
            return null;
        }
        if (uploadedFileBody == null || String.isBlank(uploadedFileName)) {
            errorMessage = 'Choose the document file before submitting.';
            return null;
        }
        if (uploadedFileBody.size() > MAX_FILE_BYTES) {
            errorMessage = 'The selected file is too large. Please upload a file up to 10 MB.';
            return null;
        }

        ContentVersion uploadedVersion = createSalesforceFile();
        Id contentDocumentId = [
            SELECT ContentDocumentId
            FROM ContentVersion
            WHERE Id = :uploadedVersion.Id
            LIMIT 1
        ].ContentDocumentId;

        linkFile(contentDocumentId);

        upload.Submitted_File_URL__c = URL.getOrgDomainUrl().toExternalForm() + '/lightning/r/ContentDocument/' + contentDocumentId + '/view';
        upload.Applicant_Email__c = String.isBlank(applicantEmail) ? upload.Applicant_Email__c : applicantEmail.trim();
        upload.Mobile_Number__c = String.isBlank(mobileNumber) ? upload.Mobile_Number__c : mobileNumber.trim();
        upload.Upload_Status__c = 'Submitted';
        upload.Uploaded_Date__c = Date.today();
        upload.Agent_Notes__c = buildNotes(upload.Agent_Notes__c, applicantNotes);
        update upload;

        updateRelatedDocument();

        submitted = true;
        errorMessage = null;
        loadUpload();
        return null;
    }

    public List<SelectOption> getUploadOptions() {
        List<SelectOption> options = new List<SelectOption>();
        if (documentUploads == null) {
            return options;
        }

        for (Applicant_Upload__c item : documentUploads) {
            options.add(new SelectOption(
                String.valueOf(item.Id),
                item.Document_Type__c + ' - ' + item.Upload_Status__c
            ));
        }
        return options;
    }

    public Boolean getHasDocumentChecklist() {
        return documentUploads != null && documentUploads.size() > 1;
    }

    private void loadUpload() {
        upload = [
            SELECT Id, Name, Applicant_Name__c, Applicant_Email__c, Mobile_Number__c,
                Document_Type__c, Submitted_File_URL__c, Upload_Status__c, Agent_Notes__c,
                Auto_Loan_Application__c, Application_Document__c
            FROM Applicant_Upload__c
            WHERE Id = :requestId
            LIMIT 1
        ];
        selectedUploadId = String.valueOf(upload.Id);
        applicantEmail = upload.Applicant_Email__c;
        mobileNumber = upload.Mobile_Number__c;
        loadDocumentUploads();
    }

    private void loadDocumentUploads() {
        documentUploads = new List<Applicant_Upload__c>();
        if (upload.Auto_Loan_Application__c == null) {
            documentUploads.add(upload);
            return;
        }

        documentUploads = [
            SELECT Id, Name, Applicant_Name__c, Applicant_Email__c, Mobile_Number__c,
                Document_Type__c, Submitted_File_URL__c, Upload_Status__c, Agent_Notes__c,
                Auto_Loan_Application__c, Application_Document__c
            FROM Applicant_Upload__c
            WHERE Auto_Loan_Application__c = :upload.Auto_Loan_Application__c
            ORDER BY Document_Type__c, CreatedDate
        ];
        if (documentUploads.isEmpty()) {
            documentUploads.add(upload);
        }
    }

    private Applicant_Upload__c selectedUpload() {
        if (documentUploads == null || documentUploads.isEmpty()) {
            return upload;
        }
        Id selectedId;
        try {
            selectedId = String.isBlank(selectedUploadId) ? upload.Id : (Id) selectedUploadId;
        } catch (Exception ex) {
            selectedId = upload.Id;
        }

        for (Applicant_Upload__c item : documentUploads) {
            if (item.Id == selectedId) {
                return item;
            }
        }
        return upload;
    }

    private ContentVersion createSalesforceFile() {
        String safeFileName = uploadedFileName.replace('\\', '/');
        if (safeFileName.contains('/')) {
            safeFileName = safeFileName.substringAfterLast('/');
        }

        String title = safeFileName;
        if (title.contains('.')) {
            title = title.substringBeforeLast('.');
        }

        ContentVersion version = new ContentVersion(
            Title = String.isBlank(title) ? upload.Document_Type__c : title,
            PathOnClient = safeFileName,
            VersionData = uploadedFileBody,
            Upload_Request_Id_fileupload__c = String.valueOf(upload.Id)
        );
        insert version;
        return version;
    }

    private void linkFile(Id contentDocumentId) {
        List<ContentDocumentLink> links = new List<ContentDocumentLink>();
        links.add(new ContentDocumentLink(
            ContentDocumentId = contentDocumentId,
            LinkedEntityId = upload.Id,
            ShareType = 'V',
            Visibility = 'AllUsers'
        ));

        if (upload.Application_Document__c != null) {
            links.add(new ContentDocumentLink(
                ContentDocumentId = contentDocumentId,
                LinkedEntityId = upload.Application_Document__c,
                ShareType = 'V',
                Visibility = 'AllUsers'
            ));
        }

        if (upload.Auto_Loan_Application__c != null) {
            links.add(new ContentDocumentLink(
                ContentDocumentId = contentDocumentId,
                LinkedEntityId = upload.Auto_Loan_Application__c,
                ShareType = 'V',
                Visibility = 'AllUsers'
            ));
        }

        insert links;
    }

    private void updateRelatedDocument() {
        if (upload.Application_Document__c == null) {
            return;
        }

        Application_Document__c document = new Application_Document__c(
            Id = upload.Application_Document__c,
            Document_Status__c = 'Submitted',
            Submitted_File_URL__c = upload.Submitted_File_URL__c,
            Supervisor_Download_Ready__c = true
        );
        update document;
    }

    private static String buildNotes(String existingNotes, String newNotes) {
        if (String.isBlank(newNotes)) {
            return existingNotes;
        }

        String stampedNotes = 'Applicant note ' + String.valueOf(DateTime.now()) + ': ' + newNotes.trim();
        return String.isBlank(existingNotes) ? stampedNotes : existingNotes + '\n' + stampedNotes;
    }
}