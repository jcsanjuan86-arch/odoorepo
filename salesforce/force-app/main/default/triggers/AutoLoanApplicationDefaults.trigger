trigger AutoLoanApplicationDefaults on Auto_Loan_Application__c (before insert, before update) {
    AutobotiqueRecordDefaults.beforeSaveApplications(Trigger.new, Trigger.oldMap);
}
