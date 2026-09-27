/**
 * Before-save defaults for Vehicle Inventory and Auto Loan Applications.
 *
 * 1. Keeps each currency field and its "(PHP)" number twin equal. Screens,
 *    Apex and validation rules read the *_PHP__c fields while page layouts
 *    show the currency fields, so both must always match.
 * 2. When an agent picks (or changes) the Selected Vehicle, copies the car's
 *    details and price onto the application, fills the downpayment if it is
 *    blank, and derives the loan amount. Monthly amortization is left to the
 *    agent on purpose.
 * 3. Defaults the Assigned Agent to the record owner when the owner is a user.
 *
 * Replaces the never-activated flows Populate_Vehicle_Details_From_Inventory and
 * Assign_Autobotique_Agent, which overwrote agent input on every save and failed
 * for cars without default terms or records owned by a queue.
 */
public with sharing class AutobotiqueRecordDefaults {
    private static final Map<String, String> VEHICLE_MONEY = new Map<String, String>{
        'Selling_Price__c' => 'Selling_Price_PHP__c',
        'Suggested_Downpayment__c' => 'Suggested_Downpayment_PHP__c'
    };
    private static final Map<String, String> APPLICATION_MONEY = new Map<String, String>{
        'Vehicle_Price__c' => 'Vehicle_Price_PHP__c',
        'Downpayment__c' => 'Downpayment_PHP__c',
        'Loan_Amount__c' => 'Loan_Amount_PHP__c',
        'Monthly_Amortization__c' => 'Monthly_Amortization_PHP__c',
        'Borrower_Monthly_Income__c' => 'Borrower_Monthly_Income_PHP__c',
        'CoBorrower_Monthly_Income__c' => 'CoBorrower_Monthly_Income_PHP__c'
    };

    public static void beforeSaveVehicles(List<Vehicle_Inventory__c> records, Map<Id, Vehicle_Inventory__c> oldMap) {
        for (Vehicle_Inventory__c record : records) {
            mirrorMoney(record, oldMap == null ? null : oldMap.get(record.Id), VEHICLE_MONEY);
        }
    }

    public static void beforeSaveApplications(List<Auto_Loan_Application__c> records, Map<Id, Auto_Loan_Application__c> oldMap) {
        List<Auto_Loan_Application__c> vehicleChanged = new List<Auto_Loan_Application__c>();
        Set<Id> vehicleIds = new Set<Id>();
        for (Auto_Loan_Application__c record : records) {
            Auto_Loan_Application__c old = oldMap == null ? null : oldMap.get(record.Id);
            mirrorMoney(record, old, APPLICATION_MONEY);
            if (record.Assigned_Agent__c == null && record.OwnerId != null
                    && record.OwnerId.getSObjectType() == User.SObjectType) {
                record.Assigned_Agent__c = record.OwnerId;
            }
            if (record.Selected_Vehicle__c != null
                    && (old == null || old.Selected_Vehicle__c != record.Selected_Vehicle__c)) {
                vehicleChanged.add(record);
                vehicleIds.add(record.Selected_Vehicle__c);
            }
        }
        if (!vehicleIds.isEmpty()) {
            Map<Id, Vehicle_Inventory__c> vehicles = new Map<Id, Vehicle_Inventory__c>([
                SELECT Id, Brand__c, Model__c, Year__c, Condition__c, Odometer__c, Plate_Number__c,
                    Selling_Price__c, Selling_Price_PHP__c, Suggested_Downpayment__c,
                    Suggested_Downpayment_PHP__c, Default_Terms__c
                FROM Vehicle_Inventory__c
                WHERE Id IN :vehicleIds
            ]);
            for (Auto_Loan_Application__c record : vehicleChanged) {
                Vehicle_Inventory__c car = vehicles.get(record.Selected_Vehicle__c);
                if (car != null) {
                    copyVehicle(record, car, oldMap != null);
                }
            }
        }
        for (Auto_Loan_Application__c record : records) {
            deriveLoanAmount(record, oldMap == null ? null : oldMap.get(record.Id));
        }
    }

    private static void copyVehicle(Auto_Loan_Application__c record, Vehicle_Inventory__c car, Boolean isUpdate) {
        record.Vehicle_Brand__c = car.Brand__c;
        record.Vehicle_Model__c = car.Model__c;
        record.Vehicle_Year__c = car.Year__c;
        record.Vehicle_Odometer__c = car.Odometer__c;
        record.Vehicle_Plate_Number__c = car.Plate_Number__c;
        if (car.Condition__c != null) {
            record.Vehicle_Type__c = car.Condition__c;
        }
        Decimal price = firstNonNull(car.Selling_Price_PHP__c, car.Selling_Price__c);
        // A newly inserted application keeps a price the agent typed; switching cars always reprices.
        if (price != null && (isUpdate || record.Vehicle_Price_PHP__c == null)) {
            setMoney(record, 'Vehicle_Price__c', 'Vehicle_Price_PHP__c', price);
        }
        if (String.isBlank(record.Terms__c) && car.Default_Terms__c != null) {
            record.Terms__c = car.Default_Terms__c;
        }
        if (record.Downpayment_PHP__c == null) {
            Decimal downpayment = record.Payment_Option__c == 'Cash'
                ? record.Vehicle_Price_PHP__c
                : firstNonNull(car.Suggested_Downpayment_PHP__c, car.Suggested_Downpayment__c);
            if (downpayment != null) {
                setMoney(record, 'Downpayment__c', 'Downpayment_PHP__c', downpayment);
            }
        }
    }

    /** Loan = price - downpayment for financing, 0 for cash; recomputed only when an input changed. */
    private static void deriveLoanAmount(Auto_Loan_Application__c record, Auto_Loan_Application__c old) {
        Boolean inputsChanged = old == null
            || record.Vehicle_Price_PHP__c != old.Vehicle_Price_PHP__c
            || record.Downpayment_PHP__c != old.Downpayment_PHP__c
            || record.Payment_Option__c != old.Payment_Option__c;
        if (!inputsChanged) {
            return;
        }
        if (record.Payment_Option__c == 'Cash') {
            setMoney(record, 'Loan_Amount__c', 'Loan_Amount_PHP__c', 0);
        } else if (record.Vehicle_Price_PHP__c != null && record.Downpayment_PHP__c != null
                && (old != null || record.Loan_Amount_PHP__c == null)) {
            setMoney(record, 'Loan_Amount__c', 'Loan_Amount_PHP__c',
                Math.max(record.Vehicle_Price_PHP__c - record.Downpayment_PHP__c, (Decimal) 0));
        }
    }

    /**
     * Copy whichever side of each currency / PHP pair the user changed onto the other.
     * On insert, a blank side is filled from the other. If both changed, the currency field wins.
     */
    @TestVisible
    private static void mirrorMoney(SObject record, SObject old, Map<String, String> pairs) {
        for (String currencyField : pairs.keySet()) {
            String numberField = pairs.get(currencyField);
            Decimal currencyValue = (Decimal) record.get(currencyField);
            Decimal numberValue = (Decimal) record.get(numberField);
            if (currencyValue == numberValue) {
                continue;
            }
            Boolean currencyChanged = old == null ? currencyValue != null : currencyValue != (Decimal) old.get(currencyField);
            Boolean numberChanged = old == null ? numberValue != null : numberValue != (Decimal) old.get(numberField);
            if (numberChanged && !currencyChanged) {
                record.put(currencyField, numberValue);
            } else {
                record.put(numberField, currencyValue);
            }
        }
    }

    private static void setMoney(SObject record, String currencyField, String numberField, Decimal value) {
        record.put(currencyField, value);
        record.put(numberField, value);
    }

    private static Decimal firstNonNull(Decimal first, Decimal second) {
        return first != null ? first : second;
    }
}
