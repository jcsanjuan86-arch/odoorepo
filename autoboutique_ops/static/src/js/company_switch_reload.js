/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";

// Odoo keeps the app launcher menu in the browser cache. Reload on a company
// switch so company-aware menu rules are applied before the new work context.
patch(CompanySelector.prototype, {
    async apply() {
        user.activateCompanies(this.selectedCompaniesIds, {
            includeChildCompanies: false,
            reload: true,
        });
    },
});
