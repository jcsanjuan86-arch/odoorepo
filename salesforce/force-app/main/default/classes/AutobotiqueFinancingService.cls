/**
 * Odoo calls this when a Financing Tracker account changes:
 * POST /services/apexrest/autobotique/financing
 * {"applicationId": "a02...", "status": "Approved", "bank": "TFS",
 *  "amountApproved": 550000, "releaseDate": "2026-11-06"}
 *
 * Loan applications are private, so instead of giving the integration user
 * edit (or Modify All) access, this endpoint writes only the read-only
 * Financing fields agents see on the application. Only users with the
 * Odoo_Integration custom permission may call it.
 */
@RestResource(urlMapping='/autobotique/financing/*')
global without sharing class AutobotiqueFinancingService {

    global class Result {
        public Boolean ok;
        public String message;
        public String errorCode;
    }

    @HttpPost
    global static Result updateFinancing() {
        RestResponse response = RestContext.response;
        if (!FeatureManagement.checkPermission('Odoo_Integration')) {
            return fail(response, 403, 'FORBIDDEN', 'Only the Odoo integration user may update financing details.');
        }
        Map<String, Object> body;
        try {
            body = (Map<String, Object>) JSON.deserializeUntyped(RestContext.request.requestBody.toString());
        } catch (Exception error) {
            return fail(response, 400, 'BAD_REQUEST', 'Send JSON with applicationId and the financing details.');
        }
        String applicationId = (String) body.get('applicationId');
        List<Auto_Loan_Application__c> rows = String.isBlank(applicationId) ? new List<Auto_Loan_Application__c>() : [
            SELECT Id FROM Auto_Loan_Application__c WHERE Id = :applicationId LIMIT 1
        ];
        if (rows.isEmpty()) {
            return fail(response, 404, 'NOT_FOUND', 'Loan application not found.');
        }
        Auto_Loan_Application__c application = rows[0];
        try {
            Object amount = body.get('amountApproved');
            String releaseDate = (String) body.get('releaseDate');
            application.Financing_Status__c = ((String) body.get('status'))?.left(60);
            application.Financing_Bank__c = ((String) body.get('bank'))?.left(80);
            application.Financing_Amount_Approved__c = amount == null ? null : Decimal.valueOf(String.valueOf(amount));
            application.Financing_Release_Date__c = String.isBlank(releaseDate) ? null : Date.valueOf(releaseDate);
        } catch (Exception error) {
            return fail(response, 400, 'BAD_REQUEST', 'Invalid financing details: ' + error.getMessage());
        }
        Database.SaveResult saved = Database.update(application, false);
        if (!saved.isSuccess()) {
            return fail(response, 400, 'FIELD_CUSTOM_VALIDATION_EXCEPTION', saved.getErrors()[0].getMessage());
        }
        Result output = new Result();
        output.ok = true;
        output.message = 'Financing details updated.';
        return output;
    }

    private static Result fail(RestResponse response, Integer status, String code, String message) {
        if (response != null) {
            response.statusCode = status;
        }
        Result output = new Result();
        output.ok = false;
        output.errorCode = code;
        output.message = message;
        return output;
    }
}
