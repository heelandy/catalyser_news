#!/usr/bin/env python3
"""
market_data_verify.py

Separate verification layer for newly added market-data files.

This module does not update active market data, reaction profiles, live signals,
or the dashboard. It inspects a candidate OHLC file and writes verification
reports so the dataset can be accepted or rejected before use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


OHLC_COLUMNS = ["open", "high", "low", "close"]
CANONICAL_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]

ALIASES = {
    "datetime": ["date", "datetime", "timestamp", "timestamp_et", "time", "bar_time"],
    "open": ["open", "o"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "c", "last", "price"],
    "volume": ["volume", "vol", "v"],
}


def clean_column(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "")


def numeric_series(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip()
    multiplier = pd.Series(1.0, index=values.index)
    suffix = text.str.extract(r"([kKmMbB])\s*$", expand=False).str.lower()
    multiplier = multiplier.mask(suffix == "k", 1_000.0)
    multiplier = multiplier.mask(suffix == "m", 1_000_000.0)
    multiplier = multiplier.mask(suffix == "b", 1_000_000_000.0)
    clean = (
        text.str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace(r"[kKmMbB]\s*$", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    return pd.to_numeric(clean, errors="coerce") * multiplier


def choose_column(columns: list[str], explicit: str, logical_name: str, required: bool = True) -> str | None:
    clean_explicit = clean_column(explicit) if explicit else ""
    if clean_explicit:
        if clean_explicit not in columns:
            raise ValueError(f"{explicit!r} was not found in columns: {', '.join(columns)}")
        return clean_explicit
    for candidate in ALIASES[logical_name]:
        if candidate in columns:
            return candidate
    if required:
        raise ValueError(f"Could not detect {logical_name} column in: {', '.join(columns)}")
    return None


def percentile(values: pd.Series, q: float) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.quantile(q))


def parse_candidate(path: Path, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    raw = pd.read_csv(path)
    original_columns = list(raw.columns)
    raw.columns = [clean_column(col) for col in raw.columns]

    datetime_col = choose_column(raw.columns.tolist(), args.datetime_column, "datetime")
    open_col = choose_column(raw.columns.tolist(), args.open_column, "open")
    high_col = choose_column(raw.columns.tolist(), args.high_column, "high")
    low_col = choose_column(raw.columns.tolist(), args.low_column, "low")
    close_col = choose_column(raw.columns.tolist(), args.close_column, "close")
    volume_col = choose_column(raw.columns.tolist(), args.volume_column, "volume", required=False)

    local_raw = pd.to_datetime(raw[datetime_col], errors="coerce")
    parsed_failures = int(local_raw.isna().sum())
    localized = local_raw.dt.tz_localize(
        ZoneInfo(args.input_timezone),
        nonexistent="shift_forward",
        ambiguous="NaT",
    )
    localization_failures = int(localized.isna().sum()) - parsed_failures

    out = pd.DataFrame()
    out["date"] = localized.dt.tz_convert("UTC").dt.tz_localize(None)
    for logical, col in [("open", open_col), ("high", high_col), ("low", low_col), ("close", close_col)]:
        out[logical] = numeric_series(raw[col])
    out["volume"] = numeric_series(raw[volume_col]) if volume_col else 0
    out["adj_close"] = out["close"]

    local = pd.DataFrame()
    local["local_time"] = localized
    for col in OHLC_COLUMNS + ["volume"]:
        local[col] = out[col]

    meta = {
        "input": str(path),
        "raw_rows": int(len(raw)),
        "original_columns": original_columns,
        "clean_columns": list(raw.columns),
        "datetime_column": datetime_col,
        "open_column": open_col,
        "high_column": high_col,
        "low_column": low_col,
        "close_column": close_col,
        "volume_column": volume_col or "",
        "input_timezone": args.input_timezone,
        "datetime_parse_failures": parsed_failures,
        "timezone_localization_failures": max(0, localization_failures),
    }

    valid_mask = out[["date", "open", "high", "low", "close"]].notna().all(axis=1)
    out = out.loc[valid_mask].copy()
    local = local.loc[valid_mask].copy()
    sort_index = out["date"].sort_values(kind="mergesort").index
    out = out.loc[sort_index].reset_index(drop=True)
    local = local.loc[sort_index].reset_index(drop=True)
    out = out[CANONICAL_COLUMNS]
    return out, local, meta


def basic_quality(df: pd.DataFrame, tick_size: float, expected_seconds: int) -> dict:
    duplicates = int(df["date"].duplicated().sum())
    diffs = df["date"].sort_values().diff().dropna().dt.total_seconds()
    interval_counts = diffs.value_counts().head(15)
    gap_rows = []
    if not diffs.empty:
        sorted_df = df.sort_values("date").reset_index(drop=True)
        gap_mask = diffs > expected_seconds
        top_gaps = diffs[gap_mask].sort_values(ascending=False).head(25)
        for idx, seconds in top_gaps.items():
            gap_rows.append(
                {
                    "previous_date": str(sorted_df.loc[idx - 1, "date"]),
                    "date": str(sorted_df.loc[idx, "date"]),
                    "gap_seconds": float(seconds),
                }
            )

    high_less_low = int((df["high"] < df["low"]).sum())
    high_below_open_close = int((df["high"] < df[["open", "close"]].max(axis=1)).sum())
    low_above_open_close = int((df["low"] > df[["open", "close"]].min(axis=1)).sum())
    negative_volume = int((df["volume"] < 0).sum())
    zero_volume = int((df["volume"] == 0).sum())

    tick_issues = {}
    if tick_size > 0:
        for col in OHLC_COLUMNS:
            scaled = df[col] / tick_size
            tick_issues[col] = int((np.abs(scaled - np.round(scaled)) > 1e-7).sum())

    by_year = df.assign(year=df["date"].dt.year).groupby("year").size().to_dict()
    by_month = df.assign(month=df["date"].dt.to_period("M").astype(str)).groupby("month").size().to_dict()

    return {
        "rows": int(len(df)),
        "start": df["date"].min().isoformat(sep=" ") if not df.empty else "",
        "end": df["date"].max().isoformat(sep=" ") if not df.empty else "",
        "duplicate_timestamps": duplicates,
        "null_counts": {col: int(df[col].isna().sum()) for col in CANONICAL_COLUMNS},
        "ohlc_issues": {
            "high_less_than_low": high_less_low,
            "high_below_open_or_close": high_below_open_close,
            "low_above_open_or_close": low_above_open_close,
        },
        "volume_issues": {
            "negative_volume": negative_volume,
            "zero_volume": zero_volume,
        },
        "tick_size": tick_size,
        "tick_issues": tick_issues,
        "interval_seconds": {
            "mode": float(diffs.mode().iloc[0]) if not diffs.empty else None,
            "median": float(diffs.median()) if not diffs.empty else None,
            "p95": percentile(diffs, 0.95),
            "top_counts": {str(float(k)): int(v) for k, v in interval_counts.items()},
        },
        "large_gaps": gap_rows,
        "rows_by_year": {str(k): int(v) for k, v in by_year.items()},
        "rows_by_month": {str(k): int(v) for k, v in by_month.items()},
    }


def load_reference(path: str) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    ref_path = Path(path)
    if not ref_path.exists():
        return pd.DataFrame()
    if ref_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(ref_path)
    else:
        df = pd.read_csv(ref_path)
    df.columns = [clean_column(col) for col in df.columns]
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in [c for c in OHLC_COLUMNS + ["volume"] if c in df.columns]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def compare_intraday(candidate: pd.DataFrame, reference: pd.DataFrame, tolerance: float) -> dict:
    if candidate.empty or reference.empty:
        return {"status": "not_run", "reason": "missing candidate or reference"}

    hourly = (
        candidate.set_index("date")
        .sort_index()
        .resample("60min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=OHLC_COLUMNS)
        .reset_index()
    )
    ref = reference[["date", *[col for col in OHLC_COLUMNS if col in reference.columns]]].copy()
    merged = hourly.merge(ref, on="date", suffixes=("_candidate", "_reference"))
    if merged.empty:
        return {"status": "not_run", "reason": "no overlapping hourly timestamps"}

    diffs = {}
    max_abs = 0.0
    within_all = pd.Series(True, index=merged.index)
    for col in OHLC_COLUMNS:
        diff = (merged[f"{col}_candidate"] - merged[f"{col}_reference"]).abs()
        diffs[col] = {
            "max_abs": float(diff.max()),
            "mean_abs": float(diff.mean()),
            "within_tolerance_count": int((diff <= tolerance).sum()),
        }
        max_abs = max(max_abs, float(diff.max()))
        within_all &= diff <= tolerance
    close_offset = merged["close_candidate"] - merged["close_reference"]
    candidate_delta = merged["close_candidate"].diff()
    reference_delta = merged["close_reference"].diff()
    delta_diff = (candidate_delta - reference_delta).abs().dropna()
    delta_corr = candidate_delta.corr(reference_delta)
    return {
        "status": "ok" if int(within_all.sum()) == len(merged) else "mismatch",
        "comparison": "candidate_1m_resampled_to_60m_vs_reference_60m",
        "overlap_rows": int(len(merged)),
        "all_ohlc_within_tolerance_rows": int(within_all.sum()),
        "tolerance_points": tolerance,
        "max_abs_ohlc_diff": max_abs,
        "diffs": diffs,
        "close_offset_points": {
            "mean": float(close_offset.mean()),
            "std": float(close_offset.std()),
            "min": float(close_offset.min()),
            "max": float(close_offset.max()),
        },
        "close_delta_comparison": {
            "correlation": None if pd.isna(delta_corr) else float(delta_corr),
            "mean_abs_delta_diff": None if delta_diff.empty else float(delta_diff.mean()),
            "max_abs_delta_diff": None if delta_diff.empty else float(delta_diff.max()),
            "within_1_point_count": int((delta_diff <= 1.0).sum()) if not delta_diff.empty else 0,
            "delta_rows": int(len(delta_diff)),
        },
        "first_overlap": str(merged["date"].min()),
        "last_overlap": str(merged["date"].max()),
    }


def futures_session_date(local_time: pd.Series) -> pd.Series:
    local_naive = local_time.dt.tz_localize(None)
    session = local_naive.dt.normalize()
    after_open = local_naive.dt.hour >= 18
    return (session + pd.to_timedelta(after_open.astype(int), unit="D")).dt.date


def compare_daily(local_candidate: pd.DataFrame, reference: pd.DataFrame, tolerance: float) -> dict:
    if local_candidate.empty or reference.empty:
        return {"status": "not_run", "reason": "missing candidate or reference"}

    working = local_candidate.dropna(subset=["local_time"]).copy()
    working["session_date"] = futures_session_date(working["local_time"])
    daily = (
        working.sort_values("local_time")
        .groupby("session_date")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .reset_index()
    )
    daily["session_date"] = pd.to_datetime(daily["session_date"])

    ref = reference[["date", *[col for col in OHLC_COLUMNS if col in reference.columns]]].copy()
    ref["date"] = ref["date"].dt.normalize()
    merged = daily.merge(ref, left_on="session_date", right_on="date", suffixes=("_candidate", "_reference"))
    if merged.empty:
        return {"status": "not_run", "reason": "no overlapping daily dates"}

    diffs = {}
    max_abs = 0.0
    within_all = pd.Series(True, index=merged.index)
    for col in OHLC_COLUMNS:
        diff = (merged[f"{col}_candidate"] - merged[f"{col}_reference"]).abs()
        diffs[col] = {
            "max_abs": float(diff.max()),
            "mean_abs": float(diff.mean()),
            "within_tolerance_count": int((diff <= tolerance).sum()),
        }
        max_abs = max(max_abs, float(diff.max()))
        within_all &= diff <= tolerance
    close_offset = merged["close_candidate"] - merged["close_reference"]
    candidate_delta = merged["close_candidate"].diff()
    reference_delta = merged["close_reference"].diff()
    delta_diff = (candidate_delta - reference_delta).abs().dropna()
    delta_corr = candidate_delta.corr(reference_delta)
    return {
        "status": "ok" if int(within_all.sum()) == len(merged) else "mismatch",
        "comparison": "candidate_1m_session_daily_vs_reference_daily",
        "overlap_rows": int(len(merged)),
        "all_ohlc_within_tolerance_rows": int(within_all.sum()),
        "tolerance_points": tolerance,
        "max_abs_ohlc_diff": max_abs,
        "diffs": diffs,
        "close_offset_points": {
            "mean": float(close_offset.mean()),
            "std": float(close_offset.std()),
            "min": float(close_offset.min()),
            "max": float(close_offset.max()),
        },
        "close_delta_comparison": {
            "correlation": None if pd.isna(delta_corr) else float(delta_corr),
            "mean_abs_delta_diff": None if delta_diff.empty else float(delta_diff.mean()),
            "max_abs_delta_diff": None if delta_diff.empty else float(delta_diff.max()),
            "within_1_point_count": int((delta_diff <= 1.0).sum()) if not delta_diff.empty else 0,
            "delta_rows": int(len(delta_diff)),
        },
        "first_overlap": str(merged["session_date"].min()),
        "last_overlap": str(merged["session_date"].max()),
    }


def verdict(meta: dict, quality: dict, intraday: dict, daily: dict) -> dict:
    blockers = []
    warnings = []

    if meta["datetime_parse_failures"]:
        blockers.append(f"{meta['datetime_parse_failures']} timestamp parse failures")
    if quality["duplicate_timestamps"]:
        blockers.append(f"{quality['duplicate_timestamps']} duplicate UTC timestamps")
    if any(quality["ohlc_issues"].values()):
        blockers.append(f"OHLC integrity issues: {quality['ohlc_issues']}")
    if any(quality["tick_issues"].values()):
        warnings.append(f"Non-tick-aligned prices: {quality['tick_issues']}")
    if meta["timezone_localization_failures"]:
        warnings.append(f"{meta['timezone_localization_failures']} timezone localization failures, likely DST fallback ambiguous minutes")
    if meta["raw_rows"] in {1048575, 1048576}:
        warnings.append("Row count is at or one row below Excel's worksheet limit; check for export truncation")
    if intraday.get("status") == "mismatch":
        warnings.append("Candidate differs from Yahoo 60m reference on overlapping hourly bars")
    if daily.get("status") == "mismatch":
        warnings.append("Candidate differs from Yahoo daily reference on overlapping sessions")

    approved = not blockers and intraday.get("status") in {"ok", "not_run"} and daily.get("status") in {"ok", "not_run"}
    if warnings and (intraday.get("status") == "mismatch" or daily.get("status") == "mismatch"):
        approved = False
    return {
        "approved_for_model_use": bool(approved),
        "label": "pass" if approved else "do_not_use_yet",
        "blockers": blockers,
        "warnings": warnings,
    }


def write_summary_csv(path: Path, report: dict) -> None:
    rows = [
        {"section": "verdict", "metric": "label", "value": report["verdict"]["label"]},
        {"section": "verdict", "metric": "approved_for_model_use", "value": report["verdict"]["approved_for_model_use"]},
        {"section": "quality", "metric": "rows", "value": report["quality"]["rows"]},
        {"section": "quality", "metric": "start", "value": report["quality"]["start"]},
        {"section": "quality", "metric": "end", "value": report["quality"]["end"]},
        {"section": "quality", "metric": "duplicate_timestamps", "value": report["quality"]["duplicate_timestamps"]},
        {"section": "quality", "metric": "interval_mode_seconds", "value": report["quality"]["interval_seconds"]["mode"]},
        {"section": "intraday_reference", "metric": "status", "value": report["intraday_reference"].get("status")},
        {"section": "intraday_reference", "metric": "overlap_rows", "value": report["intraday_reference"].get("overlap_rows", "")},
        {"section": "intraday_reference", "metric": "max_abs_ohlc_diff", "value": report["intraday_reference"].get("max_abs_ohlc_diff", "")},
        {"section": "daily_reference", "metric": "status", "value": report["daily_reference"].get("status")},
        {"section": "daily_reference", "metric": "overlap_rows", "value": report["daily_reference"].get("overlap_rows", "")},
        {"section": "daily_reference", "metric": "max_abs_ohlc_diff", "value": report["daily_reference"].get("max_abs_ohlc_diff", "")},
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a candidate futures OHLC dataset before model use.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--datetime-column", default="")
    parser.add_argument("--input-timezone", default="UTC")
    parser.add_argument("--open-column", default="")
    parser.add_argument("--high-column", default="")
    parser.add_argument("--low-column", default="")
    parser.add_argument("--close-column", default="")
    parser.add_argument("--volume-column", default="")
    parser.add_argument("--expected-interval-seconds", type=int, default=60)
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--reference-intraday", default="")
    parser.add_argument("--reference-daily", default="")
    parser.add_argument("--price-tolerance", type=float, default=0.25)
    parser.add_argument("--report-output", default="market_data_verification_report.json")
    parser.add_argument("--summary-output", default="market_data_verification_summary.csv")
    parser.add_argument("--canonical-output", default="")
    args = parser.parse_args()

    candidate, local_candidate, meta = parse_candidate(Path(args.input), args)
    quality = basic_quality(candidate, args.tick_size, args.expected_interval_seconds)
    intraday_ref = compare_intraday(candidate, load_reference(args.reference_intraday), args.price_tolerance)
    daily_ref = compare_daily(local_candidate, load_reference(args.reference_daily), args.price_tolerance)

    report = {
        "meta": meta,
        "quality": quality,
        "intraday_reference": intraday_ref,
        "daily_reference": daily_ref,
    }
    report["verdict"] = verdict(meta, quality, intraday_ref, daily_ref)

    Path(args.report_output).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    write_summary_csv(Path(args.summary_output), report)
    if args.canonical_output:
        candidate.to_csv(args.canonical_output, index=False)

    print(f"Wrote verification report to {args.report_output}")
    print(f"Wrote verification summary to {args.summary_output}")
    if args.canonical_output:
        print(f"Wrote canonical candidate to {args.canonical_output}")
    print(f"Verdict: {report['verdict']['label']}")
    print(f"Rows: {quality['rows']}  Range: {quality['start']} -> {quality['end']}")
    print(f"Duplicates: {quality['duplicate_timestamps']}  OHLC issues: {quality['ohlc_issues']}")
    print(f"Intraday reference: {intraday_ref.get('status')}  Daily reference: {daily_ref.get('status')}")


if __name__ == "__main__":
    main()
