import { LightningElement, wire } from 'lwc';
import { NavigationMixin } from 'lightning/navigation';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { refreshApex } from '@salesforce/apex';
import getFinalApplications from '@salesforce/apex/FinalApplicationReviewController.getFinalApplications';
import getReviewDetail from '@salesforce/apex/FinalApplicationReviewController.getReviewDetail';
import startFinalReview from '@salesforce/apex/FinalApplicationReviewController.startFinalReview';
import markDocument from '@salesforce/apex/FinalApplicationReviewController.markDocument';
import returnToAgent from '@salesforce/apex/FinalApplicationReviewController.returnToAgent';
import completeFinalReview from '@salesforce/apex/FinalApplicationReviewController.completeFinalReview';

export default class FinalApplicationReview extends NavigationMixin(LightningElement) {
    applicationsWire;
    detailWire;
    applications = [];
    selectedApplicationId;
    selectedDetail;
    reviewNotes = '';
    isWorking = false;

    @wire(getFinalApplications)
    wiredApplications(value) {
        this.applicationsWire = value;
        if (value.data) {
            if (!this.selectedApplicationId && this.applications.length > 0) {
                this.selectedApplicationId = this.applications[0].id;
            }
            if (!this.selectedApplicationId && value.data.length > 0) {
                this.selectedApplicationId = value.data[0].id;
            }
            this.applications = value.data.map((application) => ({
                ...application,
                className: application.id === this.selectedApplicationId ? 'queue-item selected' : 'queue-item'
            }));
        }
    }

    @wire(getReviewDetail, { applicationId: '$selectedApplicationId' })
    wiredDetail(value) {
        this.detailWire = value;
        if (value.data) {
            this.selectedDetail = value.data;
            this.reviewNotes = value.data.notes || '';
        }
    }

    get hasApplications() {
        return this.applications.length > 0;
    }

    selectApplication(event) {
        this.selectedApplicationId = event.currentTarget.dataset.id;
        this.selectedDetail = undefined;
        this.applications = this.applications.map((application) => ({
            ...application,
            className: application.id === this.selectedApplicationId ? 'queue-item selected' : 'queue-item'
        }));
    }

    handleNotesChange(event) {
        this.reviewNotes = event.target.value;
    }

    async handleStartReview() {
        await this.runAction(
            () => startFinalReview({ applicationId: this.selectedApplicationId }),
            'Final review started.'
        );
    }

    async markDocumentDone(event) {
        await this.updateDocument(event.currentTarget.dataset.id, 'Done');
    }

    async markDocumentNeedsCorrection(event) {
        await this.updateDocument(event.currentTarget.dataset.id, 'Needs Correction');
    }

    async updateDocument(documentId, finalCheckStatus) {
        await this.runAction(
            () => markDocument({ documentId, finalCheckStatus, notes: this.reviewNotes }),
            finalCheckStatus === 'Done' ? 'Requirement marked done.' : 'Requirement marked for correction.'
        );
    }

    async handleReturn() {
        await this.runAction(
            () => returnToAgent({ applicationId: this.selectedApplicationId, notes: this.reviewNotes }),
            'Application returned to the assigned agent.'
        );
    }

    async handleComplete() {
        await this.runAction(
            () => completeFinalReview({ applicationId: this.selectedApplicationId, notes: this.reviewNotes }),
            'Final review completed.'
        );
    }

    async refreshAll() {
        await Promise.all([
            this.applicationsWire ? refreshApex(this.applicationsWire) : Promise.resolve(),
            this.detailWire ? refreshApex(this.detailWire) : Promise.resolve()
        ]);
    }

    openRecord() {
        if (!this.selectedDetail?.application?.recordUrl) {
            return;
        }
        this[NavigationMixin.Navigate]({
            type: 'standard__webPage',
            attributes: {
                url: this.selectedDetail.application.recordUrl
            }
        });
    }

    async runAction(action, successMessage) {
        this.isWorking = true;
        try {
            await action();
            this.showToast('Success', successMessage, 'success');
            await this.refreshAll();
        } catch (error) {
            this.showToast('Review action failed', this.errorMessage(error), 'error');
        } finally {
            this.isWorking = false;
        }
    }

    showToast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }

    errorMessage(error) {
        return error?.body?.message || error?.message || 'Unexpected Salesforce error.';
    }
}