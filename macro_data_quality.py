#!/usr/bin/env python3
"""
macro_data_quality.py

Quality report for market-data and macro-release coverage.

This module stays separate from fetching, reaction learning, and signal scoring.
It answers: "Is the data clean enough to trust the probability study?"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_MARKET_COLUMNS = ["date", "open", "high", "low", "close"]


def load_market_data(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    if "datetime" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"datetime": "date"})
    if "timestamp" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"timestamp": "date"})
    missing = [col for col in REQUIRED_MARKET_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"market data missing required column(s): {', '.join(missing)}")
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(None)
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def load_events(path: str) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    df.columns = [str(col).strip() for col in df.columns]
    time_col = "release_time" if "release_time" in df.columns else "date" if "date" in df.columns else ""
    if not time_col:
        return pd.DataFrame()
    df["release_time"] = pd.to_datetime(df[time_col], utc=True, errors="coerce").dt.tz_convert(None)
    return df.dropna(subset=["release_time"]).reset_index(drop=True)


def seconds_summary(diffs: pd.Series) -> dict:
    clean = diffs.dropna().dt.total_seconds()
    if clean.empty:
        return {"mode": None, "median": None, "p95": None}
    mode = clean.value_counts().idxmax()
    return {
        "mode": float(mode),
        "median": float(clean.median()),
        "p95": float(clean.quantile(0.95)),
    }


def gap_rows(df: pd.DataFrame, expected_seconds: float | None, limit: int) -> list[dict]:
    if expected_seconds is None or df.empty:
        return []
    working = df[["date"]].copy()
    working["previous_date"] = working["date"].shift(1)
    working["gap_seconds"] = (working["date"] - working["previous_date"]).dt.total_seconds()
    gaps = working[working["gap_seconds"] > expected_seconds * 1.5].sort_values("gap_seconds", ascending=False)
    rows = []
    for _, row in gaps.head(limit).iterrows():
        rows.append(
            {
                "previous_date": row["previous_date"].isoformat(sep=" ") if pd.notna(row["previous_date"]) else "",
                "date": row["date"].isoformat(sep=" "),
                "gap_seconds": float(row["gap_seconds"]),
            }
        )
    return rows


def nearest_bar_delays(events: pd.DataFrame, bars: pd.DataFrame) -> pd.Series:
    if events.empty or bars.empty:
        return pd.Series(dtype=float)
    bar_times = bars["date"].dropna().sort_values().reset_index(drop=True)
    values = bar_times.values
    delays = []
    for release_time in events["release_time"]:
        idx = int(np.searchsorted(values, np.datetime64(release_time), side="left"))
        if idx >= len(values):
            continue
        delay = (bar_times.iloc[idx] - release_time).total_seconds() / 60.0
        delays.append(delay)
    return pd.Series(delays, dtype=float)


def release_coverage(events: pd.DataFrame, bars: pd.DataFrame) -> dict:
    if events.empty or bars.empty:
        return {
            "events_loaded": int(len(events)),
            "events_inside_market_range": 0,
            "events_outside_market_range": int(len(events)),
            "nearest_bar_delay_minutes": {},
        }
    start = bars["date"].min()
    end = bars["date"].max()
    inside = events[(events["release_time"] >= start) & (events["release_time"] <= end)]
    delays = nearest_bar_delays(inside, bars)
    delay_summary = {}
    if not delays.empty:
        delay_summary = {
            "min": float(delays.min()),
            "median": float(delays.median()),
            "max": float(delays.max()),
            "exact_or_negative_count": int((delays <= 0).sum()),
            "within_5_minutes_count": int((delays <= 5).sum()),
        }
    return {
        "events_loaded": int(len(events)),
        "events_inside_market_range": int(len(inside)),
        "events_outside_market_range": int(len(events) - len(inside)),
        "market_start": start.isoformat(sep=" "),
        "market_end": end.isoformat(sep=" "),
        "nearest_bar_delay_minutes": delay_summary,
    }


def quality_report(market_data: str, events_file: str, max_gaps: int) -> tuple[dict, pd.DataFrame]:
    bars = load_market_data(market_data)
    events = load_events(events_file)

    null_counts = {col: int(bars[col].isna().sum()) for col in bars.columns}
    duplicate_timestamps = int(bars["date"].duplicated().sum())
    valid = bars.dropna(subset=REQUIRED_MARKET_COLUMNS)
    diffs = valid["date"].diff()
    interval = seconds_summary(diffs)
    expected_seconds = interval["mode"]

    high_low_bad = int((valid["high"] < valid["low"]).sum())
    high_body_bad = int((valid["high"] < valid[["open", "close"]].max(axis=1)).sum())
    low_body_bad = int((valid["low"] > valid[["open", "close"]].min(axis=1)).sum())
    volume_missing = int(valid["volume"].isna().sum()) if "volume" in valid.columns else len(valid)

    report = {
        "market_data": market_data,
        "events_file": events_file,
        "rows": int(len(bars)),
        "usable_rows": int(len(valid)),
        "start": valid["date"].min().isoformat(sep=" ") if not valid.empty else "",
        "end": valid["date"].max().isoformat(sep=" ") if not valid.empty else "",
        "duplicate_timestamps": duplicate_timestamps,
        "null_counts": null_counts,
        "interval_seconds": interval,
        "large_gaps": gap_rows(valid, expected_seconds, max_gaps),
        "ohlc_issues": {
            "high_less_than_low": high_low_bad,
            "high_below_open_or_close": high_body_bad,
            "low_above_open_or_close": low_body_bad,
            "volume_missing": volume_missing,
        },
        "release_coverage": release_coverage(events, valid),
    }

    score = 100
    score -= min(25, duplicate_timestamps)
    score -= min(25, high_low_bad + high_body_bad + low_body_bad)
    score -= min(20, int(null_counts.get("date", 0)) + int(null_counts.get("close", 0)))
    score -= min(20, len(report["large_gaps"]))
    if report["release_coverage"]["events_loaded"] and not report["release_coverage"]["events_inside_market_range"]:
        score -= 20
    report["quality_score"] = max(0, int(score))
    report["quality_label"] = "good" if score >= 85 else "watch" if score >= 65 else "poor"

    summary_rows = [
        {"metric": "rows", "value": report["rows"]},
        {"metric": "usable_rows", "value": report["usable_rows"]},
        {"metric": "duplicate_timestamps", "value": duplicate_timestamps},
        {"metric": "interval_mode_seconds", "value": expected_seconds},
        {"metric": "large_gap_count", "value": len(report["large_gaps"])},
        {"metric": "high_less_than_low", "value": high_low_bad},
        {"metric": "high_below_open_or_close", "value": high_body_bad},
        {"metric": "low_above_open_or_close", "value": low_body_bad},
        {"metric": "events_loaded", "value": report["release_coverage"]["events_loaded"]},
        {"metric": "events_inside_market_range", "value": report["release_coverage"]["events_inside_market_range"]},
        {"metric": "quality_score", "value": report["quality_score"]},
        {"metric": "quality_label", "value": report["quality_label"]},
    ]
    return report, pd.DataFrame(summary_rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create a market-data quality report for the macro catalyst pipeline.")
    p.add_argument("--market-data", default="data/NQ_5min_data.csv")
    p.add_argument("--events-file", default="macro_releases.csv")
    p.add_argument("--report-output", default="macro_data_quality_report.json")
    p.add_argument("--summary-output", default="macro_data_quality_summary.csv")
    p.add_argument("--max-gaps", type=int, default=20)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    report, summary = quality_report(args.market_data, args.events_file, args.max_gaps)
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary.to_csv(args.summary_output, index=False)
    print(f"Wrote data quality report to {args.report_output}")
    print(f"Wrote data quality summary to {args.summary_output}")
    print(f"Quality: {report['quality_label']} ({report['quality_score']}/100)")


if __name__ == "__main__":
    main()
