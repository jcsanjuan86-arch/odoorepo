trigger AutobotiqueMessagingSession on MessagingSession (after update) {
    AutobotiqueRouter.onOwnerChange(Trigger.new, Trigger.oldMap);
}
