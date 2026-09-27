trigger AutoLoanApplicationOdooSync on Auto_Loan_Application__c (after insert, after update) {
    OdooWebhookNotifier.notifyChanged(Trigger.new);
}
