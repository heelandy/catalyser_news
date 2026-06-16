#!/usr/bin/env python3
"""
macro_daily_confirmation.py

Separate daily confirmation layer for the macro signal contract.

This module lets the project use the daily 2020-2025 source that is available
now without pretending it is a 1m/5m reaction model. It reads the trust-adjusted
live signal, matches each row to a daily reaction profile, and writes a current
signal file with daily confirmation fields and lightly blended final
probabilities.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from macro_regime import apply_regime_to_frame, load_regime_context
from macro_subscriber_fields import enrich_signal_frame


MATCH_ORDER = [
    ("event_family_market_bias", ["event_family", "market_bias_side"]),
    ("category_market_bias", ["catalyst_category", "market_bias_side"]),
    ("event_family_side", ["event_family", "surprise_side"]),
    ("event_family_all", ["event_family"]),
    ("category_all", ["catalyst_category"]),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply separate daily confirmation profiles to live macro signals.")
    p.add_argument("--signals", default="macro_live_signal_adjusted.csv")
    p.add_argument("--daily-profiles", default="studies/macro_reaction_profiles_investing_daily.csv")
    p.add_argument("--output", default="macro_live_signal_current.csv")
    p.add_argument("--summary-output", default="macro_daily_confirmation_report.json")
    p.add_argument("--source-label", default="investing_daily_clean")
    p.add_argument("--bullish-threshold", type=float, default=0.57)
    p.add_argument("--bearish-threshold", type=float, default=0.43)
    p.add_argument("--max-blend-weight", type=float, default=0.18)
    p.add_argument("--min-sample-size", type=int, default=3)
    p.add_argument("--sample-prior", type=float, default=12.0)
    p.add_argument("--regime-context", default="macro_regime_context.json", help="Optional manual/news regime context JSON")
    p.add_argument("--generated-regime-context", default="macro_live_regime_context.json", help="Generated tape/news regime context JSON")
    p.add_argument("--market-data", default="data/NQ_5min_data.csv", help="Live market data CSV used for subscriber watch levels")
    return p.parse_args()


def as_float(value: Any, default: float = np.nan) -> float:
    if value is None or value == "":
        return default
    try:
        out = float(value)
    except Exception:
        return default
    return default if pd.isna(out) else out


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def text_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def warning_text(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        if part is None or pd.isna(part):
            continue
        for token in str(part or "").split(";"):
            clean = token.strip()
            if clean and clean not in tokens:
                tokens.append(clean)
    return ";".join(tokens)


def direction_from_probability(probability: float, bullish_threshold: float, bearish_threshold: float) -> str:
    if probability >= bullish_threshold:
        return "bullish"
    if probability <= bearish_threshold:
        return "bearish"
    return "mixed"


def signal_surprise_side(signal: pd.Series) -> str:
    return text_value(signal.get("surprise_side") or signal.get("raw_surprise_side"))


def profile_matches(signal: pd.Series, profiles: pd.DataFrame, group_type: str, keys: list[str]) -> pd.DataFrame:
    if "group_type" not in profiles.columns:
        return pd.DataFrame()
    candidates = profiles[profiles["group_type"].fillna("").astype(str) == group_type]
    for key in keys:
        if key not in candidates.columns:
            return pd.DataFrame()
        if key == "surprise_side":
            signal_value = signal_surprise_side(signal)
        else:
            signal_value = text_value(signal.get(key))
        if not signal_value:
            return pd.DataFrame()
        candidates = candidates[candidates[key].fillna("").astype(str).str.strip() == signal_value]
    if candidates.empty:
        return candidates
    candidates = candidates.copy()
    candidates["sample_size"] = pd.to_numeric(candidates.get("sample_size"), errors="coerce").fillna(0)
    candidates["sample_confidence"] = pd.to_numeric(candidates.get("sample_confidence"), errors="coerce").fillna(0)
    candidates["edge"] = (pd.to_numeric(candidates.get("bullish_probability"), errors="coerce").fillna(0.5) - 0.5).abs()
    return candidates.sort_values(["sample_confidence", "sample_size", "edge"], ascending=False)


def find_daily_profile(signal: pd.Series, profiles: pd.DataFrame) -> pd.Series | None:
    for group_type, keys in MATCH_ORDER:
        candidates = profile_matches(signal, profiles, group_type, keys)
        if not candidates.empty:
            return candidates.iloc[0]
    return None


def base_probability(signal: pd.Series) -> float:
    return clamp(
        as_float(
            signal.get("final_bullish_probability"),
            as_float(
                signal.get("trust_adjusted_bullish_probability"),
                as_float(signal.get("calibrated_bullish_probability"), 0.5),
            ),
        ),
        0.0,
        1.0,
    )


def base_confidence(signal: pd.Series) -> float:
    return clamp(
        as_float(
            signal.get("final_confidence"),
            as_float(signal.get("trust_adjusted_confidence"), as_float(signal.get("confidence"), 0.0)),
        ),
        0.0,
        1.0,
    )


def profile_key(profile: pd.Series) -> str:
    pieces = [text_value(profile.get("group_type"))]
    for key in ["event_family", "catalyst_category", "surprise_side", "market_bias_side"]:
        value = text_value(profile.get(key))
        if value:
            pieces.append(f"{key}={value}")
    return "|".join(pieces)


def confirmation_match(base_direction: str, daily_direction: str) -> str:
    if daily_direction == "mixed":
        return "neutral"
    if base_direction == "mixed":
        return "daily_leans"
    if daily_direction == base_direction:
        return "with_signal"
    return "against_signal"


def apply_daily_confirmation(signal: pd.Series, profile: pd.Series | None, args: argparse.Namespace) -> dict[str, Any]:
    base_bull = base_probability(signal)
    base_bear = 1.0 - base_bull
    base_conf = base_confidence(signal)
    base_dir = text_value(signal.get("final_expected_direction") or signal.get("trust_adjusted_direction") or signal.get("expected_direction") or "mixed").lower()
    base_warning = signal.get("final_warning") or signal.get("trust_warning") or signal.get("warning") or ""

    if profile is None:
        return {
            "base_final_bullish_probability": base_bull,
            "base_final_bearish_probability": base_bear,
            "base_final_expected_direction": base_dir,
            "base_final_confidence": base_conf,
            "daily_confirmation_source": args.source_label,
            "daily_confirmation_group_type": "",
            "daily_confirmation_group_key": "",
            "daily_confirmation_sample_size": 0,
            "daily_confirmation_bullish_probability": np.nan,
            "daily_confirmation_bearish_probability": np.nan,
            "daily_confirmation_expected_direction": "unknown",
            "daily_confirmation_match": "no_profile",
            "daily_confirmation_weight": 0.0,
            "daily_confirmation_avg_return_pts": np.nan,
            "daily_confirmation_market_move_probability": np.nan,
            "daily_confirmation_confidence_label": "",
            "daily_confirmation_note": "No matching daily profile; trust-adjusted signal left unchanged.",
            "final_bullish_probability": base_bull,
            "final_bearish_probability": base_bear,
            "final_expected_direction": base_dir,
            "final_confidence": base_conf,
            "final_confidence_label": text_value(signal.get("final_confidence_label") or signal.get("trust_adjusted_confidence_label") or signal.get("confidence_label")),
            "final_warning": warning_text(base_warning, "no_daily_confirmation"),
        }

    sample_size = int(as_float(profile.get("sample_size"), 0))
    daily_bull = clamp(as_float(profile.get("bullish_probability"), 0.5), 0.0, 1.0)
    daily_bear = 1.0 - daily_bull
    daily_dir = direction_from_probability(daily_bull, args.bullish_threshold, args.bearish_threshold)
    match = confirmation_match(base_dir, daily_dir)
    sample_reliability = sample_size / (sample_size + args.sample_prior) if sample_size > 0 else 0.0
    edge = abs(daily_bull - 0.5) * 2.0
    blend_weight = clamp(args.max_blend_weight * sample_reliability * edge, 0.0, args.max_blend_weight)
    if sample_size < args.min_sample_size:
        blend_weight = 0.0

    final_bull = clamp(base_bull + blend_weight * (daily_bull - base_bull), 0.0, 1.0)
    final_bear = 1.0 - final_bull
    final_dir = direction_from_probability(final_bull, args.bullish_threshold, args.bearish_threshold)

    if match == "with_signal":
        confidence_delta = blend_weight * 0.25
        daily_warning = ""
    elif match == "against_signal":
        confidence_delta = -blend_weight * 0.35
        daily_warning = "daily_confirmation_disagrees"
    elif match == "daily_leans":
        confidence_delta = blend_weight * 0.10
        daily_warning = ""
    else:
        confidence_delta = 0.0
        daily_warning = ""

    final_conf = clamp(base_conf + confidence_delta, 0.0, 1.0)
    final_label = "high" if final_conf >= 0.67 else "medium" if final_conf >= 0.45 else "low"

    return {
        "base_final_bullish_probability": base_bull,
        "base_final_bearish_probability": base_bear,
        "base_final_expected_direction": base_dir,
        "base_final_confidence": base_conf,
        "daily_confirmation_source": args.source_label,
        "daily_confirmation_group_type": text_value(profile.get("group_type")),
        "daily_confirmation_group_key": profile_key(profile),
        "daily_confirmation_sample_size": sample_size,
        "daily_confirmation_bullish_probability": daily_bull,
        "daily_confirmation_bearish_probability": daily_bear,
        "daily_confirmation_expected_direction": daily_dir,
        "daily_confirmation_match": match,
        "daily_confirmation_weight": blend_weight,
        "daily_confirmation_avg_return_pts": as_float(profile.get("avg_return_pts")),
        "daily_confirmation_market_move_probability": as_float(profile.get("market_move_probability")),
        "daily_confirmation_confidence_label": text_value(profile.get("confidence_label")),
        "daily_confirmation_note": (
            f"{args.source_label} {profile_key(profile)} sample={sample_size}, "
            f"daily_bull={daily_bull:.3f}, blend_weight={blend_weight:.3f}, match={match}"
        ),
        "final_bullish_probability": final_bull,
        "final_bearish_probability": final_bear,
        "final_expected_direction": final_dir,
        "final_confidence": final_conf,
        "final_confidence_label": final_label,
        "final_warning": warning_text(base_warning, daily_warning),
    }


def build_report(out: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    counts = out["daily_confirmation_match"].value_counts(dropna=False).to_dict()
    changed = (
        pd.to_numeric(out["final_bullish_probability"], errors="coerce")
        - pd.to_numeric(out["base_final_bullish_probability"], errors="coerce")
    ).abs()
    return {
        "signals": args.signals,
        "daily_profiles": args.daily_profiles,
        "output": args.output,
        "source_label": args.source_label,
        "rows": int(len(out)),
        "match_counts": {str(key): int(value) for key, value in counts.items()},
        "avg_abs_probability_adjustment": float(changed.mean()) if len(changed) else 0.0,
        "max_abs_probability_adjustment": float(changed.max()) if len(changed) else 0.0,
        "changed_direction_rows": int((out["final_expected_direction"].astype(str) != out["base_final_expected_direction"].astype(str)).sum()),
        "regime_conflict_counts": {str(key): int(value) for key, value in out.get("market_regime_conflict", pd.Series(dtype=str)).value_counts(dropna=False).to_dict().items()},
        "trade_state_counts": {str(key): int(value) for key, value in out.get("trade_state", pd.Series(dtype=str)).value_counts(dropna=False).to_dict().items()},
        "note": "Daily confirmation is a separate baseline layer. It does not replace 1m/5m release-reaction modeling.",
    }


def main() -> None:
    args = parse_args()
    signals = pd.read_csv(args.signals)
    profiles = pd.read_csv(args.daily_profiles)

    rows = []
    for _, signal in signals.iterrows():
        profile = find_daily_profile(signal, profiles)
        out = signal.to_dict()
        out.update(apply_daily_confirmation(signal, profile, args))
        rows.append(out)

    output = pd.DataFrame(rows)
    regime_context = load_regime_context(args.regime_context, output.to_dict("records"), args.generated_regime_context)
    output = apply_regime_to_frame(output, regime_context, args.bullish_threshold, args.bearish_threshold)
    output = enrich_signal_frame(output, args.market_data)
    output.to_csv(args.output, index=False)
    report = build_report(output, args)
    Path(args.summary_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote daily-confirmed current signal to {args.output}")
    print(f"Wrote daily confirmation report to {args.summary_output}")
    print(
        f"Rows={report['rows']}, matches={report['match_counts']}, "
        f"avg_adjustment={report['avg_abs_probability_adjustment']:.4f}"
    )


if __name__ == "__main__":
    main()
