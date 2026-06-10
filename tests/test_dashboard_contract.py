import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardContractTests(unittest.TestCase):
    def test_dashboard_loads_news_summary_and_stale_warning_contract(self):
        app = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("macro_news_feed_summary.json", app)
        self.assertIn("state.newsSummary", app)
        self.assertIn("News summary JSON could not be loaded", app)
        self.assertIn("News feed stale", app)
        self.assertIn("news-warning", app)
        self.assertIn(".news-warning", styles)
        self.assertIn(".news-meta", styles)

    def test_dashboard_asset_versions_are_present(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertRegex(html, r"styles\.css\?v=[0-9a-f]{12}")
        self.assertRegex(html, r"app\.js\?v=[0-9a-f]{12}")


if __name__ == "__main__":
    unittest.main()
