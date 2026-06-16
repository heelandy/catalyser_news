import json
import unittest

import pandas as pd

import macro_subscriber_fields as subscriber


class SubscriberFieldTests(unittest.TestCase):
    def sample_row(self):
        return {
            "release_time": "2026-06-15T12:30:00",
            "title": "Nonfarm Payrolls",
            "event_family": "nfp",
            "release_status": "released",
            "previous": "179K",
            "forecast": "80K",
            "actual": "172K",
            "final_expected_direction": "bearish",
            "final_confidence": "0.82",
            "trade_state": "no_long_wait_for_reclaim",
            "trade_state_reason": "Release is bearish; avoid long NQ until tape confirms.",
            "market_rule_note": "Hot labor data can lift Fed pressure.",
            "live_market_regime_reason": "Yields and tape are bearish.",
            "market_regime_conflict": "none",
        }

    def test_enrich_signal_row_adds_standard_subscriber_fields(self):
        row = self.sample_row()
        fields = subscriber.enrich_signal_row(
            row,
            {
                "source": "data/NQ_5min_data.csv",
                "last_bar_time": "2026-06-15 12:25:00",
                "latest_close": 21500.25,
                "recent_high": 21540.0,
                "recent_low": 21480.5,
            },
        )

        self.assertIn("Nonfarm Payrolls", fields["subscriber_summary"])
        self.assertIn("Bearish", fields["expected_market_effect"])
        self.assertEqual(fields["standardized_risk_level"], "HIGH")
        self.assertIn("Hot labor data", fields["subscriber_reasoning"])
        self.assertIn("Wait", fields["risk_warning"])
        self.assertEqual(fields["expires_at"], "2026-06-15T14:30:00Z")
        self.assertIn("Educational", fields["educational_disclaimer"])

        watch = json.loads(fields["watch_levels_json"])
        self.assertEqual(watch["recent_high"], 21540.0)
        self.assertEqual(watch["recent_low"], 21480.5)
        self.assertIn("invalidation", watch)

    def test_fomc_signals_get_longer_expiry(self):
        row = {
            **self.sample_row(),
            "event_family": "fomc_rates",
            "title": "Fed Funds Tgt Rate",
        }
        self.assertEqual(
            subscriber.enrich_signal_row(row)["expires_at"],
            "2026-06-15T16:30:00Z",
        )

    def test_enrich_signal_frame_preserves_rows_and_adds_columns(self):
        frame = pd.DataFrame([self.sample_row()])
        enriched = subscriber.enrich_signal_frame(frame)

        self.assertEqual(len(enriched), 1)
        for column in subscriber.SUBSCRIBER_FIELD_COLUMNS:
            self.assertIn(column, enriched.columns)


if __name__ == "__main__":
    unittest.main()
