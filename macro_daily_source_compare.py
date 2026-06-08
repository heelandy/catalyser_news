#!/usr/bin/env python3
"""
macro_daily_source_compare.py

Compare daily macro-reaction results across two market-data sources.

This module is deliberately separate from the live signal pipeline. It reads
already-built reaction CSVs, compares the same release moments across sources,
and writes source-agreement/accuracy artifacts for research.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare daily macro reaction behavior across two sources.")
    p.add_argument("--left-reactions", default="macro_reactions_yahoo_daily.csv")
    p.add_argument("--right-reactions", default="macro_reactions_investing_daily.csv")
    p.add_argument("--left-name", default="yahoo_daily")
    p.add_argument("--right-name", default="investing_daily")
    p.add_argument("--neutral-threshold-pts", type=float, default=10.0)
    p.add_argument("--comparison-output", default="macro_daily_source_comparison.csv")
    p.add_argument("--summary-output", default="macro_daily_source_comparison_report.json")
    p.add_argument("--group-output", default="macro_daily_source_comparison_groups.csv")
    return p.parse_args()


def direction_from_return(value: float, neutral_threshold_pts: float) -> str:
    if pd.isna(value):
        return "unknown"
    if value > neutral_threshold_pts:
        return "bullish"
    if value < -neutral_threshold_pts:
        return "bearish"
    return "mixed"


def expected_from_market_bias(value: object) -> str:
    text = str(value or "").strip().lower()
    if text == "market_positive":
        return "bullish"
    if text == "market_negative":
        return "bearish"
    if text in {"market_neutral", "market_mixed", "market_unknown", ""}:
        return "mixed"
    return "mixed"


def load_reactions(path: str, source_name: str, neutral_threshold_pts: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "reaction_return_pts" not in df.columns:
        raise ValueError(f"{path} is missing reaction_return_pts")
    if "event_cluster_id" in df.columns:
        key = df["event_cluster_id"].fillna("").astype(str).str.strip()
    else:
        key = pd.Series("", index=df.index)
    fallback = (
        df.get("release_time", pd.Series("", index=df.index)).fillna("").astype(str)
        + "|"
        + df.get("title", pd.Series("", index=df.index)).fillna("").astype(str)
    )
    df = df.copy()
    df["compare_key"] = np.where(key != "", key, fallback)
    df["reaction_return_pts"] = pd.to_numeric(df["reaction_return_pts"], errors="coerce")
    df["actual_direction"] = df["reaction_return_pts"].apply(lambda value: direction_from_return(value, neutral_threshold_pts))
    df["expected_from_market_bias"] = df.get("market_bias_side", pd.Series("", index=df.index)).apply(expected_from_market_bias)
    df["bias_direction_correct"] = df["expected_from_market_bias"] == df["actual_direction"]
    df["source_name"] = source_name
    return df


def merge_sources(left: pd.DataFrame, right: pd.DataFrame, left_name: str, right_name: str) -> pd.DataFrame:
    keep_cols = [
        "compare_key",
        "release_time",
        "title",
        "event_family",
        "catalyst_category",
        "surprise_side",
        "market_bias_side",
        "expected_from_market_bias",
        "reaction_return_pts",
        "reaction_return_pct",
        "actual_direction",
        "bias_direction_correct",
        "market_session",
    ]
    left_keep = left[[col for col in keep_cols if col in left.columns]].copy()
    right_keep = right[[col for col in keep_cols if col in right.columns]].copy()
    merged = left_keep.merge(right_keep, on="compare_key", how="inner", suffixes=(f"_{left_name}", f"_{right_name}"))
    merged["return_diff_pts"] = merged[f"reaction_return_pts_{right_name}"] - merged[f"reaction_return_pts_{left_name}"]
    merged["abs_return_diff_pts"] = merged["return_diff_pts"].abs()
    merged["direction_match"] = merged[f"actual_direction_{left_name}"] == merged[f"actual_direction_{right_name}"]
    merged["same_sign"] = np.sign(merged[f"reaction_return_pts_{left_name}"]) == np.sign(merged[f"reaction_return_pts_{right_name}"])
    return merged


def summarize_group(group: pd.DataFrame, group_type: str, group_key: str, left_name: str, right_name: str) -> dict[str, Any]:
    corr = group[f"reaction_return_pts_{left_name}"].corr(group[f"reaction_return_pts_{right_name}"])
    return {
        "group_type": group_type,
        "group_key": group_key,
        "matched_events": int(len(group)),
        "direction_agreement": float(group["direction_match"].mean()) if len(group) else np.nan,
        "same_sign_agreement": float(group["same_sign"].mean()) if len(group) else np.nan,
        "return_correlation": None if pd.isna(corr) else float(corr),
        "avg_abs_return_diff_pts": float(group["abs_return_diff_pts"].mean()) if len(group) else np.nan,
        f"{left_name}_bias_accuracy": float(group[f"bias_direction_correct_{left_name}"].mean()) if len(group) else np.nan,
        f"{right_name}_bias_accuracy": float(group[f"bias_direction_correct_{right_name}"].mean()) if len(group) else np.nan,
        f"{left_name}_avg_return_pts": float(group[f"reaction_return_pts_{left_name}"].mean()) if len(group) else np.nan,
        f"{right_name}_avg_return_pts": float(group[f"reaction_return_pts_{right_name}"].mean()) if len(group) else np.nan,
    }


def build_group_summary(merged: pd.DataFrame, left_name: str, right_name: str) -> pd.DataFrame:
    rows = [summarize_group(merged, "overall", "all", left_name, right_name)]
    group_fields = [
        ("event_family", f"event_family_{left_name}"),
        ("catalyst_category", f"catalyst_category_{left_name}"),
        ("market_bias_side", f"market_bias_side_{left_name}"),
    ]
    for group_type, col in group_fields:
        if col not in merged.columns:
            continue
        for value, group in merged.groupby(col, dropna=False):
            label = str(value or "").strip() or "blank"
            rows.append(summarize_group(group, group_type, label, left_name, right_name))
    return pd.DataFrame(rows)


def build_report(
    left: pd.DataFrame,
    right: pd.DataFrame,
    merged: pd.DataFrame,
    groups: pd.DataFrame,
    args: argparse.Namespace,
) -> dict[str, Any]:
    overall = groups[groups["group_type"] == "overall"].iloc[0].to_dict() if not groups.empty else {}
    left_keys = set(left["compare_key"])
    right_keys = set(right["compare_key"])
    largest_disagreements = (
        merged.sort_values("abs_return_diff_pts", ascending=False)
        .head(15)
        .to_dict("records")
    )
    compact_disagreements = []
    for row in largest_disagreements:
        compact_disagreements.append(
            {
                "release_time": row.get(f"release_time_{args.left_name}"),
                "title": row.get(f"title_{args.left_name}"),
                f"{args.left_name}_return_pts": row.get(f"reaction_return_pts_{args.left_name}"),
                f"{args.right_name}_return_pts": row.get(f"reaction_return_pts_{args.right_name}"),
                "abs_return_diff_pts": row.get("abs_return_diff_pts"),
                f"{args.left_name}_direction": row.get(f"actual_direction_{args.left_name}"),
                f"{args.right_name}_direction": row.get(f"actual_direction_{args.right_name}"),
            }
        )
    return {
        "left_name": args.left_name,
        "right_name": args.right_name,
        "left_reactions": args.left_reactions,
        "right_reactions": args.right_reactions,
        "neutral_threshold_pts": args.neutral_threshold_pts,
        "rows": {
            "left_rows": int(len(left)),
            "right_rows": int(len(right)),
            "matched_events": int(len(merged)),
            "left_only_events": int(len(left_keys - right_keys)),
            "right_only_events": int(len(right_keys - left_keys)),
        },
        "overall": overall,
        "largest_disagreements": compact_disagreements,
        "note": "Accuracy is measured as market_bias_side direction versus same-day close reaction direction.",
    }


def main() -> None:
    args = parse_args()
    left = load_reactions(args.left_reactions, args.left_name, args.neutral_threshold_pts)
    right = load_reactions(args.right_reactions, args.right_name, args.neutral_threshold_pts)
    merged = merge_sources(left, right, args.left_name, args.right_name)
    groups = build_group_summary(merged, args.left_name, args.right_name)

    merged.to_csv(args.comparison_output, index=False)
    groups.to_csv(args.group_output, index=False)
    report = build_report(left, right, merged, groups, args)
    Path(args.summary_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote source comparison rows to {args.comparison_output}")
    print(f"Wrote grouped comparison rows to {args.group_output}")
    print(f"Wrote report to {args.summary_output}")
    if report["overall"]:
        print(
            "Overall: "
            f"matched={report['rows']['matched_events']}, "
            f"direction_agreement={report['overall']['direction_agreement']:.3f}, "
            f"return_correlation={report['overall']['return_correlation']:.3f}"
        )


if __name__ == "__main__":
    main()
