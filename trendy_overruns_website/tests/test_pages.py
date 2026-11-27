from odoo.tests.common import TransactionCase, tagged

from ..models.website import tel_href


@tagged("post_install", "-at_install")
class TestTrendyOverrunsPages(TransactionCase):
    """Branch contact details, About Us, and the real numbers in place of Odoo's sample ones."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env["res.company"].create({"name": "Test Overruns"})
        cls.site = cls.env["website"].create({"name": "Test Trendy Overruns", "company_id": company.id})
        other = cls.env["res.company"].create({"name": "Test Other Shop"})
        cls.other_site = cls.env["website"].create({"name": "Test Other Website", "company_id": other.id})

    def render(self, template, website=None, **values):
        return str(self.env["ir.qweb"]._render(template, dict(values, website=website or self.site)))

    def test_phone_links(self):
        self.assertEqual(tel_href("7720-5279"), "tel:+63277205279")
        self.assertEqual(tel_href("7-944-6449"), "tel:+63279446449")
        self.assertEqual(tel_href("(02) 7254-0989"), "tel:+63272540989")
        self.assertEqual(tel_href("0963-296-2332"), "tel:+639632962332")
        self.assertEqual(tel_href(""), "")

    def test_branch_details(self):
        html = self.render("trendy_overruns_website.branch_cards", compact=False)
        for text in ("Lilac – Marikina", "Katipunan – Quezon City", "Tomas Morato – Quezon City",
                     "Fairview – Quezon City", "Valenzuela", "Anne Banadera", "0963-296-2332",
                     "tel:+63272540989", "11:00 AM – 8:00 PM (Daily)", "valenzuela-3.jpg"):
            self.assertIn(text, html)
        self.assertNotIn("to follow", html, "Unknown OIC or mobile numbers are left out")

        compact = self.render("trendy_overruns_website.branch_cards", compact=True)
        self.assertIn("/branches#katipunan", compact)
        self.assertNotIn("katipunan-2.jpg", compact, "The homepage shows only the storefront photo")

    def test_about_and_tiktok(self):
        about = self.env.ref("trendy_overruns_website.page_about")
        self.assertEqual(about.url, "/about-us")
        self.assertIn("Your style. Your choice. Your Trendy finds.", about.view_id.arch)
        self.assertIn("tiktok.com/@trendyoverruns_boutique", self.render("trendy_overruns_website.tiktok_cta"))

    def test_no_sample_numbers_on_overruns(self):
        self.assertTrue(self.site._to_is_overruns())
        self.assertFalse(self.other_site._to_is_overruns())
        # The Contact page, header and footer switch to the branch details on Overruns only.
        for xmlid in ("website.contactus", "website.layout", "website.placeholder_header_text_element"):
            arch = self.env.ref(xmlid).get_combined_arch()
            self.assertIn("_to_is_overruns()", arch, xmlid)
        branches = self.render("trendy_overruns_website.contact_branch_list")
        self.assertIn("tel:+63285115559", branches)
        self.assertIn("0927-372-8172", branches)
        self.assertNotIn("555-555-5556", branches)
