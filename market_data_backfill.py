#!/usr/bin/env python3
"""
market_data_backfill.py

Separate backfill planner for market-data gaps.

This module does not learn reactions, normalize vendor exports, or update live
signals. It only inspects existing OHLC files, compares them with a desired date
range, and optionally calls the existing Yahoo downloader for ranges that Yahoo
can realistically serve.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_TICKER = "NQ=F"
DEFAULT_DESIRED_START = "2020-01-01"
DEFAULT_OUTPUT_DIR = "market_data_backfills"

DEFAULT_FILES = {
    "1m": "NQ_1min_data.csv",
    "5m": "data/NQ_5min_data.csv",
    "15m": "NQ_15min_data.csv",
    "60m": "NQ_60min_data.csv",
    "1d": "data/NQ_F_daily.csv",
}

YAHOO_INTRADAY_MAX_DAYS = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}


@dataclass
class RangeInfo:
    interval: str
    path: Path
    rows: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    exists: bool
    error: str = ""


def parse_date(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(None).normalize()


def file_range(interval: str, path: Path) -> RangeInfo:
    if not path.exists():
        return RangeInfo(interval=interval, path=path, rows=0, start=None, end=None, exists=False)
    try:
        if path.suffix.lower() == ".parquet":
            df = pd.read_parquet(path, columns=["date"])
        else:
            df = pd.read_csv(path, usecols=["date"])
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if dates.empty:
            return RangeInfo(interval=interval, path=path, rows=len(df), start=None, end=None, exists=True, error="no valid dates")
        return RangeInfo(
            interval=interval,
            path=path,
            rows=len(df),
            start=dates.min(),
            end=dates.max(),
            exists=True,
        )
    except Exception as exc:
        return RangeInfo(interval=interval, path=path, rows=0, start=None, end=None, exists=True, error=str(exc))


def yahoo_cutoff(interval: str, as_of: pd.Timestamp) -> pd.Timestamp | None:
    max_days = YAHOO_INTRADAY_MAX_DAYS.get(interval)
    if max_days is None:
        return None
    return as_of - pd.Timedelta(days=max_days)


def status_for_missing_range(interval: str, missing_start: pd.Timestamp, missing_end: pd.Timestamp, as_of: pd.Timestamp) -> tuple[str, str]:
    if missing_start >= missing_end:
        return "covered", "No missing range."
    cutoff = yahoo_cutoff(interval, as_of)
    if cutoff is None:
        return "yahoo_eligible", "Daily or higher interval can be requested by date range."
    if missing_end < cutoff:
        return "external_required", f"Yahoo {interval} history is limited to about {YAHOO_INTRADAY_MAX_DAYS[interval]} days."
    if missing_start < cutoff:
        return "partial_yahoo_eligible", f"Only the portion after {cutoff.date()} is likely available from Yahoo."
    return "yahoo_eligible", "Range is inside Yahoo's usual intraday availability window."


def backfill_rows(interval: str, info: RangeInfo, desired_start: pd.Timestamp, desired_end: pd.Timestamp, as_of: pd.Timestamp) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if info.start is None or info.end is None:
        status, note = status_for_missing_range(interval, desired_start, desired_end, as_of)
        rows.append(make_row(interval, info.path, desired_start, desired_end, info, status, note))
        return rows

    if desired_start < info.start:
        status, note = status_for_missing_range(interval, desired_start, info.start, as_of)
        rows.append(make_row(interval, info.path, desired_start, info.start, info, status, note))
    if info.end < desired_end:
        status, note = status_for_missing_range(interval, info.end, desired_end, as_of)
        rows.append(make_row(interval, info.path, info.end, desired_end, info, status, note))
    if not rows:
        rows.append(make_row(interval, info.path, info.start, info.end, info, "covered", "Existing file covers the desired range."))
    return rows


def make_row(
    interval: str,
    path: Path,
    missing_start: pd.Timestamp,
    missing_end: pd.Timestamp,
    info: RangeInfo,
    status: str,
    note: str,
) -> dict[str, Any]:
    return {
        "interval": interval,
        "file": str(path),
        "file_exists": info.exists,
        "rows": info.rows,
        "file_start": info.start.isoformat(sep=" ") if info.start is not None else "",
        "file_end": info.end.isoformat(sep=" ") if info.end is not None else "",
        "missing_start": missing_start.isoformat(sep=" "),
        "missing_end": missing_end.isoformat(sep=" "),
        "status": status,
        "note": note or info.error,
    }


def output_name(output_dir: Path, ticker: str, interval: str, start: str, end: str) -> Path:
    safe = ticker.replace("^", "_").replace("=", "_").replace("/", "_").replace(" ", "_")
    return output_dir / f"{safe}_{interval}_{start}_to_{end}.csv"


def execute_yahoo_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for row in rows:
        if row["status"] not in {"yahoo_eligible", "partial_yahoo_eligible"}:
            continue
        start = str(row["missing_start"])[:10]
        end = str(row["missing_end"])[:10]
        if row["status"] == "partial_yahoo_eligible":
            cutoff = yahoo_cutoff(row["interval"], pd.Timestamp(args.as_of))
            if cutoff is not None:
                start = max(pd.Timestamp(start), cutoff.normalize()).date().isoformat()
        out_csv = output_name(output_dir, args.ticker, row["interval"], start, end)
        command = [
            sys.executable,
            args.fetch_script,
            "--ticker",
            args.ticker,
            "--interval",
            row["interval"],
            "--start-date",
            start,
            "--end-date",
            end,
            "--out-csv",
            str(out_csv),
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        results.append(
            {
                "interval": row["interval"],
                "start": start,
                "end": end,
                "out_csv": str(out_csv),
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
                "command": " ".join(command),
            }
        )
    return results


def parse_files(values: list[str]) -> dict[str, str]:
    files = dict(DEFAULT_FILES)
    for value in values:
        if "=" not in value:
            raise ValueError(f"--file value must be interval=path, got {value!r}")
        interval, path = value.split("=", 1)
        files[interval.strip()] = path.strip()
    return files


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan and optionally run separate market-data backfill requests.")
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--desired-start", default=DEFAULT_DESIRED_START)
    parser.add_argument("--desired-end", default=date.today().isoformat())
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--intervals", nargs="+", default=["1m", "5m", "15m", "60m"])
    parser.add_argument("--file", action="append", default=[], help="Override file mapping as interval=path")
    parser.add_argument("--plan-output", default="market_data_backfill_plan.csv")
    parser.add_argument("--report-output", default="market_data_backfill_report.json")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fetch-script", default="fetch_nq_yahoo.py")
    parser.add_argument("--execute-yahoo", action="store_true", help="Run eligible requests via fetch_nq_yahoo.py")
    args = parser.parse_args()

    files = parse_files(args.file)
    desired_start = parse_date(args.desired_start)
    desired_end = parse_date(args.desired_end)
    as_of = parse_date(args.as_of)
    if desired_start >= desired_end:
        raise SystemExit("--desired-start must be before --desired-end")

    plan_rows: list[dict[str, Any]] = []
    ranges = []
    for interval in args.intervals:
        info = file_range(interval, Path(files.get(interval, f"{interval}.csv")))
        ranges.append(info)
        plan_rows.extend(backfill_rows(interval, info, desired_start, desired_end, as_of))

    execution = execute_yahoo_rows(plan_rows, args) if args.execute_yahoo else []
    report = {
        "ticker": args.ticker,
        "desired_start": desired_start.isoformat(sep=" "),
        "desired_end": desired_end.isoformat(sep=" "),
        "as_of": as_of.isoformat(sep=" "),
        "notes": [
            "This module only plans/executes market-data backfills.",
            "Use futures_data_adapter.py to normalize/merge successful external exports.",
            "Yahoo intraday history has hard lookback limits; old intraday gaps require an external vendor/export.",
        ],
        "ranges": [
            info.__dict__
            | {
                "path": str(info.path),
                "start": str(info.start) if info.start is not None else "",
                "end": str(info.end) if info.end is not None else "",
            }
            for info in ranges
        ],
        "plan": plan_rows,
        "execution": execution,
    }

    write_csv(Path(args.plan_output), plan_rows)
    Path(args.report_output).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"Wrote backfill plan to {args.plan_output}")
    print(f"Wrote backfill report to {args.report_output}")
    for row in plan_rows:
        print(f"{row['interval']:>4} {row['status']:>23} {row['missing_start']} -> {row['missing_end']}  {row['note']}")
    if execution:
        failures = [item for item in execution if item["returncode"] != 0]
        print(f"Executed {len(execution)} Yahoo request(s); failures={len(failures)}")


if __name__ == "__main__":
    main()
