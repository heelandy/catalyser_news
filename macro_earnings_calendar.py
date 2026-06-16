#!/usr/bin/env python3
"""
Fetch NQ-relevant earnings dates and normalize them as catalyst rows.

The default provider is Yahoo Finance's public earnings calendar endpoint. If
the provider fails, this script still writes an empty CSV and records the
failure in macro_source_health so the main pipeline can keep running.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from catalyser_news import build_catalyst_rows, iso_utc_z, write_catalyst_csv
from macro_source_health import DEFAULT_HISTORY, DEFAULT_SUMMARY, record_attempts


YAHOO_EARNINGS_URL = "https://query1.finance.yahoo.com/v7/finance/calendar/earnings"
DEFAULT_SYMBOLS = "NVDA,MSFT,AAPL,AMZN,META,GOOGL,AVGO,AMD,TSLA,NFLX"
HIGH_IMPACT_SYMBOLS = {"NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "AMD", "TSLA"}
COMPAT_FIELDS = [
    "date",
    "start",
    "title",
    "note",
    "provider",
    "category",
    "release_time",
    "previous",
    "forecast",
    "actual",
    "unit",
    "importance_raw",
    "source",
    "source_url",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def split_symbols(value: str) -> list[str]:
    return [part.strip().upper() for part in str(value or "").split(",") if part.strip()]


def clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def number_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except Exception:
        return clean(value)
    if not math.isfinite(number):
        return ""
    return f"{number:.4g}"


def parse_datetime(value: Any, fallback: datetime | None = None) -> datetime | None:
    if value in (None, ""):
        return fallback
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except Exception:
            return fallback
    text = clean(value)
    if not text:
        return fallback
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_in_window(dt: datetime, anchor: datetime, lookback_days: int, lookahead_days: int) -> bool:
    start = (anchor - timedelta(days=lookback_days)).date()
    end = (anchor + timedelta(days=lookahead_days)).date()
    return start <= dt.date() <= end


def source_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    finance = payload.get("finance") if isinstance(payload.get("finance"), dict) else {}
    for result in finance.get("result") or []:
        earnings = result.get("earnings")
        if isinstance(earnings, list):
            entries.extend(item for item in earnings if isinstance(item, dict))
        elif isinstance(earnings, dict):
            nested = earnings.get("earnings") or earnings.get("events") or earnings.get("result")
            if isinstance(nested, list):
                entries.extend(item for item in nested if isinstance(item, dict))
            else:
                entries.append(earnings)

    quote_summary = payload.get("quoteSummary") if isinstance(payload.get("quoteSummary"), dict) else {}
    for result in quote_summary.get("result") or []:
        calendar = result.get("calendarEvents") if isinstance(result.get("calendarEvents"), dict) else {}
        earnings = calendar.get("earnings") if isinstance(calendar.get("earnings"), dict) else {}
        dates = earnings.get("earningsDate") or []
        if isinstance(dates, dict):
            dates = [dates]
        for date_item in dates:
            row = dict(earnings)
            if isinstance(date_item, dict):
                row.update(date_item)
            else:
                row["earningsDate"] = date_item
            entries.append(row)
    return entries


def normalize_yahoo_earnings(symbol: str, payload: dict[str, Any], anchor: datetime, lookback_days: int, lookahead_days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in source_entries(payload):
        dt = parse_datetime(
            first_value(
                entry,
                "startdatetime",
                "startDateTime",
                "startDate",
                "reportDate",
                "date",
                "raw",
                "earningsDate",
            )
        )
        if dt is None or not date_in_window(dt, anchor, lookback_days, lookahead_days):
            continue

        ticker = clean(first_value(entry, "ticker", "symbol")) or symbol
        company = clean(first_value(entry, "companyshortname", "companyShortName", "company", "name"))
        estimate = number_text(first_value(entry, "epsestimate", "epsEstimate", "eps_estimate", "estimate", "earningsAverage", "epsAverage"))
        actual = number_text(first_value(entry, "epsactual", "epsActual", "eps_actual", "actual", "reportedEPS"))
        previous = number_text(first_value(entry, "epsprevious", "epsPrevious", "yearAgoEps"))
        surprise_pct = number_text(first_value(entry, "epssurprisepct", "epsSurprisePct", "surprisePercent", "surprise_pct"))
        time_type = clean(first_value(entry, "time", "timeType", "earningsCallTime"))
        title = f"{ticker} earnings"
        if company:
            title = f"{ticker} earnings - {company}"
        note_parts = [
            "Company earnings catalyst for NQ/QQQ risk appetite.",
            f"EPS estimate={estimate or '--'}",
            f"actual={actual or 'waiting'}",
        ]
        if previous:
            note_parts.append(f"previous={previous}")
        if surprise_pct:
            note_parts.append(f"surprise_pct={surprise_pct}")
        if time_type:
            note_parts.append(f"time={time_type}")
        note_parts.append("Use guidance/news and post-release tape confirmation before treating it as a directional index signal.")
        rows.append(
            {
                "date": iso_utc_z(dt),
                "start": iso_utc_z(dt),
                "title": title,
                "note": "; ".join(note_parts),
                "provider": "yahoo_earnings",
                "category": "earnings",
                "release_time": iso_utc_z(dt),
                "previous": previous,
                "forecast": estimate,
                "actual": actual,
                "unit": "EPS",
                "importance_raw": "3" if ticker.upper() in HIGH_IMPACT_SYMBOLS else "2",
                "source": "Yahoo Finance earnings calendar",
                "source_url": f"https://finance.yahoo.com/quote/{ticker}/analysis",
            }
        )
    return rows


def fetch_yahoo_earnings_symbol(symbol: str, timeout: int) -> dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; nq-macro-catalyst/1.0)"}
    response = requests.get(YAHOO_EARNINGS_URL, params={"symbol": symbol}, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def write_compat_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COMPAT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in COMPAT_FIELDS})


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    anchor = parse_datetime(args.as_of, utc_now()) or utc_now()
    raw_rows: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in split_symbols(args.symbols):
        started = utc_now()
        try:
            payload = fetch_yahoo_earnings_symbol(symbol, args.timeout)
            rows = normalize_yahoo_earnings(symbol, payload, anchor, args.lookback_days, args.lookahead_days)
            raw_rows.extend(rows)
            attempts.append(
                {
                    "provider": "yahoo_earnings",
                    "ok": True,
                    "rows": len(rows),
                    "elapsed_seconds": (utc_now() - started).total_seconds(),
                }
            )
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            attempts.append(
                {
                    "provider": "yahoo_earnings",
                    "ok": False,
                    "rows": 0,
                    "error": f"{symbol}: {exc}",
                    "elapsed_seconds": (utc_now() - started).total_seconds(),
                }
            )

    unique: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        key = f"{row.get('release_time')}|{row.get('title')}"
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (row.get("release_time") or "", row.get("title") or "")), attempts, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch NQ-relevant earnings calendar rows.")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument("--lookahead-days", type=int, default=21)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--output", default="macro_earnings_calendar.csv")
    parser.add_argument("--raw-output", default="macro_earnings_calendar_raw.csv")
    parser.add_argument("--summary-output", default="macro_earnings_calendar_summary.json")
    parser.add_argument("--source-health-output", default=DEFAULT_SUMMARY)
    parser.add_argument("--source-health-history", default=DEFAULT_HISTORY)
    parser.add_argument("--skip-source-health", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, attempts, errors = build_rows(args)
    write_compat_csv(Path(args.raw_output), rows)
    scored_rows = build_catalyst_rows(
        rows,
        as_of=args.as_of or None,
        lookback_days=args.lookback_days,
        lookahead_days=args.lookahead_days,
        symbols="NQ,QQQ,SPY",
        include_closed=True,
    )
    write_catalyst_csv(args.output, scored_rows)
    checked_at = iso_utc_z(utc_now())
    summary = {
        "checked_at": checked_at,
        "provider": "yahoo_earnings",
        "symbols": split_symbols(args.symbols),
        "rows": len(scored_rows),
        "raw_rows": len(rows),
        "errors": errors,
        "latest_titles": [row.get("title") for row in scored_rows[:10]],
    }
    write_summary(Path(args.summary_output), summary)
    if not args.skip_source_health:
        record_attempts(
            "earnings_calendar",
            attempts,
            source_used="yahoo_earnings" if rows else "",
            summary_path=args.source_health_output,
            history_path=args.source_health_history,
            checked_at=checked_at,
        )
    print(f"Wrote {len(scored_rows)} earnings catalyst rows to {args.output}.")
    if errors:
        print("Earnings fetch warnings: " + "; ".join(errors[:5]))


if __name__ == "__main__":
    main()
