import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.dashboard_server import email_status, valid_email


class DashboardServerTests(unittest.TestCase):
    def test_valid_email_accepts_one_address_only(self):
        self.assertTrue(valid_email("person@example.com"))
        self.assertFalse(valid_email("Person <person@example.com>"))
        self.assertFalse(valid_email("one@example.com,two@example.com"))
        self.assertFalse(valid_email("person@example.com\r\nBcc: other@example.com"))

    def test_email_status_reports_configuration_without_exposing_password(self):
        config = {
            "targets": "risk_lock,popup,email",
            "min_severity": "info",
            "email": {"to": "person@example.com", "from": "person@example.com"},
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "person@example.com",
                "password_env": "TEST_SMTP_PASSWORD",
                "starttls": True,
            },
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "tools.dashboard_server.user_environment", return_value="secret-value"
        ):
            path = Path(tmp) / "notify.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            status = email_status(path)

        self.assertTrue(status["configured"])
        self.assertTrue(status["automatic_enabled"])
        self.assertTrue(status["mirrors_dashboard_alerts"])
        self.assertTrue(status["password_present"])
        self.assertEqual(status["recipient"], "person@example.com")
        self.assertNotIn("password", status)
        self.assertNotIn("secret-value", json.dumps(status))

    def test_email_status_requires_password_when_smtp_user_is_set(self):
        config = {
            "email": {"to": "person@example.com", "from": "person@example.com"},
            "smtp": {"host": "smtp.example.com", "user": "person@example.com"},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "tools.dashboard_server.user_environment", return_value=""
        ):
            path = Path(tmp) / "notify.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            status = email_status(path)

        self.assertFalse(status["configured"])
        self.assertFalse(status["password_present"])


if __name__ == "__main__":
    unittest.main()
