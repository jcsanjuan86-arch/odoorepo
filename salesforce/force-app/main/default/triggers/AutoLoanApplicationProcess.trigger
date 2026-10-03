trigger AutoLoanApplicationProcess on Auto_Loan_Application__c (after update) {
    AutobotiqueProcessAutomation.afterUpdateApplications(Trigger.new, Trigger.oldMap);
}
