@IsTest
private class AutobotiqueRouterTest {

    private static List<User> agents() {
        List<User> users = new List<User>();
        Id profileId = UserInfo.getProfileId();
        for (String name : new List<String>{ 'Ana', 'Ben' }) {
            String login = 'router.' + name.toLowerCase() + '.' + String.valueOf(Crypto.getRandomInteger()).remove('-') + '@example.com';
            users.add(new User(
                FirstName = name, LastName = 'Agent', Alias = name.toLowerCase() + 'agt', Email = login, Username = login,
                ProfileId = profileId, TimeZoneSidKey = 'Asia/Manila', LocaleSidKey = 'en_US',
                EmailEncodingKey = 'UTF-8', LanguageLocaleKey = 'en_US'
            ));
        }
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert users;
        }
        AutobotiqueRouter.testPool = new Set<Id>{ users[0].Id, users[1].Id };
        return users;
    }

    private static void online(Map<Id, Decimal> freeCapacity) {
        AutobotiqueRouter.testFreeCapacity = freeCapacity;
    }

    private static Facebook_Inquiry__c websiteLead(Id contactId) {
        Facebook_Inquiry__c lead = new Facebook_Inquiry__c(
            Customer_Name__c = 'Web Buyer', Channel__c = 'Website', Contact__c = contactId,
            Facebook_User_ID__c = 'website-' + String.valueOf(Crypto.getRandomInteger()),
            Inquiry_Status__c = 'New', Lead_Stage__c = 'New Message'
        );
        insert lead;
        return [SELECT Id, Assigned_Agent__c, OwnerId FROM Facebook_Inquiry__c WHERE Id = :lead.Id];
    }

    private static Contact customer(Id personalAgent) {
        Contact person = new Contact(FirstName = 'Repeat', LastName = 'Buyer', Personal_Agent__c = personalAgent);
        insert person;
        return person;
    }

    @IsTest
    static void roundRobinGivesEveryAgentATurn() {
        List<User> team = agents();
        online(new Map<Id, Decimal>{ team[0].Id => 5, team[1].Id => 5 });

        AutobotiqueRouter.Picker picker = new AutobotiqueRouter.Picker('Website_Leads', 'Website_Leads');
        AutobotiqueRouter.Result first = picker.pick(null);
        AutobotiqueRouter.Result second = picker.pick(null);

        System.assertNotEquals(null, first.agentId);
        System.assertNotEquals(first.agentId, second.agentId, 'The next lead goes to the other agent.');
        System.assertEquals('Round robin', first.reason);
    }

    @IsTest
    static void returningCustomerGoesToTheirPersonalAgent() {
        List<User> team = agents();
        online(new Map<Id, Decimal>{ team[0].Id => 5, team[1].Id => 5 });
        Contact repeat = customer(team[1].Id);

        Facebook_Inquiry__c lead = websiteLead(repeat.Id);
        Facebook_Inquiry__c again = websiteLead(repeat.Id);

        System.assertEquals(team[1].Id, lead.Assigned_Agent__c, 'The personal agent gets the customer.');
        System.assertEquals(team[1].Id, lead.OwnerId);
        System.assertEquals(team[1].Id, again.Assigned_Agent__c, 'Every time the customer comes back.');
    }

    @IsTest
    static void offlineOrFullPersonalAgentFallsBackToRoundRobin() {
        List<User> team = agents();
        online(new Map<Id, Decimal>{ team[0].Id => 5 });
        Contact repeat = customer(team[1].Id);
        System.assertEquals(team[0].Id, websiteLead(repeat.Id).Assigned_Agent__c, 'Offline personal agent: next agent.');

        online(new Map<Id, Decimal>{ team[0].Id => 3, team[1].Id => 0 });
        AutobotiqueRouter.Result full = new AutobotiqueRouter.Picker('Website_Leads', 'Website_Leads').pick(team[1].Id);
        System.assertEquals(team[0].Id, full.agentId, 'An agent at capacity is skipped.');
        System.assert(full.reason.contains('personal agent offline or full'), full.reason);
    }

    @IsTest
    static void nobodyOnlineLeavesTheLeadInTheQueue() {
        agents();
        online(new Map<Id, Decimal>());
        Facebook_Inquiry__c lead = websiteLead(null);
        System.assertEquals(null, lead.Assigned_Agent__c, 'Nobody is assigned while everyone is offline.');
        List<Group> queues = [SELECT Id FROM Group WHERE DeveloperName = 'Website_Leads' AND Type = 'Queue'];
        if (!queues.isEmpty()) {
            System.assertEquals(queues[0].Id, lead.OwnerId, 'The lead waits in the Website Leads queue.');
        }
    }

    @IsTest
    static void omniFlowActionPicksAnAgent() {
        List<User> team = agents();
        online(new Map<Id, Decimal>());
        Contact repeat = customer(team[0].Id);
        Facebook_Inquiry__c lead = websiteLead(repeat.Id);

        online(new Map<Id, Decimal>{ team[0].Id => 5, team[1].Id => 5 });
        AutobotiqueRouter.Request request = new AutobotiqueRouter.Request();
        request.recordId = lead.Id;
        List<AutobotiqueRouter.Result> results = AutobotiqueRouter.pickForRecords(new List<AutobotiqueRouter.Request>{ request });

        System.assertEquals(team[0].Id, results[0].agentId);
        System.assertEquals('Personal agent', results[0].reason);
    }

    @IsTest
    static void acceptingMakesYouThePersonalAgent() {
        List<User> team = agents();
        online(new Map<Id, Decimal>());
        Contact firstTime = customer(null);
        Facebook_Inquiry__c lead = websiteLead(firstTime.Id);

        Test.startTest();
        update new Facebook_Inquiry__c(Id = lead.Id, OwnerId = team[1].Id); // what Omni-Channel does on accept
        new AutobotiqueRouter.PushToInbox(new Map<Id, Id>{ lead.Id => team[1].Id }).execute(null);
        Test.stopTest();

        System.assertEquals(team[1].Id, [SELECT Personal_Agent__c FROM Contact WHERE Id = :firstTime.Id].Personal_Agent__c,
            'The first agent to accept becomes the personal agent.');
        System.assertEquals(team[1].Id, [SELECT Assigned_Agent__c FROM Facebook_Inquiry__c WHERE Id = :lead.Id].Assigned_Agent__c);
    }

    @IsTest
    static void messengerCustomersComeBackToTheirAgent() {
        List<User> team = agents();
        List<MessagingChannel> pages = [SELECT Id FROM MessagingChannel WHERE MessageType = 'Facebook' LIMIT 1];
        if (pages.isEmpty()) {
            return; // No Facebook page in this org.
        }
        MessagingEndUser person = new MessagingEndUser(Name = 'Messenger Buyer', MessagingChannelId = pages[0].Id,
            MessageType = 'Facebook', MessagingPlatformKey = 'router-test-' + String.valueOf(Crypto.getRandomInteger()));
        insert person;
        MessagingSession first = new MessagingSession(MessagingEndUserId = person.Id, MessagingChannelId = pages[0].Id, Status = 'Ended');
        insert first;

        Test.startTest();
        update new MessagingSession(Id = first.Id, OwnerId = team[1].Id); // agent accepts the first chat
        Test.stopTest();
        System.assertEquals(team[1].Id, [SELECT Personal_Agent__c FROM MessagingEndUser WHERE Id = :person.Id].Personal_Agent__c);

        // Accepting the chat creates the customer inquiry; the agent does not click anything.
        Id inquiryId = [SELECT Facebook_Inquiry__c FROM MessagingSession WHERE Id = :first.Id].Facebook_Inquiry__c;
        System.assertNotEquals(null, inquiryId, 'The accepted chat is linked to a new customer inquiry.');
        Facebook_Inquiry__c inquiry = [SELECT OwnerId, Assigned_Agent__c, Customer_Name__c FROM Facebook_Inquiry__c WHERE Id = :inquiryId];
        System.assertEquals(team[1].Id, inquiry.Assigned_Agent__c);
        System.assertEquals(team[1].Id, inquiry.OwnerId);
        System.assertEquals('Messenger Buyer', inquiry.Customer_Name__c);

        // The customer comes back while the personal agent is offline (Messenger reuses the session record,
        // unlinked here): another agent takes the chat and the same open inquiry, not a duplicate.
        update new MessagingSession(Id = first.Id, Facebook_Inquiry__c = null, OwnerId = team[0].Id);
        System.assertEquals(inquiryId, [SELECT Facebook_Inquiry__c FROM MessagingSession WHERE Id = :first.Id].Facebook_Inquiry__c,
            'A returning customer keeps one open inquiry.');
        System.assertEquals(1, [SELECT COUNT() FROM Facebook_Inquiry__c WHERE Facebook_User_ID__c = :person.Id]);
        inquiry = [SELECT Assigned_Agent__c, Previous_Agent__c FROM Facebook_Inquiry__c WHERE Id = :inquiryId];
        System.assertEquals(team[0].Id, inquiry.Assigned_Agent__c);
        System.assertEquals(team[1].Id, inquiry.Previous_Agent__c);

        // The customer messages again: routing looks the personal agent up through the Messaging User.
        online(new Map<Id, Decimal>{ team[0].Id => 5, team[1].Id => 5 });
        AutobotiqueRouter.Request request = new AutobotiqueRouter.Request();
        request.recordId = first.Id;
        AutobotiqueRouter.Result result = AutobotiqueRouter.pickForRecords(new List<AutobotiqueRouter.Request>{ request })[0];
        System.assertEquals(team[1].Id, result.agentId, 'The returning Messenger customer goes to their personal agent.');
    }

    @IsTest
    static void newFacebookPagesAreFlaggedUntilRouted() {
        List<String> pages = AutobotiqueFollowUpJob.unroutedPages();
        System.assertNotEquals(null, pages);
        AutobotiqueFollowUpJob.alertUnroutedPages(new List<String>{ 'New Test Page' });
    }
}
