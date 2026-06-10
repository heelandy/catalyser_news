import csv
import tempfile
import unittest
from pathlib import Path

import macro_alert_notify as notify
import macro_pipeline_alerts as alerts


class AlertRiskLockTests(unittest.TestCase):
    def test_signal_risk_lock_detects_release_positive_live_bearish(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "release_time",
                        "title",
                        "event_family",
                        "release_rule_direction",
                        "live_market_regime_direction",
                        "live_market_regime",
                        "market_regime_conflict",
                        "trade_state",
                        "trade_state_reason",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "release_time": "2026-06-10T08:30:00Z",
                        "title": "NFP",
                        "event_family": "labor",
                        "release_rule_direction": "bullish",
                        "live_market_regime_direction": "bearish",
                        "live_market_regime": "bearish_tape_news",
                        "market_regime_conflict": "market_regime_conflict",
                        "trade_state": "no_long_wait_for_reclaim",
                        "trade_state_reason": "Release rule is positive, but live regime is bearish.",
                    }
                )

            locks = notify.signal_risk_locks(path)

        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0]["severity"], "high")
        self.assertEqual(locks[0]["trade_state"], "no_long_wait_for_reclaim")

    def test_alert_detector_emits_risk_lock_triggered(self):
        previous = {
            "NFP": {
                "title": "NFP",
                "release_time": "2026-06-10T08:30:00Z",
                "direction": "bullish",
                "market_regime_conflict": "none",
                "trade_state": "watch_only",
                "live_market_regime_direction": "mixed",
            }
        }
        current = {
            "NFP": {
                **previous["NFP"],
                "market_regime_conflict": "market_regime_conflict",
                "trade_state": "no_long_wait_for_reclaim",
                "live_market_regime_direction": "bearish",
                "trade_state_reason": "Avoid long NQ until tape confirms.",
            }
        }

        emitted = alerts.signal_alerts(current, previous, False, 0.10, 0.15)
        types = {alert["alert_type"] for alert in emitted}

        self.assertIn("risk_lock_triggered", types)
        self.assertIn("live_regime_changed", types)


if __name__ == "__main__":
    unittest.main()
