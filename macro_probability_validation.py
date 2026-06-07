#!/usr/bin/env python3
"""
macro_probability_validation.py

Reliability report for macro signal probabilities.

This module reads macro_signal_grades.csv and checks whether forecast
probabilities line up with actual bullish/bearish NQ outcomes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_BINS = [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 1.0]


def parse_bins(value: str) -> list[float]:
    bins = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(bins) < 2:
        raise ValueError("need at least two bin edges")
    return sorted(set(bins))


def load_grades(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} does not exist")
    df = pd.read_csv(p)
    required = ["predicted_bullish_probability", "primary_actual_direction", "was_prediction_correct"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"grades file missing required column(s): {', '.join(missing)}")
    df = df.copy()
    df["predicted_bullish_probability"] = pd.to_numeric(df["predicted_bullish_probability"], errors="coerce")
    df["predicted_bearish_probability"] = pd.to_numeric(df.get("predicted_bearish_probability"), errors="coerce")
    df["confidence"] = pd.to_numeric(df.get("confidence"), errors="coerce")
    df["was_prediction_correct"] = pd.to_numeric(df["was_prediction_correct"], errors="coerce")
    df["actual_bullish"] = np.where(df["primary_actual_direction"] == "bullish", 1.0, np.where(df["primary_actual_direction"] == "bearish", 0.0, np.nan))
    df["actual_bearish"] = np.where(df["primary_actual_direction"] == "bearish", 1.0, np.where(df["primary_actual_direction"] == "bullish", 0.0, np.nan))
    df["probability_edge"] = (df["predicted_bullish_probability"] - 0.5).abs() * 2.0
    df["brier_bullish"] = (df["predicted_bullish_probability"] - df["actual_bullish"]) ** 2
    return df.dropna(subset=["predicted_bullish_probability"]).reset_index(drop=True)


def summarize_group(group: pd.DataFrame) -> dict:
    directional = group.dropna(subset=["actual_bullish"])
    out = {
        "sample_size": int(len(group)),
        "directional_sample_size": int(len(directional)),
        "avg_predicted_bullish_probability": float(group["predicted_bullish_probability"].mean()),
        "avg_probability_edge": float(group["probability_edge"].mean()),
        "avg_confidence": float(group["confidence"].mean()) if "confidence" in group else np.nan,
        "primary_direction_accuracy": float(group["was_prediction_correct"].mean()),
    }
    if directional.empty:
        out.update(
            {
                "actual_bullish_rate": np.nan,
                "calibration_error": np.nan,
                "brier_bullish": np.nan,
            }
        )
    else:
        actual_rate = float(directional["actual_bullish"].mean())
        predicted = float(directional["predicted_bullish_probability"].mean())
        out.update(
            {
                "actual_bullish_rate": actual_rate,
                "calibration_error": predicted - actual_rate,
                "brier_bullish": float(directional["brier_bullish"].mean()),
            }
        )
    return out


def probability_band_rows(df: pd.DataFrame, bins: list[float]) -> pd.DataFrame:
    labels = [f"{bins[i]:.2f}-{bins[i + 1]:.2f}" for i in range(len(bins) - 1)]
    working = df.copy()
    working["probability_band"] = pd.cut(
        working["predicted_bullish_probability"],
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=False,
    )
    rows = []
    for band, group in working.groupby("probability_band", dropna=False, observed=False):
        if group.empty or pd.isna(band):
            continue
        row = {"group_type": "probability_band", "group_value": str(band)}
        row.update(summarize_group(group))
        rows.append(row)
    return pd.DataFrame(rows)


def grouped_rows(df: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("overall", []),
        ("reaction_source", ["reaction_source"]),
        ("event_family", ["event_family"]),
        ("catalyst_category", ["catalyst_category"]),
        ("market_bias_side", ["market_bias_side"]),
        ("confidence_label", ["confidence_label"]),
        ("event_family_market_bias", ["event_family", "market_bias_side"]),
    ]
    rows = []
    for group_type, keys in specs:
        grouped = [((), df)] if not keys else df.groupby(keys, dropna=False)
        for key_values, group in grouped:
            if group.empty:
                continue
            if keys and not isinstance(key_values, tuple):
                key_values = (key_values,)
            row = {
                "group_type": group_type,
                "group_value": "overall" if not keys else "|".join(f"{key}={value}" for key, value in zip(keys, key_values)),
            }
            for key, value in zip(keys, key_values if keys else ()):
                row[key] = value
            row.update(summarize_group(group))
            rows.append(row)
    return pd.DataFrame(rows)


def build_validation(grades_path: str, bins: list[float]) -> tuple[dict, pd.DataFrame]:
    grades = load_grades(grades_path)
    rows = pd.concat([grouped_rows(grades), probability_band_rows(grades, bins)], ignore_index=True)
    overall = summarize_group(grades)
    summary = {
        "grades_file": grades_path,
        "rows_loaded": int(len(grades)),
        "overall": overall,
        "probability_bins": bins,
        "notes": [
            "calibration_error is avg predicted bullish probability minus actual bullish rate",
            "brier_bullish is lower when probability forecasts are better calibrated",
        ],
    }
    return summary, rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate probability calibration from macro signal grades.")
    p.add_argument("--grades", default="macro_signal_grades.csv")
    p.add_argument("--summary-output", default="macro_probability_validation_report.json")
    p.add_argument("--rows-output", default="macro_probability_validation.csv")
    p.add_argument("--bins", default=",".join(str(v) for v in DEFAULT_BINS))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    summary, rows = build_validation(args.grades, parse_bins(args.bins))
    Path(args.summary_output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows.to_csv(args.rows_output, index=False)
    overall = summary["overall"]
    print(f"Wrote probability validation report to {args.summary_output}")
    print(f"Wrote probability validation rows to {args.rows_output}")
    print(
        "Overall: "
        f"accuracy={overall['primary_direction_accuracy']:.3f}, "
        f"actual_bullish_rate={overall['actual_bullish_rate']:.3f}, "
        f"brier={overall['brier_bullish']:.3f}"
    )


if __name__ == "__main__":
    main()
