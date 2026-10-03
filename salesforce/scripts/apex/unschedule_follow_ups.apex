for (CronTrigger t : [SELECT Id FROM CronTrigger WHERE CronJobDetail.Name LIKE 'Autobotique follow-ups%']) { System.abortJob(t.Id); }
System.debug(LoggingLevel.ERROR, 'LEFT ' + [SELECT COUNT() FROM CronTrigger WHERE CronJobDetail.Name LIKE 'Autobotique follow-ups%']);
