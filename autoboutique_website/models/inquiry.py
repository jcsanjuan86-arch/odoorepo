from odoo import api, fields, models

from odoo.addons.autoboutique_ops.models.automation import schedule_todo


class WebsiteInquiry(models.Model):
    _name = "autoboutique.website.inquiry"
    _description = "Website Vehicle Inquiry"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char("Full Name", required=True, tracking=True)
    phone = fields.Char("Mobile / Phone")
    email = fields.Char()
    message = fields.Text()
    source = fields.Selection([
        ("contact", "Contact Page"), ("vehicle", "Vehicle Page"), ("lead", "Vehicle Inquiry Form"),
        ("calculator", "Payment Calculator"),
    ], default="contact", required=True)
    vehicle_id = fields.Many2one("autoboutique.vehicle", string="Vehicle")
    vehicle_interest = fields.Char("Vehicle Interest")
    body_type = fields.Selection([
        ("sedan", "Sedan"), ("suv", "SUV"), ("pickup", "Pickup"), ("mpv", "MPV"), ("van", "Van"), ("others", "Others"),
    ])
    payment_option = fields.Selection([("cash", "Cash"), ("financing", "Financing")])
    employment_status = fields.Selection([
        ("employed", "Employed"), ("self_employed", "Self-Employed"), ("business_owner", "Business Owner"),
        ("ofw", "OFW"), ("freelancer", "Freelancer"), ("others", "Others"),
    ])
    monthly_income = fields.Selection([
        ("20_30", "₱20,000 – ₱30,000"), ("30_50", "₱30,001 – ₱50,000"), ("50_80", "₱50,001 – ₱80,000"),
        ("80_100", "₱80,001 – ₱100,000"), ("100_plus", "Above ₱100,000"),
    ])
    assistance = fields.Selection([
        ("quotation", "Request a Quotation"), ("visit", "Schedule a Showroom Visit"),
        ("test_drive", "Book a Test Drive"), ("financing", "Financing Assistance"),
    ], string="How can we assist you?")
    downpayment_percent = fields.Integer("Downpayment %")
    term_months = fields.Integer("Term (months)")
    consent = fields.Boolean("Agreed to be contacted")
    state = fields.Selection([("new", "New"), ("contacted", "Contacted"), ("closed", "Closed")],
                             default="new", required=True, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    salesforce_inquiry_id = fields.Char("Salesforce Lead ID", copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        inquiries = super().create(vals_list)
        # With the Salesforce integration active, agents work the lead there; otherwise Odoo calls back.
        sync = self.env["autoboutique.salesforce.sync"] if "autoboutique.salesforce.sync" in self.env else None
        for inquiry in inquiries:
            queued = sync and sync.sudo()._enqueue_website_inquiry(inquiry)
            if not queued:
                schedule_todo(inquiry, "manager", "Call back website inquiry",
                              note="%s via %s%s." % (inquiry.name, dict(self._fields["source"].selection)[inquiry.source],
                                                     " about %s" % inquiry.vehicle_id._ab_web_title() if inquiry.vehicle_id else ""))
        return inquiries

    def action_mark_contacted(self):
        self.write({"state": "contacted"})

    def action_close(self):
        self.write({"state": "closed"})
