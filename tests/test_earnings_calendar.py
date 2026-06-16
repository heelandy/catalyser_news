import unittest
from datetime import datetime, timezone

import catalyser_news as catalyser
import macro_earnings_calendar as earnings


class EarningsCalendarTests(unittest.TestCase):
    def test_yahoo_eps_beat_becomes_bullish_earnings_catalyst(self):
        payload = {
            "finance": {
                "result": [
                    {
                        "symbol": "NVDA",
                        "earnings": [
                            {
                                "ticker": "NVDA",
                                "companyshortname": "NVIDIA Corporation",
                                "startdatetime": "2026-06-20T20:00:00Z",
                                "epsestimate": 1.00,
                                "epsactual": 1.25,
                                "epssurprisepct": 25,
                            }
                        ],
                    }
                ]
            }
        }
        anchor = datetime(2026, 6, 16, tzinfo=timezone.utc)

        rows = earnings.normalize_yahoo_earnings("NVDA", payload, anchor, 2, 21)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast"], "1")
        self.assertEqual(rows[0]["actual"], "1.25")

        scored = catalyser.build_catalyst_rows(rows, as_of="2026-06-16", lookback_days=2, lookahead_days=21)
        self.assertEqual(scored[0]["catalyst_category"], "earnings")
        self.assertEqual(scored[0]["release_status"], "released")
        self.assertEqual(scored[0]["market_rule_direction"], "higher_is_bullish")
        self.assertEqual(scored[0]["market_bias_label"], "bullish")

    def test_estimate_without_actual_waits_for_release(self):
        payload = {
            "finance": {
                "result": [
                    {
                        "symbol": "MSFT",
                        "earnings": [
                            {
                                "ticker": "MSFT",
                                "startdatetime": "2026-06-21T12:00:00Z",
                                "epsestimate": 2.5,
                            }
                        ],
                    }
                ]
            }
        }
        anchor = datetime(2026, 6, 16, tzinfo=timezone.utc)

        rows = earnings.normalize_yahoo_earnings("MSFT", payload, anchor, 2, 21)
        scored = catalyser.build_catalyst_rows(rows, as_of="2026-06-16", lookback_days=2, lookahead_days=21)

        self.assertEqual(scored[0]["release_status"], "waiting_actual")
        self.assertEqual(scored[0]["forecast"], "2.5")
        self.assertEqual(scored[0]["actual"], "")

    def test_quote_summary_calendar_events_are_supported(self):
        payload = {
            "quoteSummary": {
                "result": [
                    {
                        "calendarEvents": {
                            "earnings": {
                                "earningsAverage": 3.0,
                                "earningsDate": [{"raw": 1782297600}],
                            }
                        }
                    }
                ]
            }
        }
        anchor = datetime(2026, 6, 16, tzinfo=timezone.utc)

        rows = earnings.normalize_yahoo_earnings("AAPL", payload, anchor, 2, 21)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast"], "3")
        self.assertIn("AAPL earnings", rows[0]["title"])


if __name__ == "__main__":
    unittest.main()
