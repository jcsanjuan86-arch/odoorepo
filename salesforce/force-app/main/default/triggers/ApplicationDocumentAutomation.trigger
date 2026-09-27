trigger ApplicationDocumentAutomation on Application_Document__c (before insert, before update, after insert, after update) {
    if (Trigger.isBefore) {
        RequirementsAutomation.beforeSave(Trigger.new, Trigger.oldMap);
    } else {
        RequirementsAutomation.afterSave(Trigger.new, Trigger.oldMap);
    }
}
