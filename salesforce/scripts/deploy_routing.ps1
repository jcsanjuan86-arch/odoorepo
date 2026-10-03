# Deploys agent routing (personal agent + round robin, 5 per agent, Website Leads channel).
# Pauses the follow-up jobs (Salesforce blocks deploys while they are scheduled), deploys, then restarts them.
# Run from the salesforce folder:  powershell -File scripts\deploy_routing.ps1
param([ValidateSet('validate', 'start')][string]$Mode = 'start')
Set-Location (Split-Path $PSScriptRoot -Parent)
sf apex run -f scripts\apex\unschedule_follow_ups.apex | Select-String "LEFT"
$d = "force-app\main\default"
$src = @(
    "$d\classes\AutobotiqueProcessAutomation.cls", "$d\classes\AutobotiqueProcessAutomationTest.cls",
    "$d\classes\AutobotiqueFollowUpJob.cls", "$d\classes\AutobotiqueReleaseService.cls",
    "$d\classes\AutobotiqueReleaseServiceTest.cls", "$d\classes\AutobotiqueMessagingActionsController.cls",
    "$d\triggers\AutoLoanApplicationProcess.trigger", "$d\triggers\FacebookInquiryAutomation.trigger",
    "$d\triggers\ContactMobileGuard.trigger", "$d\lwc\autobotiqueLeadProcessPanel", "$d\lwc\autobotiqueMessagingCrmPanel",
    "$d\objects\Facebook_Inquiry__c\fields\Channel__c.field-meta.xml",
    "$d\objects\User\fields\Autobotique_Website_Leads__c.field-meta.xml", "$d\notificationtypes",
    "$d\permissionsets\Odoo_Integration.permissionset-meta.xml", "$d\permissionsets\Autobotique_Staff.permissionset-meta.xml",
    "$d\classes\AutobotiqueRouter.cls", "$d\classes\AutobotiqueRouterTest.cls", "$d\triggers\AutobotiqueMessagingSession.trigger",
    "$d\objects\Contact\fields\Personal_Agent__c.field-meta.xml", "$d\objects\MessagingEndUser\fields\Personal_Agent__c.field-meta.xml",
    "$d\serviceChannels", "$d\servicePresenceStatuses", "$d\queueRoutingConfigs", "$d\queues", "$d\presenceUserConfigs",
    "$d\flows\Autobotique_Messaging_Routing.flow-meta.xml"
)
$a = @('project', 'deploy', $Mode, '-o', 'myorg', '--test-level', 'RunSpecifiedTests', '--wait', '30', '--json')
foreach ($s in $src) { $a += @('--source-dir', $s) }
foreach ($t in "AutobotiqueProcessAutomationTest", "AutobotiqueRouterTest", "AutobotiqueReleaseServiceTest", "AutobotiqueMsgActionsTest",
    "FinalApplicationReviewControllerTest", "RequirementsAutomationTest", "AutobotiqueRecordDefaultsTest",
    "CallcenterModulesDashboardControllerTest", "FacebookLeadKanbanControllerTest",
    "AutobotiquePublicUploadControllerTest", "OdooWebhookNotifierTest") { $a += @('--tests', $t) }
$r = sf @a 2>$null | ConvertFrom-Json
"status: $($r.status) $($r.result.status) success=$($r.result.success)"
if ($r.message) { "msg: $($r.message)" }
$r.result.details.componentFailures | Where-Object { $_.problem } | ForEach-Object { "COMPONENT FAIL $($_.fullName) [$($_.componentType)] line $($_.lineNumber): $($_.problem)" }
$r.result.details.runTestResult.failures | Where-Object { $_.message } | ForEach-Object { "TEST FAIL $($_.name).$($_.methodName): $($_.message) | $($_.stackTrace)" }
$r.result.details.runTestResult.codeCoverageWarnings | Where-Object { $_.message } | ForEach-Object { "COVERAGE: $($_.name) $($_.message)" }
"tests: $($r.result.numberTestsCompleted) completed, $($r.result.numberTestErrors) errors; id: $($r.result.id)"

sf apex run -f scripts\apex\schedule_follow_ups.apex | Select-String "SCHEDULED"

