#!/usr/bin/env python3
"""
macro_signal_performance.py

Post-release grading for the macro catalyst engine.

This module stays separate from:
  - catalyser_news.py, which fetches/scores live releases.
  - macro_reaction_study.py, which measures historical price reactions.

It compares predicted live signals against measured NQ reactions and writes:
  - macro_signal_grades.csv: one row per signal/reaction source.
  - macro_signal_performance.csv: dashboard-ready accuracy summaries.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_WINDOWS = [5, 15, 30, 60]


def parse_windows(value: str) -> list[int]:
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def parse_dt_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(None)


def as_number(value, default=np.nan) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def direction_from_return(value, neutral_threshold_pts: float) -> str:
    value = as_number(value)
    if pd.isna(value):
        return "unknown"
    if value > neutral_threshold_pts:
        return "bullish"
    if value < -neutral_threshold_pts:
        return "bearish"
    return "mixed"


def is_correct(predicted: str, actual: str) -> float:
    predicted = str(predicted or "mixed")
    actual = str(actual or "unknown")
    if actual == "unknown":
        return np.nan
    if predicted == actual:
        return 1.0
    if predicted == "mixed" and actual == "mixed":
        return 1.0
    return 0.0


def signal_strength(probability: float) -> float:
    if pd.isna(probability):
        return np.nan
    return abs(float(probability) - 0.5) * 2.0


def source_label(path: str) -> str:
    stem = Path(path).stem.lower()
    if "1m" in stem:
        return "1m"
    if "5m" in stem:
        return "5m"
    if "15m" in stem:
        return "15m"
    if "60m" in stem:
        return "60m"
    return Path(path).stem


def load_signals(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "release_time" not in df.columns:
        raise ValueError("signals file must contain release_time")
    df = df.copy()
    df["release_time"] = parse_dt_series(df["release_time"])
    df = df.dropna(subset=["release_time"]).reset_index(drop=True)
    return df


def load_reactions(path: str, label: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "release_time" not in df.columns:
        raise ValueError(f"{path} must contain release_time")
    df = df.copy()
    df["release_time"] = parse_dt_series(df["release_time"])
    df["reaction_source"] = label or source_label(path)
    return df.dropna(subset=["release_time"]).reset_index(drop=True)


def choose_primary_window(row: pd.Series, windows: list[int], fallback: int) -> int:
    window_label = str(row.get("window_label") or "")
    if window_label.endswith("m"):
        try:
            return int(window_label[:-1])
        except ValueError:
            pass
    return fallback if fallback in windows else windows[-1]


def grade_signal_against_reaction(
    signal: pd.Series,
    reaction: pd.Series,
    windows: list[int],
    primary_window: int,
    neutral_threshold_pts: float,
) -> dict:
    predicted = str(signal.get("expected_direction") or "mixed")
    bull_prob = as_number(signal.get("calibrated_bullish_probability"), as_number(signal.get("bullish_probability"), 0.5))
    bear_prob = 1.0 - bull_prob if not pd.isna(bull_prob) else np.nan
    primary = choose_primary_window(reaction, windows, primary_window)
    primary_return = as_number(reaction.get(f"return_{primary}m_pts"), as_number(reaction.get("reaction_return_pts")))
    primary_actual = direction_from_return(primary_return, neutral_threshold_pts)

    row = {
        "release_time": signal.get("release_time"),
        "title": signal.get("title", ""),
        "reaction_title": reaction.get("title", ""),
        "cluster_titles": reaction.get("cluster_titles", ""),
        "event_family": signal.get("event_family") or reaction.get("event_family", ""),
        "catalyst_category": signal.get("catalyst_category") or reaction.get("catalyst_category", ""),
        "market_bias_side": signal.get("market_bias_side", ""),
        "raw_surprise_side": signal.get("raw_surprise_side", ""),
        "surprise": signal.get("surprise", ""),
        "surprise_basis": signal.get("surprise_basis", ""),
        "predicted_direction": predicted,
        "predicted_bullish_probability": bull_prob,
        "predicted_bearish_probability": bear_prob,
        "prediction_edge": signal_strength(bull_prob),
        "confidence": as_number(signal.get("confidence")),
        "confidence_label": signal.get("confidence_label", ""),
        "historical_group_type": signal.get("historical_group_type", ""),
        "historical_sample_size": signal.get("historical_sample_size", ""),
        "warning": signal.get("warning", ""),
        "reaction_source": reaction.get("reaction_source", ""),
        "reaction_window_label": reaction.get("window_label", ""),
        "primary_window_minutes": primary,
        "primary_return_pts": primary_return,
        "primary_actual_direction": primary_actual,
        "was_prediction_correct": is_correct(predicted, primary_actual),
        "mfe_pts": as_number(reaction.get("mfe_pts")),
        "mae_pts": as_number(reaction.get("mae_pts")),
    }

    actual_directions = []
    for minutes in windows:
        ret = as_number(reaction.get(f"return_{minutes}m_pts"))
        actual = direction_from_return(ret, neutral_threshold_pts)
        actual_directions.append(actual)
        row[f"actual_{minutes}m_return_pts"] = ret
        row[f"actual_{minutes}m_direction"] = actual
        row[f"correct_{minutes}m"] = is_correct(predicted, actual)
        row[f"mfe_{minutes}m_pts"] = as_number(reaction.get(f"mfe_{minutes}m_pts"))
        row[f"mae_{minutes}m_pts"] = as_number(reaction.get(f"mae_{minutes}m_pts"))

    known = [d for d in actual_directions if d != "unknown"]
    row["direction_changed_across_windows"] = len(set(known)) > 1 if known else False
    return row


def build_grades(
    signals: pd.DataFrame,
    reactions: pd.DataFrame,
    windows: list[int],
    primary_window: int,
    neutral_threshold_pts: float,
) -> pd.DataFrame:
    rows = []
    reactions_by_time = {time: group for time, group in reactions.groupby("release_time")}

    for _, signal in signals.iterrows():
        release_time = signal["release_time"]
        matches = reactions_by_time.get(release_time)
        if matches is None or matches.empty:
            continue
        for _, reaction in matches.iterrows():
            rows.append(grade_signal_against_reaction(signal, reaction, windows, primary_window, neutral_threshold_pts))

    return pd.DataFrame(rows)


def summarize_accuracy(grades: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    rows = []
    group_specs = [
        ("overall", []),
        ("reaction_source", ["reaction_source"]),
        ("event_family", ["event_family"]),
        ("catalyst_category", ["catalyst_category"]),
        ("market_bias_side", ["market_bias_side"]),
        ("confidence_label", ["confidence_label"]),
        ("event_family_market_bias", ["event_family", "market_bias_side"]),
        ("source_family", ["reaction_source", "event_family"]),
        ("source_bias", ["reaction_source", "market_bias_side"]),
    ]

    for group_type, keys in group_specs:
        grouped = [((), grades)] if not keys else grades.groupby(keys, dropna=False)
        for key_values, group in grouped:
            if group.empty:
                continue
            if keys and not isinstance(key_values, tuple):
                key_values = (key_values,)
            base = {
                "group_type": group_type,
                "reaction_source": "",
                "event_family": "",
                "catalyst_category": "",
                "market_bias_side": "",
                "confidence_label": "",
                "sample_size": int(len(group)),
                "avg_predicted_bullish_probability": float(pd.to_numeric(group["predicted_bullish_probability"], errors="coerce").mean()),
                "avg_confidence": float(pd.to_numeric(group["confidence"], errors="coerce").mean()),
                "avg_primary_return_pts": float(pd.to_numeric(group["primary_return_pts"], errors="coerce").mean()),
                "primary_accuracy": float(pd.to_numeric(group["was_prediction_correct"], errors="coerce").mean()),
                "whipsaw_rate": float(group["direction_changed_across_windows"].mean()),
            }
            for key, value in zip(keys, key_values if keys else ()):
                base[key] = value
            for minutes in windows:
                base[f"accuracy_{minutes}m"] = float(pd.to_numeric(group[f"correct_{minutes}m"], errors="coerce").mean())
                base[f"avg_return_{minutes}m_pts"] = float(pd.to_numeric(group[f"actual_{minutes}m_return_pts"], errors="coerce").mean())
            rows.append(base)

    return pd.DataFrame(rows).sort_values(["group_type", "sample_size"], ascending=[True, False])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grade macro live signals against post-release NQ reactions.")
    p.add_argument("--signals", default="macro_live_signal.csv", help="UI-ready live signal CSV")
    p.add_argument("--reactions", nargs="+", default=["macro_reactions_1m.csv", "macro_reactions_5m.csv"], help="Reaction CSV files")
    p.add_argument("--reaction-labels", nargs="*", help="Optional labels matching --reactions")
    p.add_argument("--windows-minutes", default=",".join(map(str, DEFAULT_WINDOWS)))
    p.add_argument("--primary-window-minutes", type=int, default=60)
    p.add_argument("--neutral-threshold-pts", type=float, default=0.0)
    p.add_argument("--grades-output", default="macro_signal_grades.csv")
    p.add_argument("--performance-output", default="macro_signal_performance.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    windows = parse_windows(args.windows_minutes)
    signals = load_signals(args.signals)

    labels = args.reaction_labels or []
    reaction_frames = []
    for idx, path in enumerate(args.reactions):
        label = labels[idx] if idx < len(labels) else None
        reaction_frames.append(load_reactions(path, label=label))
    reactions = pd.concat(reaction_frames, ignore_index=True)

    grades = build_grades(signals, reactions, windows, args.primary_window_minutes, args.neutral_threshold_pts)
    grades.to_csv(args.grades_output, index=False)
    print(f"Wrote {len(grades)} graded signal rows to {args.grades_output}.")

    performance = summarize_accuracy(grades, windows)
    performance.to_csv(args.performance_output, index=False)
    print(f"Wrote {len(performance)} performance rows to {args.performance_output}.")

    if not performance.empty:
        cols = ["group_type", "reaction_source", "event_family", "market_bias_side", "sample_size", "primary_accuracy", "whipsaw_rate", "avg_primary_return_pts"]
        print("\nTop performance summary:")
        print(performance[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
