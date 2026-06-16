import json
import tempfile
import unittest
from pathlib import Path

import macro_source_health as health


class SourceHealthTests(unittest.TestCase):
    def test_records_attempts_and_consecutive_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "health.json"
            history_path = Path(tmp) / "health.jsonl"

            health.record_attempts(
                "news_feed",
                [{"provider": "yahoo", "ok": False, "rows": 0, "error": "timeout"}],
                summary_path=summary_path,
                history_path=history_path,
                checked_at="2026-06-16T10:00:00Z",
            )
            summary = health.record_attempts(
                "news_feed",
                [{"provider": "yahoo", "ok": True, "rows": 3}],
                source_used="yahoo",
                summary_path=summary_path,
                history_path=history_path,
                checked_at="2026-06-16T10:01:00Z",
            )

            provider = summary["providers"]["news_feed:yahoo"]
            self.assertEqual(provider["attempts"], 2)
            self.assertEqual(provider["successes"], 1)
            self.assertEqual(provider["failures"], 1)
            self.assertEqual(provider["consecutive_failures"], 0)
            self.assertEqual(summary["latest_source_used_by_type"]["news_feed"], "yahoo")

            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["providers"]["news_feed:yahoo"]["latest_rows"], 3)
            self.assertEqual(len(history_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_failure_streak_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = health.record_attempts(
                "economic_calendar",
                [
                    {"provider": "tradingview_calendar", "ok": False, "rows": 0, "error": "429"},
                    {"provider": "tradingview_calendar", "ok": False, "rows": 0, "error": "timeout"},
                ],
                summary_path=Path(tmp) / "health.json",
                history_path=Path(tmp) / "health.jsonl",
            )

            provider = summary["providers"]["economic_calendar:tradingview_calendar"]
            self.assertEqual(provider["consecutive_failures"], 2)
            self.assertFalse(provider["latest_ok"])


if __name__ == "__main__":
    unittest.main()
