import { LightningElement, api } from 'lwc';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import getQueue from '@salesforce/apex/ApplicationRequirementsController.getQueue';
import getChecklist from '@salesforce/apex/ApplicationRequirementsController.getChecklist';
import attachUploadedFile from '@salesforce/apex/ApplicationRequirementsController.attachUploadedFile';
import createUploadRequestFromApplication from '@salesforce/apex/AutobotiqueMessagingActionsController.createUploadRequestFromApplication';

const ACCEPTED_FORMATS = ['.pdf', '.jpg', '.jpeg', '.png', '.heic', '.doc', '.docx'];

const BADGES = {
    Missing: 'slds-badge',
    Uploaded: 'slds-badge slds-theme_info',
    Checked: 'slds-badge slds-theme_success',
    'Needs Correction': 'slds-badge slds-theme_error'
};

/**
 * Requirements checklist. On the Requirements tab it lists the agent's
 * applications on the left; on a Loan Application page (recordId set) it shows
 * that application's checklist only.
 */
export default class ApplicationRequirements extends LightningElement {
    @api recordId;
    acceptedFormats = ACCEPTED_FORMATS;
    mineOnly = true;
    queue = [];
    selectedId;
    checklist;
    isLoading = false;
    customerLink;

    connectedCallback() {
        if (this.recordId) {
            this.selectedId = this.recordId;
            this.loadChecklist();
        } else {
            this.loadQueue();
        }
    }

    get isRecordPage() {
        return Boolean(this.recordId);
    }

    get isAppPage() {
        return !this.recordId;
    }

    get queueItems() {
        return this.queue.map((row) => ({
            ...row,
            cssClass: 'queue-item slds-p-around_small' + (row.id === this.selectedId ? ' selected' : ''),
            progress: `${row.uploaded}/${row.required} uploaded`,
            flag: row.needsCorrection ? `${row.needsCorrection} to fix` : row.returned ? 'Returned' : ''
        }));
    }

    get hasQueue() {
        return this.queue.length > 0;
    }

    get scopeLabel() {
        return this.mineOnly ? 'Show all applications' : 'Show my applications';
    }

    get requirements() {
        return (this.checklist?.requirements || []).map((row) => ({
            ...row,
            badgeClass: BADGES[row.label] || 'slds-badge',
            needsFix: row.label === 'Needs Correction',
            canUpload: row.label !== 'Checked',
            uploadLabel: row.fileUrl ? 'Replace file' : 'Upload'
        }));
    }

    get application() {
        return this.checklist?.application;
    }

    get progressValue() {
        const app = this.application;
        return app && app.required ? Math.round((app.uploaded / app.required) * 100) : 0;
    }

    get progressText() {
        const app = this.application;
        return app ? `${app.uploaded} of ${app.required} required documents uploaded` : '';
    }

    get statusHint() {
        const status = this.application?.status;
        if (status === 'Final Review') {
            return 'With the final checker. Documents marked Needs Correction come back here automatically.';
        }
        if (status === 'Returned to Agent') {
            return 'Returned by the final checker. Upload the corrected documents; the application goes back to Final Review automatically.';
        }
        return 'Upload every required document. When all are uploaded the application goes to Final Review automatically.';
    }

    async loadQueue() {
        this.isLoading = true;
        try {
            this.queue = await getQueue({ mineOnly: this.mineOnly });
            if (!this.selectedId && this.queue.length) {
                this.selectedId = this.queue[0].id;
            }
            if (this.selectedId) {
                await this.loadChecklist();
            } else {
                this.checklist = undefined;
            }
        } catch (error) {
            this.toast('Could not load applications', this.message(error), 'error');
        } finally {
            this.isLoading = false;
        }
    }

    async loadChecklist() {
        if (!this.selectedId) {
            return;
        }
        try {
            this.checklist = await getChecklist({ applicationId: this.selectedId });
        } catch (error) {
            this.toast('Could not load requirements', this.message(error), 'error');
        }
    }

    handleSelect(event) {
        this.selectedId = event.currentTarget.dataset.id;
        this.customerLink = undefined;
        this.loadChecklist();
    }

    handleScope() {
        this.mineOnly = !this.mineOnly;
        this.selectedId = undefined;
        this.loadQueue();
    }

    handleRefresh() {
        if (this.isRecordPage) {
            this.loadChecklist();
        } else {
            this.loadQueue();
        }
    }

    async handleUploadFinished(event) {
        const documentId = event.target.dataset.id;
        const files = event.detail.files || [];
        if (!files.length) {
            return;
        }
        try {
            await attachUploadedFile({ documentId, contentDocumentId: files[files.length - 1].documentId });
            this.toast('Uploaded', `${files[files.length - 1].name} saved to the requirement.`, 'success');
            this.handleRefresh();
        } catch (error) {
            this.toast('Upload saved, but the checklist was not updated', this.message(error), 'error');
        }
    }

    async handleCustomerLink() {
        try {
            const result = await createUploadRequestFromApplication({ applicationId: this.selectedId });
            this.customerLink = result.publicUrl;
            if (result.publicUploadReady && this.customerLink && navigator?.clipboard?.writeText) {
                await navigator.clipboard.writeText(this.customerLink);
                this.toast('Customer link copied', 'Paste it into the customer conversation.', 'success');
            } else {
                this.toast('Upload request created', result.message, result.publicUploadReady ? 'success' : 'warning');
            }
        } catch (error) {
            this.toast('Could not create the customer link', this.message(error), 'error');
        }
    }

    toast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }

    message(error) {
        return error?.body?.message || error?.message || 'Unexpected Salesforce error.';
    }
}
