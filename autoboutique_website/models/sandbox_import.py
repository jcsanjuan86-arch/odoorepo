"""Import the 13 sandbox website vehicles into the Vehicle Master.

The dataset (data/sandbox_vehicles.json) was captured from the sandbox
WordPress site. "Import Sandbox Vehicles" creates or updates one Ready for
Sale vehicle per listing with its listing photo; a cron job then downloads the
banner, variants, feature rows and gallery photos one vehicle at a time.
"""
import base64
import json
import logging
import re

import requests

from odoo import api, models
from odoo.modules import module as odoo_module
from odoo.exceptions import UserError
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

DATASET = "autoboutique_website/data/sandbox_vehicles.json"
SANDBOX_HOST = "saddlebrown-guanaco-660591.hostingersite.com"
TIMEOUT = 30


def _download(url):
    """Return base64 image data for a sandbox URL or a module static path."""
    if not url:
        return False
    if url.startswith("/"):
        with file_open(url.lstrip("/"), "rb") as handle:
            return base64.b64encode(handle.read())
    if SANDBOX_HOST not in url:
        raise UserError("Refusing to download an image from outside the sandbox site: %s" % url)
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return base64.b64encode(response.content)


def _split_name(name, brand):
    year = re.search(r"\b(19|20)\d{2}\b", name)
    model = re.sub(r"\b(19|20)\d{2}\b", "", name)
    model = re.sub(r"(?i)\b%s\b" % re.escape(brand or ""), "", model) if brand else model
    model = re.sub(r"\s+", " ", model).strip() or name
    return (int(year.group(0)) if year else 0), model


class Vehicle(models.Model):
    _inherit = "autoboutique.vehicle"

    @api.model
    def _ab_sandbox_dataset(self):
        with file_open(DATASET, "r") as handle:
            return json.load(handle)

    @api.model
    def _ab_website_company(self):
        website = self.env["website"].search([("name", "=", "Autoboutique")], limit=1)
        company = website.company_id or self.env["res.company"].search([("name", "=ilike", "Autoboutique")], limit=1)
        if not company:
            raise UserError("The Autoboutique company was not found.")
        return company

    @api.model
    def _ab_listing_product(self, company, year, make, model):
        name = " ".join(filter(None, [str(year or ""), make, model])).strip()
        Product = self.env["product.product"].with_company(company)
        product = Product.search([("name", "=", name), ("tracking", "=", "serial"),
                                  ("company_id", "in", [company.id, False])], limit=1)
        return product or Product.create({
            "name": name, "type": "consu", "is_storable": True, "tracking": "serial",
            "company_id": company.id, "purchase_ok": True, "sale_ok": True, "invoice_policy": "order",
        })

    @api.model
    def action_import_sandbox_vehicles(self):
        """Create or update the sandbox listings. Photos beyond the listing photo follow in the background."""
        company = self._ab_website_company()
        Vehicle = self.with_company(company).with_context(ab_automating=True, tracking_disable=True)
        created = updated = 0
        for row in self._ab_sandbox_dataset():
            year, model = _split_name(row["name"], row["brand"])
            vehicle = Vehicle.search([("wp_import_ref", "=", row["wp_id"]), ("company_id", "=", company.id)], limit=1)
            values = {
                "name": row["name"],
                "make": row["brand"],
                "model": model,
                "model_year": year,
                "selling_price": row["price"],
                "website_title": row["name"],
                "website_slug": row["slug"],
                "website_tagline": row.get("tagline") or False,
                "website_description": row.get("description") or False,
                "website_sequence": row.get("sequence", 100),
                "website_featured": True,
                "website_published": True,
                "wp_import_ref": row["wp_id"],
                "wp_gallery_pending": True,
            }
            if not vehicle:
                values.update({
                    "company_id": company.id,
                    "product_id": self._ab_listing_product(company, year, row["brand"], model).id,
                    "state": "ready",
                })
                try:
                    values["website_card_image"] = _download(row.get("card_image") or row.get("main_image"))
                    values["website_menu_image"] = _download(row.get("menu_image")) if row.get("menu_image") else False
                except Exception as exc:  # noqa: BLE001 - the cron retries missing photos
                    _logger.warning("Sandbox import: listing photo for %s failed: %s", row["name"], exc)
                Vehicle.create(values)
                created += 1
            else:
                vehicle.write(values)
                updated += 1
        cron = self.env.ref("autoboutique_website.cron_import_sandbox_photos", raise_if_not_found=False)
        if cron:
            cron._trigger()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {
                "title": "Sandbox vehicles imported",
                "message": "%d created, %d updated. Banners, variants and galleries are downloading in the "
                           "background (a few minutes)." % (created, updated),
                "type": "success", "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def _cron_import_sandbox_photos(self):
        rows = {row["wp_id"]: row for row in self._ab_sandbox_dataset()}
        pending = self.sudo().search([("wp_gallery_pending", "=", True), ("wp_import_ref", "!=", 0)])
        for vehicle in pending:
            row = rows.get(vehicle.wp_import_ref)
            try:
                with self.env.cr.savepoint():
                    if row:
                        vehicle._ab_import_photos(row)
                    vehicle.wp_gallery_pending = False
            except Exception as exc:  # noqa: BLE001 - logged, retried on the next run
                self.env.invalidate_all()
                _logger.warning("Sandbox import: photos for %s failed: %s", vehicle.display_name, exc)
                continue
            if not odoo_module.current_test:
                self.env["ir.cron"]._commit_progress(1)

    def _ab_import_photos(self, row):
        self.ensure_one()
        values = {}
        if not self.website_card_image:
            values["website_card_image"] = _download(row.get("card_image") or row.get("main_image"))
        if not self.website_menu_image and row.get("menu_image"):
            values["website_menu_image"] = _download(row["menu_image"])
        if row.get("hero"):
            values["website_hero_image"] = _download(row["hero"])
        if not self.website_variant_ids and row.get("variants"):
            values["website_variant_ids"] = [(0, 0, {
                "sequence": index,
                "name": variant["title"],
                "price_label": variant.get("price"),
                "monthly_label": variant.get("monthly"),
                "image": _download(variant.get("image")),
                **{spec["label"].lower(): spec["value"] for spec in variant.get("specs", [])
                   if spec["label"].lower() in ("engine", "suspension", "brakes", "transmission")},
                "color_ids": [(0, 0, {"sequence": n, "hex_code": color["hex"], "image": _download(color["image"])})
                              for n, color in enumerate(variant.get("colors", []))],
            }) for index, variant in enumerate(row["variants"])]
        if not self.website_feature_ids and row.get("features"):
            values["website_feature_ids"] = [(0, 0, {
                "sequence": index, "name": feature["title"], "text": feature["text"],
                "image": _download(feature["image"]),
            }) for index, feature in enumerate(row["features"])]
        if not self.website_gallery_ids and row.get("gallery"):
            values["website_gallery_ids"] = [(0, 0, {"sequence": index, "image": _download(url)})
                                             for index, url in enumerate(row["gallery"])]
        if values:
            self.write(values)
