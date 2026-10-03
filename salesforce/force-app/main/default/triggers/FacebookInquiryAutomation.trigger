trigger FacebookInquiryAutomation on Facebook_Inquiry__c (before insert) {
    AutobotiqueProcessAutomation.beforeInsertInquiries(Trigger.new);
}
