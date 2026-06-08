#!/usr/bin/env python3
"""
dabento_nq_adapter.py

Normalize Dabento GLBX MDP3 NQ OHLCV exports into the canonical OHLC schema.

The raw Dabento file can contain multiple NQ contracts at the same timestamp.
This module keeps the concern separate from the rest of the pipeline by:

1. Scanning the raw file in chunks.
2. Choosing the dominant contract for each futures session by total volume.
3. Writing a canonical continuous source-interval file.
4. Deriving 5-minute and 60-minute bars when the source is 1-minute data.

It does not change market_data_config.json, reaction profiles, live signals, or
the dashboard. Those integration steps happen only after verification.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OHLC_COLUMNS = ["open", "high", "low", "close"]
CANONICAL_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize Dabento NQ OHLCV 1m data and derive higher timeframes.")
    p.add_argument("--input", default="dabento/glbx-mdp3-20200101-20251231.ohlcv-1m.csv")
    p.add_argument("--source-interval", choices=["1m", "1h"], default="1m", help="Interval of the raw Dabento OHLCV file")
    p.add_argument("--chunksize", type=int, default=500_000)
    p.add_argument("--symbol-regex", default=r"^NQ[FGHJKMNQUVXZ][0-9]$", help="Regex for NQ futures symbols to include")
    p.add_argument("--session-timezone", default="America/New_York")
    p.add_argument("--session-open-hour", type=int, default=18)
    p.add_argument("--tick-size", type=float, default=0.25)
    p.add_argument("--out-1m", default="NQ_dabento_1min_data.csv")
    p.add_argument("--out-5m", default="NQ_dabento_5min_data.csv")
    p.add_argument("--out-60m", default="NQ_dabento_60min_data.csv")
    p.add_argument("--roll-map-output", default="NQ_dabento_roll_map.csv")
    p.add_argument("--report-output", default="dabento_nq_adapter_report.json")
    return p.parse_args()


def clean_chunk(raw: pd.DataFrame, symbol_pattern: re.Pattern[str], args: argparse.Namespace) -> pd.DataFrame:
    required = ["ts_event", "open", "high", "low", "close", "volume", "symbol"]
    missing = [col for col in required if col not in raw.columns]
    if missing:
        raise ValueError(f"Dabento file is missing required columns: {missing}")

    df = raw[required].copy()
    df["symbol"] = df["symbol"].astype("string").str.strip()
    df = df[df["symbol"].str.match(symbol_pattern, na=False)].copy()
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    for col in OHLC_COLUMNS + ["volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", *OHLC_COLUMNS, "volume"])
    if df.empty:
        return df

    local = df["date"].dt.tz_convert(args.session_timezone)
    session = local.dt.normalize()
    after_open = local.dt.hour >= args.session_open_hour
    session = session + pd.to_timedelta(after_open.astype(int), unit="D")
    df["session_date"] = session.dt.strftime("%Y-%m-%d")
    df["date"] = df["date"].dt.tz_convert(None)
    return df


def tick_issue_count(df: pd.DataFrame, tick_size: float) -> int:
    if tick_size <= 0 or df.empty:
        return 0
    count = 0
    for col in OHLC_COLUMNS:
        scaled = df[col] / tick_size
        count += int((scaled - scaled.round()).abs().gt(1e-7).sum())
    return count


def scan_input(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, dict[str, float]], dict[str, Any]]:
    symbol_pattern = re.compile(args.symbol_regex)
    session_symbol_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"volume": 0.0, "rows": 0.0})
    symbol_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"rows": 0, "volume": 0.0, "start": None, "end": None})
    raw_rows = 0
    nq_rows = 0
    ohlc_issues = {"high_less_than_low": 0, "high_below_open_or_close": 0, "low_above_open_or_close": 0}
    tick_issues = 0
    min_date = None
    max_date = None

    for raw in pd.read_csv(args.input, chunksize=args.chunksize):
        raw_rows += int(len(raw))
        df = clean_chunk(raw, symbol_pattern, args)
        if df.empty:
            continue
        nq_rows += int(len(df))
        min_date = df["date"].min() if min_date is None else min(min_date, df["date"].min())
        max_date = df["date"].max() if max_date is None else max(max_date, df["date"].max())

        ohlc_issues["high_less_than_low"] += int((df["high"] < df["low"]).sum())
        ohlc_issues["high_below_open_or_close"] += int((df["high"] < df[["open", "close"]].max(axis=1)).sum())
        ohlc_issues["low_above_open_or_close"] += int((df["low"] > df[["open", "close"]].min(axis=1)).sum())
        tick_issues += tick_issue_count(df, args.tick_size)

        grouped = df.groupby(["session_date", "symbol"], dropna=False).agg(volume=("volume", "sum"), rows=("volume", "size"))
        for (session_date, symbol), row in grouped.iterrows():
            key = f"{session_date}|{symbol}"
            session_symbol_stats[key]["volume"] += float(row["volume"])
            session_symbol_stats[key]["rows"] += float(row["rows"])

        by_symbol = df.groupby("symbol", dropna=False).agg(rows=("volume", "size"), volume=("volume", "sum"), start=("date", "min"), end=("date", "max"))
        for symbol, row in by_symbol.iterrows():
            stats = symbol_stats[str(symbol)]
            stats["rows"] += int(row["rows"])
            stats["volume"] += float(row["volume"])
            start = row["start"]
            end = row["end"]
            stats["start"] = start if stats["start"] is None else min(stats["start"], start)
            stats["end"] = end if stats["end"] is None else max(stats["end"], end)

    best_by_session: dict[str, dict[str, float | str]] = {}
    for key, stats in session_symbol_stats.items():
        session_date, symbol = key.split("|", 1)
        current = best_by_session.get(session_date)
        if current is None or float(stats["volume"]) > float(current["volume"]):
            best_by_session[session_date] = {
                "session_date": session_date,
                "symbol": symbol,
                "volume": float(stats["volume"]),
                "rows": float(stats["rows"]),
            }

    dominant_by_session = {session: str(stats["symbol"]) for session, stats in best_by_session.items()}
    report = {
        "input": args.input,
        "raw_rows": raw_rows,
        "nq_rows": nq_rows,
        "start": min_date.isoformat(sep=" ") if min_date is not None else "",
        "end": max_date.isoformat(sep=" ") if max_date is not None else "",
        "sessions": len(dominant_by_session),
        "symbols": len(symbol_stats),
        "ohlc_issues": ohlc_issues,
        "tick_issues": tick_issues,
        "symbol_stats": {
            symbol: {
                "rows": int(stats["rows"]),
                "volume": float(stats["volume"]),
                "start": stats["start"].isoformat(sep=" ") if stats["start"] is not None else "",
                "end": stats["end"].isoformat(sep=" ") if stats["end"] is not None else "",
            }
            for symbol, stats in sorted(symbol_stats.items())
        },
    }
    return dominant_by_session, best_by_session, report


def build_continuous_bars(args: argparse.Namespace, dominant_by_session: dict[str, str]) -> pd.DataFrame:
    symbol_pattern = re.compile(args.symbol_regex)
    selected_chunks = []
    selected_rows = 0

    for raw in pd.read_csv(args.input, chunksize=args.chunksize):
        df = clean_chunk(raw, symbol_pattern, args)
        if df.empty:
            continue
        expected_symbol = df["session_date"].map(dominant_by_session)
        selected = df[df["symbol"] == expected_symbol].copy()
        if selected.empty:
            continue
        selected_rows += int(len(selected))
        selected_chunks.append(selected[["date", "open", "high", "low", "close", "volume", "symbol", "session_date"]])

    if not selected_chunks:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    selected = pd.concat(selected_chunks, ignore_index=True).sort_values(["date", "symbol"], kind="mergesort")
    duplicates_before = int(selected["date"].duplicated().sum())
    canonical = (
        selected.groupby("date", as_index=False, sort=True)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=OHLC_COLUMNS)
    )
    canonical["adj_close"] = canonical["close"]
    canonical = canonical[CANONICAL_COLUMNS]
    canonical.attrs["selected_rows"] = selected_rows
    canonical.attrs["duplicates_before_aggregation"] = duplicates_before
    return canonical


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    working = df.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    out = (
        working.set_index("date")
        .sort_index()
        .resample(rule, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=OHLC_COLUMNS)
        .reset_index()
    )
    out["adj_close"] = out["close"]
    return out[CANONICAL_COLUMNS]


def interval_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    dates = pd.to_datetime(df["date"], errors="coerce").dropna().sort_values()
    diffs = dates.diff().dropna().dt.total_seconds()
    if diffs.empty:
        return {}
    return {
        "mode_seconds": float(diffs.mode().iloc[0]) if not diffs.mode().empty else None,
        "median_seconds": float(diffs.median()),
        "p95_seconds": float(diffs.quantile(0.95)),
        "top_counts": {str(k): int(v) for k, v in diffs.value_counts().head(10).items()},
    }


def write_canonical(df: pd.DataFrame, path: str) -> None:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    out.to_csv(path, index=False)


def write_roll_map(best_by_session: dict[str, dict[str, float | str]], path: str) -> None:
    rows = sorted(best_by_session.values(), key=lambda row: str(row["session_date"]))
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> None:
    args = parse_args()
    dominant_by_session, best_by_session, report = scan_input(args)
    continuous = build_continuous_bars(args, dominant_by_session)

    if args.source_interval == "1m":
        one_minute = continuous
        five_minute = resample_ohlcv(one_minute, "5min")
        sixty_minute = resample_ohlcv(one_minute, "60min")
        write_canonical(one_minute, args.out_1m)
        write_canonical(five_minute, args.out_5m)
        write_canonical(sixty_minute, args.out_60m)
        row_counts = {
            "one_minute": int(len(one_minute)),
            "five_minute": int(len(five_minute)),
            "sixty_minute": int(len(sixty_minute)),
        }
        intervals = {
            "one_minute": interval_summary(one_minute),
            "five_minute": interval_summary(five_minute),
            "sixty_minute": interval_summary(sixty_minute),
        }
        output_files = {
            "one_minute": args.out_1m,
            "five_minute": args.out_5m,
            "sixty_minute": args.out_60m,
            "roll_map": args.roll_map_output,
        }
    else:
        sixty_minute = continuous
        write_canonical(sixty_minute, args.out_60m)
        row_counts = {"sixty_minute": int(len(sixty_minute))}
        intervals = {"sixty_minute": interval_summary(sixty_minute)}
        output_files = {
            "sixty_minute": args.out_60m,
            "roll_map": args.roll_map_output,
        }

    write_roll_map(best_by_session, args.roll_map_output)

    report["source_interval"] = args.source_interval
    report["outputs"] = output_files
    report["selected_rows_before_aggregation"] = int(continuous.attrs.get("selected_rows", 0))
    report["duplicate_selected_timestamps_before_aggregation"] = int(continuous.attrs.get("duplicates_before_aggregation", 0))
    report["canonical_rows"] = row_counts
    report["canonical_range"] = {
        "start": pd.to_datetime(continuous["date"]).min().isoformat(sep=" ") if not continuous.empty else "",
        "end": pd.to_datetime(continuous["date"]).max().isoformat(sep=" ") if not continuous.empty else "",
    }
    report["intervals"] = intervals
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.source_interval == "1m":
        print(f"Wrote {row_counts['one_minute']:,} 1m rows to {args.out_1m}")
        print(f"Wrote {row_counts['five_minute']:,} 5m rows to {args.out_5m}")
    print(f"Wrote {row_counts['sixty_minute']:,} 60m rows to {args.out_60m}")
    print(f"Wrote roll map to {args.roll_map_output}")
    print(f"Wrote report to {args.report_output}")


if __name__ == "__main__":
    main()
