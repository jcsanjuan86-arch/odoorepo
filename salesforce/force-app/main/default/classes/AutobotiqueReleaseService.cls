/**
 * Odoo calls this when the car is handed over: POST /services/apexrest/autobotique/release
 * {"applicationId": "a02...", "plateNumber": "NIC 7909", "odometer": 42000}
 *
 * Loan applications are private, so instead of giving the integration user
 * edit (or Modify All) access, this endpoint performs exactly one change:
 * Status -> Released, plus the plate and odometer the release rule requires.
 * Only users with the Odoo_Integration custom permission may call it.
 */
@RestResource(urlMapping='/autobotique/release/*')
global without sharing class AutobotiqueReleaseService {

    global class Result {
        public Boolean ok;
        public String message;
        public String errorCode;
    }

    @HttpPost
    global static Result release() {
        RestResponse response = RestContext.response;
        Result output = new Result();
        if (!FeatureManagement.checkPermission('Odoo_Integration')) {
            return fail(response, 403, 'FORBIDDEN', 'Only the Odoo integration user may release applications.');
        }
        Map<String, Object> body;
        try {
            body = (Map<String, Object>) JSON.deserializeUntyped(RestContext.request.requestBody.toString());
        } catch (Exception error) {
            return fail(response, 400, 'BAD_REQUEST', 'Send JSON with applicationId, plateNumber and odometer.');
        }
        String applicationId = (String) body.get('applicationId');
        List<Auto_Loan_Application__c> rows = String.isBlank(applicationId) ? new List<Auto_Loan_Application__c>() : [
            SELECT Id, Status__c, Vehicle_Plate_Number__c, Vehicle_Odometer__c
            FROM Auto_Loan_Application__c WHERE Id = :applicationId LIMIT 1
        ];
        if (rows.isEmpty()) {
            return fail(response, 404, 'NOT_FOUND', 'Loan application not found.');
        }
        Auto_Loan_Application__c application = rows[0];
        if (application.Status__c == 'Released') {
            output.ok = true;
            output.message = 'Already released.';
            return output;
        }
        String plate = (String) body.get('plateNumber');
        if (String.isNotBlank(plate)) {
            application.Vehicle_Plate_Number__c = plate.left(20);
        }
        Object odometer = body.get('odometer');
        if (odometer != null) {
            application.Vehicle_Odometer__c = Decimal.valueOf(String.valueOf(odometer));
        }
        application.Status__c = 'Released';
        Database.SaveResult saved = Database.update(application, false);
        if (!saved.isSuccess()) {
            String message = saved.getErrors()[0].getMessage();
            return fail(response, 400, 'FIELD_CUSTOM_VALIDATION_EXCEPTION', message);
        }
        output.ok = true;
        output.message = 'Application released.';
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
