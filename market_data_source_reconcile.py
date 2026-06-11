#!/usr/bin/env python3
"""
market_data_source_reconcile.py

Separate source-reconciliation layer for daily futures market data.

This module compares a candidate source, such as an Investing.com daily export,
against a reference source, such as Yahoo daily NQ data. It does not update the
active model, dashboard, live signals, or config. It writes audit artifacts and
an optional clean canonical candidate for later model experiments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from market_data_verify import clean_column, numeric_series


OHLC_COLUMNS = ["open", "high", "low", "close"]
CANONICAL_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reconcile a candidate daily futures source against a reference source.")
    p.add_argument("--candidate", required=True, help="Candidate CSV, e.g. Investing.com daily export")
    p.add_argument("--reference", default="data/NQ_F_daily.csv", help="Reference daily OHLC CSV")
    p.add_argument("--source-name", default="investing", help="Source label used in report metadata")
    p.add_argument("--date-column", default="Date")
    p.add_argument("--open-column", default="Open")
    p.add_argument("--high-column", default="High")
    p.add_argument("--low-column", default="Low")
    p.add_argument("--close-column", default="Price")
    p.add_argument("--volume-column", default="Vol.")
    p.add_argument("--tick-size", type=float, default=0.25)
    p.add_argument("--price-tolerance", type=float, default=0.25)
    p.add_argument("--round-to-tick", action="store_true", help="Round candidate OHLC values to the nearest tick before output")
    p.add_argument("--keep-unmatched", action="store_true", help="Allow rows without a reference match into the clean candidate")
    p.add_argument("--reconciliation-output", default="market_data_source_reconciliation_investing_vs_yahoo.csv")
    p.add_argument("--candidate-output", default="NQ_investing_daily_clean_candidate.csv")
    p.add_argument("--report-output", default="market_data_source_reconciliation_investing_vs_yahoo_report.json")
    return p.parse_args()


def nearest_tick(values: pd.Series, tick_size: float) -> pd.Series:
    if tick_size <= 0:
        return values
    return (values / tick_size).round() * tick_size


def tick_issue_mask(df: pd.DataFrame, tick_size: float) -> pd.Series:
    if tick_size <= 0:
        return pd.Series(False, index=df.index)
    mask = pd.Series(False, index=df.index)
    for col in OHLC_COLUMNS:
        scaled = df[col] / tick_size
        mask |= (scaled - scaled.round()).abs() > 1e-7
    return mask


def normalize_candidate(args: argparse.Namespace) -> pd.DataFrame:
    raw = pd.read_csv(args.candidate)
    original_columns = list(raw.columns)
    raw.columns = [clean_column(col) for col in raw.columns]

    column_map = {
        "date": clean_column(args.date_column),
        "open": clean_column(args.open_column),
        "high": clean_column(args.high_column),
        "low": clean_column(args.low_column),
        "close": clean_column(args.close_column),
        "volume": clean_column(args.volume_column),
    }
    missing = [name for name, col in column_map.items() if col not in raw.columns and name != "volume"]
    if missing:
        raise ValueError(f"candidate is missing required columns after cleaning: {missing}; saw {original_columns}")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw[column_map["date"]], errors="coerce").dt.normalize()
    for col in OHLC_COLUMNS:
        out[f"source_{col}"] = numeric_series(raw[column_map[col]])
    if column_map["volume"] in raw.columns:
        out["source_volume"] = numeric_series(raw[column_map["volume"]])
    else:
        out["source_volume"] = 0

    out = out.dropna(subset=["date", *[f"source_{col}" for col in OHLC_COLUMNS]])
    out = out.sort_values("date", kind="mergesort").reset_index(drop=True)
    out["source_date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def normalize_reference(path: str) -> pd.DataFrame:
    ref = pd.read_csv(path)
    ref.columns = [clean_column(col) for col in ref.columns]
    if "date" not in ref.columns:
        raise ValueError("reference must contain a date column")
    missing = [col for col in OHLC_COLUMNS if col not in ref.columns]
    if missing:
        raise ValueError(f"reference is missing required OHLC columns: {missing}")

    ref["date"] = pd.to_datetime(ref["date"], errors="coerce").dt.normalize()
    for col in OHLC_COLUMNS + ["volume"]:
        if col in ref.columns:
            ref[col] = pd.to_numeric(ref[col], errors="coerce")
    ref = ref.dropna(subset=["date", *OHLC_COLUMNS]).sort_values("date").reset_index(drop=True)
    return ref[["date", *OHLC_COLUMNS, *[col for col in ["volume"] if col in ref.columns]]]


def build_reconciliation(candidate: pd.DataFrame, reference: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    working = candidate.copy()
    for col in OHLC_COLUMNS:
        source_col = f"source_{col}"
        rounded_col = f"candidate_{col}"
        working[rounded_col] = nearest_tick(working[source_col], args.tick_size) if args.round_to_tick else working[source_col]
    working["candidate_volume"] = working["source_volume"].fillna(0)

    candidate_ohlc_valid = (
        (working["candidate_high"] >= working[["candidate_open", "candidate_close"]].max(axis=1))
        & (working["candidate_low"] <= working[["candidate_open", "candidate_close"]].min(axis=1))
        & (working["candidate_high"] >= working["candidate_low"])
    )
    source_tick_issues = tick_issue_mask(working.rename(columns={f"source_{col}": col for col in OHLC_COLUMNS}), args.tick_size)
    rounded_changed = pd.Series(False, index=working.index)
    for col in OHLC_COLUMNS:
        rounded_changed |= (working[f"candidate_{col}"] - working[f"source_{col}"]).abs() > 1e-7

    ref = reference.rename(columns={col: f"reference_{col}" for col in OHLC_COLUMNS})
    if "volume" in ref.columns:
        ref = ref.rename(columns={"volume": "reference_volume"})
    merged = working.merge(ref, on="date", how="left")
    merged["has_reference"] = merged["reference_close"].notna()

    within = pd.Series(True, index=merged.index)
    max_diff = pd.Series(np.nan, index=merged.index)
    for col in OHLC_COLUMNS:
        diff_col = f"{col}_abs_diff"
        merged[diff_col] = (merged[f"candidate_{col}"] - merged[f"reference_{col}"]).abs()
        max_diff = pd.concat([max_diff, merged[diff_col]], axis=1).max(axis=1, skipna=True)
        within &= merged[diff_col].le(args.price_tolerance).fillna(False)
    merged["max_abs_ohlc_diff"] = max_diff
    merged["reference_within_tolerance"] = within & merged["has_reference"]
    merged["candidate_ohlc_valid"] = candidate_ohlc_valid
    merged["source_tick_issue"] = source_tick_issues
    merged["rounded_to_tick"] = rounded_changed

    merged["clean_candidate"] = (
        merged["candidate_ohlc_valid"]
        & (merged["reference_within_tolerance"] | (args.keep_unmatched & ~merged["has_reference"]))
    )
    merged["status"] = np.select(
        [
            ~merged["candidate_ohlc_valid"],
            merged["has_reference"] & ~merged["reference_within_tolerance"],
            ~merged["has_reference"],
            merged["clean_candidate"],
        ],
        ["source_ohlc_invalid", "reference_mismatch", "no_reference", "clean"],
        default="review",
    )

    order = [
        "date",
        "status",
        "clean_candidate",
        "has_reference",
        "reference_within_tolerance",
        "candidate_ohlc_valid",
        "source_tick_issue",
        "rounded_to_tick",
        "max_abs_ohlc_diff",
    ]
    value_cols = []
    for col in OHLC_COLUMNS:
        value_cols.extend([f"source_{col}", f"candidate_{col}", f"reference_{col}", f"{col}_abs_diff"])
    return merged[order + value_cols + ["candidate_volume"]]


def write_clean_candidate(reconciliation: pd.DataFrame, output: str) -> pd.DataFrame:
    clean = reconciliation[reconciliation["clean_candidate"]].copy()
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(clean["date"]).dt.strftime("%Y-%m-%d")
    for col in OHLC_COLUMNS:
        out[col] = clean[f"candidate_{col}"]
    out["adj_close"] = out["close"]
    out["volume"] = clean["candidate_volume"].fillna(0)
    out = out[CANONICAL_COLUMNS]
    out.to_csv(output, index=False)
    return out


def build_report(reconciliation: pd.DataFrame, clean_candidate: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    overlap = reconciliation[reconciliation["has_reference"]]
    mismatches = reconciliation[reconciliation["status"] == "reference_mismatch"].copy()
    top_mismatches = (
        mismatches.sort_values("max_abs_ohlc_diff", ascending=False)
        .head(15)[["date", "max_abs_ohlc_diff", "source_close", "candidate_close", "reference_close"]]
        .assign(date=lambda df: pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"))
        .to_dict("records")
    )
    return {
        "source_name": args.source_name,
        "candidate": args.candidate,
        "reference": args.reference,
        "tick_size": args.tick_size,
        "price_tolerance": args.price_tolerance,
        "round_to_tick": bool(args.round_to_tick),
        "keep_unmatched": bool(args.keep_unmatched),
        "rows": {
            "candidate_rows": int(len(reconciliation)),
            "reference_overlap_rows": int(len(overlap)),
            "clean_candidate_rows": int(len(clean_candidate)),
            "reference_match_rows": int(reconciliation["reference_within_tolerance"].sum()),
            "reference_mismatch_rows": int((reconciliation["status"] == "reference_mismatch").sum()),
            "no_reference_rows": int((reconciliation["status"] == "no_reference").sum()),
            "source_ohlc_invalid_rows": int((reconciliation["status"] == "source_ohlc_invalid").sum()),
            "source_tick_issue_rows": int(reconciliation["source_tick_issue"].sum()),
            "rounded_to_tick_rows": int(reconciliation["rounded_to_tick"].sum()),
        },
        "coverage": {
            "candidate_start": pd.to_datetime(reconciliation["date"]).min().strftime("%Y-%m-%d") if not reconciliation.empty else "",
            "candidate_end": pd.to_datetime(reconciliation["date"]).max().strftime("%Y-%m-%d") if not reconciliation.empty else "",
            "clean_start": clean_candidate["date"].min() if not clean_candidate.empty else "",
            "clean_end": clean_candidate["date"].max() if not clean_candidate.empty else "",
        },
        "diff_summary": {
            "max_abs_ohlc_diff": None if overlap.empty else float(overlap["max_abs_ohlc_diff"].max()),
            "mean_abs_ohlc_diff": None if overlap.empty else float(overlap["max_abs_ohlc_diff"].mean()),
            "median_abs_ohlc_diff": None if overlap.empty else float(overlap["max_abs_ohlc_diff"].median()),
        },
        "top_mismatches": top_mismatches,
        "approved_for_active_model": False,
        "note": "Generated as a separate source candidate. Active Yahoo-based model is unchanged.",
    }


def main() -> None:
    args = parse_args()
    candidate = normalize_candidate(args)
    reference = normalize_reference(args.reference)
    reconciliation = build_reconciliation(candidate, reference, args)
    reconciliation.to_csv(args.reconciliation_output, index=False)
    clean_candidate = write_clean_candidate(reconciliation, args.candidate_output)
    report = build_report(reconciliation, clean_candidate, args)
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote reconciliation rows to {args.reconciliation_output}")
    print(f"Wrote clean candidate rows to {args.candidate_output}")
    print(f"Wrote report to {args.report_output}")
    print(
        "Clean rows: "
        f"{report['rows']['clean_candidate_rows']} / {report['rows']['candidate_rows']} "
        f"(overlap matches: {report['rows']['reference_match_rows']})"
    )


if __name__ == "__main__":
    main()
