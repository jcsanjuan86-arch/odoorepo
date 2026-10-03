/**
 * Scheduled every 15 minutes (see scripts/apex/schedule_follow_ups.apex).
 *
 * - Follow-up due: an open inquiry or application whose Next Follow-Up Date is
 *   today or earlier gets one open task for its agent.
 * - No reply: a new inquiry still at "New Message" 30 minutes after it arrived
 *   gets a high-priority task and a bell/mobile notification for its agent.
 *
 * A record never gets a second task of the same kind while one is still open.
 */
public without sharing class AutobotiqueFollowUpJob implements Schedulable {
    public static final String FOLLOW_UP_PREFIX = 'Autobotique follow-up: ';
    public static final String NO_REPLY_PREFIX = 'Autobotique reply now: ';
    public static final Integer NO_REPLY_MINUTES = 30;

    private static final Set<String> CLOSED_INQUIRY = new Set<String>{ 'Converted', 'Closed', 'Not Qualified' };
    private static final Set<String> CLOSED_APPLICATION = new Set<String>{ 'Approved', 'Rejected', 'Released' };

    public void execute(SchedulableContext context) {
        run();
    }

    public static Integer run() {
        List<Task> tasks = new List<Task>();
        List<Facebook_Inquiry__c> noReply = new List<Facebook_Inquiry__c>();
        Date today = Date.today();
        Datetime cutoff = Datetime.now().addMinutes(-NO_REPLY_MINUTES);

        List<Facebook_Inquiry__c> inquiries = [
            SELECT Id, Customer_Name__c, Assigned_Agent__c, OwnerId, Lead_Stage__c, Next_Follow_Up_Date__c,
                Next_Action__c, Channel__c, CreatedDate
            FROM Facebook_Inquiry__c
            WHERE Inquiry_Status__c NOT IN :CLOSED_INQUIRY
            AND (Next_Follow_Up_Date__c <= :today OR (Lead_Stage__c = 'New Message' AND CreatedDate <= :cutoff))
            LIMIT 2000
        ];
        List<Auto_Loan_Application__c> applications = [
            SELECT Id, Name, Assigned_Agent__c, OwnerId, Status__c, Next_Follow_Up_Date__c
            FROM Auto_Loan_Application__c
            WHERE Status__c NOT IN :CLOSED_APPLICATION AND Next_Follow_Up_Date__c <= :today
            LIMIT 2000
        ];

        Set<Id> recordIds = new Set<Id>();
        for (Facebook_Inquiry__c inquiry : inquiries) {
            recordIds.add(inquiry.Id);
        }
        for (Auto_Loan_Application__c application : applications) {
            recordIds.add(application.Id);
        }
        Set<String> openKeys = new Set<String>();
        for (Task existing : [
            SELECT WhatId, Subject FROM Task
            WHERE IsClosed = false AND WhatId IN :recordIds
            AND (Subject LIKE 'Autobotique follow-up:%' OR Subject LIKE 'Autobotique reply now:%')
        ]) {
            openKeys.add(existing.WhatId + (existing.Subject.startsWith(NO_REPLY_PREFIX) ? ':reply' : ':follow'));
        }

        for (Facebook_Inquiry__c inquiry : inquiries) {
            Id owner = userOf(inquiry.Assigned_Agent__c, inquiry.OwnerId);
            if (owner == null) {
                continue;
            }
            String name = String.isBlank(inquiry.Customer_Name__c) ? 'customer' : inquiry.Customer_Name__c;
            if (inquiry.Lead_Stage__c == 'New Message' && inquiry.CreatedDate <= cutoff) {
                if (!openKeys.contains(inquiry.Id + ':reply')) {
                    tasks.add(task(owner, inquiry.Id, NO_REPLY_PREFIX + name + ' is waiting',
                        'This ' + (inquiry.Channel__c == null ? 'inquiry' : inquiry.Channel__c + ' inquiry') +
                        ' has had no reply for ' + NO_REPLY_MINUTES + ' minutes. Reply, then set Lead Stage to Contacted.',
                        'High', today));
                    noReply.add(inquiry);
                }
            } else if (inquiry.Next_Follow_Up_Date__c != null && inquiry.Next_Follow_Up_Date__c <= today
                    && !openKeys.contains(inquiry.Id + ':follow')) {
                tasks.add(task(owner, inquiry.Id, FOLLOW_UP_PREFIX + name,
                    'Next action: ' + (inquiry.Next_Action__c == null ? 'follow up' : inquiry.Next_Action__c) +
                    '. Move Next Follow-Up Date forward after you contact the customer.',
                    'Normal', inquiry.Next_Follow_Up_Date__c));
            }
        }
        for (Auto_Loan_Application__c application : applications) {
            Id owner = userOf(application.Assigned_Agent__c, application.OwnerId);
            if (owner == null || openKeys.contains(application.Id + ':follow')) {
                continue;
            }
            tasks.add(task(owner, application.Id, FOLLOW_UP_PREFIX + application.Name,
                'Application status: ' + application.Status__c +
                '. Chase the missing documents, then move Next Follow-Up Date forward.',
                'Normal', application.Next_Follow_Up_Date__c));
        }

        if (!tasks.isEmpty()) {
            Database.insert(tasks, false);
        }
        notify(noReply);
        return tasks.size();
    }

    private static Id userOf(Id agentId, Id ownerId) {
        if (agentId != null) {
            return agentId;
        }
        return ownerId != null && String.valueOf(ownerId).startsWith('005') ? ownerId : null;
    }

    private static Task task(Id owner, Id whatId, String subject, String description, String priority, Date dueDate) {
        return new Task(
            OwnerId = owner, WhatId = whatId, Subject = subject.left(255), Description = description,
            Priority = priority, Status = 'Not Started', ActivityDate = dueDate
        );
    }

    private static void notify(List<Facebook_Inquiry__c> inquiries) {
        if (inquiries.isEmpty()) {
            return;
        }
        List<CustomNotificationType> types = [
            SELECT Id FROM CustomNotificationType WHERE DeveloperName = 'Autobotique_Alert' LIMIT 1
        ];
        if (types.isEmpty()) {
            return;
        }
        for (Facebook_Inquiry__c inquiry : inquiries) {
            Id owner = userOf(inquiry.Assigned_Agent__c, inquiry.OwnerId);
            Messaging.CustomNotification notification = new Messaging.CustomNotification();
            notification.setNotificationTypeId(types[0].Id);
            notification.setTitle('Customer waiting ' + NO_REPLY_MINUTES + '+ minutes');
            notification.setBody((String.isBlank(inquiry.Customer_Name__c) ? 'A customer' : inquiry.Customer_Name__c) +
                ' has not received a reply yet.');
            notification.setTargetId(inquiry.Id);
            try {
                notification.send(new Set<String>{ String.valueOf(owner) });
            } catch (Exception error) {
                System.debug(LoggingLevel.WARN, 'Autobotique notification failed: ' + error.getMessage());
            }
        }
    }
}
