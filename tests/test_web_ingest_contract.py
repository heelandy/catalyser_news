import json
import unittest

import macro_web_ingest as ingest


class WebIngestContractTests(unittest.TestCase):
    def sample_row(self):
        return {
            "release_time": "2026-06-15T12:30:00",
            "title": "Nonfarm Payrolls",
            "source": "TradingView",
            "source_url": "https://www.tradingview.com/economic-calendar/",
            "event_family": "nfp",
            "release_status": "released",
            "previous": "179K",
            "forecast": "80K",
            "actual": "172K",
            "release_rule_direction": "bearish",
            "live_market_regime_direction": "bearish",
            "final_expected_direction": "bearish",
            "final_bullish_probability": "0.22",
            "final_confidence": "0.82",
            "trade_state": "no_long_wait_for_reclaim",
            "trade_state_reason": "Release is bearish; avoid long NQ until tape confirms.",
            "final_warning": "Release rule is bearish and live regime is bearish.",
            "market_regime_conflict": "none",
            "market_rule_note": "Hot labor data can lift Fed pressure.",
            "live_market_regime_reason": "Yields and tape are bearish.",
            "subscriber_summary": "Hot NFP creates downside pressure for NQ.",
            "expected_market_effect": "Bearish for NQ/Nasdaq; avoid longs until reclaim confirmation.",
            "standardized_risk_level": "HIGH",
            "subscriber_reasoning": "Hot labor data can lift yields and pressure growth stocks.",
            "risk_warning": "Wait for reclaim before considering long NQ.",
            "watch_levels_json": '{"recent_high":21540.0,"recent_low":21480.5,"source":"test"}',
            "invalidation_scenario": "Bearish read invalidates if NQ reclaims 21540.",
            "expires_at": "2026-06-15T14:30:00Z",
            "educational_disclaimer": "Educational and informational use only. This is not financial advice.",
        }

    def test_build_payload_maps_signal_row_to_canonical_contract(self):
        payload = ingest.build_payload(
            self.sample_row(), generated_at="2026-06-15T13:00:00Z"
        )

        ingest.validate_payload(payload)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["newsEvent"]["occurredAt"], "2026-06-15T12:30:00Z")
        self.assertEqual(payload["marketReaction"]["finalBias"], "BEARISH")
        self.assertEqual(payload["marketReaction"]["confidence"], 82)
        self.assertEqual(payload["marketReaction"]["bullishProbability"], 22.0)
        self.assertEqual(payload["marketReaction"]["riskLevel"], "HIGH")
        self.assertEqual(payload["marketReaction"]["expectedReaction"], "Bearish for NQ/Nasdaq; avoid longs until reclaim confirmation.")
        self.assertEqual(payload["marketReaction"]["watchLevels"]["recent_high"], 21540.0)
        self.assertEqual(payload["marketReaction"]["invalidation"], "Bearish read invalidates if NQ reclaims 21540.")
        self.assertEqual(payload["marketReaction"]["expiresAt"], "2026-06-15T14:30:00Z")
        self.assertEqual(payload["alert"]["state"], "PENDING")
        self.assertEqual(payload["alert"]["summary"], "Hot NFP creates downside pressure for NQ.")
        self.assertIn("Educational", payload["alert"]["disclaimer"])

    def test_waiting_rows_are_skipped_unless_requested(self):
        row = self.sample_row()
        row["release_status"] = "waiting_actual"
        row["actual"] = ""
        row["trade_state"] = "watch_only"

        self.assertFalse(ingest.alertable(row, include_waiting=False))
        self.assertTrue(ingest.alertable(row, include_waiting=True))

    def test_risk_lock_rows_are_alertable_and_high_risk(self):
        row = self.sample_row()
        row["release_status"] = "waiting_actual"
        row["actual"] = ""
        row["market_regime_conflict"] = "market_regime_conflict"

        self.assertTrue(ingest.alertable(row, include_waiting=False))
        self.assertEqual(ingest.risk_level(row), "HIGH")

    def test_signature_uses_timestamp_and_body(self):
        body = json.dumps({"ok": True}, separators=(",", ":"), sort_keys=True)
        first = ingest.sign_body("0123456789abcdef0123456789abcdef", 1800000000, body)
        second = ingest.sign_body("0123456789abcdef0123456789abcdef", 1800000001, body)

        self.assertTrue(first.startswith("sha256="))
        self.assertNotEqual(first, second)

    def test_validate_payload_rejects_invalid_bias(self):
        payload = ingest.build_payload(
            self.sample_row(), generated_at="2026-06-15T13:00:00Z"
        )
        payload["alert"]["bias"] = "DOWN"

        with self.assertRaisesRegex(ValueError, "alert.bias is invalid"):
            ingest.validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
