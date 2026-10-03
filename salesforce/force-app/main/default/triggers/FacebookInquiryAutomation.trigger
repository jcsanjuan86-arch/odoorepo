trigger FacebookInquiryAutomation on Facebook_Inquiry__c (before insert, after insert, before update, after update) {
    if (Trigger.isBefore && Trigger.isInsert) {
        AutobotiqueProcessAutomation.beforeInsertInquiries(Trigger.new);
    } else if (Trigger.isBefore) {
        AutobotiqueRouter.syncAssignedAgent(Trigger.new, Trigger.oldMap);
    } else {
        if (Trigger.isInsert) {
            AutobotiqueProcessAutomation.afterInsertInquiries(Trigger.new);
        }
        AutobotiqueRouter.onOwnerChange(Trigger.new, Trigger.oldMap);
    }
}
