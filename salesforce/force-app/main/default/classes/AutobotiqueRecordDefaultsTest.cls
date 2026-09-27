@IsTest
private class AutobotiqueRecordDefaultsTest {
    private static Vehicle_Inventory__c vehicle(String stock, Decimal price, Decimal downpayment, String status) {
        Vehicle_Inventory__c car = new Vehicle_Inventory__c(
            Vehicle_Name__c = '2024 Toyota Vios ' + stock, Brand__c = 'Toyota', Model__c = 'Vios', Year__c = 2024,
            Condition__c = 'Used', Odometer__c = 18500, Plate_Number__c = 'ABC 1234',
            Inventory_Status__c = status, Stock_Number__c = stock, Selling_Price__c = price,
            Suggested_Downpayment_PHP__c = downpayment, Default_Terms__c = '48'
        );
        insert car;
        return car;
    }

    private static Auto_Loan_Application__c reload(Id applicationId) {
        return [
            SELECT Vehicle_Brand__c, Vehicle_Model__c, Vehicle_Year__c, Vehicle_Type__c, Vehicle_Odometer__c,
                Vehicle_Plate_Number__c, Vehicle_Price__c, Vehicle_Price_PHP__c, Downpayment__c, Downpayment_PHP__c,
                Loan_Amount__c, Loan_Amount_PHP__c, Monthly_Amortization_PHP__c, Terms__c, Assigned_Agent__c
            FROM Auto_Loan_Application__c WHERE Id = :applicationId
        ];
    }

    private static void assertAmount(Decimal expected, Decimal actual) {
        assertAmount(expected, actual, 'Amount');
    }

    private static void assertAmount(Decimal expected, Decimal actual, String message) {
        Assert.isTrue(actual != null && actual == expected, message + ': expected ' + expected + ' but was ' + actual);
    }

    @IsTest
    static void vehicleMoneyFieldsStayEqual() {
        Vehicle_Inventory__c car = vehicle('RD-001', 748000, 148000, 'Available');
        car = [SELECT Selling_Price_PHP__c, Suggested_Downpayment__c FROM Vehicle_Inventory__c WHERE Id = :car.Id];
        assertAmount(748000, car.Selling_Price_PHP__c, 'PHP twin filled on insert');
        assertAmount(148000, car.Suggested_Downpayment__c, 'Currency twin filled on insert');

        car.Selling_Price_PHP__c = 735000;
        update car;
        car = [SELECT Selling_Price__c, Selling_Price_PHP__c FROM Vehicle_Inventory__c WHERE Id = :car.Id];
        assertAmount(735000, car.Selling_Price__c, 'Editing the PHP field updates the currency field');
    }

    @IsTest
    static void financingApplicationCopiesTheSelectedCar() {
        Vehicle_Inventory__c car = vehicle('RD-002', 748000, 148000, 'Available');
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Name = 'Financing Test', Status__c = 'Draft', Payment_Option__c = 'Financing',
            Selected_Vehicle__c = car.Id
        );
        insert application;

        Auto_Loan_Application__c saved = reload(application.Id);
        Assert.areEqual('Toyota', saved.Vehicle_Brand__c);
        Assert.areEqual('Vios', saved.Vehicle_Model__c);
        Assert.isTrue(saved.Vehicle_Year__c == 2024, 'Year copied');
        Assert.areEqual('Used', saved.Vehicle_Type__c);
        Assert.isTrue(saved.Vehicle_Odometer__c == 18500, 'Odometer copied');
        Assert.areEqual('ABC 1234', saved.Vehicle_Plate_Number__c);
        assertAmount(748000, saved.Vehicle_Price__c);
        assertAmount(748000, saved.Vehicle_Price_PHP__c);
        assertAmount(148000, saved.Downpayment_PHP__c);
        assertAmount(600000, saved.Loan_Amount_PHP__c);
        assertAmount(600000, saved.Loan_Amount__c);
        Assert.areEqual('48', saved.Terms__c);
        Assert.isNull(saved.Monthly_Amortization_PHP__c, 'Amortization is left to the agent');
        Assert.areEqual(UserInfo.getUserId(), saved.Assigned_Agent__c, 'Agent defaults to the owner');
    }

    @IsTest
    static void cashApplicationHasNoLoan() {
        Vehicle_Inventory__c car = vehicle('RD-003', 538000, 100000, 'Available');
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Name = 'Cash Test', Status__c = 'Draft', Payment_Option__c = 'Cash', Selected_Vehicle__c = car.Id
        );
        insert application;

        Auto_Loan_Application__c saved = reload(application.Id);
        assertAmount(538000, saved.Downpayment_PHP__c, 'Cash buyers pay the full price');
        assertAmount(0, saved.Loan_Amount_PHP__c);
    }

    @IsTest
    static void agentInputIsKeptAndChangingCarsReprices() {
        Vehicle_Inventory__c first = vehicle('RD-004', 700000, 100000, 'Available');
        Vehicle_Inventory__c second = vehicle('RD-005', 800000, 150000, 'Reserved');
        Auto_Loan_Application__c application = new Auto_Loan_Application__c(
            Name = 'Agent Input Test', Status__c = 'Draft', Payment_Option__c = 'Financing',
            Selected_Vehicle__c = first.Id, Downpayment_PHP__c = 200000, Terms__c = '36'
        );
        insert application;
        Auto_Loan_Application__c saved = reload(application.Id);
        assertAmount(200000, saved.Downpayment__c, 'Agent downpayment kept and mirrored');
        assertAmount(500000, saved.Loan_Amount_PHP__c);
        Assert.areEqual('36', saved.Terms__c, 'Agent terms kept');

        application.Selected_Vehicle__c = second.Id; // Reserved cars stay open to more applicants
        update application;
        saved = reload(application.Id);
        assertAmount(800000, saved.Vehicle_Price_PHP__c, 'Switching cars reprices');
        assertAmount(600000, saved.Loan_Amount_PHP__c, 'Loan follows the new price');
    }

    @IsTest
    static void soldCarsCannotBeSelected() {
        Vehicle_Inventory__c sold = vehicle('RD-006', 650000, 100000, 'Sold');
        Boolean blocked = false;
        try {
            insert new Auto_Loan_Application__c(Name = 'Sold Car Test', Status__c = 'Draft', Selected_Vehicle__c = sold.Id);
        } catch (DmlException e) {
            blocked = e.getMessage().contains('already sold');
        }
        Assert.isTrue(blocked, 'Selecting a sold car is rejected');
    }
}
