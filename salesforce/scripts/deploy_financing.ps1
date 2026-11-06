# Deploys the Financing Tracker link: the Financing fields and service on the loan application,
# plus Plate Number first and VIN relabelled Chassis No. on vehicles.
# Run from the salesforce folder:  powershell -File scripts\deploy_financing.ps1 -Mode validate
param([ValidateSet('validate', 'start')][string]$Mode = 'validate')
Set-Location (Split-Path $PSScriptRoot -Parent)
$d = "force-app\main\default"
$o = "$d\objects"
$src = @(
    "$o\Auto_Loan_Application__c\fields\Financing_Partner__c.field-meta.xml",
    "$o\Auto_Loan_Application__c\fields\Financing_Status__c.field-meta.xml",
    "$o\Auto_Loan_Application__c\fields\Financing_Bank__c.field-meta.xml",
    "$o\Auto_Loan_Application__c\fields\Financing_Amount_Approved__c.field-meta.xml",
    "$o\Auto_Loan_Application__c\fields\Financing_Release_Date__c.field-meta.xml",
    "$o\Vehicle_Inventory__c\fields\VIN__c.field-meta.xml",
    "$o\Vehicle_Inventory__c\validationRules\Odoo_Owned_Fields_Locked.validationRule-meta.xml",
    "$d\layouts\Auto_Loan_Application__c-Auto Loan Application Layout.layout-meta.xml",
    "$d\layouts\Vehicle_Inventory__c-Vehicle Inventory Layout.layout-meta.xml",
    "$d\classes\AutobotiqueFinancingService.cls", "$d\classes\AutobotiqueFinancingServiceTest.cls",
    "$d\permissionsets\Odoo_Integration.permissionset-meta.xml", "$d\permissionsets\Autobotique_Staff.permissionset-meta.xml"
)
$a = @('project', 'deploy', $Mode, '-o', 'myorg', '--test-level', 'RunSpecifiedTests', '--wait', '30', '--json')
foreach ($s in $src) { $a += @('--source-dir', $s) }
foreach ($t in "AutobotiqueFinancingServiceTest", "AutobotiqueReleaseServiceTest", "OdooWebhookNotifierTest",
    "AutobotiqueProcessAutomationTest") { $a += @('--tests', $t) }
$r = sf @a 2>$null | ConvertFrom-Json
"status: $($r.status) $($r.result.status) success=$($r.result.success)"
if ($r.message) { "msg: $($r.message)" }
$r.result.details.componentFailures | Where-Object { $_.problem } | ForEach-Object { "COMPONENT FAIL $($_.fullName) [$($_.componentType)] line $($_.lineNumber): $($_.problem)" }
$r.result.details.runTestResult.failures | Where-Object { $_.message } | ForEach-Object { "TEST FAIL $($_.name).$($_.methodName): $($_.message) | $($_.stackTrace)" }
$r.result.details.runTestResult.codeCoverageWarnings | Where-Object { $_.message } | ForEach-Object { "COVERAGE: $($_.name) $($_.message)" }
"tests: $($r.result.numberTestsCompleted) completed, $($r.result.numberTestErrors) errors; id: $($r.result.id)"
