from odoo import models

TIKTOK_URL = "https://www.tiktok.com/@trendyoverruns_boutique"

# Branch contact details from the brand brief. Telephone/mobile/OIC marked "to follow" stay
# empty until known; empty values are not shown on the website.
BRANCHES = [
    {"key": "lilac", "name": "Lilac – Marikina",
     "address": "106 Lilac St, Concepcion Dos, Marikina City, 1811 Metro Manila",
     "oic": "", "phone": "7720-5279", "mobile": "", "hours": "12:00 PM – 9:00 PM (Daily)"},
    {"key": "katipunan", "name": "Katipunan – Quezon City",
     "address": "Ext, 226 Katipunan Ave, Project 4, Quezon City, 1800 Metro Manila",
     "oic": "Anne Banadera", "phone": "7791-1976", "mobile": "0963-296-2332", "hours": "12:00 PM – 9:00 PM (Daily)"},
    {"key": "tomas-morato", "name": "Tomas Morato – Quezon City",
     "address": "Corner Tomas Morato Ave, Diliman, Quezon City, Metro Manila",
     "oic": "Chen Rongcales", "phone": "7-944-6449", "mobile": "0964-183-4408", "hours": "12:00 PM – 9:00 PM"},
    {"key": "fairview", "name": "Fairview – Quezon City",
     "address": "Lot 8, Blk 11, Dahlia Ave, West Fairview, Quezon City, Metro Manila",
     "oic": "Phi Divad", "phone": "(02) 7254-0989", "mobile": "0927-372-8172", "hours": "12:00 PM – 9:00 PM (Daily)"},
    {"key": "valenzuela", "name": "Valenzuela",
     "address": "Unit 17-B, 2/F Valtown Center, Valenzuela",
     "oic": "Amegin Suarez", "phone": "8511-5559", "mobile": "0946-799-6406", "hours": "11:00 AM – 8:00 PM (Daily)"},
]


def tel_href(number):
    """'tel:' link in international form: Metro Manila landlines get +632, mobiles +63."""
    digits = "".join(ch for ch in number or "" if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("09"):
        return "tel:+63" + digits[1:]
    if digits.startswith("02"):
        digits = digits[2:]
    return "tel:+632" + digits


class Website(models.Model):
    _inherit = "website"

    def _to_is_overruns(self):
        """The Trendy Overruns website: its company is the Overruns company.

        The shared header, footer and Contact page get Overruns content only here,
        so the Autoboutique website keeps its own."""
        self.ensure_one()
        return "overruns" in (self.company_id.name or "").lower()

    def _to_branches(self):
        return [dict(branch, phone_href=tel_href(branch["phone"]), mobile_href=tel_href(branch["mobile"]))
                for branch in BRANCHES]

    def _to_tiktok_url(self):
        return TIKTOK_URL
