trigger ContactMobileGuard on Contact (before insert, before update) {
    AutobotiqueProcessAutomation.beforeSaveContacts(Trigger.new, Trigger.oldMap);
}
