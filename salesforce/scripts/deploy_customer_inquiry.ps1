# Customer Inquiry: the renamed labels (API names stay) and the inquiry created when an agent accepts a chat.
# Pauses the follow-up jobs (Salesforce blocks deploys while they are scheduled), deploys, then restarts them.
# Run from the salesforce folder:  powershell -File scripts\deploy_customer_inquiry.ps1
param([ValidateSet('validate', 'start')][string]$Mode = 'start')
Set-Location (Split-Path $PSScriptRoot -Parent)
sf apex run -f scripts\apex\unschedule_follow_ups.apex | Select-String "LEFT"
$d = "force-app\main\default"
$o = "$d\objects\Facebook_Inquiry__c"
$src = @(
    "$o\Facebook_Inquiry__c.object-meta.xml",
    "$o\fields\Assigned_Agent__c.field-meta.xml", "$o\fields\Previous_Agent__c.field-meta.xml",
    "$o\fields\Auto_Loan_Application__c.field-meta.xml", "$o\fields\Case__c.field-meta.xml",
    "$o\fields\Contact__c.field-meta.xml", "$o\fields\Vehicle_Interested__c.field-meta.xml",
    "$d\objects\MessagingSession\fields\Facebook_Inquiry__c.field-meta.xml",
    "$d\flexipages\Facebook_Inquiry_Record_Page.flexipage-meta.xml", "$d\tabs\Facebook_Leads_Kanban.tab-meta.xml",
    "$d\lwc\facebookQualifiedLeadsKanban", "$d\lwc\autobotiqueMessagingCrmPanel",
    "$d\classes\FacebookLeadKanbanController.cls", "$d\classes\FacebookLeadKanbanControllerTest.cls",
    "$d\classes\AutobotiqueMessagingActionsController.cls", "$d\triggers\AutobotiqueMessagingSession.trigger",
    "$d\classes\AutobotiqueRouterTest.cls"
)
$a = @('project', 'deploy', $Mode, '-o', 'myorg', '--test-level', 'RunSpecifiedTests', '--wait', '30', '--json')
foreach ($s in $src) { $a += @('--source-dir', $s) }
foreach ($t in "FacebookLeadKanbanControllerTest", "AutobotiqueMsgActionsTest", "AutobotiqueProcessAutomationTest",
    "AutobotiqueRouterTest") { $a += @('--tests', $t) }
$r = sf @a 2>$null | ConvertFrom-Json
"status: $($r.status) $($r.result.status) success=$($r.result.success)"
if ($r.message) { "msg: $($r.message)" }
$r.result.details.componentFailures | Where-Object { $_.problem } | ForEach-Object { "COMPONENT FAIL $($_.fullName) [$($_.componentType)] line $($_.lineNumber): $($_.problem)" }
$r.result.details.runTestResult.failures | Where-Object { $_.message } | ForEach-Object { "TEST FAIL $($_.name).$($_.methodName): $($_.message) | $($_.stackTrace)" }
$r.result.details.runTestResult.codeCoverageWarnings | Where-Object { $_.message } | ForEach-Object { "COVERAGE: $($_.name) $($_.message)" }
"tests: $($r.result.numberTestsCompleted) completed, $($r.result.numberTestErrors) errors; id: $($r.result.id)"

sf apex run -f scripts\apex\schedule_follow_ups.apex | Select-String "SCHEDULED"
