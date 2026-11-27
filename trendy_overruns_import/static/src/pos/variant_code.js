import { patch } from "@web/core/utils/patch";
import { normalize } from "@web/core/l10n/utils";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";

// Disloq variant codes such as 2608060227122-14: typing one finds the product, and scanning
// it (or typing it and pressing Enter) adds the item with its size and colour already chosen.
const VARIANT_CODE = /^\S+-\d+$/;

patch(ProductTemplate.prototype, {
    get searchString() {
        const base = super.searchString;
        return this.disloq_variant_codes ? `${base} ${normalize(this.disloq_variant_codes)}` : base;
    },
});

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        if (await this.addDisloqVariant(code.base_code, { code })) {
            return;
        }
        return super._barcodeProductAction(code);
    },

    async onPressEnterKey() {
        const word = this.pos.searchProductWord.trim();
        if (await this.addDisloqVariant(word)) {
            this.pos.searchProductWord = "";
            return;
        }
        return super.onPressEnterKey();
    },

    async addDisloqVariant(text, opts = {}) {
        if (!text || !VARIANT_CODE.test(text)) {
            return false;
        }
        const match = await this.pos.data.silentCall("trendy.overruns.variant.code", "pos_find", [text]);
        if (!match) {
            return false;
        }
        let template = this.pos.models["product.template"].get(match.product_tmpl_id);
        if (!template) {
            await this.pos.loadNewProducts([["id", "=", match.product_tmpl_id]]);
            template = this.pos.models["product.template"].get(match.product_tmpl_id);
        }
        if (!template) {
            return false;
        }
        this.sound.play("beep");
        await this.pos.addLineToCurrentOrder(
            {
                product_id: template.product_variant_ids[0],
                product_tmpl_id: template,
                payload: {
                    attribute_value_ids: match.value_ids,
                    attribute_custom_values: {},
                    price_extra: match.price_extra || 0,
                },
            },
            opts,
            true
        );
        this.numberBuffer.reset();
        return true;
    },
});
