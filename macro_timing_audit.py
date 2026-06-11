#!/usr/bin/env python3
"""
macro_timing_audit.py

Release-time precision audit for macro events and market bars.

This module checks the alignment between catalyst release times and the market
OHLC timestamps used by reaction studies.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def load_market(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    df = pd.read_parquet(p) if p.suffix.lower() == ".parquet" else pd.read_csv(p)
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    if "datetime" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"datetime": "date"})
    if "timestamp" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"timestamp": "date"})
    if "date" not in df.columns:
        raise ValueError("market data must contain date/datetime/timestamp")
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(None)
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def load_events(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    df = pd.read_csv(p)
    time_col = "release_time" if "release_time" in df.columns else "date" if "date" in df.columns else ""
    if not time_col:
        raise ValueError("events file must contain release_time or date")
    df["release_time"] = pd.to_datetime(df[time_col], utc=True, errors="coerce").dt.tz_convert(None)
    return df.dropna(subset=["release_time"]).sort_values("release_time").reset_index(drop=True)


def infer_bar_seconds(bars: pd.DataFrame) -> float:
    diffs = bars["date"].diff().dropna().dt.total_seconds()
    if diffs.empty:
        return 0.0
    return float(diffs.value_counts().idxmax())


def row_value(row: pd.Series, key: str) -> str:
    if key not in row.index or pd.isna(row.get(key)):
        return ""
    return str(row.get(key))


def audit_rows(events: pd.DataFrame, bars: pd.DataFrame, tolerance_minutes: float) -> pd.DataFrame:
    bar_times = bars["date"].reset_index(drop=True)
    values = bar_times.values
    rows = []
    for _, event in events.iterrows():
        release_time = event["release_time"]
        idx_next = int(np.searchsorted(values, np.datetime64(release_time), side="left"))
        idx_prev = idx_next - 1
        prev_bar = bar_times.iloc[idx_prev] if 0 <= idx_prev < len(bar_times) else pd.NaT
        next_bar = bar_times.iloc[idx_next] if 0 <= idx_next < len(bar_times) else pd.NaT
        prev_delay = (release_time - prev_bar).total_seconds() / 60.0 if pd.notna(prev_bar) else np.nan
        next_delay = (next_bar - release_time).total_seconds() / 60.0 if pd.notna(next_bar) else np.nan
        nearest_delay = np.nanmin([abs(prev_delay) if pd.notna(prev_delay) else np.nan, abs(next_delay) if pd.notna(next_delay) else np.nan])
        if pd.isna(next_bar):
            label = "after_market_data"
        elif pd.isna(prev_bar):
            label = "before_market_data"
        elif abs(next_delay) <= tolerance_minutes:
            label = "aligned_next_bar"
        elif nearest_delay <= tolerance_minutes:
            label = "aligned_nearest_bar"
        else:
            label = "timing_gap"
        rows.append(
            {
                "release_time": release_time,
                "title": row_value(event, "title"),
                "event_family": row_value(event, "event_family"),
                "catalyst_category": row_value(event, "catalyst_category"),
                "release_status": row_value(event, "release_status"),
                "previous_bar_time": prev_bar,
                "next_bar_time": next_bar,
                "minutes_since_previous_bar": prev_delay,
                "minutes_to_next_bar": next_delay,
                "nearest_abs_delay_minutes": nearest_delay,
                "alignment_label": label,
            }
        )
    return pd.DataFrame(rows)


def audit_summary(rows: pd.DataFrame, bars: pd.DataFrame, market_data: str, events_file: str, tolerance_minutes: float) -> dict:
    bar_seconds = infer_bar_seconds(bars)
    counts = rows["alignment_label"].value_counts().to_dict() if not rows.empty else {}
    in_range = rows[~rows["alignment_label"].isin(["before_market_data", "after_market_data"])] if not rows.empty else rows
    delays = pd.to_numeric(in_range.get("nearest_abs_delay_minutes"), errors="coerce") if not in_range.empty else pd.Series(dtype=float)
    return {
        "market_data": market_data,
        "events_file": events_file,
        "bar_interval_seconds_mode": bar_seconds,
        "tolerance_minutes": tolerance_minutes,
        "event_count": int(len(rows)),
        "in_range_event_count": int(len(in_range)),
        "alignment_counts": {str(k): int(v) for k, v in counts.items()},
        "nearest_abs_delay_minutes": {
            "median": float(delays.median()) if not delays.dropna().empty else None,
            "max": float(delays.max()) if not delays.dropna().empty else None,
            "p95": float(delays.quantile(0.95)) if not delays.dropna().empty else None,
        },
        "market_start": bars["date"].min().isoformat(sep=" ") if not bars.empty else "",
        "market_end": bars["date"].max().isoformat(sep=" ") if not bars.empty else "",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit release-time alignment against market bars.")
    p.add_argument("--market-data", default="data/NQ_5min_data.csv")
    p.add_argument("--events-file", default="macro_releases.csv")
    p.add_argument("--rows-output", default="macro_timing_audit.csv")
    p.add_argument("--summary-output", default="macro_timing_audit_report.json")
    p.add_argument("--tolerance-minutes", type=float, default=5.0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bars = load_market(args.market_data)
    events = load_events(args.events_file)
    rows = audit_rows(events, bars, args.tolerance_minutes)
    summary = audit_summary(rows, bars, args.market_data, args.events_file, args.tolerance_minutes)
    rows.to_csv(args.rows_output, index=False)
    Path(args.summary_output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote timing audit rows to {args.rows_output}")
    print(f"Wrote timing audit report to {args.summary_output}")
    print(f"Alignment counts: {summary['alignment_counts']}")


if __name__ == "__main__":
    main()
