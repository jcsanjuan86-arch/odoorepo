import { LightningElement, api, wire } from 'lwc';
import { NavigationMixin } from 'lightning/navigation';
import { getRecord, getFieldValue, getFieldDisplayValue } from 'lightning/uiRecordApi';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { refreshApex } from '@salesforce/apex';
import ensureFacebookInquiry from '@salesforce/apex/AutobotiqueMessagingActionsController.ensureFacebookInquiry';
import createLoanApplication from '@salesforce/apex/AutobotiqueMessagingActionsController.createLoanApplication';
import getAvailableCarsMessage from '@salesforce/apex/AutobotiqueMessagingActionsController.getAvailableCarsMessage';

import CASE_ID from '@salesforce/schema/MessagingSession.CaseId';
import CONTACT_ID from '@salesforce/schema/MessagingSession.EndUserContactId';
import LEAD_ID from '@salesforce/schema/MessagingSession.LeadId';
import OPPORTUNITY_ID from '@salesforce/schema/MessagingSession.OpportunityId';
import FACEBOOK_INQUIRY_ID from '@salesforce/schema/MessagingSession.Facebook_Inquiry__c';
import AUTO_LOAN_APPLICATION_ID from '@salesforce/schema/MessagingSession.Auto_Loan_Application__c';
import INQUIRY_CUSTOMER_NAME from '@salesforce/schema/Facebook_Inquiry__c.Customer_Name__c';
import INQUIRY_STATUS from '@salesforce/schema/Facebook_Inquiry__c.Inquiry_Status__c';
import INQUIRY_EXISTING_CLIENT from '@salesforce/schema/Facebook_Inquiry__c.Existing_Client__c';
import INQUIRY_PREVIOUS_AGENT from '@salesforce/schema/Facebook_Inquiry__c.Previous_Agent__c';
import INQUIRY_ASSIGNED_AGENT from '@salesforce/schema/Facebook_Inquiry__c.Assigned_Agent__c';
import INQUIRY_LEAD_STAGE from '@salesforce/schema/Facebook_Inquiry__c.Lead_Stage__c';
import INQUIRY_LEAD_PRIORITY from '@salesforce/schema/Facebook_Inquiry__c.Lead_Priority__c';
import INQUIRY_NEXT_ACTION from '@salesforce/schema/Facebook_Inquiry__c.Next_Action__c';
import INQUIRY_NEXT_FOLLOW_UP from '@salesforce/schema/Facebook_Inquiry__c.Next_Follow_Up_Date__c';
import INQUIRY_PAYMENT_INTENT from '@salesforce/schema/Facebook_Inquiry__c.Payment_Intent__c';
import INQUIRY_VEHICLE_INTERESTED from '@salesforce/schema/Facebook_Inquiry__c.Vehicle_Interested__c';
import INQUIRY_AUTO_LOAN_APPLICATION from '@salesforce/schema/Facebook_Inquiry__c.Auto_Loan_Application__c';
import APP_STATUS from '@salesforce/schema/Auto_Loan_Application__c.Status__c';
import APP_ASSIGNED_AGENT from '@salesforce/schema/Auto_Loan_Application__c.Assigned_Agent__c';
import APP_SELECTED_VEHICLE from '@salesforce/schema/Auto_Loan_Application__c.Selected_Vehicle__c';
import APP_PAYMENT_OPTION from '@salesforce/schema/Auto_Loan_Application__c.Payment_Option__c';
import APP_NEXT_FOLLOW_UP from '@salesforce/schema/Auto_Loan_Application__c.Next_Follow_Up_Date__c';

const FIELDS = [
    CASE_ID,
    CONTACT_ID,
    LEAD_ID,
    OPPORTUNITY_ID,
    FACEBOOK_INQUIRY_ID,
    AUTO_LOAN_APPLICATION_ID
];

const RECORD_CONFIG = [
    { label: 'Facebook Inquiry', field: FACEBOOK_INQUIRY_ID, objectApiName: 'Facebook_Inquiry__c', icon: 'standard:messaging_user' },
    { label: 'Loan Application', field: AUTO_LOAN_APPLICATION_ID, objectApiName: 'Auto_Loan_Application__c', icon: 'standard:record' },
    { label: 'Contact', field: CONTACT_ID, objectApiName: 'Contact', icon: 'standard:contact' },
    { label: 'Case', field: CASE_ID, objectApiName: 'Case', icon: 'standard:case' }
];

