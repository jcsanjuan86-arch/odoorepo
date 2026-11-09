"""Inventory Status: the monthly CAR INVENTORY sheet, kept live from the Vehicle Master.

One row per car in stock, grouped by brand and model, with the columns of the former
"2026 INVENTORY STATUS" workbook; cars sold in the chosen month are listed on top.
"""
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .autofill import _join
from .extended import SOLD_STATES, STOCK_STATES

# Monthly amortization = ((price - downpayment) * add-on rate + (price - downpayment)) / months
AMORTIZATION = [(36, 0.4447), (48, 0.5973), (60, 0.7699)]

STOCK_OWNERS = [("autoboutique", "Auto Boutique"), ("bdo", "BDO"), ("other", "Other")]
LOCATIONS = [
    ("ab_showroom", "AB Showroom"), ("ordonez", "Ordonez"), ("shop", "Paint / Mechanical Shop"),
    ("modular", "Modular"), ("other_dealer", "Other Dealer"), ("delivery", "Delivery"),
    ("awarded", "Awarded"), ("other", "Other"),
]
MARKETING = [("to_shoot", "To Shoot"), ("done", "Done")]
PAPERS = [("with", "With Papers"), ("without", "Without Papers")]

HEADERS = [
    ("INV", "text"), ("TYPE OF CAR", "text"), ("PLATE", "text"), ("LOCATION", "text"),
    ("MARKETING STATUS", "text"), ("UNIT STATUS BY: FINANCING", "text"), ("SELLING PRICE", "money"),
    ("DOWNPAYMENT", "money"), ("3 YRS", "money"), ("4 YRS", "money"), ("5 YRS", "money"),
    ("SOLD TO", "text"), ("DATE SOLD", "text"), ("AGENT", "text"), ("FINANCING PARTNER", "text"),
    ("BANK FROM", "text"), ("BIDDER", "text"), ("ODO", "int"), ("UNIT STATUS BY: OPERATIONS", "text"),
    ("OPERATIONS: REMARKS", "text"), ("PAPER STATUS", "text"), ("WITH / WITHOUT PAPERS", "text"),
    ("PLATE STATUS", "text"), ("REGISTRATION STATUS", "text"), ("TRANSFER STATUS", "text"), ("REMARKS", "text"),
]


