#!/usr/bin/env python3
"""
macro_pipeline_runner.py

Small orchestration layer for the macro catalyst pipeline.

The runner does not merge module responsibilities. It calls each module through
its CLI in a repeatable order:
  1. Optional Yahoo market-data refresh.
  2. Live macro calendar/release fetch.
  3. Live signal calibration.
  4. Optional post-release performance refresh.
  5. Trust adjustment for the UI contract.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_REACTION_FILES = ["macro_reactions_1m.csv", "macro_reactions_5m.csv", "macro_reactions_60m.csv"]
DEFAULT_REACTION_LABELS = ["1m", "5m", "60m"]


@dataclass
class Stage:
    name: str
    command: list[str]
    required_inputs: list[str]
    expected_outputs: list[str]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def log(message: str, log_file: Path | None = None) -> None:
    line = f"[{now_iso()}] {message}"
    print(line, flush=True)
    if log_file:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def existing_file(path: str, root: Path) -> bool:
    return (root / path).exists() and (root / path).is_file()


def check_required(stage: Stage, root: Path) -> list[str]:
    return [path for path in stage.required_inputs if not existing_file(path, root)]


def run_stage(stage: Stage, root: Path, dry_run: bool, log_file: Path | None) -> None:
    missing = check_required(stage, root)
    if missing:
        raise RuntimeError(f"{stage.name} missing required input(s): {', '.join(missing)}")

    log(f"START {stage.name}: {command_text(stage.command)}", log_file)
    if dry_run:
        log(f"DRY RUN {stage.name}: command not executed", log_file)
        return

    proc = subprocess.Popen(
        stage.command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for output_line in proc.stdout:
        log(f"{stage.name}: {output_line.rstrip()}", log_file)
    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"{stage.name} failed with exit code {return_code}")

    missing_outputs = [path for path in stage.expected_outputs if not existing_file(path, root)]
    if missing_outputs:
        raise RuntimeError(f"{stage.name} did not create expected output(s): {', '.join(missing_outputs)}")
    log(f"DONE {stage.name}", log_file)


def python_cmd(args: argparse.Namespace, script_name: str) -> list[str]:
    return [args.python, script_name]


def build_stages(args: argparse.Namespace) -> list[Stage]:
    stages: list[Stage] = []

    if args.market_preset != "none":
        stages.append(
            Stage(
                name="market_data_refresh",
                command=python_cmd(args, "fetch_nq_yahoo.py") + ["--preset", args.market_preset],
                required_inputs=[],
                expected_outputs=[],
            )
        )

    if not args.skip_live_fetch:
        live_command = python_cmd(args, "catalyser_news.py") + [
            "--calendar",
            "--tv-calendar",
            "--tv-countries",
            args.tv_countries,
            "--tv-min-importance",
            str(args.tv_min_importance),
            "--lookback-days",
            str(args.lookback_days),
            "--lookahead-days",
            str(args.lookahead_days),
            "--macro-output",
            args.macro_output,
            "--output",
            args.news_output,
        ]
        if args.watch_releases:
            live_command += [
                "--watch-releases",
                "--poll-seconds",
                str(args.poll_seconds),
                "--watch-minutes",
                str(args.watch_minutes),
            ]
        if args.skip_closed_catalysts:
            live_command.append("--skip-closed-catalysts")
        if args.te_calendar:
            live_command += ["--te-calendar", "--te-country", args.te_country, "--te-min-importance", str(args.te_min_importance)]

        stages.append(
            Stage(
                name="live_calendar_fetch",
                command=live_command,
                required_inputs=[],
                expected_outputs=[args.macro_output],
            )
        )

    if not args.skip_calibration:
        stages.append(
            Stage(
                name="live_signal_calibration",
                command=python_cmd(args, "macro_reaction_study.py")
                + [
                    "--calibrate-live",
                    args.macro_output,
                    "--profiles",
                    args.profiles,
                    "--calibrated-output",
                    args.calibrated_output,
                    "--live-signal-output",
                    args.live_signal_output,
                ],
                required_inputs=[args.macro_output, args.profiles],
                expected_outputs=[args.calibrated_output, args.live_signal_output],
            )
        )

    if args.refresh_performance:
        performance_command = python_cmd(args, "macro_signal_performance.py") + [
            "--signals",
            args.live_signal_output,
            "--reactions",
            *args.reaction_files,
        ]
        if args.reaction_labels:
            performance_command += ["--reaction-labels", *args.reaction_labels]
        performance_command += [
            "--windows-minutes",
            args.performance_windows,
            "--primary-window-minutes",
            str(args.performance_primary_window),
            "--neutral-threshold-pts",
            str(args.neutral_threshold_pts),
            "--grades-output",
            args.grades_output,
            "--performance-output",
            args.performance_output,
        ]
        stages.append(
            Stage(
                name="signal_performance_refresh",
                command=performance_command,
                required_inputs=[args.live_signal_output, *args.reaction_files],
                expected_outputs=[args.grades_output, args.performance_output],
            )
        )

    if not args.skip_trust:
        stages.append(
            Stage(
                name="trust_adjustment",
                command=python_cmd(args, "macro_signal_trust.py")
                + [
                    "--signals",
                    args.live_signal_output,
                    "--performance",
                    args.performance_output,
                    "--weights-output",
                    args.trust_weights_output,
                    "--adjusted-output",
                    args.adjusted_signal_output,
                ],
                required_inputs=[args.live_signal_output, args.performance_output],
                expected_outputs=[args.trust_weights_output, args.adjusted_signal_output],
            )
        )

    return stages


def write_status(path: Path | None, status: dict, dry_run: bool) -> None:
    if not path or dry_run:
        return
    path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_cycle(args: argparse.Namespace, root: Path, cycle: int) -> bool:
    log_file = Path(args.log_file) if args.log_file else None
    stages = build_stages(args)
    status = {
        "cycle": cycle,
        "started_at": now_iso(),
        "finished_at": None,
        "ok": False,
        "failed_stage": "",
        "stages": [stage.name for stage in stages],
        "adjusted_signal_output": args.adjusted_signal_output,
    }

    log(f"Pipeline cycle {cycle} starting with {len(stages)} stage(s)", log_file)
    try:
        if args.reaction_labels and len(args.reaction_labels) != len(args.reaction_files):
            raise RuntimeError("--reaction-labels must have the same count as --reaction-files")
        for stage in stages:
            run_stage(stage, root, args.dry_run, log_file)
        status["ok"] = True
        log(f"Pipeline cycle {cycle} complete", log_file)
        return True
    except Exception as exc:
        status["failed_stage"] = str(exc)
        log(f"Pipeline cycle {cycle} failed: {exc}", log_file)
        return False
    finally:
        status["finished_at"] = now_iso()
        write_status(Path(args.status_output) if args.status_output else None, status, args.dry_run)


def sleep_between_cycles(seconds: int, log_file: Path | None) -> None:
    if seconds <= 0:
        return
    log(f"Sleeping {seconds} second(s) before next cycle", log_file)
    time.sleep(seconds)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the macro catalyst pipeline as separate CLI stages.")
    p.add_argument("--python", default=sys.executable, help="Python executable used to launch child modules")
    p.add_argument("--run-forever", action="store_true", help="Keep running cycles until Ctrl+C")
    p.add_argument("--max-cycles", type=int, default=0, help="Optional max cycles for --run-forever; 0 means unlimited")
    p.add_argument("--loop-seconds", type=int, default=60, help="Seconds between cycles when --run-forever is set")
    p.add_argument("--stop-on-error", action="store_true", help="Stop a forever run after a failed cycle")
    p.add_argument("--dry-run", action="store_true", help="Print commands and validate inputs without running stages")
    p.add_argument("--log-file", default="macro_pipeline_runner.log")
    p.add_argument("--status-output", default="macro_pipeline_status.json")

    p.add_argument("--market-preset", choices=["none", "daily", "intraday", "intraday-deep"], default="none")

    p.add_argument("--skip-live-fetch", action="store_true")
    p.add_argument("--tv-countries", default="us")
    p.add_argument("--tv-min-importance", type=int, default=1)
    p.add_argument("--lookback-days", type=int, default=2)
    p.add_argument("--lookahead-days", type=int, default=14)
    p.add_argument("--watch-releases", action="store_true")
    p.add_argument("--poll-seconds", type=int, default=15)
    p.add_argument("--watch-minutes", type=int, default=30)
    p.add_argument("--skip-closed-catalysts", action="store_true")
    p.add_argument("--te-calendar", action="store_true")
    p.add_argument("--te-country", default="united states")
    p.add_argument("--te-min-importance", type=int, default=2)
    p.add_argument("--macro-output", default="macro_releases.csv")
    p.add_argument("--news-output", default="news_summary.csv")

    p.add_argument("--skip-calibration", action="store_true")
    p.add_argument("--profiles", default="macro_reaction_profiles_5m.csv")
    p.add_argument("--calibrated-output", default="macro_releases_calibrated.csv")
    p.add_argument("--live-signal-output", default="macro_live_signal.csv")

    p.add_argument("--refresh-performance", action="store_true")
    p.add_argument("--reaction-files", nargs="*", default=DEFAULT_REACTION_FILES)
    p.add_argument("--reaction-labels", nargs="*", default=None)
    p.add_argument("--performance-windows", default="5,15,30,60,240,390")
    p.add_argument("--performance-primary-window", type=int, default=60)
    p.add_argument("--neutral-threshold-pts", type=float, default=0.0)
    p.add_argument("--grades-output", default="macro_signal_grades.csv")
    p.add_argument("--performance-output", default="macro_signal_performance.csv")

    p.add_argument("--skip-trust", action="store_true")
    p.add_argument("--trust-weights-output", default="macro_signal_trust_weights.csv")
    p.add_argument("--adjusted-signal-output", default="macro_live_signal_adjusted.csv")
    return p.parse_args()


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.reaction_labels is None:
        args.reaction_labels = DEFAULT_REACTION_LABELS if args.reaction_files == DEFAULT_REACTION_FILES else []
    return args


def main() -> None:
    args = normalize_args(parse_args())
    root = Path.cwd()
    log_file = Path(args.log_file) if args.log_file else None
    cycle = 1

    try:
        while True:
            ok = run_cycle(args, root, cycle)
            if not args.run_forever:
                raise SystemExit(0 if ok else 1)
            if not ok and args.stop_on_error:
                raise SystemExit(1)
            if args.max_cycles and cycle >= args.max_cycles:
                raise SystemExit(0 if ok else 1)
            cycle += 1
            sleep_between_cycles(args.loop_seconds, log_file)
    except KeyboardInterrupt:
        log("Pipeline stopped by user", log_file)


if __name__ == "__main__":
    main()