const INQUIRY_FIELDS = [
    INQUIRY_CUSTOMER_NAME,
    INQUIRY_STATUS,
    INQUIRY_EXISTING_CLIENT,
    INQUIRY_PREVIOUS_AGENT,
    INQUIRY_ASSIGNED_AGENT,
    INQUIRY_LEAD_STAGE,
    INQUIRY_LEAD_PRIORITY,
    INQUIRY_NEXT_ACTION,
    INQUIRY_NEXT_FOLLOW_UP,
    INQUIRY_PAYMENT_INTENT,
    INQUIRY_VEHICLE_INTERESTED,
    INQUIRY_AUTO_LOAN_APPLICATION
];

const APPLICATION_FIELDS = [
    APP_STATUS,
    APP_ASSIGNED_AGENT,
    APP_SELECTED_VEHICLE,
    APP_PAYMENT_OPTION,
    APP_NEXT_FOLLOW_UP
];

export default class AutobotiqueMessagingCrmPanel extends NavigationMixin(LightningElement) {
    @api recordId;
    isWorking = false;
    carMessage;

    @wire(getRecord, { recordId: '$recordId', fields: FIELDS })
    messagingSession;

    @wire(getRecord, { recordId: '$facebookInquiryId', fields: INQUIRY_FIELDS })
    facebookInquiry;

    @wire(getRecord, { recordId: '$loanApplicationId', fields: APPLICATION_FIELDS })
    loanApplication;

    get leadButtonLabel() {
        return this.facebookInquiryId ? 'Open Autobotique Lead' : 'Create Autobotique Lead';
    }

    get isInquiryConverted() {
        const inquiry = this.facebookInquiry.data;
        return (
            this.recordDisplay(inquiry, INQUIRY_STATUS) === 'Converted' &&
            this.recordDisplay(inquiry, INQUIRY_LEAD_STAGE) === 'Converted to Application'
        );
    }

    get showCreateApplication() {
        // One click from the lead: the server qualifies and converts it if needed.
        return Boolean(this.loanApplicationId || this.facebookInquiryId);
    }

    get applicationButtonLabel() {
        return this.loanApplicationId ? 'Go To Application' : 'Start Application';
    }

    get applicationButtonIcon() {
        return this.loanApplicationId ? 'utility:forward' : 'utility:record_create';
    }

    get facebookInquiryId() {
        return this.sessionField(FACEBOOK_INQUIRY_ID);
    }

    get sessionLoanApplicationId() {
        return this.sessionField(AUTO_LOAN_APPLICATION_ID);
    }

    get inquiryLoanApplicationId() {
        const data = this.facebookInquiry.data;
        return data ? this.recordField(data, INQUIRY_AUTO_LOAN_APPLICATION) : null;
    }

    get loanApplicationId() {
        return this.sessionLoanApplicationId || this.inquiryLoanApplicationId;
    }

    get contactId() {
        return this.sessionField(CONTACT_ID);
    }

    get recordLinks() {
        const data = this.messagingSession.data;
        if (!data) {
            return [];
        }

        return RECORD_CONFIG.map((item) => {
            const id = getFieldValue(data, item.field);
            return id
                ? {
                      ...item,
                      status: 'Linked',
                      url: `/lightning/r/${item.objectApiName}/${id}/view`
                  }
                : null;
        }).filter(Boolean);
    }

    get customerRows() {
        const inquiry = this.facebookInquiry.data;
        const app = this.loanApplication.data;
        return [
            { label: 'Customer', value: this.recordDisplay(inquiry, INQUIRY_CUSTOMER_NAME) || 'Not linked' },
            { label: 'Existing Client', value: this.recordField(inquiry, INQUIRY_EXISTING_CLIENT) ? 'Yes' : 'No' },
            { label: 'Previous Agent', value: this.recordDisplay(inquiry, INQUIRY_PREVIOUS_AGENT) || 'None' },
            { label: 'Assigned Agent', value: this.recordDisplay(inquiry, INQUIRY_ASSIGNED_AGENT) || this.recordDisplay(app, APP_ASSIGNED_AGENT) || 'Unassigned' },
            { label: 'Last Application', value: this.loanApplicationId ? 'Linked' : 'None' }
        ];
    }

