/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const pad = (number) => String(number).padStart(2, "0");

export class FinancingReport extends Component {
    static template = "autoboutique_ops.FinancingReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const now = new Date();
        this.tab = this.props.action.params?.tab || "daily";
        this.state = useState({
            data: null,
            day: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
            month: `${now.getFullYear()}-${pad(now.getMonth() + 1)}`,
            year: now.getFullYear(),
            quarter: Math.floor(now.getMonth() / 3) + 1,
        });
        onWillStart(() => this.load());
    }

    get picker() {
        return { daily: "day", monthly: "month", financing: "month", overall: "year", average: "year", quarter: "quarter" }[this.tab];
    }

    get anchor() {
        switch (this.picker) {
            case "day":
                return this.state.day;
            case "month":
                return `${this.state.month}-01`;
            case "quarter":
                return `${this.state.year}-${pad((this.state.quarter - 1) * 3 + 1)}-01`;
            default:
                return `${this.state.year}-01-01`;
        }
    }

    async load() {
        this.state.data = await this.orm.call("autoboutique.financing.account", "get_report", [this.tab], {
            anchor: this.anchor,
        });
    }

    async onChange(key, event) {
        const value = event.target.value;
        if (value) {
            this.state[key] = ["year", "quarter"].includes(key) ? parseInt(value) : value;
            await this.load();
        }
    }

    format(value, kind) {
        if (value === "" || typeof value === "string") {
            return value;
        }
        switch (kind) {
            case "money":
                return value.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            case "pct":
                return `${(value * 100).toFixed(1)}%`;
            case "dec":
                return value.toFixed(1);
            default:
                return value.toLocaleString("en-PH");
        }
    }
}

registry.category("actions").add("autoboutique_financing_report", FinancingReport);
