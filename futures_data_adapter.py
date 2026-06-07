#!/usr/bin/env python3
"""
futures_data_adapter.py

Normalize external futures OHLC/tick CSV exports into the canonical market-data
format used by macro_reaction_study.py:

  date,open,high,low,close,adj_close,volume

Use this when Yahoo's intraday limits are too shallow and a deeper futures data
source exports CSV files from a broker, charting platform, or paid feed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


CANONICAL_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]

ALIASES = {
    "datetime": ["datetime", "date_time", "time", "timestamp", "ts", "bar_time", "start_time"],
    "date": ["date", "day", "session_date"],
    "time": ["time", "clock", "bar_time"],
    "open": ["open", "o", "open_price"],
    "high": ["high", "h", "high_price"],
    "low": ["low", "l", "low_price"],
    "close": ["close", "c", "last", "last_price", "price", "settle", "settlement"],
    "volume": ["volume", "vol", "v", "total_volume", "qty", "size"],
}


def clean_column(name: object) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def first_existing(columns: set[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def choose_column(df: pd.DataFrame, explicit: str | None, logical_name: str, required: bool = True) -> str | None:
    columns = set(df.columns)
    if explicit:
        col = clean_column(explicit)
        if col not in columns:
            raise ValueError(f"--{logical_name}-column {explicit!r} was not found in input columns")
        return col
    found = first_existing(columns, ALIASES[logical_name])
    if required and not found:
        raise ValueError(f"Could not detect required {logical_name} column. Available columns: {', '.join(df.columns)}")
    return found


def read_input_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"{path} has no rows")
    df.columns = [clean_column(col) for col in df.columns]
    df["_source_file"] = path.name
    return df


def parse_datetime(
    df: pd.DataFrame,
    datetime_column: str | None,
    date_column: str | None,
    time_column: str | None,
    input_timezone: str,
) -> pd.Series:
    columns = set(df.columns)

    if datetime_column:
        if datetime_column not in columns:
            raise ValueError(f"datetime column {datetime_column!r} was not found")
        raw = df[datetime_column]
    else:
        detected_datetime = first_existing(columns, ALIASES["datetime"])
        detected_date = date_column or first_existing(columns, ALIASES["date"])
        detected_time = time_column or first_existing(columns, ALIASES["time"])

        if detected_date and detected_date not in columns:
            raise ValueError(f"date column {detected_date!r} was not found")
        if detected_time and detected_time not in columns:
            raise ValueError(f"time column {detected_time!r} was not found")

        if detected_date and detected_time and detected_date != detected_time:
            raw = df[detected_date].astype(str).str.strip() + " " + df[detected_time].astype(str).str.strip()
        elif detected_datetime:
            raw = df[detected_datetime]
        elif detected_date:
            raw = df[detected_date]
        else:
            raise ValueError("Could not detect datetime or date/time columns")

    parsed = pd.to_datetime(raw, errors="coerce")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(ZoneInfo(input_timezone), nonexistent="shift_forward", ambiguous="NaT")
    else:
        parsed = parsed.dt.tz_convert(ZoneInfo(input_timezone))

    return parsed.dt.tz_convert("UTC").dt.tz_localize(None)


def normalize_rows(args: argparse.Namespace) -> pd.DataFrame:
    frames = [read_input_csv(Path(path)) for path in args.input]
    raw = pd.concat(frames, ignore_index=True)

    datetime_column = clean_column(args.datetime_column) if args.datetime_column else None
    date_column = clean_column(args.date_column) if args.date_column else None
    time_column = clean_column(args.time_column) if args.time_column else None

    output = pd.DataFrame()
    output["date"] = parse_datetime(raw, datetime_column, date_column, time_column, args.input_timezone)

    close_col = choose_column(raw, args.close_column, "close", required=True)
    open_col = choose_column(raw, args.open_column, "open", required=False) or close_col
    high_col = choose_column(raw, args.high_column, "high", required=False) or close_col
    low_col = choose_column(raw, args.low_column, "low", required=False) or close_col
    volume_col = choose_column(raw, args.volume_column, "volume", required=False)

    output["open"] = pd.to_numeric(raw[open_col], errors="coerce")
    output["high"] = pd.to_numeric(raw[high_col], errors="coerce")
    output["low"] = pd.to_numeric(raw[low_col], errors="coerce")
    output["close"] = pd.to_numeric(raw[close_col], errors="coerce")
    output["volume"] = pd.to_numeric(raw[volume_col], errors="coerce") if volume_col else 0
    output["adj_close"] = output["close"]

    output = output.dropna(subset=["date", "open", "high", "low", "close"])
    output = output.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    if args.start_date:
        start = pd.Timestamp(args.start_date)
        output = output[output["date"] >= start]
    if args.end_date:
        end = pd.Timestamp(args.end_date)
        output = output[output["date"] < end]

    if args.resample:
        output = resample_bars(output, args.resample)

    return output[CANONICAL_COLUMNS].reset_index(drop=True)


def resample_bars(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if df.empty:
        return df
    bars = df.set_index("date").sort_index()
    aggregated = bars.resample(frequency, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "adj_close": "last",
            "volume": "sum",
        }
    )
    aggregated = aggregated.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return aggregated


def interval_seconds(df: pd.DataFrame) -> list[float]:
    if len(df) < 2:
        return []
    diffs = df["date"].sort_values().diff().dropna().dt.total_seconds()
    if diffs.empty:
        return []
    return [float(value) for value in diffs.value_counts().head(5).index]


def write_outputs(df: pd.DataFrame, args: argparse.Namespace) -> dict:
    out_path = Path(args.out_csv)
    df.to_csv(out_path, index=False)

    summary = {
        "created_from": args.input,
        "out_csv": str(out_path),
        "rows": int(len(df)),
        "start": df["date"].min().isoformat(sep=" ") if not df.empty else "",
        "end": df["date"].max().isoformat(sep=" ") if not df.empty else "",
        "input_timezone": args.input_timezone,
        "resample": args.resample or "",
        "common_interval_seconds": interval_seconds(df),
        "columns": CANONICAL_COLUMNS,
    }

    if args.summary_output:
        Path(args.summary_output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize external futures CSV exports for the macro reaction study.")
    p.add_argument("--input", nargs="+", required=True, help="One or more external CSV exports")
    p.add_argument("--out-csv", required=True, help="Canonical output CSV path")
    p.add_argument("--summary-output", default="", help="Optional JSON summary path")
    p.add_argument("--input-timezone", default="UTC", help="Timezone for naive input timestamps, e.g. UTC or America/New_York")
    p.add_argument("--resample", default="", help="Optional pandas frequency, e.g. 1min, 5min, 15min, 60min")
    p.add_argument("--start-date", default="", help="Optional inclusive UTC-naive start timestamp/date")
    p.add_argument("--end-date", default="", help="Optional exclusive UTC-naive end timestamp/date")

    p.add_argument("--datetime-column", default="")
    p.add_argument("--date-column", default="")
    p.add_argument("--time-column", default="")
    p.add_argument("--open-column", default="")
    p.add_argument("--high-column", default="")
    p.add_argument("--low-column", default="")
    p.add_argument("--close-column", default="")
    p.add_argument("--volume-column", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = normalize_rows(args)
    if df.empty:
        raise SystemExit("No usable rows after normalization.")

    summary = write_outputs(df, args)
    print(f"Saved {summary['rows']} canonical rows to {summary['out_csv']}")
    print(f"Range: {summary['start']} -> {summary['end']}")
    print(f"Common intervals seconds: {summary['common_interval_seconds']}")


if __name__ == "__main__":
    main()
