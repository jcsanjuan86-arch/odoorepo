/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PALETTE = ["#714B67", "#017E84", "#E9A23B", "#D9534F", "#2A9D8F", "#6C8EBF", "#B56576", "#8D99AE",
    "#457B9D", "#A7C957"];
const STOCK_STATES = ["receiving", "qc", "repair", "detailing", "ready", "reserved"];
const SOLD_STATES = ["sold", "payment", "released", "documents"];

export class ManagementDashboard extends Component {
    static template = "autoboutique_ops.ManagementDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true, period: "month", dateFrom: "", dateTo: "" });
        this.periods = [
            { key: "month", label: "This month" }, { key: "quarter", label: "This quarter" },
            { key: "year", label: "This year" }, { key: "12m", label: "Last 12 months" }, { key: "custom", label: "Custom" },
        ];
        this.canvases = {
            pipeline: useRef("pipeline"), monthly: useRef("monthly"), aging: useRef("aging"),
            costs: useRef("costs"), makes: useRef("makes"), agents: useRef("agents"),
            turnaround: useRef("turnaround"), receivables: useRef("receivables"),
        };
        this.charts = [];
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => this.destroyCharts());
    }

    periodDates() {
        const today = new Date();
        const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        const y = today.getFullYear();
        const m = today.getMonth();
        switch (this.state.period) {
            case "quarter":
                return [iso(new Date(y, m - (m % 3), 1)), iso(today)];
            case "year":
                return [iso(new Date(y, 0, 1)), iso(today)];
            case "12m":
                return [iso(new Date(y, m - 11, 1)), iso(today)];
            case "custom":
                return [this.state.dateFrom || iso(new Date(y, m, 1)), this.state.dateTo || iso(today)];
            default:
                return [iso(new Date(y, m, 1)), iso(today)];
        }
    }

    get periodLabel() {
        return this.periods.find((p) => p.key === this.state.period)?.label.toLowerCase() || "";
    }

    async load() {
        this.state.loading = true;
        const [dateFrom, dateTo] = this.periodDates();
        this.state.data = await this.orm.call("autoboutique.dashboard", "get_dashboard_data", [], {
            date_from: dateFrom, date_to: dateTo,
        });
        this.state.loading = false;
    }

    async refresh() {
        await this.load();
        this.renderCharts();
    }

    async setPeriod(key) {
        this.state.period = key;
        if (key === "custom") {
            const [dateFrom, dateTo] = this.periodDates();
            this.state.dateFrom = this.state.dateFrom || dateFrom;
            this.state.dateTo = this.state.dateTo || dateTo;
        }
        await this.refresh();
    }

    async setCustomDate(field, ev) {
        this.state[field] = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            await this.refresh();
        }
    }

    openInvoices(moveType, name, extraDomain = []) {
        this.action.doAction({
            type: "ir.actions.act_window", name, res_model: "account.move",
            views: [[false, "list"], [false, "form"]],
            domain: [["move_type", "=", moveType], ["state", "=", "posted"],
                ["payment_state", "in", ["not_paid", "partial"]], ...extraDomain],
        });
    }

    openReceivables() {
        this.openInvoices("out_invoice", "Unpaid Customer Invoices");
    }

    openPayables() {
        this.openInvoices("in_invoice", "Unpaid Supplier Bills");
    }

    openReleasedPendingDocs() {
        this.openVehicles([["state", "=", "released"]], "Released, Documents Pending");
    }

    money(value) {
        const currency = this.state.data?.currency || "PHP";
        return new Intl.NumberFormat("en-PH", { style: "currency", currency, maximumFractionDigits: 0 }).format(value || 0);
    }

    shortMoney(value) {
        const abs = Math.abs(value || 0);
        if (abs >= 1e6) {
            return `₱${(value / 1e6).toFixed(1)}M`;
        }
        if (abs >= 1e3) {
            return `₱${(value / 1e3).toFixed(0)}K`;
        }
        return `₱${Math.round(value || 0)}`;
    }

    openVehicles(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "autoboutique.vehicle",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openStock() {
        this.openVehicles([["state", "in", STOCK_STATES]], "Cars in Stock");
    }

    openReady() {
        this.openVehicles([["state", "=", "ready"]], "Ready for Sale");
    }

    openSold() {
        this.openVehicles([["state", "in", SOLD_STATES]], "Sold Cars");
    }

    openVehicle(id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "autoboutique.vehicle", res_id: id,
            views: [[false, "form"]] });
    }

    openApplications() {
        this.action.doAction({
            type: "ir.actions.act_window", name: "Open Sales Applications",
            res_model: "autoboutique.sales.application", views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["draft", "approval", "approved", "reserved"]]],
        });
    }

    destroyCharts() {
        this.charts.forEach((chart) => chart.destroy());
        this.charts = [];
    }

    chart(ref, config) {
        if (this.canvases[ref].el) {
            this.charts.push(new Chart(this.canvases[ref].el, config));
        }
    }

    renderCharts() {
        this.destroyCharts();
        const data = this.state.data;
        if (!data) {
            return;
        }
        const style = getComputedStyle(document.body);
        Chart.defaults.color = style.color;
        Chart.defaults.borderColor = "rgba(128,128,128,0.18)";
        const moneyTicks = { precision: 0, callback: (value) => this.shortMoney(value) };
        const noLegend = { legend: { display: false } };

        this.chart("pipeline", {
            type: "bar",
            data: {
                labels: data.pipeline.map((p) => p.label),
                datasets: [{
                    data: data.pipeline.map((p) => p.count),
                    backgroundColor: data.pipeline.map((p) => (SOLD_STATES.includes(p.state) ? PALETTE[1] : PALETTE[0])),
                    borderRadius: 4,
                }],
            },
            options: {
                maintainAspectRatio: false, plugins: noLegend,
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
                onClick: (event, elements) => {
                    if (elements.length) {
                        const stage = data.pipeline[elements[0].index];
                        this.openVehicles([["state", "=", stage.state]], stage.label);
                    }
                },
            },
        });

        this.chart("monthly", {
            data: {
                labels: data.monthly.map((m) => m.label),
                datasets: [
                    { type: "bar", label: "Revenue (before VAT)", data: data.monthly.map((m) => m.revenue),
                        backgroundColor: PALETTE[0], borderRadius: 4, yAxisID: "y" },
                    { type: "line", label: "Gross profit", data: data.monthly.map((m) => m.profit),
                        borderColor: PALETTE[2], backgroundColor: PALETTE[2], tension: 0.3, yAxisID: "y" },
                    { type: "line", label: "Cars sold", data: data.monthly.map((m) => m.count),
                        borderColor: PALETTE[1], backgroundColor: PALETTE[1], borderDash: [5, 4], yAxisID: "count" },
                ],
            },
            options: {
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, ticks: moneyTicks },
                    count: { position: "right", beginAtZero: true, grid: { display: false }, ticks: { precision: 0 } },
                },
                plugins: { tooltip: { callbacks: {
                    label: (ctx) => (ctx.dataset.yAxisID === "count" ? `${ctx.dataset.label}: ${ctx.raw}`
                        : `${ctx.dataset.label}: ${this.money(ctx.raw)}`),
                } } },
            },
        });

        this.chart("aging", {
            type: "bar",
            data: {
                labels: data.aging.map((a) => a.label),
                datasets: [{ data: data.aging.map((a) => a.count),
                    backgroundColor: [PALETTE[4], PALETTE[2], "#E76F51", PALETTE[3]], borderRadius: 4 }],
            },
            options: { maintainAspectRatio: false, plugins: noLegend,
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
        });

        const costLabels = Object.keys(data.costs);
        this.chart("costs", {
            type: "doughnut",
            data: { labels: costLabels, datasets: [{ data: costLabels.map((k) => data.costs[k]),
                backgroundColor: [PALETTE[0], PALETTE[3], PALETTE[1]] }] },
            options: { maintainAspectRatio: false, cutout: "60%",
                plugins: { legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${this.money(ctx.raw)}` } } } },
        });

        this.chart("makes", {
            type: "bar",
            data: { labels: data.makes.map((m) => m.label),
                datasets: [{ data: data.makes.map((m) => m.count), backgroundColor: PALETTE, borderRadius: 4 }] },
            options: { indexAxis: "y", maintainAspectRatio: false, plugins: noLegend,
                scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
                onClick: (event, elements) => {
                    if (elements.length) {
                        const make = data.makes[elements[0].index].label;
                        this.openVehicles([["make", "=", make], ["state", "in", STOCK_STATES]], `${make} in Stock`);
                    }
                } },
        });

        const stages = data.turnaround.stages;
        this.chart("turnaround", {
            type: "bar",
            data: {
                labels: stages.map((s) => s.label),
                datasets: [
                    { label: `Average days (cars that moved on, ${this.periodLabel})`, data: stages.map((s) => s.avg_days),
                        backgroundColor: PALETTE[0], borderRadius: 4 },
                    { label: "Days so far (cars there now)", data: stages.map((s) => s.waiting_days),
                        backgroundColor: PALETTE[2], borderRadius: 4 },
                ],
            },
            options: {
                indexAxis: "y", maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" }, tooltip: { callbacks: {
                    label: (ctx) => {
                        const stage = stages[ctx.dataIndex];
                        const cars = ctx.datasetIndex === 0 ? stage.done : stage.waiting;
                        return `${ctx.dataset.label}: ${ctx.raw} days (${cars} cars)`;
                    },
                } } },
                scales: { x: { beginAtZero: true, title: { display: true, text: "days" } } },
                onClick: (event, elements) => {
                    if (elements.length) {
                        const stage = stages[elements[0].index];
                        this.openVehicles([["state", "=", stage.state]], stage.label);
                    }
                },
            },
        });

        if (data.cash) {
            this.chart("receivables", {
                type: "bar",
                data: {
                    labels: data.cash.aging.map((a) => a.label),
                    datasets: [{ data: data.cash.aging.map((a) => a.amount),
                        backgroundColor: [PALETTE[4], PALETTE[2], "#E76F51", PALETTE[3], "#9B2226"], borderRadius: 4 }],
                },
                options: { maintainAspectRatio: false, plugins: { legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => this.money(ctx.raw) } } },
                    scales: { y: { beginAtZero: true, ticks: moneyTicks } },
                    onClick: () => this.openReceivables() },
            });
        }

        this.chart("agents", {
            type: "bar",
            data: { labels: data.agents.map((a) => a.label),
                datasets: [{ label: "Sales", data: data.agents.map((a) => a.revenue),
                    backgroundColor: PALETTE[1], borderRadius: 4 }] },
            options: { maintainAspectRatio: false, plugins: { legend: { display: false },
                tooltip: { callbacks: { label: (ctx) =>
                    `${this.money(ctx.raw)} (${data.agents[ctx.dataIndex].count} cars)` } } },
                scales: { y: { beginAtZero: true, ticks: moneyTicks } } },
        });
    }
}

registry.category("actions").add("autoboutique_management_dashboard", ManagementDashboard);
