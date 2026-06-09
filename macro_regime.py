#!/usr/bin/env python3
"""
Shared live-regime filter for macro catalyst signals.

The event-level market rule answers "what does this number usually imply?".
The live-regime layer answers "does the current tape/news backdrop agree with
that event-level rule?". It can infer a simple context from current released
signals, or use an optional manual/news override JSON.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RELEASE_RULES = {
    "market_positive": ("bullish", "Release-rule positive"),
    "market_negative": ("bearish", "Release-rule negative"),
    "market_neutral": ("mixed", "Release-rule neutral"),
    "market_unknown": ("unknown", "Release-rule unknown"),
}


def text_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        out = float(value)
    except Exception:
        return default
    return default if pd.isna(out) else out


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def warning_text(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        for token in text_value(part).split(";"):
            clean = token.strip()
            if clean and clean not in tokens:
                tokens.append(clean)
    return ";".join(tokens)


def parse_time(value: Any) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def direction_from_probability(probability: float, bullish_threshold: float, bearish_threshold: float) -> str:
    if probability >= bullish_threshold:
        return "bullish"
    if probability <= bearish_threshold:
        return "bearish"
    return "mixed"


def release_rule_fields(row: dict[str, Any]) -> dict[str, Any]:
    side = text_value(row.get("market_bias_side")).lower()
    direction, label = RELEASE_RULES.get(side, ("unknown", "Release-rule unknown"))
    return {
        "release_rule_side": side or "market_unknown",
        "release_rule_direction": direction,
        "release_rule_label": label,
    }


def _manual_context(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    valid_until = parse_time(data.get("valid_until") or data.get("expires_at"))
    if valid_until and valid_until < utc_now():
        return {
            "live_market_regime": "neutral",
            "live_market_regime_direction": "mixed",
            "live_market_regime_confidence": 0.0,
            "live_market_regime_reason": f"{p.name} expired at {valid_until.isoformat()}",
            "live_market_regime_source": "manual_expired",
        }

    regime = text_value(data.get("live_market_regime") or data.get("regime") or "manual_context")
    direction = text_value(data.get("live_market_regime_direction") or data.get("direction") or "mixed").lower()
    if direction not in {"bullish", "bearish", "mixed"}:
        direction = "mixed"
    confidence = clamp(as_float(data.get("live_market_regime_confidence") or data.get("confidence"), 0.65), 0.0, 1.0)
    reason = text_value(data.get("live_market_regime_reason") or data.get("reason") or "Manual/news regime context")
    source = text_value(data.get("live_market_regime_source") or data.get("source") or f"manual:{p.name}")
    return {
        "live_market_regime": regime,
        "live_market_regime_direction": direction,
        "live_market_regime_confidence": confidence,
        "live_market_regime_reason": reason,
        "live_market_regime_source": source,
    }


def infer_regime_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    released_count = 0

    for row in rows:
        if text_value(row.get("release_status")).lower() != "released":
            continue
        released_count += 1
        fields = release_rule_fields(row)
        rule_direction = fields["release_rule_direction"]
        family = text_value(row.get("event_family")).lower()
        category = text_value(row.get("catalyst_category")).lower()
        title = text_value(row.get("title"))
        surprise = text_value(row.get("raw_surprise_side") or row.get("surprise_side")).lower()
        confidence = clamp(as_float(row.get("market_rule_confidence"), 0.5), 0.25, 1.0)
        importance = 1.25 if category in {"labor", "inflation", "central_bank"} else 0.75
        contribution = confidence * importance

        if rule_direction == "bearish":
            score -= contribution
            if family in {"nonfarm_payrolls", "adp_employment", "jobless_claims", "jolts_job_openings"}:
                reasons.append(f"{title}: labor surprise leaning hawkish/bearish")
            elif category == "inflation":
                reasons.append(f"{title}: inflation pressure bearish")
            elif category == "central_bank":
                reasons.append(f"{title}: central-bank pressure bearish")
            else:
                reasons.append(f"{title}: release-rule negative")
        elif rule_direction == "bullish":
            score += contribution
            if surprise in {"negative", "cooler", "soft"} and category in {"inflation", "labor"}:
                reasons.append(f"{title}: cooler data easing Fed pressure")
            else:
                reasons.append(f"{title}: release-rule positive")

    if score <= -0.70:
        direction = "bearish"
        regime = "bearish_hawkish_pressure"
    elif score >= 0.70:
        direction = "bullish"
        regime = "bullish_relief_growth"
    else:
        direction = "mixed"
        regime = "neutral_mixed"

    confidence = clamp(abs(score) / 2.5, 0.0, 0.80)
    reason = "; ".join(reasons[:4]) if reasons else "No strong released macro regime signal in current window"
    return {
        "live_market_regime": regime,
        "live_market_regime_direction": direction,
        "live_market_regime_confidence": confidence,
        "live_market_regime_reason": reason,
        "live_market_regime_source": f"inferred_from_released_signals:{released_count}",
    }


def load_regime_context(path: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    manual = _manual_context(path)
    return manual if manual is not None else infer_regime_context(rows)


def apply_regime_to_row(
    row: dict[str, Any],
    context: dict[str, Any],
    bullish_threshold: float,
    bearish_threshold: float,
) -> dict[str, Any]:
    out = release_rule_fields(row)
    regime = {
        "live_market_regime": text_value(context.get("live_market_regime") or "neutral_mixed"),
        "live_market_regime_direction": text_value(context.get("live_market_regime_direction") or "mixed").lower(),
        "live_market_regime_confidence": clamp(as_float(context.get("live_market_regime_confidence"), 0.0), 0.0, 1.0),
        "live_market_regime_reason": text_value(context.get("live_market_regime_reason")),
        "live_market_regime_source": text_value(context.get("live_market_regime_source") or "inferred"),
    }
    out.update(regime)

    release_dir = out["release_rule_direction"]
    regime_dir = regime["live_market_regime_direction"]
    status = text_value(row.get("release_status")).lower()
    final_bull = clamp(
        as_float(
            row.get("final_bullish_probability")
            or row.get("trust_adjusted_bullish_probability")
            or row.get("calibrated_bullish_probability"),
            0.5,
        ),
        0.0,
        1.0,
    )
    final_conf = clamp(as_float(row.get("final_confidence") or row.get("trust_adjusted_confidence") or row.get("confidence"), 0.0), 0.0, 1.0)
    final_dir = text_value(row.get("final_expected_direction") or row.get("trust_adjusted_direction") or row.get("expected_direction") or "mixed").lower()
    if final_dir not in {"bullish", "bearish", "mixed"}:
        final_dir = direction_from_probability(final_bull, bullish_threshold, bearish_threshold)

    warnings: list[str] = []
    conflict = "none"
    trade_state = "wait_for_actual" if status == "waiting_actual" else "watch_only"
    trade_reason = "No strong live regime conflict detected."

    bearish_regime = regime_dir == "bearish" and regime["live_market_regime_confidence"] >= 0.35
    bullish_regime = regime_dir == "bullish" and regime["live_market_regime_confidence"] >= 0.35

    if bearish_regime and release_dir == "bullish":
        conflict = "release_rule_positive_vs_bearish_regime"
        warnings.append("regime_conflict_release_positive")
        trade_state = "no_long_wait_for_reclaim"
        trade_reason = "Release rule is positive, but live regime is bearish; avoid long NQ until tape confirms."
        if final_dir == "bullish":
            final_dir = "mixed"
            final_conf = min(final_conf, 0.22)
            final_bull = min(final_bull, bullish_threshold - 0.01)
            warnings.append("regime_blocks_long")
    elif bullish_regime and release_dir == "bearish":
        conflict = "release_rule_negative_vs_bullish_regime"
        warnings.append("regime_conflict_release_negative")
        trade_state = "no_short_wait_for_breakdown"
        trade_reason = "Release rule is negative, but live regime is bullish; avoid short NQ until tape confirms."
        if final_dir == "bearish":
            final_dir = "mixed"
            final_conf = min(final_conf, 0.22)
            final_bull = max(final_bull, bearish_threshold + 0.01)
            warnings.append("regime_blocks_short")
    elif bearish_regime:
        trade_state = "short_only_after_confirmation" if final_dir == "bearish" else "wait_for_bearish_confirmation"
        trade_reason = "Live regime is bearish; longs require a reclaim/confirmation first."
    elif bullish_regime:
        trade_state = "long_only_after_confirmation" if final_dir == "bullish" else "wait_for_bullish_confirmation"
        trade_reason = "Live regime is bullish; shorts require breakdown/confirmation first."
    elif status == "released" and final_dir in {"bullish", "bearish"}:
        trade_state = f"{final_dir}_candidate_after_confirmation"
        trade_reason = "No live regime conflict; still require price confirmation before trade."

    out["market_regime_conflict"] = conflict
    out["trade_state"] = trade_state
    out["trade_state_reason"] = trade_reason
    out["final_bullish_probability"] = final_bull
    out["final_bearish_probability"] = 1.0 - final_bull
    out["final_expected_direction"] = final_dir
    out["final_confidence"] = final_conf
    out["final_confidence_label"] = "high" if final_conf >= 0.70 else "medium" if final_conf >= 0.40 else "low"
    out["final_warning"] = warning_text(row.get("final_warning") or row.get("trust_warning") or row.get("warning"), *warnings)
    return out


def apply_regime_to_frame(
    frame: pd.DataFrame,
    context: dict[str, Any],
    bullish_threshold: float,
    bearish_threshold: float,
) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        out = row.to_dict()
        out.update(apply_regime_to_row(out, context, bullish_threshold, bearish_threshold))
        rows.append(out)
    return pd.DataFrame(rows)
