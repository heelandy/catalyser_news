import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import macro_pipeline_alerts as alerts_mod


def snapshot(title, regime="mixed", status="waiting_actual"):
    return {
        "release_time": "2026-06-18T12:30:00",
        "title": title,
        "source": "tradingview",
        "event_family": "test",
        "catalyst_category": "test",
        "status": status,
        "previous": "",
        "forecast": "",
        "actual": "",
        "market_bias_side": "",
        "direction": "mixed",
        "bullish_probability": 0.5,
        "confidence": 0.2,
        "confidence_label": "",
        "warning": "",
        "live_market_regime": f"{regime}_tape_news",
        "live_market_regime_direction": regime,
        "live_market_regime_reason": "reason " * 60,
        "market_regime_conflict": "none",
        "trade_state": "watch_only",
        "trade_state_reason": "",
    }


class AlertClusteringTests(unittest.TestCase):
    def test_regime_change_collapses_into_one_alert(self):
        titles = ["CPI MM, SA", "Retail Sales MM", "Fed Funds Tgt Rate", "Building Permits"]
        previous = {f"t|{t}|s": snapshot(t, regime="mixed") for t in titles}
        current = {f"t|{t}|s": snapshot(t, regime="bearish") for t in titles}

        alerts = alerts_mod.signal_alerts(current, previous, False, 0.10, 0.15)
        regime_alerts = [a for a in alerts if a["alert_type"] == "live_regime_changed"]

        self.assertEqual(len(regime_alerts), 1)
        alert = regime_alerts[0]
        self.assertEqual(alert["severity"], "high")
        self.assertEqual(alert["title"], "Live Market Regime")
        self.assertIn("affecting 4 catalysts", alert["message"])
        self.assertIn("CPI MM, SA", alert["message"])
        self.assertLess(len(alert["message"]), 600)

    def test_single_regime_change_keeps_signal_title(self):
        previous = {"t|CPI|s": snapshot("CPI", regime="mixed")}
        current = {"t|CPI|s": snapshot("CPI", regime="bullish")}

        alerts = alerts_mod.signal_alerts(current, previous, False, 0.10, 0.15)
        regime_alerts = [a for a in alerts if a["alert_type"] == "live_regime_changed"]

        self.assertEqual(len(regime_alerts), 1)
        self.assertEqual(regime_alerts[0]["title"], "CPI")
        self.assertEqual(regime_alerts[0]["severity"], "medium")

    def test_many_new_signals_collapse_into_one_alert(self):
        previous = {"t|Old|s": snapshot("Old")}
        current = dict(previous)
        for title in ["A", "B", "C"]:
            current[f"t|{title}|s"] = snapshot(title)

        alerts = alerts_mod.signal_alerts(current, previous, False, 0.10, 0.15)
        new_alerts = [a for a in alerts if a["alert_type"] == "new_signal"]

        self.assertEqual(len(new_alerts), 1)
        self.assertIn("3 new macro signals", new_alerts[0]["message"])


if __name__ == "__main__":
    unittest.main()
