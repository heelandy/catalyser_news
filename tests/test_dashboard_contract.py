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

    def test_dashboard_alert_popup_contract(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("alertPopupLayer", html)
        self.assertIn("staleBanner", html)
        self.assertIn("maybeShowAlertPopups", app)
        self.assertIn("renderAlertPopupCard", app)
        self.assertIn("renderStaleBanner", app)
        self.assertIn("Mixed Bias — Use Caution", app)
        self.assertIn("setInterval", app)
        self.assertIn(".alert-popup", styles)
        self.assertIn(".popup-tile", styles)
        self.assertIn(".popup-caution", styles)
        self.assertIn(".stale-banner", styles)

    def test_dashboard_master_detail_interactions(self):
        app = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "dashboard" / "styles.css").read_text(encoding="utf-8")

        # Fixed overlays with their own display value override the hidden
        # attribute and silently shield the page from clicks/scroll, so every
        # such element needs an explicit [hidden] display:none rule.
        self.assertIn(".alert-popup-layer[hidden]", styles)
        self.assertIn(".stale-banner[hidden]", styles)

        self.assertIn("selectSignalRow", app)
        self.assertIn("openSignalPopup", app)
        self.assertIn("moveSelection", app)
        self.assertIn("dblclick", app)
        self.assertIn("ArrowDown", app)
        self.assertIn("surpriseText", app)
        self.assertIn("scrollTop", app)
        self.assertIn("max-height: calc(100vh - 120px)", styles)

    def test_dashboard_asset_versions_are_present(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertRegex(html, r"styles\.css\?v=[0-9a-f]{12}")
        self.assertRegex(html, r"app\.js\?v=[0-9a-f]{12}")

    def test_dashboard_email_test_contract(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="emailBtn"', html)
        self.assertIn('id="emailDialog"', html)
        self.assertIn('id="sendTestEmailBtn"', html)
        self.assertIn("../api/email-status", app)
        self.assertIn("../api/test-email", app)
        self.assertIn("openEmailDialog", app)
        self.assertIn("sendTestEmail", app)
        self.assertIn("Automatic popup-to-email delivery is enabled", app)
        self.assertIn(".settings-dialog", styles)
        self.assertIn(".email-test-result.success", styles)


if __name__ == "__main__":
    unittest.main()
