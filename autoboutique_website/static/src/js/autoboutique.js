/** @odoo-module ignore **/
/* Prime Auto Boutique website interactions. Plain DOM code, active only inside .ab-site. */
(function () {
    "use strict";

    const peso = (n) => Math.round(n).toLocaleString("en-PH");
    const all = (root, sel) => Array.from(root.querySelectorAll(sel));

    function initHeader(site) {
        const header = site.querySelector(".ab-header");
        if (!header) {
            return;
        }
        const burger = header.querySelector(".ab-burger");
        burger && burger.addEventListener("click", () => {
            const open = header.classList.toggle("is-open");
            burger.setAttribute("aria-expanded", open ? "true" : "false");
        });
        all(header, ".ab-has-mega > .ab-nav-link").forEach((btn) => {
            btn.addEventListener("click", () => {
                const item = btn.parentElement;
                const open = !item.classList.contains("is-open");
                all(header, ".ab-has-mega.is-open").forEach((other) => other.classList.remove("is-open"));
                item.classList.toggle("is-open", open);
                btn.setAttribute("aria-expanded", open ? "true" : "false");
            });
        });
        document.addEventListener("click", (ev) => {
            if (!header.contains(ev.target)) {
                all(header, ".ab-has-mega.is-open").forEach((item) => item.classList.remove("is-open"));
            }
        });
        // Brand hover filters the "All vehicles" grid in the mega menu.
        all(header, ".ab-brand-link").forEach((link) => {
            link.addEventListener("mouseenter", () => {
                all(header, ".ab-brand-link").forEach((l) => l.classList.toggle("is-active", l === link));
                const brand = link.dataset.brand;
                all(header, ".ab-mega-car").forEach((car) => {
                    car.hidden = Boolean(brand) && car.dataset.brand !== brand;
                });
            });
        });
        const overlay = header.querySelector(".ab-search-overlay");
        const toggle = header.querySelector(".ab-search-toggle");
        if (overlay && toggle) {
            toggle.addEventListener("click", () => {
                overlay.hidden = !overlay.hidden;
                if (!overlay.hidden) {
                    overlay.querySelector("input").focus();
                }
            });
            overlay.querySelector(".ab-search-close").addEventListener("click", () => { overlay.hidden = true; });
        }
    }

    function initSlider(site) {
        all(site, "[data-ab-slider]").forEach((slider) => {
            const slides = all(slider, ".ab-slide");
            if (slides.length < 2) {
                return;
            }
            let index = 0;
            const show = (i) => {
                index = (i + slides.length) % slides.length;
                slides.forEach((s, n) => s.classList.toggle("is-active", n === index));
            };
            let timer = setInterval(() => show(index + 1), 6000);
            const restart = () => { clearInterval(timer); timer = setInterval(() => show(index + 1), 6000); };
            slider.querySelector(".ab-slide-prev").addEventListener("click", () => { show(index - 1); restart(); });
            slider.querySelector(".ab-slide-next").addEventListener("click", () => { show(index + 1); restart(); });
        });
    }

    function initTabs(site) {
        all(site, ".ab-excellence").forEach((section) => {
            all(section, ".ab-tab").forEach((tab) => {
                tab.addEventListener("click", () => {
                    all(section, ".ab-tab").forEach((t) => t.classList.toggle("is-active", t === tab));
                    all(section, ".ab-tab-panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === tab.dataset.tab));
                });
            });
            all(section, ".ab-brand-tab").forEach((tab) => {
                tab.addEventListener("click", () => {
                    all(section, ".ab-brand-tab").forEach((t) => t.classList.toggle("is-active", t === tab));
                    const brand = tab.dataset.brand;
                    all(section, ".ab-fcard").forEach((card) => {
                        card.hidden = brand ? card.dataset.brand !== brand : card.dataset.featured !== "1";
                    });
                });
            });
        });
        all(site, ".ab-pricelist-wrap").forEach((section) => {
            all(section, ".ab-pl-tab").forEach((tab) => {
                tab.addEventListener("click", () => {
                    all(section, ".ab-pl-tab").forEach((t) => t.classList.toggle("is-active", t === tab));
                    all(section, ".ab-pl-brand").forEach((b) => b.classList.toggle("is-active", b.dataset.brand === tab.dataset.brand));
                });
            });
        });
    }

    function initShop(site) {
        const shop = site.querySelector(".ab-shop");
        if (!shop) {
            return;
        }
        let brand = shop.dataset.activeBrand || "";
        const search = (shop.dataset.search || "").toLowerCase();
        const year = shop.querySelector(".ab-filter-year");
        const price = shop.querySelector(".ab-filter-price");
        const maxLabel = shop.querySelector(".ab-filter-max");
        const empty = shop.querySelector(".ab-shop-empty");
        const apply = () => {
            let shown = 0;
            all(shop, ".ab-vcard").forEach((card) => {
                const ok = (!brand || card.dataset.brand === brand)
                    && (!year.value || card.dataset.year === year.value)
                    && Number(card.dataset.price) <= Number(price.value)
                    && (!search || card.dataset.name.includes(search) || card.dataset.brand.toLowerCase().includes(search));
                card.hidden = !ok;
                shown += ok ? 1 : 0;
            });
            empty.hidden = shown > 0;
            maxLabel.textContent = "₱" + peso(price.value);
        };
        all(shop, ".ab-chip").forEach((chip) => {
            chip.addEventListener("click", () => {
                brand = chip.dataset.brand;
                all(shop, ".ab-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
                apply();
            });
        });
        year.addEventListener("change", apply);
        price.addEventListener("input", apply);
        apply();
    }

    function initVehicle(site) {
        const target = site.querySelector(".ab-variant-target");
        if (!target) {
            return;
        }
        const swap = (url) => {
            if (url) {
                target.style.opacity = 0;
                setTimeout(() => { target.src = url; target.style.opacity = 1; }, 150);
            }
        };
        all(site, ".ab-variant").forEach((card) => {
            card.addEventListener("click", (ev) => {
                if (ev.target.classList.contains("ab-swatch")) {
                    return;
                }
                all(site, ".ab-variant").forEach((c) => c.classList.toggle("is-active", c === card));
                swap(card.dataset.image);
            });
        });
        all(site, ".ab-swatch").forEach((dot) => {
            dot.addEventListener("click", () => {
                all(dot.parentElement, ".ab-swatch").forEach((d) => d.classList.toggle("is-active", d === dot));
                swap(dot.dataset.image);
            });
        });
    }

    function initLightbox(site) {
        all(site, "a.ab-lightbox").forEach((link) => {
            link.addEventListener("click", (ev) => {
                ev.preventDefault();
                const overlay = document.createElement("div");
                overlay.className = "ab-lightbox-overlay";
                overlay.innerHTML = '<img alt="">';
                overlay.querySelector("img").src = link.href;
                overlay.addEventListener("click", () => overlay.remove());
                document.addEventListener("keydown", function esc(e) {
                    if (e.key === "Escape") {
                        overlay.remove();
                        document.removeEventListener("keydown", esc);
                    }
                });
                site.appendChild(overlay);
            });
        });
    }

    // Same formula as the sandbox site: (price - downpayment) / months, no interest.
    function initCalculators(site) {
        all(site, ".ab-calc").forEach((calc) => {
            const brand = calc.querySelector(".ab-calc-brand");
            const vehicle = calc.querySelector(".ab-calc-vehicle");
            const dp = calc.querySelector(".ab-calc-dp");
            const term = calc.querySelector(".ab-calc-term");
            const out = calc.querySelector(".ab-calc-out");
            const financed = calc.querySelector(".ab-calc-financed");
            const model = calc.querySelector(".ab-calc-model");
            const result = calc.querySelector(".ab-pc-result");
            const compute = () => {
                const price = Number(vehicle.value);
                const pct = Number(dp.value);
                const months = Number(term.value);
                if (!price || !pct || !months) {
                    out.textContent = calc.dataset.abCalc === "financing" ? "-" : "---";
                    return false;
                }
                const balance = price - price * (pct / 100);
                out.textContent = peso(balance / months);
                if (financed) {
                    financed.textContent = "₱" + peso(balance);
                }
                if (model) {
                    model.textContent = vehicle.options[vehicle.selectedIndex].text;
                }
                return true;
            };
            if (brand) {
                brand.addEventListener("change", () => {
                    all(vehicle, "option[data-brand]").forEach((opt) => {
                        opt.hidden = Boolean(brand.value) && opt.dataset.brand !== brand.value;
                    });
                    if (vehicle.selectedOptions[0] && vehicle.selectedOptions[0].hidden) {
                        vehicle.value = "";
                    }
                    compute();
                });
            }
            if (calc.dataset.abCalc === "financing") {
                [vehicle, dp, term].forEach((el) => el.addEventListener("change", compute));
            } else {
                calc.querySelector(".ab-calc-go").addEventListener("click", () => {
                    if (compute() && result) {
                        result.hidden = false;
                    }
                });
            }
        });
    }

    function init() {
        const site = document.querySelector(".ab-site");
        if (!site) {
            return;
        }
        initHeader(site);
        initSlider(site);
        initTabs(site);
        initShop(site);
        initVehicle(site);
        initLightbox(site);
        initCalculators(site);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
