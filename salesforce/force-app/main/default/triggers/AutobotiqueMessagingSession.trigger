trigger AutobotiqueMessagingSession on MessagingSession (after update) {
    AutobotiqueRouter.onOwnerChange(Trigger.new, Trigger.oldMap);
    AutobotiqueMessagingActionsController.onSessionsAccepted(Trigger.new, Trigger.oldMap);
}
