// Schedules AutobotiqueFollowUpJob every 15 minutes (four hourly cron entries).
// Safe to re-run: existing Autobotique follow-up schedules are replaced.
// Run: sf apex run -o myorg -f scripts/apex/schedule_follow_ups.apex
for (CronTrigger existing : [
    SELECT Id FROM CronTrigger WHERE CronJobDetail.Name LIKE 'Autobotique follow-ups%'
]) {
    System.abortJob(existing.Id);
}
for (String minute : new List<String>{ '0', '15', '30', '45' }) {
    System.schedule('Autobotique follow-ups :' + minute.leftPad(2, '0'), '0 ' + minute + ' * * * ?', new AutobotiqueFollowUpJob());
}
System.debug(LoggingLevel.ERROR, 'SCHEDULED ' + [SELECT COUNT() FROM CronTrigger WHERE CronJobDetail.Name LIKE 'Autobotique follow-ups%']);