    get leadRows() {
        const inquiry = this.facebookInquiry.data;
        return [
            { label: 'Lead Stage', value: this.recordDisplay(inquiry, INQUIRY_LEAD_STAGE) || 'New Message' },
            { label: 'Priority', value: this.recordDisplay(inquiry, INQUIRY_LEAD_PRIORITY) || 'Warm' },
            { label: 'Next Action', value: this.recordDisplay(inquiry, INQUIRY_NEXT_ACTION) || 'Reply to Inquiry' },
            { label: 'Follow Up', value: this.recordDisplay(inquiry, INQUIRY_NEXT_FOLLOW_UP) || 'Not set' },
            { label: 'Payment', value: this.recordDisplay(inquiry, INQUIRY_PAYMENT_INTENT) || this.recordDisplay(this.loanApplication.data, APP_PAYMENT_OPTION) || 'Undecided' },
            { label: 'Vehicle', value: this.recordDisplay(inquiry, INQUIRY_VEHICLE_INTERESTED) || this.recordDisplay(this.loanApplication.data, APP_SELECTED_VEHICLE) || 'Not selected' },
            { label: 'Application Status', value: this.recordDisplay(this.loanApplication.data, APP_STATUS) || 'No application yet' }
        ];
    }

    async handleCreateInquiry() {
        if (this.facebookInquiryId) {
            this.openUrl(`/lightning/r/Facebook_Inquiry__c/${this.facebookInquiryId}/view`);
            return;
        }
        await this.runAction(
            () => ensureFacebookInquiry({ messagingSessionId: this.recordId }),
            true
        );
    }

    async handleCreateApplication() {
        if (this.loanApplicationId) {
            this.openUrl(`/lightning/r/Auto_Loan_Application__c/${this.loanApplicationId}/view`);
            return;
        }
        await this.runAction(
            () => createLoanApplication({ messagingSessionId: this.recordId }),
            true
        );
    }

    openLeadManager() {
        this.openUrl('/lightning/n/Facebook_Leads_Kanban');
    }

    openInventory() {
        this.openUrl('/lightning/o/Vehicle_Inventory__c/list?filterName=Available_Vehicles');
    }

    async handleCopyCars() {
        this.isWorking = true;
        try {
            const message = await getAvailableCarsMessage({ maxCars: 25 });
            this.carMessage = message;
            await this.copyToClipboard(message);
            this.showToast('Cars copied', 'Paste the available-car list into the chat reply box.', 'success');
        } catch (error) {
            this.showToast('Cannot copy cars', this.errorMessage(error), 'error');
        } finally {
            this.isWorking = false;
        }
    }

    async runAction(action, openRecord) {
        this.isWorking = true;
        try {
            const result = await action();
            await refreshApex(this.messagingSession);
            await refreshApex(this.facebookInquiry);
            await refreshApex(this.loanApplication);
            this.showToast('Done', result.message, 'success');
            if (openRecord && result.recordUrl) {
                this.openUrl(result.recordUrl);
            }
        } catch (error) {
            this.showToast('Cannot complete action', this.errorMessage(error), 'error');
        } finally {
            this.isWorking = false;
        }
    }

    // Records open as console tabs (same window); other pages keep using a URL.
    openUrl(url) {
        const match = /\/lightning\/r\/(\w+)\/(\w+)\/view/.exec(url || '');
        if (match) {
            this[NavigationMixin.Navigate]({
                type: 'standard__recordPage',
                attributes: { recordId: match[2], objectApiName: match[1], actionName: 'view' }
            });
            return;
        }
        this[NavigationMixin.Navigate]({ type: 'standard__webPage', attributes: { url } });
    }

    async copyToClipboard(text) {
        if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return;
        }
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        this.template.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        this.template.removeChild(textarea);
    }

    sessionField(field) {
        const data = this.messagingSession.data;
        return data ? getFieldValue(data, field) : null;
    }

    recordField(record, field) {
        return record ? getFieldValue(record, field) : null;
    }

    recordDisplay(record, field) {
        return record ? getFieldDisplayValue(record, field) || getFieldValue(record, field) : null;
    }

    showToast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }

    errorMessage(error) {
        return error?.body?.message || error?.message || 'Unexpected Salesforce error.';
    }
}