from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrendyOverrunsPages(TransactionCase):
    """Branch contact details and the About Us page, from the brand brief."""

    def render(self, template, **values):
        return str(self.env["ir.qweb"]._render(template, values))

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
