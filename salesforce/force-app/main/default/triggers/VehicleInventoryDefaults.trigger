trigger VehicleInventoryDefaults on Vehicle_Inventory__c (before insert, before update) {
    AutobotiqueRecordDefaults.beforeSaveVehicles(Trigger.new, Trigger.oldMap);
}
