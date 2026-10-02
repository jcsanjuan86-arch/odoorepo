"""Used Vehicle Acceptance Checklist on QC inspections.

Every QC inspection gets one line per active checklist item (Autoboutique >
Configuration > QC Checklist Items). Inspectors mark each line OK, Needs
Attention or N/A, add remarks and photos, and print the checklist as a PDF.
When the QC result is processed, the items that need attention are copied to
the findings and to the repair assessment's notes.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

SECTIONS = [
    ("pms", "1. PMS (Preventive Maintenance Schedule)"),
    ("engine", "2.1 Engine"),
    ("underchassis", "2.2 Underchassis"),
    ("transmission", "2.3 Transmission"),
    ("electrical", "3. Electrical"),
    ("aircon", "4. Aircon"),
    ("body", "5. Body & Paint"),
]
SECTION_SEQUENCE = {key: index for index, (key, _label) in enumerate(SECTIONS)}
# Group heading printed before a section: (heading, note).
SECTION_HEADINGS = {
    "engine": ("2. Mechanical", "Covers the powertrain and load-bearing systems, the costliest items to repair if missed."),
}
SECTION_NOTES = {
    "pms": "Verifies the vehicle's maintenance discipline against its mileage and paperwork "
           "before any physical inspection begins.",
    "electrical": "All electrical systems should be tested with the engine both off and running.",
    "aircon": "Run for at least 10-15 minutes to properly assess cooling performance and catch intermittent issues.",
    "body": "Inspect in daylight. Use a paint thickness gauge where available to detect repainted panels.",
}
STATUSES = [("ok", "OK"), ("attention", "Needs Attention"), ("na", "N/A")]


class QCChecklistItem(models.Model):
    _name = "autoboutique.qc.checklist.item"
    _description = "QC Checklist Item"
    _order = "section_sequence, sequence, id"

    name = fields.Char("Inspection Item", required=True)
    section = fields.Selection(SECTIONS, required=True)
    section_sequence = fields.Integer(compute="_compute_section_sequence", store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.depends("section")
    def _compute_section_sequence(self):
        for item in self:
            item.section_sequence = SECTION_SEQUENCE.get(item.section, 99)


class QCLine(models.Model):
    _name = "autoboutique.qc.line"
    _description = "QC Checklist Line"
    _order = "section_sequence, sequence, id"

    qc_id = fields.Many2one("autoboutique.qc", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="qc_id.company_id", store=True, index=True)
    item_id = fields.Many2one("autoboutique.qc.checklist.item", ondelete="set null")
    section = fields.Selection(SECTIONS, required=True)
    section_sequence = fields.Integer(compute="_compute_section_sequence", store=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Inspection Item", required=True)
    status = fields.Selection(STATUSES)
    # Tick boxes shown to inspectors; ticking one clears the others.
    # One compute method per tick: fields sharing a compute are protected together
    # while one of them is written, which would leave the other ticks stale.
    tick_ok = fields.Boolean("OK", compute="_compute_tick_ok", inverse="_inverse_tick_ok")
    tick_attention = fields.Boolean("Needs Attention", compute="_compute_tick_attention", inverse="_inverse_tick_attention")
    tick_na = fields.Boolean("N/A", compute="_compute_tick_na", inverse="_inverse_tick_na")
    remarks = fields.Char("Remarks / Notes")
    photo = fields.Image(max_width=1920, max_height=1920)
    photo_512 = fields.Image("Photo (512px)", related="photo", max_width=512, max_height=512, store=True)
    attachment_ids = fields.Many2many(
        "ir.attachment", "autoboutique_qc_line_ir_attachment_rel", "line_id", "attachment_id",
        string="More Photos",
    )

    @api.depends("section")
    def _compute_section_sequence(self):
        for line in self:
            line.section_sequence = SECTION_SEQUENCE.get(line.section, 99)

    @api.depends("status")
    def _compute_tick_ok(self):
        for line in self:
            line.tick_ok = line.status == "ok"

    @api.depends("status")
    def _compute_tick_attention(self):
        for line in self:
            line.tick_attention = line.status == "attention"

    @api.depends("status")
    def _compute_tick_na(self):
        for line in self:
            line.tick_na = line.status == "na"

    def _set_tick(self, status, ticked):
        for line in self:
            if ticked:
                line.status = status
            elif line.status == status:
                line.status = False

    def _inverse_tick_ok(self):
        for line in self:
            line._set_tick("ok", line.tick_ok)

    def _inverse_tick_attention(self):
        for line in self:
            line._set_tick("attention", line.tick_attention)

    def _inverse_tick_na(self):
        for line in self:
            line._set_tick("na", line.tick_na)

    @api.onchange("tick_ok")
    def _onchange_tick_ok(self):
        if self.tick_ok:
            self.update({"tick_attention": False, "tick_na": False, "status": "ok"})
        elif self.status == "ok":
            self.status = False

    @api.onchange("tick_attention")
    def _onchange_tick_attention(self):
        if self.tick_attention:
            self.update({"tick_ok": False, "tick_na": False, "status": "attention"})
        elif self.status == "attention":
            self.status = False

    @api.onchange("tick_na")
    def _onchange_tick_na(self):
        if self.tick_na:
            self.update({"tick_ok": False, "tick_attention": False, "status": "na"})
        elif self.status == "na":
            self.status = False

    def _ab_image_attachments(self):
        return self.attachment_ids.filtered(lambda a: (a.mimetype or "").startswith("image/"))


class QC(models.Model):
    _inherit = "autoboutique.qc"

    line_ids = fields.One2many("autoboutique.qc.line", "qc_id", string="Checklist")
    pms_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "pms")])
    engine_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "engine")])
    underchassis_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "underchassis")])
    transmission_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "transmission")])
    electrical_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "electrical")])
    aircon_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "aircon")])
    body_line_ids = fields.One2many("autoboutique.qc.line", "qc_id", domain=[("section", "=", "body")])
    checklist_ok_count = fields.Integer("OK", compute="_compute_checklist_counts", store=True)
    checklist_attention_count = fields.Integer("Needs Attention", compute="_compute_checklist_counts", store=True)
    checklist_na_count = fields.Integer("N/A", compute="_compute_checklist_counts", store=True)
    checklist_unchecked_count = fields.Integer("Not Checked", compute="_compute_checklist_counts", store=True)

    @api.depends("line_ids.status")
    def _compute_checklist_counts(self):
        for qc in self:
            statuses = qc.line_ids.mapped("status")
            qc.checklist_ok_count = statuses.count("ok")
            qc.checklist_attention_count = statuses.count("attention")
            qc.checklist_na_count = statuses.count("na")
            qc.checklist_unchecked_count = statuses.count(False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Inspections created with a result already (imports) keep it without a checklist.
        records.filtered(lambda q: q.result == "pending" and not q.line_ids)._ab_load_checklist()
        return records

    @api.constrains("result")
    def _check_checklist_answered(self):
        for qc in self.filtered(lambda q: q.result in ("pass", "fail")):
            unanswered = qc.line_ids.filtered(lambda line: not line.status)
            if unanswered:
                raise ValidationError(
                    "Answer every inspection point before setting the QC result. %d item(s) still have no tick, "
                    "for example: %s" % (len(unanswered), unanswered[0].name))

    def _ab_load_checklist(self):
        items = self.env["autoboutique.qc.checklist.item"].search([])
        for qc in self:
            existing = qc.line_ids.item_id
            qc.write({"line_ids": [(0, 0, {
                "item_id": item.id, "section": item.section, "sequence": item.sequence, "name": item.name,
            }) for item in items - existing]})

    def action_load_checklist(self):
        self._ab_load_checklist()

    def _ab_mark_unchecked_ok(self):
        """Test helper only: inspectors must tick every point themselves."""
        self.line_ids.filtered(lambda line: not line.status).write({"status": "ok"})

    def action_print_checklist(self):
        return self.env.ref("autoboutique_ops.action_report_qc_checklist").report_action(self)

    def _ab_attention_summary(self):
        self.ensure_one()
        labels = dict(SECTIONS)
        return "\n".join(
            "- %s: %s%s" % (labels[line.section], line.name, " (%s)" % line.remarks if line.remarks else "")
            for line in self.line_ids.filtered(lambda line: line.status == "attention")
        )

    def action_process_result(self):
        result = super().action_process_result()
        for qc in self:
            summary = qc._ab_attention_summary()
            if not summary:
                continue
            if not qc.findings:
                qc.findings = "Needs attention:\n%s" % summary
            repair = qc.repair_id
            if repair and summary not in (repair.notes or ""):
                header = "Needs attention from %s:" % qc.name
                repair.notes = "\n\n".join(filter(None, [repair.notes, "%s\n%s" % (header, summary)]))
        return result

    def _ab_report_sections(self):
        self.ensure_one()
        sections = []
        for key, label in SECTIONS:
            lines = self.line_ids.filtered(lambda line, key=key: line.section == key)
            if not lines:
                continue
            heading, heading_note = SECTION_HEADINGS.get(key, (False, False))
            sections.append({
                "label": label, "heading": heading, "heading_note": heading_note,
                "note": SECTION_NOTES.get(key), "lines": lines,
            })
        return sections

    def _ab_report_photo_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda line: line.photo or line._ab_image_attachments())
