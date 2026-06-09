#!/usr/bin/env python3
"""
macro_signal_trust.py

Feedback calibration for the macro catalyst engine.

This module stays separate from:
  - catalyser_news.py, which fetches/scores live releases.
  - macro_reaction_study.py, which creates historical reaction probabilities.
  - macro_signal_performance.py, which grades predictions after the fact.

It reads macro_signal_performance.csv, converts accuracy/whipsaw history into
trust weights, then applies those weights to macro_live_signal.csv.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from macro_regime import apply_regime_to_frame, load_regime_context


LIVE_MATCH_ORDER = [
    ("event_family_market_bias", ["event_family", "market_bias_side"]),
    ("event_family", ["event_family"]),
    ("catalyst_category", ["catalyst_category"]),
    ("market_bias_side", ["market_bias_side"]),
    ("confidence_label", ["confidence_label"]),
    ("overall", []),
]


def as_float(value, default=np.nan) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return value
    return max(low, min(high, float(value)))


def text_value(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def confidence_label(value: float) -> str:
    if pd.isna(value):
        return "low"
    if value >= 0.70:
        return "high"
    if value >= 0.40:
        return "medium"
    return "low"


def direction_from_probability(probability: float, bullish_threshold: float, bearish_threshold: float) -> str:
    if pd.isna(probability):
        return "mixed"
    if probability >= bullish_threshold:
        return "bullish"
    if probability <= bearish_threshold:
        return "bearish"
    return "mixed"


def build_group_key(row: pd.Series) -> str:
    parts = [text_value(row.get("group_type"))]
    for col in ["reaction_source", "event_family", "catalyst_category", "market_bias_side", "confidence_label"]:
        value = text_value(row.get(col))
        if value:
            parts.append(f"{col}={value}")
    return "|".join(parts)


def trust_label(weight: float) -> str:
    if weight >= 1.15:
        return "boost"
    if weight >= 0.85:
        return "steady"
    if weight >= 0.60:
        return "discount"
    return "fade"


def trust_note(row: pd.Series) -> str:
    sample_size = as_float(row.get("sample_size"), 0)
    if pd.isna(sample_size):
        sample_size = 0
    return (
        f"{text_value(row.get('group_type'))} sample={int(sample_size)}, "
        f"smoothed_accuracy={as_float(row.get('smoothed_primary_accuracy'), 0.5):.3f}, "
        f"whipsaw={as_float(row.get('whipsaw_rate'), 0.0):.3f}"
    )


def calculate_trust_weight(
    row: pd.Series,
    prior_strength: float,
    min_weight: float,
    max_weight: float,
) -> dict:
    sample_size = max(0.0, as_float(row.get("sample_size"), 0.0))
    primary_accuracy = clamp(as_float(row.get("primary_accuracy"), 0.5), 0.0, 1.0)
    whipsaw_rate = clamp(as_float(row.get("whipsaw_rate"), 0.5), 0.0, 1.0)
    if pd.isna(primary_accuracy):
        primary_accuracy = 0.5
    if pd.isna(whipsaw_rate):
        whipsaw_rate = 0.5

    if sample_size <= 0:
        smoothed_accuracy = 0.5
    else:
        estimated_correct = primary_accuracy * sample_size
        smoothed_accuracy = (estimated_correct + 0.5 * prior_strength) / (sample_size + prior_strength)

    sample_reliability = sample_size / (sample_size + prior_strength * 2.0) if sample_size > 0 else 0.0
    accuracy_edge = (smoothed_accuracy - 0.5) * 2.0
    accuracy_gain = accuracy_edge * (0.55 + 0.25 * sample_reliability)
    whipsaw_penalty = whipsaw_rate * (0.20 + 0.15 * sample_reliability)
    small_sample_penalty = (1.0 - sample_reliability) * 0.04

    weight = clamp(1.0 + accuracy_gain - whipsaw_penalty - small_sample_penalty, min_weight, max_weight)
    return {
        "smoothed_primary_accuracy": smoothed_accuracy,
        "sample_reliability": sample_reliability,
        "trust_weight": weight,
        "trust_label": trust_label(weight),
    }


def build_trust_weights(
    performance: pd.DataFrame,
    prior_strength: float,
    min_weight: float,
    max_weight: float,
) -> pd.DataFrame:
    rows = []
    for _, row in performance.iterrows():
        if not text_value(row.get("group_type")):
            continue
        metrics = calculate_trust_weight(row, prior_strength, min_weight, max_weight)
        out = row.to_dict()
        out.update(metrics)
        out["group_key"] = build_group_key(row)
        out["usable_for_live_signal"] = (
            text_value(row.get("group_type")) in {spec[0] for spec in LIVE_MATCH_ORDER}
            and not text_value(row.get("reaction_source"))
        )
        out["trust_note"] = trust_note(pd.Series(out))
        rows.append(out)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(
        ["usable_for_live_signal", "group_type", "sample_size"],
        ascending=[False, True, False],
    ).reset_index(drop=True)


def load_csv(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    return pd.read_csv(p)


def best_weight_match(signal: pd.Series, weights: pd.DataFrame) -> pd.Series | None:
    if weights.empty:
        return None
    usable = weights[weights["usable_for_live_signal"] == True]  # noqa: E712
    if usable.empty:
        return None

    for group_type, keys in LIVE_MATCH_ORDER:
        candidates = usable[usable["group_type"].astype(str) == group_type]
        for key in keys:
            signal_value = text_value(signal.get(key))
            if not signal_value:
                candidates = candidates.iloc[0:0]
                break
            candidates = candidates[candidates[key].fillna("").astype(str).str.strip() == signal_value]
        if not candidates.empty:
            return candidates.sort_values(["sample_size", "sample_reliability"], ascending=False).iloc[0]
    return None


def warning_text(existing: str, parts: list[str]) -> str:
    clean = [text_value(existing)]
    clean.extend(part for part in parts if part)
    return ";".join(part for part in clean if part)


def apply_trust_to_signal(
    signal: pd.Series,
    match: pd.Series | None,
    bullish_threshold: float,
    bearish_threshold: float,
    min_probability: float,
    max_probability: float,
) -> dict:
    base_probability = as_float(
        signal.get("calibrated_bullish_probability"),
        as_float(signal.get("historical_bullish_probability"), 0.5),
    )
    if pd.isna(base_probability):
        base_probability = 0.5

    base_confidence = as_float(signal.get("confidence"), 0.0)
    if pd.isna(base_confidence):
        base_confidence = 0.0

    if match is None:
        trust_weight_value = 1.0
        sample_reliability = 0.0
        adjusted_confidence = base_confidence
        warning = warning_text(signal.get("warning", ""), ["no_trust_history"])
        trust_fields = {
            "trust_group_type": "",
            "trust_group_key": "",
            "trust_sample_size": 0,
            "trust_primary_accuracy": np.nan,
            "trust_smoothed_primary_accuracy": 0.5,
            "trust_whipsaw_rate": np.nan,
            "trust_sample_reliability": 0.0,
            "trust_weight": trust_weight_value,
            "trust_label": "steady",
            "trust_note": "no matching trust group",
            "trust_warning": warning,
        }
    else:
        trust_weight_value = as_float(match.get("trust_weight"), 1.0)
        broad_fallback_group = text_value(match.get("group_type")) in {"market_bias_side", "confidence_label", "overall"}
        fallback_boost_capped = broad_fallback_group and trust_weight_value > 1.0
        if fallback_boost_capped:
            trust_weight_value = 1.0
        sample_reliability = as_float(match.get("sample_reliability"), 0.0)
        adjusted_confidence = clamp(base_confidence * trust_weight_value * (0.85 + 0.30 * sample_reliability), 0.0, 0.99)
        warnings = []
        if broad_fallback_group:
            warnings.append("fallback_trust_group")
        if fallback_boost_capped:
            warnings.append("fallback_boost_capped")
        if as_float(match.get("sample_size"), 0.0) < 5:
            warnings.append("low_trust_sample")
        if as_float(match.get("whipsaw_rate"), 0.0) >= 0.50:
            warnings.append("performance_whipsaw")
        if trust_weight_value < 0.85:
            warnings.append("trust_discount")
        if trust_weight_value < 0.60:
            warnings.append("trust_fade")
        warning = warning_text(signal.get("warning", ""), warnings)
        trust_fields = {
            "trust_group_type": text_value(match.get("group_type")),
            "trust_group_key": text_value(match.get("group_key")),
            "trust_sample_size": int(as_float(match.get("sample_size"), 0)),
            "trust_primary_accuracy": as_float(match.get("primary_accuracy"), np.nan),
            "trust_smoothed_primary_accuracy": as_float(match.get("smoothed_primary_accuracy"), 0.5),
            "trust_whipsaw_rate": as_float(match.get("whipsaw_rate"), np.nan),
            "trust_sample_reliability": sample_reliability,
            "trust_weight": trust_weight_value,
            "trust_label": text_value(match.get("trust_label")),
            "trust_note": text_value(match.get("trust_note")),
            "trust_warning": warning,
        }

    adjusted_probability = clamp(
        0.5 + (base_probability - 0.5) * trust_weight_value,
        min_probability,
        max_probability,
    )
    confidence_caps = []
    confidence_cap = 0.99
    trust_sample_size = as_float(trust_fields.get("trust_sample_size"), 0.0)
    trust_whipsaw = as_float(trust_fields.get("trust_whipsaw_rate"), np.nan)
    trust_reliability = as_float(trust_fields.get("trust_sample_reliability"), 0.0)
    edge = abs(adjusted_probability - 0.5)

    if match is None:
        confidence_cap = min(confidence_cap, 0.28)
        confidence_caps.append("confidence_cap_no_trust_history")
    if trust_sample_size < 5:
        confidence_cap = min(confidence_cap, 0.32)
        confidence_caps.append("confidence_cap_low_sample")
    if not pd.isna(trust_whipsaw) and trust_whipsaw >= 0.50:
        confidence_cap = min(confidence_cap, 0.28)
        confidence_caps.append("confidence_cap_whipsaw")
    if trust_reliability < 0.25:
        confidence_cap = min(confidence_cap, 0.35)
        confidence_caps.append("confidence_cap_low_reliability")
    if text_value(trust_fields.get("trust_group_type")) in {"market_bias_side", "confidence_label", "overall"}:
        confidence_cap = min(confidence_cap, 0.35)
        confidence_caps.append("confidence_cap_fallback_group")
    if edge < 0.08:
        confidence_cap = min(confidence_cap, 0.22)
        confidence_caps.append("confidence_cap_weak_edge")

    capped_confidence = clamp(adjusted_confidence, 0.0, confidence_cap)
    if capped_confidence < adjusted_confidence:
        trust_fields["trust_warning"] = warning_text(trust_fields["trust_warning"], confidence_caps)
    adjusted_confidence = capped_confidence
    adjusted_direction = direction_from_probability(adjusted_probability, bullish_threshold, bearish_threshold)
    adjusted_confidence_label = confidence_label(adjusted_confidence)

    trust_fields.update(
        {
            "trust_adjusted_bullish_probability": adjusted_probability,
            "trust_adjusted_bearish_probability": 1.0 - adjusted_probability,
            "trust_adjusted_direction": adjusted_direction,
            "trust_adjusted_confidence": adjusted_confidence,
            "trust_adjusted_confidence_label": adjusted_confidence_label,
            "final_bullish_probability": adjusted_probability,
            "final_bearish_probability": 1.0 - adjusted_probability,
            "final_expected_direction": adjusted_direction,
            "final_confidence": adjusted_confidence,
            "final_confidence_label": adjusted_confidence_label,
            "final_warning": trust_fields["trust_warning"],
        }
    )
    return trust_fields


def apply_trust(
    signals: pd.DataFrame,
    weights: pd.DataFrame,
    bullish_threshold: float,
    bearish_threshold: float,
    min_probability: float,
    max_probability: float,
) -> pd.DataFrame:
    rows = []
    for _, signal in signals.iterrows():
        match = best_weight_match(signal, weights)
        out = signal.to_dict()
        out.update(
            apply_trust_to_signal(
                signal,
                match,
                bullish_threshold,
                bearish_threshold,
                min_probability,
                max_probability,
            )
        )
        rows.append(out)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply performance-based trust weights to macro live signals.")
    p.add_argument("--signals", default="macro_live_signal.csv", help="UI-ready live signal CSV")
    p.add_argument("--performance", default="macro_signal_performance.csv", help="Signal performance summary CSV")
    p.add_argument("--weights-output", default="macro_signal_trust_weights.csv")
    p.add_argument("--adjusted-output", default="macro_live_signal_adjusted.csv")
    p.add_argument("--prior-strength", type=float, default=6.0, help="Bayesian prior strength for accuracy smoothing")
    p.add_argument("--min-weight", type=float, default=0.25)
    p.add_argument("--max-weight", type=float, default=1.35)
    p.add_argument("--bullish-threshold", type=float, default=0.57)
    p.add_argument("--bearish-threshold", type=float, default=0.43)
    p.add_argument("--min-probability", type=float, default=0.05)
    p.add_argument("--max-probability", type=float, default=0.95)
    p.add_argument("--regime-context", default="macro_regime_context.json", help="Optional manual/news regime context JSON")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    performance = load_csv(args.performance)
    signals = load_csv(args.signals)

    weights = build_trust_weights(performance, args.prior_strength, args.min_weight, args.max_weight)
    weights.to_csv(args.weights_output, index=False)
    print(f"Wrote {len(weights)} trust-weight rows to {args.weights_output}.")

    adjusted = apply_trust(
        signals,
        weights,
        args.bullish_threshold,
        args.bearish_threshold,
        args.min_probability,
        args.max_probability,
    )
    regime_context = load_regime_context(args.regime_context, adjusted.to_dict("records"))
    adjusted = apply_regime_to_frame(adjusted, regime_context, args.bullish_threshold, args.bearish_threshold)
    adjusted.to_csv(args.adjusted_output, index=False)
    print(f"Wrote {len(adjusted)} trust-adjusted live signals to {args.adjusted_output}.")

    if not adjusted.empty:
        cols = [
            "title",
            "event_family",
            "market_bias_side",
            "release_rule_label",
            "live_market_regime",
            "calibrated_bullish_probability",
            "trust_weight",
            "trust_adjusted_bullish_probability",
            "trust_adjusted_direction",
            "trust_adjusted_confidence_label",
            "trade_state",
            "trust_warning",
        ]
        print("\nAdjusted signal preview:")
        print(adjusted[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
