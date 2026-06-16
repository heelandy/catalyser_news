#!/usr/bin/env python3
"""
macro_subscriber_fields.py

Standard subscriber-facing fields for macro catalyst signals.

This is intentionally separate from fetching, calibration, trust weighting, and
daily confirmation. It takes the final signal rows and adds the fields the web
app and paid alert delivery need consistently:

- subscriber_summary
- expected_market_effect
- standardized_risk_level
- watch_levels_json
- invalidation_scenario
- expires_at
- time_sensitivity
- educational_disclaimer
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DISCLAIMER = "Educational and informational use only. This is not financial advice."
SUBSCRIBER_FIELD_COLUMNS = [
    "subscriber_summary",
    "expected_market_effect",
    "standardized_risk_level",
    "subscriber_reasoning",
    "risk_warning",
    "watch_levels_json",
    "invalidation_scenario",
    "expires_at",
    "time_sensitivity",
    "educational_disclaimer",
]


def clean(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except TypeError:
        pass
    text = str(value).strip()
    return text if text else fallback


def first_clean(row: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = clean(row.get(key))
        if value:
            return value
    return fallback


def parse_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def probability_percent(value: Any) -> int:
    number = parse_float(value)
    if number is None:
        return 0
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def final_direction(row: dict[str, Any]) -> str:
    return first_clean(
        row,
        "final_expected_direction",
        "trust_adjusted_direction",
        "expected_direction",
        fallback="mixed",
    ).lower()


def final_confidence(row: dict[str, Any]) -> int:
    return probability_percent(
        first_clean(row, "final_confidence", "trust_adjusted_confidence", "confidence")
    )


def parse_engine_time(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_market_snapshot(path: str | Path | None, lookback: int = 24) -> dict[str, Any]:
    if not path:
        return {}
    market_path = Path(path)
    if not market_path.exists():
        return {}

    rows: list[dict[str, str]] = []
    with market_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            rows.append(row)
    if not rows:
        return {}

    recent = rows[-lookback:]
    closes = [parse_float(row.get("close")) for row in recent]
    highs = [parse_float(row.get("high")) for row in recent]
    lows = [parse_float(row.get("low")) for row in recent]
    closes = [value for value in closes if value is not None]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    last = rows[-1]
    latest_close = parse_float(last.get("close"))
    if latest_close is None and closes:
        latest_close = closes[-1]

    return {
        "source": str(market_path),
        "last_bar_time": clean(last.get("date") or last.get("time") or last.get("timestamp")),
        "latest_close": latest_close,
        "recent_high": max(highs) if highs else None,
        "recent_low": min(lows) if lows else None,
    }


def standardized_risk_level(row: dict[str, Any]) -> str:
    warning = first_clean(row, "final_warning", "trust_warning", "warning").lower()
    trade_state = first_clean(row, "trade_state").lower()
    conflict = first_clean(row, "market_regime_conflict", fallback="none").lower()
    event_family = first_clean(row, "event_family").lower()
    confidence = final_confidence(row)
    released = first_clean(row, "release_status").lower() == "released" or bool(
        first_clean(row, "actual", "actual_value")
    )

    if "risk_lock" in warning:
        return "CRITICAL"
    if conflict not in {"", "none", "--"} or trade_state.startswith("no_long"):
        return "HIGH"
    if "avoid long" in warning or "no long" in warning or "whipsaw" in warning:
        return "HIGH"
    if event_family in {"fomc_rates", "fomc_statement", "cpi", "nfp"} and released:
        return "MEDIUM"
    if confidence >= 75:
        return "MEDIUM"
    return "LOW"


def subscriber_summary(row: dict[str, Any]) -> str:
    title = first_clean(row, "title", fallback="Macro catalyst")
    status = first_clean(row, "release_status", fallback="unknown").lower()
    actual = first_clean(row, "actual", "actual_value")
    forecast = first_clean(row, "forecast", "forecast_value")
    previous = first_clean(row, "previous", "previous_value")
    direction = final_direction(row)
    confidence = final_confidence(row)

    if status == "released" or actual:
        values = f"actual {actual or '--'}, forecast {forecast or '--'}, previous {previous or '--'}"
    elif forecast or previous:
        values = f"waiting for actual; forecast {forecast or '--'}, previous {previous or '--'}"
    else:
        values = "waiting for confirmed release values"

    return (
        f"{title}: {values}. Current model reads {direction} for NQ/Nasdaq "
        f"with {confidence}% confidence."
    )


def expected_market_effect(row: dict[str, Any]) -> str:
    direction = final_direction(row)
    trade_state = first_clean(row, "trade_state", fallback="watch_only").lower()
    conflict = first_clean(row, "market_regime_conflict", fallback="none").lower()

    if conflict not in {"", "none", "--"}:
        return (
            "Release rule and live market regime disagree. Treat the signal as a no-trade "
            "filter until NQ tape confirms the direction."
        )
    if direction == "bullish":
        if trade_state.startswith("long"):
            return "Bullish for NQ/Nasdaq if price holds the confirmation zone; prefer pullback/reclaim confirmation."
        return "Bullish lean for NQ/Nasdaq, but wait for tape confirmation before chasing upside."
    if direction == "bearish":
        if trade_state.startswith("no_long"):
            return "Bearish or risk-off for NQ/Nasdaq; avoid long exposure until reclaim confirmation."
        return "Bearish lean for NQ/Nasdaq; favor defensive posture until price reclaims key levels."
    if direction == "neutral":
        return "Neutral macro read; expect volatility but no clean directional edge without tape confirmation."
    return "Mixed macro read; use caution and wait for a clean NQ reclaim or breakdown."


def subscriber_reasoning(row: dict[str, Any]) -> str:
    parts = [
        first_clean(row, "market_rule_note"),
        first_clean(row, "trade_state_reason"),
        first_clean(row, "live_market_regime_reason"),
        first_clean(row, "daily_confirmation_note"),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return "; ".join(seen) or expected_market_effect(row)


def risk_warning(row: dict[str, Any]) -> str:
    warning = first_clean(
        row,
        "final_warning",
        "trust_warning",
        "warning",
        fallback="Wait for post-release tape confirmation before acting on this signal.",
    )
    risk = standardized_risk_level(row)
    if risk in {"HIGH", "CRITICAL"} and "Wait for" not in warning:
        return f"{warning}; Wait for confirmation and respect risk limits."
    return warning


def round_level(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 4) / 4


def watch_levels(row: dict[str, Any], market_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    market_snapshot = market_snapshot or {}
    direction = final_direction(row)
    trade_state = first_clean(row, "trade_state", fallback="watch_only")
    levels = {
        "source": "python_engine",
        "market_data_source": market_snapshot.get("source"),
        "market_data_last_bar": market_snapshot.get("last_bar_time"),
        "release_time": first_clean(row, "release_time", "date"),
        "trade_state": trade_state,
        "latest_close": round_level(market_snapshot.get("latest_close")),
        "recent_high": round_level(market_snapshot.get("recent_high")),
        "recent_low": round_level(market_snapshot.get("recent_low")),
    }

    recent_high = levels["recent_high"]
    recent_low = levels["recent_low"]
    if direction == "bullish":
        levels["confirmation"] = f"Hold above {recent_low}" if recent_low is not None else "Hold above reclaim zone"
        levels["invalidation"] = f"Lose {recent_low}" if recent_low is not None else "Lose confirmation zone"
        levels["upside_reclaim"] = recent_high
    elif direction == "bearish":
        levels["confirmation"] = f"Reject below {recent_high}" if recent_high is not None else "Reject below resistance"
        levels["invalidation"] = f"Reclaim {recent_high}" if recent_high is not None else "Reclaim resistance"
        levels["downside_break"] = recent_low
    else:
        levels["confirmation"] = "Break and hold outside current range"
        levels["range_high"] = recent_high
        levels["range_low"] = recent_low

    return {key: value for key, value in levels.items() if value not in {None, ""}}


def invalidation_scenario(row: dict[str, Any], levels: dict[str, Any]) -> str:
    direction = final_direction(row)
    conflict = first_clean(row, "market_regime_conflict", fallback="none").lower()
    if conflict not in {"", "none", "--"}:
        return "Directional alert invalidates until release rule and live market regime agree again."
    if direction == "bullish":
        level = levels.get("recent_low")
        return f"Bullish read invalidates if NQ loses {level} and live regime turns bearish." if level else "Bullish read invalidates if NQ loses the confirmation zone and live regime turns bearish."
    if direction == "bearish":
        level = levels.get("recent_high")
        return f"Bearish read invalidates if NQ reclaims {level} and live regime turns bullish." if level else "Bearish read invalidates if NQ reclaims resistance and live regime turns bullish."
    return "Mixed read invalidates only after a confirmed reclaim or breakdown creates a clearer directional regime."


def expiry_fields(row: dict[str, Any]) -> tuple[str, str]:
    release_time = parse_engine_time(first_clean(row, "release_time", "date"))
    event_family = first_clean(row, "event_family").lower()
    hours = 4 if event_family.startswith("fomc") else 2
    if not release_time:
        return "", "No explicit expiry set; refresh after the next pipeline cycle."
    expires_at = release_time + timedelta(hours=hours)
    return iso_z(expires_at), f"Valid until {iso_z(expires_at)} unless tape/regime changes first."


def enrich_signal_row(row: dict[str, Any], market_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    levels = watch_levels(row, market_snapshot)
    expires_at, time_sensitivity = expiry_fields(row)
    return {
        "subscriber_summary": subscriber_summary(row),
        "expected_market_effect": expected_market_effect(row),
        "standardized_risk_level": standardized_risk_level(row),
        "subscriber_reasoning": subscriber_reasoning(row),
        "risk_warning": risk_warning(row),
        "watch_levels_json": json.dumps(levels, sort_keys=True, separators=(",", ":")),
        "invalidation_scenario": invalidation_scenario(row, levels),
        "expires_at": expires_at,
        "time_sensitivity": time_sensitivity,
        "educational_disclaimer": DISCLAIMER,
    }


def enrich_signal_frame(signals: pd.DataFrame, market_data_path: str | Path | None = None) -> pd.DataFrame:
    market_snapshot = load_market_snapshot(market_data_path)
    rows = []
    for _, signal in signals.iterrows():
        out = signal.to_dict()
        out.update(enrich_signal_row(out, market_snapshot))
        rows.append(out)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add subscriber-ready fields to macro signal CSVs.")
    parser.add_argument("--signals", default="macro_live_signal_current.csv")
    parser.add_argument("--output", default="macro_live_signal_current.csv")
    parser.add_argument("--market-data", default="data/NQ_5min_data.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    signals = pd.read_csv(args.signals)
    enriched = enrich_signal_frame(signals, args.market_data)
    enriched.to_csv(args.output, index=False)
    print(f"Wrote {len(enriched)} subscriber-enriched signal rows to {args.output}.")


if __name__ == "__main__":
    main()
