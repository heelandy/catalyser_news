#!/usr/bin/env python3
"""
macro_pipeline_alerts.py

Separate alert detector for the macro catalyst pipeline.

This module does not fetch calendars, study reactions, or adjust probabilities.
It compares the latest pipeline artifacts with a saved local snapshot and emits
alerts when release state, direction, probability, or runner health changes.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ALERT_FIELDS = [
    "alert_time",
    "severity",
    "alert_type",
    "release_time",
    "title",
    "event_family",
    "catalyst_category",
    "previous_status",
    "current_status",
    "previous_actual",
    "current_actual",
    "previous_direction",
    "current_direction",
    "previous_bullish_probability",
    "current_bullish_probability",
    "previous_confidence",
    "current_confidence",
    "message",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text if text else fallback


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def first_clean(row: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = clean(row.get(key))
        if value:
            return value
    return fallback


def first_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = parse_float(row.get(key))
        if value is not None:
            return value
    return None


def percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value * 100:.1f}%"


def number_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def signal_key(row: dict[str, Any]) -> str:
    release_time = first_clean(row, "release_time", "date")
    title = first_clean(row, "title")
    source = first_clean(row, "source")
    return f"{release_time}|{title}|{source}"


def signal_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    bull = first_float(
        row,
        "final_bullish_probability",
        "trust_adjusted_bullish_probability",
        "calibrated_bullish_probability",
        "historical_bullish_probability",
    )
    confidence = first_float(row, "final_confidence", "trust_adjusted_confidence", "confidence")
    direction = first_clean(
        row,
        "final_expected_direction",
        "trust_adjusted_direction",
        "expected_direction",
        fallback="mixed",
    ).lower()
    return {
        "release_time": first_clean(row, "release_time", "date"),
        "title": first_clean(row, "title"),
        "source": first_clean(row, "source"),
        "event_family": first_clean(row, "event_family"),
        "catalyst_category": first_clean(row, "catalyst_category"),
        "status": first_clean(row, "release_status", fallback="unknown").lower(),
        "previous": first_clean(row, "previous"),
        "forecast": first_clean(row, "forecast"),
        "actual": first_clean(row, "actual"),
        "market_bias_side": first_clean(row, "market_bias_side"),
        "direction": direction,
        "bullish_probability": bull,
        "confidence": confidence,
        "confidence_label": first_clean(row, "final_confidence_label", "trust_adjusted_confidence_label", "confidence_label"),
        "warning": first_clean(row, "final_warning", "trust_warning", "warning"),
    }


def released(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("status") == "released" or bool(clean(snapshot.get("actual")))


def alert_row(
    alert_type: str,
    severity: str,
    message: str,
    current: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, str]:
    current = current or {}
    previous = previous or {}
    return {
        "alert_time": now_iso(),
        "severity": severity,
        "alert_type": alert_type,
        "release_time": clean(current.get("release_time") or previous.get("release_time")),
        "title": clean(current.get("title") or previous.get("title")),
        "event_family": clean(current.get("event_family") or previous.get("event_family")),
        "catalyst_category": clean(current.get("catalyst_category") or previous.get("catalyst_category")),
        "previous_status": clean(previous.get("status")),
        "current_status": clean(current.get("status")),
        "previous_actual": clean(previous.get("actual")),
        "current_actual": clean(current.get("actual")),
        "previous_direction": clean(previous.get("direction")),
        "current_direction": clean(current.get("direction")),
        "previous_bullish_probability": number_text(previous.get("bullish_probability")),
        "current_bullish_probability": number_text(current.get("bullish_probability")),
        "previous_confidence": number_text(previous.get("confidence")),
        "current_confidence": number_text(current.get("confidence")),
        "message": message,
    }


def actual_released_message(current: dict[str, Any]) -> str:
    return (
        f"{current['title']} actual released at {current.get('actual') or '--'} "
        f"(forecast {current.get('forecast') or '--'}, previous {current.get('previous') or '--'}). "
        f"Final direction {current.get('direction') or 'mixed'}, "
        f"bull {percent(current.get('bullish_probability'))}, "
        f"confidence {percent(current.get('confidence'))}."
    )


def signal_alerts(
    current_signals: dict[str, dict[str, Any]],
    previous_signals: dict[str, dict[str, Any]],
    emit_initial_alerts: bool,
    probability_jump_threshold: float,
    confidence_jump_threshold: float,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    first_snapshot = not previous_signals

    for key, current in sorted(current_signals.items(), key=lambda item: (item[1].get("release_time", ""), item[1].get("title", ""))):
        previous = previous_signals.get(key)
        if previous is None:
            if emit_initial_alerts or not first_snapshot:
                alerts.append(
                    alert_row(
                        "new_signal",
                        "info",
                        f"New macro signal loaded: {current['title']} at {current['release_time']}.",
                        current,
                    )
                )
            continue

        if not released(previous) and released(current):
            severity = "high" if current.get("direction") in {"bullish", "bearish"} and (current.get("confidence") or 0) >= 0.25 else "medium"
            alerts.append(alert_row("actual_released", severity, actual_released_message(current), current, previous))
        elif previous.get("status") != current.get("status"):
            alerts.append(
                alert_row(
                    "release_status_changed",
                    "medium",
                    f"{current['title']} status changed from {previous.get('status') or '--'} to {current.get('status') or '--'}.",
                    current,
                    previous,
                )
            )

        if previous.get("direction") != current.get("direction"):
            alerts.append(
                alert_row(
                    "direction_changed",
                    "medium",
                    f"{current['title']} direction changed from {previous.get('direction') or '--'} to {current.get('direction') or '--'}.",
                    current,
                    previous,
                )
            )

        previous_bull = previous.get("bullish_probability")
        current_bull = current.get("bullish_probability")
        if previous_bull is not None and current_bull is not None:
            change = abs(current_bull - previous_bull)
            if change >= probability_jump_threshold:
                severity = "high" if change >= probability_jump_threshold * 2 else "medium"
                alerts.append(
                    alert_row(
                        "probability_jump",
                        severity,
                        f"{current['title']} bullish probability moved from {percent(previous_bull)} to {percent(current_bull)}.",
                        current,
                        previous,
                    )
                )

        previous_confidence = previous.get("confidence")
        current_confidence = current.get("confidence")
        if previous_confidence is not None and current_confidence is not None:
            change = abs(current_confidence - previous_confidence)
            if change >= confidence_jump_threshold:
                alerts.append(
                    alert_row(
                        "confidence_jump",
                        "medium",
                        f"{current['title']} confidence moved from {percent(previous_confidence)} to {percent(current_confidence)}.",
                        current,
                        previous,
                    )
                )

    return alerts


def runner_alerts(status_path: Path, previous_runner: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not status_path.exists():
        return [], {"available": False, "ok": None, "failed_stage": "", "finished_at": ""}

    status = load_json(status_path)
    current_runner = {
        "available": True,
        "ok": status.get("ok"),
        "failed_stage": clean(status.get("failed_stage")),
        "finished_at": clean(status.get("finished_at")),
        "cycle": status.get("cycle"),
    }
    alerts: list[dict[str, str]] = []

    if current_runner["ok"] is False:
        failure_changed = (
            previous_runner.get("ok") is not False
            or previous_runner.get("failed_stage") != current_runner["failed_stage"]
        )
        if failure_changed:
            alerts.append(
                alert_row(
                    "pipeline_failed",
                    "high",
                    f"Pipeline failed on cycle {current_runner.get('cycle')}: {current_runner['failed_stage'] or 'unknown failure'}.",
                )
            )
    elif current_runner["ok"] is True and previous_runner.get("ok") is False:
        alerts.append(
            alert_row(
                "pipeline_recovered",
                "info",
                f"Pipeline recovered on cycle {current_runner.get('cycle')}.",
            )
        )

    return alerts, current_runner


def append_alerts(path: Path, alerts: list[dict[str, str]]) -> None:
    if not alerts:
        return
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ALERT_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(alerts)


def write_summary(path: Path, alerts: list[dict[str, str]], current_signals: dict[str, dict[str, Any]], max_alerts: int) -> None:
    released_count = sum(1 for signal in current_signals.values() if released(signal))
    waiting_count = sum(1 for signal in current_signals.values() if signal.get("status") == "waiting_actual")
    summary = {
        "checked_at": now_iso(),
        "alerts_created": len(alerts),
        "signals_seen": len(current_signals),
        "released_signals": released_count,
        "waiting_signals": waiting_count,
        "latest_alerts": alerts[-max_alerts:],
    }
    write_json(path, summary)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect macro pipeline alert conditions from local artifacts.")
    p.add_argument("--signals", default="macro_live_signal_adjusted.csv")
    p.add_argument("--status", default="macro_pipeline_status.json")
    p.add_argument("--state", default="macro_pipeline_alert_state.json")
    p.add_argument("--alerts-output", default="macro_pipeline_alerts.csv")
    p.add_argument("--summary-output", default="macro_pipeline_alert_summary.json")
    p.add_argument("--probability-jump-threshold", type=float, default=0.10)
    p.add_argument("--confidence-jump-threshold", type=float, default=0.15)
    p.add_argument("--emit-initial-alerts", action="store_true")
    p.add_argument("--max-summary-alerts", type=int, default=20)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    state_path = Path(args.state)
    state = load_json(state_path)
    previous_signals = state.get("signals", {}) if isinstance(state.get("signals"), dict) else {}
    previous_runner = state.get("runner_status", {}) if isinstance(state.get("runner_status"), dict) else {}

    rows = read_csv_rows(Path(args.signals))
    current_signals = {signal_key(row): signal_snapshot(row) for row in rows}

    alerts = signal_alerts(
        current_signals,
        previous_signals,
        args.emit_initial_alerts,
        args.probability_jump_threshold,
        args.confidence_jump_threshold,
    )
    runner_status_alerts, current_runner = runner_alerts(Path(args.status), previous_runner)
    alerts.extend(runner_status_alerts)

    append_alerts(Path(args.alerts_output), alerts)
    write_summary(Path(args.summary_output), alerts, current_signals, args.max_summary_alerts)

    next_state = {
        "created_at": state.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "signals": current_signals,
        "runner_status": current_runner,
    }
    write_json(state_path, next_state)

    print(f"Alert check complete: {len(alerts)} alert(s), {len(current_signals)} signal(s).")
    for alert in alerts:
        print(f"{alert['severity'].upper()} {alert['alert_type']}: {alert['message']}")


if __name__ == "__main__":
    main()
