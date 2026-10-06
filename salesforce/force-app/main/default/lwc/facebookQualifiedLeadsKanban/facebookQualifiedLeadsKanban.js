import { LightningElement, wire } from 'lwc';
import { NavigationMixin } from 'lightning/navigation';
import { encodeDefaultFieldValues } from 'lightning/pageReferenceUtils';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { refreshApex } from '@salesforce/apex';
import getLeads from '@salesforce/apex/FacebookLeadKanbanController.getLeads';
import updateLeadStage from '@salesforce/apex/FacebookLeadKanbanController.updateLeadStage';

const STAGES = [
    'New Message',
    'Contacted',
    'Needs Qualification',
    'Vehicle Selected',
    'Docs Requested',
    'Docs Submitted',
    'For Supervisor Review',
    'Converted to Application'
];
const STAGE_LABELS_KEY = 'autobotiqueLeadManagerStageLabels';

export default class FacebookQualifiedLeadsKanban extends NavigationMixin(LightningElement) {
    wiredResult;
    leads = [];
    error;
    isSaving = false;
    selectedLeadId;
    selectedLeadObjectApiName = 'Facebook_Inquiry__c';
    isLeadEditorOpen = false;
    isStageSettingsOpen = false;
    stageLabels = {};

    @wire(getLeads)
    wiredLeads(result) {
        this.wiredResult = result;
        if (result.data) {
            this.leads = result.data;
            this.error = undefined;
        } else if (result.error) {
            this.error = result.error.body ? result.error.body.message : result.error.message;
            this.leads = [];
        }
    }

    connectedCallback() {
        this.stageLabels = this.loadStageLabels();
    }

    get columns() {
        return STAGES.map((stage) => {
            const cards = this.leads
                .filter((lead) => lead.stage === stage)
                .map((lead) => ({
                    ...lead,
                    cardClass: `card priority-${(lead.priority || 'Warm').toLowerCase()}`,
                    followUpText: lead.followUpDate || 'No follow-up',
                    vehicleText: lead.vehicleName || 'No vehicle yet',
                    agentText: lead.assignedAgent || 'Unassigned',
                    sourceText: lead.sourceLabel || lead.channel || 'Lead',
                    clientBadge: lead.existingClient ? 'Existing' : 'New',
                    appBadge: lead.hasApplication ? 'App linked' : 'No app'
                }));
            return {
                stage,
                label: this.stageLabels[stage] || stage,
                count: cards.length,
                cards
            };
        });
    }

    get stageEditorRows() {
        return STAGES.map((stage) => ({
            value: stage,
            label: this.stageLabels[stage] || stage
        }));
    }

    get hasError() {
        return Boolean(this.error);
    }

    handleDragStart(event) {
        event.dataTransfer.setData('text/plain', event.currentTarget.dataset.id);
        event.dataTransfer.effectAllowed = 'move';
    }

    handleEditLead(event) {
        event.preventDefault();
        event.stopPropagation();
        const inquiryId = event.currentTarget.dataset.id;
        const objectApiName = event.currentTarget.dataset.objectApiName || 'Facebook_Inquiry__c';
        if (!inquiryId) {
            return;
        }

        this.selectedLeadId = inquiryId;
        this.selectedLeadObjectApiName = objectApiName;
        this.isLeadEditorOpen = true;
    }

    closeLeadEditor() {
        this.isLeadEditorOpen = false;
        this.selectedLeadId = undefined;
        this.selectedLeadObjectApiName = 'Facebook_Inquiry__c';
    }

    async handleLeadSaved() {
        this.closeLeadEditor();
        this.showToast('Lead updated', 'Lead Manager has been refreshed.', 'success');
        await refreshApex(this.wiredResult);
    }

    handleLeadSaveError(event) {
        this.showToast('Lead was not saved', event.detail?.message || 'Check required fields and try again.', 'error');
    }

    handleNewLead() {
        this[NavigationMixin.Navigate]({
            type: 'standard__objectPage',
            attributes: {
                objectApiName: 'Facebook_Inquiry__c',
                actionName: 'new'
            },
            state: {
                defaultFieldValues: encodeDefaultFieldValues({
                    Channel__c: 'Facebook Messenger',
                    Inquiry_Status__c: 'New',
                    Lead_Stage__c: 'New Message',
                    Lead_Priority__c: 'Warm',
                    Next_Action__c: 'Reply to Inquiry'
                })
            }
        });
    }

    handleNewOtherLead() {
        this[NavigationMixin.Navigate]({
            type: 'standard__objectPage',
            attributes: {
                objectApiName: 'Other_Inquiry__c',
                actionName: 'new'
            },
            state: {
                defaultFieldValues: encodeDefaultFieldValues({
                    Channel__c: 'Walk In',
                    Inquiry_Status__c: 'New',
                    Lead_Stage__c: 'New Message',
                    Lead_Priority__c: 'Warm',
                    Next_Action__c: 'Reply to Inquiry',
                    Payment_Intent__c: 'Undecided'
                })
            }
        });
    }

    handleDragOver(event) {
        event.preventDefault();
    }

    async handleDrop(event) {
        event.preventDefault();
        const inquiryId = event.dataTransfer.getData('text/plain');
        const stage = event.currentTarget.dataset.stage;
        const current = this.leads.find((lead) => lead.id === inquiryId);
        if (!inquiryId || !stage || current?.stage === stage) {
            return;
        }

        this.isSaving = true;
        this.error = undefined;
        try {
            await updateLeadStage({ inquiryId, stage });
            await refreshApex(this.wiredResult);
        } catch (error) {
            this.error = error.body ? error.body.message : error.message;
        } finally {
            this.isSaving = false;
        }
    }

    async handleRefresh() {
        this.isSaving = true;
        await refreshApex(this.wiredResult);
        this.isSaving = false;
    }

    openStageSettings() {
        this.isStageSettingsOpen = true;
    }

    closeStageSettings() {
        this.isStageSettingsOpen = false;
    }

    handleStageLabelChange(event) {
        this.stageLabels = {
            ...this.stageLabels,
            [event.currentTarget.dataset.stage]: event.detail.value
        };
    }

    saveStageLabels() {
        window.localStorage.setItem(STAGE_LABELS_KEY, JSON.stringify(this.stageLabels));
        this.closeStageSettings();
        this.showToast('Stage names updated', 'The Lead Manager column names were updated for this browser.', 'success');
    }

    resetStageLabels() {
        this.stageLabels = {};
        window.localStorage.removeItem(STAGE_LABELS_KEY);
        this.closeStageSettings();
        this.showToast('Stage names reset', 'The Lead Manager is using the Salesforce stage names again.', 'success');
    }

    loadStageLabels() {
        try {
            return JSON.parse(window.localStorage.getItem(STAGE_LABELS_KEY)) || {};
        } catch (error) {
            return {};
        }
    }

    showToast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }
}