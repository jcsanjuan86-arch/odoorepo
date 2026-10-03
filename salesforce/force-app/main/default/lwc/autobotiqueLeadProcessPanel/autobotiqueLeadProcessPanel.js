import { LightningElement, api, wire } from 'lwc';
import { NavigationMixin } from 'lightning/navigation';
import { getFieldValue, getRecord, notifyRecordUpdateAvailable } from 'lightning/uiRecordApi';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { refreshApex } from '@salesforce/apex';
import qualifyLead from '@salesforce/apex/AutobotiqueMessagingActionsController.qualifyLead';
import startApplication from '@salesforce/apex/AutobotiqueMessagingActionsController.startApplication';
import createUploadRequest from '@salesforce/apex/AutobotiqueMessagingActionsController.createUploadRequest';

import QUALIFIED from '@salesforce/schema/Facebook_Inquiry__c.Qualified_Lead__c';
import APPLICATION from '@salesforce/schema/Facebook_Inquiry__c.Auto_Loan_Application__c';
import CONTACT from '@salesforce/schema/Facebook_Inquiry__c.Contact__c';
import VEHICLE from '@salesforce/schema/Facebook_Inquiry__c.Vehicle_Interested__c';
import LEAD_STAGE from '@salesforce/schema/Facebook_Inquiry__c.Lead_Stage__c';

const FIELDS = [QUALIFIED, APPLICATION, CONTACT, VEHICLE, LEAD_STAGE];
const DOC_STAGES = ['Docs Submitted', 'For Supervisor Review', 'Converted to Application'];

export default class AutobotiqueLeadProcessPanel extends NavigationMixin(LightningElement) {
    @api recordId;
    wiredRecord;
    isWorking = false;
    uploadUrl;

    @wire(getRecord, { recordId: '$recordId', fields: FIELDS })
    wiredInquiry(result) {
        this.wiredRecord = result;
    }

    field(name) {
        return getFieldValue(this.wiredRecord?.data, name);
    }

    get isQualified() {
        return Boolean(this.field(QUALIFIED));
    }

    get applicationId() {
        return this.field(APPLICATION);
    }

    get hasApplication() {
        return Boolean(this.applicationId);
    }

    get hasContact() {
        return Boolean(this.field(CONTACT));
    }

    get hasVehicle() {
        return Boolean(this.field(VEHICLE));
    }

    get canStart() {
        return this.hasContact && this.hasVehicle;
    }

    get missingHint() {
        const missing = [];
        if (!this.hasContact) {
            missing.push('link the customer Contact');
        }
        if (!this.hasVehicle) {
            missing.push('choose the Vehicle Interested');
        }
        return missing.length ? `To start the application, ${missing.join(' and ')}.` : '';
    }

    get showQualify() {
        return !this.isQualified && !this.hasApplication;
    }

    get startDisabled() {
        return this.isWorking || (!this.hasApplication && !this.canStart);
    }

    get applicationButtonLabel() {
        return this.hasApplication ? 'Go To Application' : 'Start Application';
    }

    get applicationButtonIcon() {
        return this.hasApplication ? 'utility:forward' : 'utility:record_create';
    }

    get conversationClass() {
        return this.stepClass(this.hasContact && this.hasVehicle);
    }

    get leadClass() {
        return this.stepClass(this.isQualified || this.hasApplication);
    }

    get applicationClass() {
        return this.stepClass(this.hasApplication);
    }

    get uploadClass() {
        return this.stepClass(DOC_STAGES.includes(this.field(LEAD_STAGE)) || Boolean(this.uploadUrl));
    }

    async handleQualify() {
        await this.runAction(() => qualifyLead({ inquiryId: this.recordId }));
    }

    async handleApplication() {
        if (this.hasApplication) {
            this.openRecord(this.applicationId);
            return;
        }
        const result = await this.runAction(() => startApplication({ inquiryId: this.recordId }));
        if (result?.recordId) {
            this.openRecord(result.recordId);
        }
    }

    async handleCreateUpload() {
        const result = await this.runAction(() => createUploadRequest({ inquiryId: this.recordId }));
        if (result?.publicUrl) {
            this.uploadUrl = result.publicUrl;
            if (!result.publicUploadReady) {
                this.showToast('Public upload site not configured', 'The upload request was created, but this link is internal only. Configure the Autobotique upload site URL before sending it to customers.', 'warning');
            }
        }
    }

    openRecord(recordId) {
        this[NavigationMixin.Navigate]({
            type: 'standard__recordPage',
            attributes: { recordId, objectApiName: 'Auto_Loan_Application__c', actionName: 'view' }
        });
    }

    async runAction(action) {
        this.isWorking = true;
        try {
            const result = await action();
            await refreshApex(this.wiredRecord);
            await notifyRecordUpdateAvailable([{ recordId: this.recordId }]);
            this.showToast('Done', result.message, 'success');
            return result;
        } catch (error) {
            this.showToast('Action blocked', error?.body?.message || error?.message || 'Unexpected Salesforce error.', 'error');
            return null;
        } finally {
            this.isWorking = false;
        }
    }

    stepClass(done) {
        return done ? 'step done' : 'step';
    }

    showToast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }
}
