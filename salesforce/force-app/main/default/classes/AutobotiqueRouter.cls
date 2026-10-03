/**
 * Decides which agent gets a Facebook conversation or a website lead.
 *
 * 1. Personal agent: a customer always goes back to the first agent who accepted them
 *    (Personal Agent on the Messaging User or Contact), as long as that agent is online
 *    and has room (Omni-Channel capacity, 5 at a time by default).
 * 2. Otherwise round robin: among the queue's agents who are online and have room, the
 *    one whose last Omni-Channel assignment is the oldest gets it, so everyone gets an
 *    equal share.
 * 3. Nobody online: the work waits in the queue and Omni-Channel hands it to the first
 *    agent who comes online.
 *
 * Used by the "Autobotique Messaging Routing" Omni-Channel flow (every Facebook page) and
 * by the Facebook_Inquiry__c trigger for website leads.
 */
public without sharing class AutobotiqueRouter {
    public static final String MESSAGING_CHANNEL = 'sfdc_livemessage';
    public static final String MESSAGING_QUEUE = 'Facebook';
    public static final String WEBSITE_CHANNEL = 'Website_Leads';
    public static final String WEBSITE_QUEUE = 'Website_Leads';
    private static final Set<String> OPEN_WORK = new Set<String>{ 'Assigned', 'Opened' };

    // Tests cannot put agents online, so they supply the pool and free capacity directly.
    @TestVisible private static Set<Id> testPool;
    @TestVisible private static Map<Id, Decimal> testFreeCapacity;

    public class Request {
        @InvocableVariable(label='Record ID' description='Messaging session or website inquiry to route' required=true)
        public String recordId;
    }

    public class Result {
        @InvocableVariable(label='Agent ID' description='Blank when nobody is available; route to the queue then')
        public String agentId;
        @InvocableVariable(label='Reason')
        public String reason;
    }

    @InvocableMethod(label='Pick Autobotique Agent' category='Omni-Channel'
        description='Personal agent if online with room, otherwise the next agent in round robin. Blank when nobody is available.')
    public static List<Result> pickForRecords(List<Request> requests) {
        List<Id> recordIds = new List<Id>();
        for (Request request : requests) {
            recordIds.add(String.isBlank(request.recordId) ? null : Id.valueOf(request.recordId));
        }
        Map<Id, Id> personal = personalAgents(recordIds);
        Boolean website = !recordIds.isEmpty() && recordIds[0] != null
            && recordIds[0].getSObjectType() == Facebook_Inquiry__c.SObjectType;
        Picker picker = new Picker(website ? WEBSITE_QUEUE : MESSAGING_QUEUE, website ? WEBSITE_CHANNEL : MESSAGING_CHANNEL);
        List<Result> results = new List<Result>();
        for (Id recordId : recordIds) {
            results.add(picker.pick(personal.get(recordId)));
        }
        return results;
    }

    // ------------------------------------------------------------------ picking

    public class Picker {
        private Set<Id> pool;
        private Map<Id, Decimal> free;
        private Map<Id, Datetime> lastRouted = new Map<Id, Datetime>();

        public Picker(String queueName, String channelName) {
            pool = testPool != null ? testPool : queueMembers(queueName);
            free = testFreeCapacity != null ? testFreeCapacity.clone() : freeCapacity(pool, channelName);
            for (AggregateResult row : [
                SELECT UserId agent, MAX(CreatedDate) lastWork FROM AgentWork
                WHERE UserId IN :pool GROUP BY UserId
            ]) {
                lastRouted.put((Id) row.get('agent'), (Datetime) row.get('lastWork'));
            }
        }

        public Boolean inPool(Id agentId) {
            return agentId != null && pool.contains(agentId);
        }

        public Result pick(Id personalAgent) {
            Result result = new Result();
            Id chosen;
            if (hasRoom(personalAgent) && inPool(personalAgent)) {
                chosen = personalAgent;
                result.reason = 'Personal agent';
            } else {
                for (Id agentId : free.keySet()) {
                    if (hasRoom(agentId) && (chosen == null || routedEarlier(agentId, chosen))) {
                        chosen = agentId;
                    }
                }
                result.reason = chosen == null ? 'Nobody available - waiting in queue'
                    : personalAgent == null ? 'Round robin' : 'Round robin (personal agent offline or full)';
            }
            if (chosen != null) {
                free.put(chosen, free.get(chosen) - 1);
                lastRouted.put(chosen, Datetime.now());
                result.agentId = chosen;
            }
            return result;
        }

        private Boolean hasRoom(Id agentId) {
            return agentId != null && free.containsKey(agentId) && free.get(agentId) >= 1;
        }

        private Boolean routedEarlier(Id candidate, Id current) {
            Datetime a = lastRouted.get(candidate);
            Datetime b = lastRouted.get(current);
            if (a == b) {
                return String.valueOf(candidate) < String.valueOf(current);
            }
            return a == null || (b != null && a < b);
        }
    }

    private static Set<Id> queueMembers(String queueName) {
        Set<Id> members = new Set<Id>();
        for (GroupMember member : [
            SELECT UserOrGroupId FROM GroupMember
            WHERE Group.DeveloperName = :queueName AND Group.Type = 'Queue'
        ]) {
            if (member.UserOrGroupId.getSObjectType() == User.SObjectType) {
                members.add(member.UserOrGroupId);
            }
        }
        for (User inactive : [SELECT Id FROM User WHERE Id IN :members AND IsActive = false]) {
            members.remove(inactive.Id);
        }
        return members;
    }

    /** Online agents (status that includes the channel) mapped to the work they can still take. */
    private static Map<Id, Decimal> freeCapacity(Set<Id> pool, String channelName) {
        Set<Id> onlineStatuses = new Set<Id>();
        for (ServiceChannelStatus link : [
            SELECT ServicePresenceStatusId FROM ServiceChannelStatus WHERE ServiceChannel.DeveloperName = :channelName
        ]) {
            onlineStatuses.add(link.ServicePresenceStatusId);
        }
        Map<Id, Decimal> free = new Map<Id, Decimal>();
        for (UserServicePresence presence : [
            SELECT UserId, ConfiguredCapacity FROM UserServicePresence
            WHERE IsCurrentState = true AND UserId IN :pool AND ServicePresenceStatusId IN :onlineStatuses
        ]) {
            free.put(presence.UserId, presence.ConfiguredCapacity == null ? 0 : presence.ConfiguredCapacity);
        }
        if (free.isEmpty()) {
            return free;
        }
        for (AggregateResult row : [
            SELECT UserId agent, SUM(CapacityWeight) used FROM AgentWork
            WHERE UserId IN :free.keySet() AND Status IN :OPEN_WORK GROUP BY UserId
        ]) {
            Id agentId = (Id) row.get('agent');
            Decimal used = (Decimal) row.get('used');
            free.put(agentId, free.get(agentId) - (used == null ? 0 : used));
        }
        return free;
    }

    // ------------------------------------------------------------------ personal agents

    /** Record (messaging session or inquiry) -> its customer's personal agent, if any. */
    private static Map<Id, Id> personalAgents(List<Id> recordIds) {
        Map<Id, Id> result = new Map<Id, Id>();
        Set<Id> sessionIds = new Set<Id>();
        Set<Id> inquiryIds = new Set<Id>();
        for (Id recordId : recordIds) {
            if (recordId == null) {
                continue;
            }
            if (recordId.getSObjectType() == MessagingSession.SObjectType) {
                sessionIds.add(recordId);
            } else if (recordId.getSObjectType() == Facebook_Inquiry__c.SObjectType) {
                inquiryIds.add(recordId);
            }
        }
        if (!sessionIds.isEmpty()) {
            for (MessagingSession session : [
                SELECT Id, MessagingEndUser.Personal_Agent__c, MessagingEndUser.Contact.Personal_Agent__c
                FROM MessagingSession WHERE Id IN :sessionIds
            ]) {
                Id agent = session.MessagingEndUser?.Personal_Agent__c;
                result.put(session.Id, agent != null ? agent : session.MessagingEndUser?.Contact?.Personal_Agent__c);
            }
        }
        if (!inquiryIds.isEmpty()) {
            for (Facebook_Inquiry__c inquiry : [
                SELECT Id, Contact__r.Personal_Agent__c FROM Facebook_Inquiry__c WHERE Id IN :inquiryIds
            ]) {
                result.put(inquiry.Id, inquiry.Contact__r?.Personal_Agent__c);
            }
        }
        return result;
    }

    /**
     * When an agent accepts a conversation or lead, Omni-Channel makes them its owner. That agent
     * becomes the customer's personal agent (unless the customer already has one).
     */
    public static void onOwnerChange(List<SObject> records, Map<Id, SObject> oldMap) {
        Map<Id, Id> agentByItem = new Map<Id, Id>();
        for (SObject record : records) {
            Id owner = (Id) record.get('OwnerId');
            SObject old = oldMap == null ? null : oldMap.get(record.Id);
            if (owner != null && owner.getSObjectType() == User.SObjectType
                    && (old == null || (Id) old.get('OwnerId') != owner)) {
                agentByItem.put(record.Id, owner);
            }
        }
        if (!agentByItem.isEmpty()) {
            rememberPersonalAgents(agentByItem);
        }
    }

    /** Before update: a website lead taken from the queue (or handed over) records who is handling it. */
    public static void syncAssignedAgent(List<Facebook_Inquiry__c> records, Map<Id, Facebook_Inquiry__c> oldMap) {
        for (Facebook_Inquiry__c inquiry : records) {
            if (inquiry.Channel__c == 'Website' && inquiry.OwnerId != oldMap.get(inquiry.Id).OwnerId
                    && inquiry.OwnerId.getSObjectType() == User.SObjectType) {
                inquiry.Assigned_Agent__c = inquiry.OwnerId;
            }
        }
    }

    @TestVisible
    private static void rememberPersonalAgents(Map<Id, Id> agentByItem) {
        Set<Id> routable = new Set<Id>();
        routable.addAll(testPool != null ? testPool : queueMembers(MESSAGING_QUEUE));
        routable.addAll(testPool != null ? testPool : queueMembers(WEBSITE_QUEUE));

        Map<Id, MessagingEndUser> endUsers = new Map<Id, MessagingEndUser>();
        Map<Id, Contact> contacts = new Map<Id, Contact>();

        Set<Id> sessionIds = new Set<Id>();
        Set<Id> inquiryIds = new Set<Id>();
        for (Id itemId : agentByItem.keySet()) {
            if (itemId.getSObjectType() == MessagingSession.SObjectType) {
                sessionIds.add(itemId);
            } else if (itemId.getSObjectType() == Facebook_Inquiry__c.SObjectType) {
                inquiryIds.add(itemId);
            }
        }
        if (!sessionIds.isEmpty()) {
            for (MessagingSession session : [
                SELECT Id, MessagingEndUserId, MessagingEndUser.Personal_Agent__c,
                    MessagingEndUser.ContactId, MessagingEndUser.Contact.Personal_Agent__c
                FROM MessagingSession WHERE Id IN :sessionIds
            ]) {
                Id agent = agentByItem.get(session.Id);
                if (!routable.contains(agent)) {
                    continue;
                }
                if (session.MessagingEndUserId != null && session.MessagingEndUser.Personal_Agent__c == null) {
                    endUsers.put(session.MessagingEndUserId,
                        new MessagingEndUser(Id = session.MessagingEndUserId, Personal_Agent__c = agent));
                }
                if (session.MessagingEndUser?.ContactId != null && session.MessagingEndUser.Contact.Personal_Agent__c == null) {
                    contacts.put(session.MessagingEndUser.ContactId,
                        new Contact(Id = session.MessagingEndUser.ContactId, Personal_Agent__c = agent));
                }
            }
        }
        if (!inquiryIds.isEmpty()) {
            for (Facebook_Inquiry__c inquiry : [
                SELECT Id, Contact__c, Contact__r.Personal_Agent__c
                FROM Facebook_Inquiry__c WHERE Id IN :inquiryIds
            ]) {
                Id agent = agentByItem.get(inquiry.Id);
                if (routable.contains(agent) && inquiry.Contact__c != null && inquiry.Contact__r.Personal_Agent__c == null) {
                    contacts.put(inquiry.Contact__c, new Contact(Id = inquiry.Contact__c, Personal_Agent__c = agent));
                }
            }
        }
        // Partial success: a locked or deleted customer record must never block the agent's accept.
        Database.update(endUsers.values(), false);
        Database.update(contacts.values(), false);
    }

    // ------------------------------------------------------------------ website leads

    /** Before insert: website leads go to the personal agent or the next agent in turn, else the queue. */
    public static void assignWebsiteLeads(List<Facebook_Inquiry__c> records) {
        List<Facebook_Inquiry__c> leads = new List<Facebook_Inquiry__c>();
        Set<Id> contactIds = new Set<Id>();
        for (Facebook_Inquiry__c inquiry : records) {
            if (inquiry.Channel__c == 'Website' && inquiry.Assigned_Agent__c == null) {
                leads.add(inquiry);
                if (inquiry.Contact__c != null) {
                    contactIds.add(inquiry.Contact__c);
                }
            }
        }
        if (leads.isEmpty()) {
            return;
        }
        Map<Id, Contact> customers = new Map<Id, Contact>(
            [SELECT Id, Personal_Agent__c FROM Contact WHERE Id IN :contactIds]);
        List<Group> queues = [SELECT Id FROM Group WHERE DeveloperName = :WEBSITE_QUEUE AND Type = 'Queue' LIMIT 1];
        Picker picker = new Picker(WEBSITE_QUEUE, WEBSITE_CHANNEL);
        for (Facebook_Inquiry__c inquiry : leads) {
            Contact customer = customers.get(inquiry.Contact__c);
            Result result = picker.pick(customer == null ? null : customer.Personal_Agent__c);
            if (result.agentId != null) {
                inquiry.Assigned_Agent__c = result.agentId;
                inquiry.OwnerId = result.agentId;
            } else if (!queues.isEmpty()) {
                inquiry.OwnerId = queues[0].Id;
            }
        }
    }

    /** After insert: put agent-assigned website leads in that agent's Omni-Channel inbox. */
    public static void pushWebsiteLeads(List<Facebook_Inquiry__c> records) {
        Map<Id, Id> agentByLead = new Map<Id, Id>();
        for (Facebook_Inquiry__c inquiry : records) {
            if (inquiry.Channel__c == 'Website' && inquiry.Assigned_Agent__c != null
                    && String.valueOf(inquiry.OwnerId).startsWith('005')) {
                agentByLead.put(inquiry.Id, inquiry.Assigned_Agent__c);
            }
        }
        if (!agentByLead.isEmpty() && !Test.isRunningTest()) {
            System.enqueueJob(new PushToInbox(agentByLead));
        }
    }

    public class PushToInbox implements Queueable {
        private Map<Id, Id> agentByLead;
        public PushToInbox(Map<Id, Id> agentByLead) {
            this.agentByLead = agentByLead;
        }
        public void execute(QueueableContext context) {
            List<ServiceChannel> channels = [SELECT Id FROM ServiceChannel WHERE DeveloperName = :WEBSITE_CHANNEL LIMIT 1];
            if (channels.isEmpty()) {
                return;
            }
            List<AgentWork> work = new List<AgentWork>();
            for (Id leadId : agentByLead.keySet()) {
                work.add(new AgentWork(WorkItemId = leadId, UserId = agentByLead.get(leadId), ServiceChannelId = channels[0].Id));
            }
            // The agent may have gone offline since; the lead is still theirs and the follow-up job chases it.
            for (Database.SaveResult saved : Database.insert(work, false)) {
                if (!saved.isSuccess()) {
                    System.debug(LoggingLevel.WARN, 'Website lead not pushed to Omni-Channel: ' + saved.getErrors()[0].getMessage());
                }
            }
        }
    }
}
