#!/usr/bin/env python3
"""
Durable source-health ledger for the catalyst engine.

The pipeline has several soft-fail providers: Yahoo news, Yahoo RSS,
TradingView news-flow, TradingView/Reuters calendar, Trading Economics, and
Yahoo earnings. This module records each provider attempt to JSONL and keeps a
small rolled-up status JSON for dashboards and troubleshooting.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SUMMARY = "macro_source_health.json"
DEFAULT_HISTORY = "macro_source_health_history.jsonl"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok", "success"}
    return bool(value)


def clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_attempt(
    source_type: str,
    attempt: dict[str, Any],
    checked_at: str,
    source_used: str = "",
) -> dict[str, Any]:
    provider = clean(attempt.get("provider") or attempt.get("source") or source_type)
    ok = as_bool(attempt.get("ok"))
    rows = attempt.get("rows", 0)
    try:
        rows = int(rows)
    except Exception:
        rows = 0
    elapsed = attempt.get("elapsed_seconds", "")
    try:
        elapsed = round(float(elapsed), 3)
    except Exception:
        elapsed = ""
    return {
        "checked_at": checked_at,
        "source_type": clean(source_type),
        "provider": provider,
        "ok": ok,
        "rows": rows,
        "selected": bool(source_used and provider == source_used),
        "source_used": clean(source_used),
        "error": clean(attempt.get("error")),
        "warning": clean(attempt.get("warning")),
        "elapsed_seconds": elapsed,
    }


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def write_history(path: Path, rows: list[dict[str, Any]], max_history: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = rows[-max_history:] if max_history > 0 else rows
    with path.open("w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def summarize_history(rows: list[dict[str, Any]], updated_at: str) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    latest_source_used_by_type: dict[str, str] = {}
    for row in rows:
        source_type = clean(row.get("source_type"))
        provider = clean(row.get("provider"))
        grouped[(source_type, provider)].append(row)
        source_used = clean(row.get("source_used"))
        if source_used:
            latest_source_used_by_type[source_type] = source_used

    providers: dict[str, dict[str, Any]] = {}
    for (source_type, provider), attempts in sorted(grouped.items()):
        successes = [row for row in attempts if as_bool(row.get("ok"))]
        failures = [row for row in attempts if not as_bool(row.get("ok"))]
        consecutive_failures = 0
        for row in reversed(attempts):
            if as_bool(row.get("ok")):
                break
            consecutive_failures += 1
        latest = attempts[-1]
        key = f"{source_type}:{provider}"
        providers[key] = {
            "source_type": source_type,
            "provider": provider,
            "attempts": len(attempts),
            "successes": len(successes),
            "failures": len(failures),
            "consecutive_failures": consecutive_failures,
            "latest_at": clean(latest.get("checked_at")),
            "latest_ok": as_bool(latest.get("ok")),
            "latest_rows": int(latest.get("rows") or 0),
            "latest_error": clean(latest.get("error")),
            "latest_warning": clean(latest.get("warning")),
            "last_success_at": clean(successes[-1].get("checked_at")) if successes else "",
            "last_failure_at": clean(failures[-1].get("checked_at")) if failures else "",
        }

    latest = rows[-20:]
    return {
        "updated_at": updated_at,
        "provider_count": len(providers),
        "latest_source_used_by_type": latest_source_used_by_type,
        "providers": providers,
        "latest": latest,
    }


def record_attempts(
    source_type: str,
    attempts: list[dict[str, Any]],
    source_used: str = "",
    summary_path: str | Path = DEFAULT_SUMMARY,
    history_path: str | Path = DEFAULT_HISTORY,
    checked_at: datetime | str | None = None,
    max_history: int = 1000,
) -> dict[str, Any]:
    if not attempts:
        return summarize_history(read_history(Path(history_path)), iso_z(utc_now()))
    if checked_at is None:
        checked_text = iso_z(utc_now())
    elif isinstance(checked_at, datetime):
        checked_text = iso_z(checked_at)
    else:
        checked_text = clean(checked_at)

    history = read_history(Path(history_path))
    history.extend(normalize_attempt(source_type, attempt, checked_text, source_used) for attempt in attempts)
    write_history(Path(history_path), history, max_history)
    summary = summarize_history(history[-max_history:] if max_history > 0 else history, checked_text)
    summary_file = Path(summary_path)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record catalyst provider source-health attempts.")
    parser.add_argument("--source-type", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--ok", action="store_true")
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--source-used", default="")
    parser.add_argument("--error", default="")
    parser.add_argument("--warning", default="")
    parser.add_argument("--elapsed-seconds", type=float, default=0.0)
    parser.add_argument("--summary-output", default=DEFAULT_SUMMARY)
    parser.add_argument("--history-output", default=DEFAULT_HISTORY)
    parser.add_argument("--max-history", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = record_attempts(
        args.source_type,
        [
            {
                "provider": args.provider,
                "ok": args.ok,
                "rows": args.rows,
                "error": args.error,
                "warning": args.warning,
                "elapsed_seconds": args.elapsed_seconds,
            }
        ],
        source_used=args.source_used,
        summary_path=args.summary_output,
        history_path=args.history_output,
        max_history=args.max_history,
    )
    print(f"Recorded source health for {args.source_type}:{args.provider}. Providers tracked: {summary['provider_count']}.")


if __name__ == "__main__":
    main()
