#!/usr/bin/env python3
"""
Build a generated live-regime context from market tape, alert signals, and news.

This writes macro_live_regime_context.json. The manual macro_regime_context.json
can still override it, but the pipeline no longer depends on manual context for
live tape/news regime input.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


BEARISH_TERMS = (
    "hawkish",
    "rate hike",
    "higher yields",
    "hot jobs",
    "hot nfp",
    "inflation pressure",
    "selloff",
    "slump",
    "risk-off",
    "chip stocks",
    "semiconductor",
    "ai unwind",
)
BULLISH_TERMS = (
    "dovish",
    "rate cut",
    "cooler inflation",
    "soft jobs",
    "risk-on",
    "rally",
    "rebound",
    "relief",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def text_value(value: Any) -> str:
    return str(value if value is not None else "").strip()


def split_field(value: Any) -> list[str]:
    return [part.strip() for part in text_value(value).replace(",", ";").split(";") if part.strip()]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return default if pd.isna(out) else out


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_time(value: Any) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        parsed = pd.to_datetime(text, errors="coerce", utc=True)
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime().astimezone(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def contribution(source: str, direction: str, confidence: float, weight: float, reason: str) -> dict[str, Any]:
    direction = direction if direction in {"bullish", "bearish", "mixed"} else "mixed"
    sign = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0
    confidence = clamp(confidence, 0.0, 1.0)
    return {
        "source": source,
        "direction": direction,
        "confidence": confidence,
        "weight": clamp(weight, 0.0, 1.0),
        "score": sign * confidence * clamp(weight, 0.0, 1.0),
        "reason": reason,
    }


def load_market_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_market_data(args: argparse.Namespace) -> str:
    if args.market_data:
        return args.market_data
    config = load_market_config(args.market_config)
    return text_value(config.get("active_market_data_file")) or "data/NQ_5min_data.csv"


def market_tape_component(args: argparse.Namespace, now: datetime) -> list[dict[str, Any]]:
    path = Path(resolve_market_data(args))
    if not path.exists():
        return [contribution("market_tape", "mixed", 0.0, 0.0, f"{path.name} missing")]

    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return [contribution("market_tape", "mixed", 0.0, 0.0, f"{path.name} unreadable: {exc}")]

    date_col = next((col for col in ("date", "datetime", "timestamp", "time") if col in frame.columns), "")
    if not date_col or "close" not in frame.columns:
        return [contribution("market_tape", "mixed", 0.0, 0.0, f"{path.name} missing date/close columns")]

    frame = frame[[date_col, "close"]].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().sort_values(date_col)
    if len(frame) < 60:
        return [contribution("market_tape", "mixed", 0.0, 0.0, f"{path.name} has too few clean bars")]

    latest = frame.iloc[-1]
    latest_time = latest[date_col].to_pydatetime().astimezone(timezone.utc)
    stale_minutes = (now - latest_time).total_seconds() / 60.0
    if stale_minutes > args.max_market_stale_minutes:
        return [
            contribution(
                "market_tape",
                "mixed",
                0.0,
                0.0,
                f"{path.name} stale: latest bar {iso_z(latest_time)}",
            )
        ]

    close = frame["close"]
    ema_fast = close.ewm(span=args.ema_fast, adjust=False).mean().iloc[-1]
    ema_slow = close.ewm(span=args.ema_slow, adjust=False).mean().iloc[-1]
    lookback = min(args.return_bars, len(close) - 1)
    ret = (close.iloc[-1] / close.iloc[-lookback - 1]) - 1.0
    recent = close.pct_change().tail(lookback).dropna()
    vol = float(recent.std()) if len(recent) else 0.0

    if close.iloc[-1] > ema_fast > ema_slow and ret >= args.tape_return_threshold:
        return [
            contribution(
                "market_tape",
                "bullish",
                clamp(0.45 + min(abs(ret) * 20, 0.30), 0.0, 0.75),
                0.85,
                f"NQ tape above EMA stack, {lookback}-bar return {ret:.2%}",
            )
        ]
    if close.iloc[-1] < ema_fast < ema_slow and ret <= -args.tape_return_threshold:
        return [
            contribution(
                "market_tape",
                "bearish",
                clamp(0.45 + min(abs(ret) * 20, 0.30), 0.0, 0.75),
                0.85,
                f"NQ tape below EMA stack, {lookback}-bar return {ret:.2%}",
            )
        ]
    if vol >= args.tape_volatility_threshold and ret < 0:
        return [contribution("market_tape", "bearish", 0.35, 0.65, f"NQ tape volatile with negative return, vol {vol:.3%}")]
    return [contribution("market_tape", "mixed", 0.15, 0.50, f"NQ tape mixed, {lookback}-bar return {ret:.2%}")]


def load_json_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("signals") or data.get("items") or data.get("alerts")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [data]
    return []


def load_csv_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def signal_direction(item: dict[str, Any]) -> str:
    direction = text_value(item.get("direction") or item.get("side")).lower()
    if direction in {"bullish", "long", "buy", "call"}:
        return "bullish"
    if direction in {"bearish", "short", "sell", "put"}:
        return "bearish"
    blob = " ".join(text_value(item.get(key)) for key in ("signal", "message", "alert", "title", "thesis")).lower()
    if " long" in f" {blob}" or "orb long" in blob or "buy call" in blob:
        return "bullish"
    if " short" in f" {blob}" or "orb short" in blob or "buy put" in blob:
        return "bearish"
    return "mixed"


def tape_signal_components(args: argparse.Namespace, now: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_path in args.tape_signal_files:
        path = Path(raw_path)
        items = load_json_items(path) if path.suffix.lower() == ".json" else load_csv_items(path)
        for item in items:
            valid_until = parse_time(item.get("valid_until") or item.get("expires_at"))
            timestamp = parse_time(item.get("time") or item.get("timestamp") or item.get("alert_time") or item.get("created_at"))
            if valid_until and valid_until < now:
                continue
            if not valid_until and timestamp:
                age_minutes = (now - timestamp).total_seconds() / 60.0
                if age_minutes > args.max_tape_signal_minutes:
                    continue

            direction = signal_direction(item)
            if direction == "mixed":
                continue
            base_conf = as_float(item.get("confidence"), args.tape_signal_confidence)
            if not valid_until and not timestamp:
                base_conf = min(base_conf, 0.35)
            source = text_value(item.get("source") or path.stem or "tape_signal")
            message = text_value(item.get("reason") or item.get("message") or item.get("signal") or f"{source} {direction}")
            out.append(contribution(source, direction, base_conf, args.tape_signal_weight, message))
    return out


def news_context_components(args: argparse.Namespace, now: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in load_json_items(Path(args.news_context)):
        valid_until = parse_time(item.get("valid_until") or item.get("expires_at"))
        if valid_until and valid_until < now:
            continue
        direction = signal_direction(item)
        if direction == "mixed":
            continue
        flags = split_field(item.get("risk_flags"))
        confidence = as_float(item.get("confidence"), 0.55)
        if direction == "bearish" and any(flag in flags for flag in ("macro_policy_pressure", "nq_growth_pressure", "risk_off")):
            confidence = max(confidence, 0.68)
        out.append(
            contribution(
                text_value(item.get("source") or "news_context"),
                direction,
                confidence,
                args.news_weight,
                text_value(item.get("reason") or item.get("message") or item.get("headline") or "news context"),
            )
        )

    feed_path = Path(args.news_feed)
    if feed_path.exists():
        for row in load_csv_items(feed_path):
            direction = text_value(row.get("direction")).lower()
            if direction not in {"bullish", "bearish"}:
                continue
            published = parse_time(row.get("published_at"))
            if published:
                age_minutes = (now - published).total_seconds() / 60.0
                if age_minutes > args.max_news_feed_minutes:
                    continue
            flags = split_field(row.get("risk_flags"))
            themes = split_field(row.get("themes") or row.get("categories"))
            confidence = as_float(row.get("confidence"), 0.25)
            if direction == "bearish" and any(flag in flags for flag in ("macro_policy_pressure", "nq_growth_pressure", "risk_off")):
                confidence = max(confidence, 0.68)
            if direction == "bearish" and {"rates", "chips_ai"} <= set(themes):
                confidence = max(confidence, 0.62)
            title = text_value(row.get("title") or "news item")
            reason = text_value(row.get("reason") or title)
            flag_note = f" flags={','.join(flags[:4])}" if flags else ""
            out.append(contribution("news_feed", direction, confidence, args.news_weight, f"{title}: {reason}{flag_note}"))

    summary_path = Path(args.news_summary)
    if summary_path.exists():
        for row in load_csv_items(summary_path):
            symbol = text_value(row.get("symbol")).upper()
            if symbol not in {"NQ", "QQQ", "SPY", "ES"}:
                continue
            norm_score = as_float(row.get("norm_score"), 0.0)
            if norm_score >= args.news_score_threshold:
                out.append(contribution("news_summary", "bullish", min(0.50, abs(norm_score) * 2.0), args.news_weight, f"{symbol} news score {norm_score:.3f}"))
            elif norm_score <= -args.news_score_threshold:
                out.append(contribution("news_summary", "bearish", min(0.50, abs(norm_score) * 2.0), args.news_weight, f"{symbol} news score {norm_score:.3f}"))

    text_blob = ""
    for path in (Path(args.news_context), summary_path):
        if path.exists() and path.suffix.lower() in {".txt", ".json", ".csv"}:
            try:
                text_blob += "\n" + path.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                pass
    bearish_hits = sum(1 for term in BEARISH_TERMS if term in text_blob)
    bullish_hits = sum(1 for term in BULLISH_TERMS if term in text_blob)
    if bearish_hits > bullish_hits and bearish_hits:
        out.append(contribution("news_terms", "bearish", min(0.65, 0.25 + bearish_hits * 0.08), args.news_weight, f"bearish news terms hit={bearish_hits}"))
    elif bullish_hits > bearish_hits and bullish_hits:
        out.append(contribution("news_terms", "bullish", min(0.65, 0.25 + bullish_hits * 0.08), args.news_weight, f"bullish news terms hit={bullish_hits}"))
    return out


def build_context(components: list[dict[str, Any]], now: datetime, valid_minutes: int) -> dict[str, Any]:
    active = [item for item in components if abs(as_float(item.get("score"), 0.0)) > 0]
    score = clamp(sum(as_float(item.get("score"), 0.0) for item in active), -1.0, 1.0)
    if score >= 0.35:
        direction = "bullish"
        regime = "bullish_tape_news"
    elif score <= -0.35:
        direction = "bearish"
        regime = "bearish_tape_news"
    else:
        direction = "mixed"
        regime = "neutral_mixed"
    confidence = clamp(abs(score), 0.0, 0.85)
    reasons = [text_value(item.get("reason")) for item in sorted(active, key=lambda x: abs(as_float(x.get("score"), 0.0)), reverse=True)]
    if not reasons:
        reasons = [text_value(item.get("reason")) for item in components if text_value(item.get("reason"))]
    reason = "; ".join(reasons[:4]) or "No active tape/news regime signal"
    return {
        "generated_at": iso_z(now),
        "valid_until": iso_z(now + timedelta(minutes=valid_minutes)),
        "live_market_regime": regime,
        "live_market_regime_direction": direction,
        "live_market_regime_confidence": confidence,
        "live_market_regime_reason": reason,
        "live_market_regime_source": "generated:tape_news_rules",
        "score": score,
        "components": components,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build generated live regime context from tape/news rules.")
    p.add_argument("--market-config", default="market_data_config.json")
    p.add_argument("--market-data", default="")
    p.add_argument("--news-summary", default="news_summary.csv")
    p.add_argument("--news-context", default="macro_news_context.json")
    p.add_argument("--news-feed", default="macro_news_feed.csv")
    p.add_argument("--tape-signal-files", nargs="*", default=["macro_tape_signals.json", "macro_tape_signals.csv"])
    p.add_argument("--output", default="macro_live_regime_context.json")
    p.add_argument("--context-valid-minutes", type=int, default=45)
    p.add_argument("--max-market-stale-minutes", type=int, default=180)
    p.add_argument("--max-tape-signal-minutes", type=int, default=180)
    p.add_argument("--max-news-feed-minutes", type=int, default=720)
    p.add_argument("--ema-fast", type=int, default=21)
    p.add_argument("--ema-slow", type=int, default=50)
    p.add_argument("--return-bars", type=int, default=78)
    p.add_argument("--tape-return-threshold", type=float, default=0.0025)
    p.add_argument("--tape-volatility-threshold", type=float, default=0.0030)
    p.add_argument("--tape-signal-confidence", type=float, default=0.70)
    p.add_argument("--tape-signal-weight", type=float, default=0.90)
    p.add_argument("--news-weight", type=float, default=0.75)
    p.add_argument("--news-score-threshold", type=float, default=0.15)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    now = utc_now()
    components = []
    components.extend(market_tape_component(args, now))
    components.extend(tape_signal_components(args, now))
    components.extend(news_context_components(args, now))
    context = build_context(components, now, args.context_valid_minutes)
    Path(args.output).write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.output}: {context['live_market_regime']} "
        f"{context['live_market_regime_direction']} confidence={context['live_market_regime_confidence']:.2f}"
    )


if __name__ == "__main__":
    main()