def amortization(price, downpayment):
    financed = (price or 0.0) - (downpayment or 0.0)
    if not price or financed <= 0:
        return [0.0] * len(AMORTIZATION)
    return [(financed * rate + financed) / months for months, rate in AMORTIZATION]


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    stock_owner = fields.Selection(STOCK_OWNERS, "Inventory Of", default="autoboutique")
    location = fields.Selection(LOCATIONS, default="ab_showroom")
    marketing_status = fields.Selection(MARKETING, default="to_shoot",
                                        help="Photos and listing: To Shoot until the car has been shot.")
    downpayment = fields.Monetary(currency_field="currency_id")
    amortization_3y = fields.Monetary("3 Yrs", compute="_compute_amortization", currency_field="currency_id")
    amortization_4y = fields.Monetary("4 Yrs", compute="_compute_amortization", currency_field="currency_id")
    amortization_5y = fields.Monetary("5 Yrs", compute="_compute_amortization", currency_field="currency_id")
    bank_from = fields.Char("Bank From", compute="_compute_bank_from", store=True, readonly=False,
                            help="Where the unit came from; filled from the supplier.")
    bidder = fields.Char()
    operations_remarks = fields.Char("Operations Remarks")
    paper_status = fields.Char()
    papers = fields.Selection(PAPERS, "With / Without Papers")
    plate_status = fields.Char()
    transfer_status = fields.Char(help="By the liaison officer / document controller.")
    inventory_remarks = fields.Char("Remarks")

    @api.depends("selling_price", "downpayment")
    def _compute_amortization(self):
        for vehicle in self:
            (vehicle.amortization_3y, vehicle.amortization_4y,
             vehicle.amortization_5y) = amortization(vehicle.selling_price, vehicle.downpayment)

    @api.depends("supplier_id")
    def _compute_bank_from(self):
        for vehicle in self:
            vehicle.bank_from = vehicle.bank_from or vehicle.supplier_id.name

    # -- report --------------------------------------------------------------------

    def _ab_financing_status(self):
        if self.state == "reserved":
            return "RESERVED"
        if self.state in SOLD_STATES:
            return "SOLD"
        return "N/A"

    def _ab_operations_status(self):
        if self.state == "ready" or self.state in SOLD_STATES or self.state == "reserved":
            return "READY"
        open_repairs = self.repair_ids.filtered(lambda r: r.state != "done")
        work = ", ".join(open_repairs.line_ids.mapped("name"))
        label = dict(self._fields["state"].selection).get(self.state, "")
        return work or label.upper()

    def _ab_financing_partner(self):
        account = self.env["autoboutique.financing.account"].sudo().search(
            [("vehicle_id", "=", self.id), ("status", "not in", ("decline", "cancelled", "cancelled_unresponsive",
                                                                  "cmap_low", "cancelled_approved"))],
            order="id desc", limit=1)
        return account.bank_id.name or ""

    def _ab_date_sold(self):
        order = self.sale_order_id
        if order and order.state == "sale" and order.date_order:
            return fields.Date.to_date(order.date_order)
        return False

    def _ab_status_row(self):
        label = lambda field: dict(self._fields[field].selection).get(self[field], "") if self[field] else ""
        amort = amortization(self.selling_price, self.downpayment)
        sold = self._ab_date_sold()
        return [
            label("stock_owner").upper(),
            _join(self.model_year, self.make, self.model, self.variant, self.color, self.transmission).upper(),
            self.plate_number or "", label("location").upper(), label("marketing_status").upper(),
            self._ab_financing_status(), self.selling_price or "", self.downpayment or "",
            *[value or "" for value in amort],
            self.customer_id.name or "", sold.strftime("%m/%d/%Y") if sold else "", self.sales_agent_id.name or "",
            self._ab_financing_partner(), self.bank_from or "", self.bidder or "", self.mileage or "",
            self._ab_operations_status(), self.operations_remarks or "", self.paper_status or "",
            label("papers").upper(), self.plate_status or "",
            dict(self._fields["registration_status"].selection).get(self.registration_status, "")
            if self.registration_status else "",
            self.transfer_status or "", self.inventory_remarks or "",
        ]

    @staticmethod
    def _ab_row(cells, kind=None):
        return {"cells": cells, "kind": kind}

    def _ab_grouped_rows(self):
        """Brand, then model, as section rows, like the sheet."""
        blank = [""] * len(HEADERS)
        groups = defaultdict(lambda: defaultdict(lambda: self.browse()))
        for vehicle in self:
            groups[(vehicle.make or "").upper()][(vehicle.model or "").upper()] |= vehicle
        rows = []
        for make in sorted(groups):
            rows.append(self._ab_row(["", make] + blank[2:], "section"))
            for model in sorted(groups[make]):
                cars = groups[make][model].sorted(lambda v: (-(v.model_year or 0), v.plate_number or ""))
                rows.append(self._ab_row(["", model] + blank[2:], "subsection"))
                rows.extend(self._ab_row(car._ab_status_row()) for car in cars)
        return rows

    def _ab_incoming_rows(self):
        """Cars won at auction that have not arrived yet."""
        receivings = self.env["autoboutique.receiving"].search([
            ("vehicle_id", "=", False), ("state", "in", ("draft", "expected", "arrived", "checking", "confirmed"))])
        rows = []
        for receiving in receivings:
            line = receiving.bid_line_id
            cells = [""] * len(HEADERS)
            cells[0] = "AUTO BOUTIQUE"
            cells[1] = _join(line.model_year, line.make, line.model, line.color, line.transmission).upper()
            cells[2] = line.plate_number or ""
            cells[3] = "AWARDED" if receiving.state == "draft" else "DELIVERY"
            cells[4] = cells[5] = "N/A"
            cells[15] = line.bid_id.supplier_id.name or ""
            rows.append(self._ab_row(cells))
        return rows

    @api.model
    def get_report(self, tab="inventory", anchor=None):
        day = fields.Date.to_date(anchor) if anchor else fields.Date.context_today(self)
        start = day.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        stock = self.search([("state", "in", STOCK_STATES)])
        sold = self.search([("state", "in", SOLD_STATES)]).filtered(
            lambda v: v._ab_date_sold() and start <= v._ab_date_sold() <= end)
        incoming = self._ab_incoming_rows()
        headers = [header for header, _kind in HEADERS]
        formats = [kind for _header, kind in HEADERS]

        def count_table(title, field, records):
            labels = dict(self._fields[field].selection)
            counts = defaultdict(int)
            for vehicle in records:
                counts[vehicle[field]] += 1
            rows = [self._ab_row([labels[key].upper(), counts[key]]) for key in labels if counts[key]]
            if counts[False]:
                rows.append(self._ab_row(["NOT SET", counts[False]]))
            return {"title": title, "headers": ["", ""], "formats": ["text", "int"],
                    "rows": rows + [self._ab_row(["TOTAL", len(records)], "total")]}

        return {"title": "CAR INVENTORY - %s" % day.strftime("%B %Y").upper(), "tables": [
            count_table("Inventory Of", "stock_owner", stock),
            count_table("Location", "location", stock),
            count_table("Marketing Status", "marketing_status", stock),
            {"title": "Summary", "headers": ["", ""], "formats": ["text", "int"], "rows": [
                self._ab_row(["IN STOCK", len(stock)], "total"),
                self._ab_row(["RESERVED", len(stock.filtered(lambda v: v.state == "reserved"))]),
                self._ab_row(["READY FOR SALE", len(stock.filtered(lambda v: v.state == "ready"))]),
                self._ab_row(["IN QC / REPAIR / DETAILING",
                              len(stock.filtered(lambda v: v.state in ("receiving", "qc", "repair", "detailing")))]),
                self._ab_row(["INCOMING (DELIVERY / AWARDED)", len(incoming)]),
                self._ab_row(["SOLD - %s" % day.strftime("%B").upper(), len(sold)], "total"),
            ]},
            {"title": "Sold - %s" % day.strftime("%B %Y"), "wide": True, "headers": headers, "formats": formats,
             "rows": [self._ab_row(car._ab_status_row()) for car in sold]
             or [self._ab_row(["No unit sold this month"] + [""] * (len(HEADERS) - 1))]},
            {"title": "Units", "wide": True, "headers": headers, "formats": formats,
             "rows": ([self._ab_row(["", "INCOMING"] + [""] * (len(HEADERS) - 2), "section")] + incoming
                      if incoming else []) + stock._ab_grouped_rows()},
        ]}
