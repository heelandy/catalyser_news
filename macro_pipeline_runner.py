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
DEFAULT_PROFILES = "macro_reaction_profiles_5m.csv"
DEFAULT_DAILY_CONFIRMATION_PROFILES = "macro_reaction_profiles_investing_daily.csv"


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


def load_market_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def market_config_summary(config: dict) -> dict:
    default_source = str(config.get("default_source") or "yahoo")
    yahoo = config.get("yahoo") if isinstance(config.get("yahoo"), dict) else {}
    external = config.get("external_api") if isinstance(config.get("external_api"), dict) else {}
    return {
        "default_source": default_source,
        "active_market_data_file": config.get("active_market_data_file", ""),
        "active_profiles_file": config.get("active_profiles_file", ""),
        "yahoo_enabled": bool(yahoo.get("enabled", default_source == "yahoo")),
        "yahoo_ticker": yahoo.get("ticker", ""),
        "yahoo_preset": yahoo.get("preset", ""),
        "yahoo_refresh_on_runner": bool(yahoo.get("refresh_on_runner", False)),
        "external_api_enabled": bool(external.get("enabled", False)),
        "external_api_provider": external.get("provider", ""),
    }


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
        market_command = python_cmd(args, "fetch_nq_yahoo.py") + ["--preset", args.market_preset]
        if args.market_ticker:
            market_command += ["--ticker", args.market_ticker]
        stages.append(
            Stage(
                name="market_data_refresh",
                command=market_command,
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

    if args.refresh_quality:
        stages.append(
            Stage(
                name="data_quality_report",
                command=python_cmd(args, "macro_data_quality.py")
                + [
                    "--market-data",
                    args.active_market_data_file,
                    "--events-file",
                    args.macro_output,
                    "--report-output",
                    args.data_quality_report_output,
                    "--summary-output",
                    args.data_quality_summary_output,
                ],
                required_inputs=[args.active_market_data_file, args.macro_output],
                expected_outputs=[args.data_quality_report_output, args.data_quality_summary_output],
            )
        )

    if args.refresh_timing_audit:
        stages.append(
            Stage(
                name="timing_precision_audit",
                command=python_cmd(args, "macro_timing_audit.py")
                + [
                    "--market-data",
                    args.active_market_data_file,
                    "--events-file",
                    args.macro_output,
                    "--rows-output",
                    args.timing_audit_rows_output,
                    "--summary-output",
                    args.timing_audit_report_output,
                    "--tolerance-minutes",
                    str(args.timing_tolerance_minutes),
                ],
                required_inputs=[args.active_market_data_file, args.macro_output],
                expected_outputs=[args.timing_audit_rows_output, args.timing_audit_report_output],
            )
        )

    if args.refresh_probability_validation:
        stages.append(
            Stage(
                name="probability_validation",
                command=python_cmd(args, "macro_probability_validation.py")
                + [
                    "--grades",
                    args.grades_output,
                    "--summary-output",
                    args.probability_validation_report_output,
                    "--rows-output",
                    args.probability_validation_rows_output,
                ],
                required_inputs=[args.grades_output],
                expected_outputs=[args.probability_validation_report_output, args.probability_validation_rows_output],
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
                    "--regime-context",
                    args.regime_context,
                ],
                required_inputs=[args.live_signal_output, args.performance_output],
                expected_outputs=[args.trust_weights_output, args.adjusted_signal_output],
            )
        )

    if not args.skip_daily_confirmation:
        stages.append(
            Stage(
                name="daily_confirmation",
                command=python_cmd(args, "macro_daily_confirmation.py")
                + [
                    "--signals",
                    args.adjusted_signal_output,
                    "--daily-profiles",
                    args.daily_confirmation_profiles,
                    "--output",
                    args.current_signal_output,
                    "--summary-output",
                    args.daily_confirmation_report_output,
                    "--source-label",
                    args.daily_confirmation_source_label,
                    "--regime-context",
                    args.regime_context,
                ],
                required_inputs=[args.adjusted_signal_output, args.daily_confirmation_profiles],
                expected_outputs=[args.current_signal_output, args.daily_confirmation_report_output],
            )
        )

    return stages


def write_status(path: Path | None, status: dict, dry_run: bool) -> None:
    if not path or dry_run:
        return
    path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_alert_detector(args: argparse.Namespace, root: Path, log_file: Path | None) -> None:
    if args.skip_alerts or args.dry_run:
        return

    command = python_cmd(args, "macro_pipeline_alerts.py") + [
        "--signals",
        args.alert_signal_output,
        "--state",
        args.alert_state_output,
        "--alerts-output",
        args.alerts_output,
        "--summary-output",
        args.alert_summary_output,
        "--probability-jump-threshold",
        str(args.alert_probability_jump_threshold),
        "--confidence-jump-threshold",
        str(args.alert_confidence_jump_threshold),
    ]
    if args.status_output:
        command += ["--status", args.status_output]
    if args.emit_initial_alerts:
        command.append("--emit-initial-alerts")

    log(f"START alert_detector: {command_text(command)}", log_file)
    proc = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for output_line in proc.stdout:
        log(f"alert_detector: {output_line.rstrip()}", log_file)
    return_code = proc.wait()
    if return_code != 0:
        log(f"alert_detector failed with exit code {return_code}", log_file)
    else:
        log("DONE alert_detector", log_file)


def run_alert_notifier(args: argparse.Namespace, root: Path, log_file: Path | None) -> None:
    if not args.notify_alerts or args.dry_run:
        return

    command = python_cmd(args, "macro_alert_notify.py") + [
        "--summary",
        args.alert_summary_output,
        "--alerts-csv",
        args.alerts_output,
        "--state",
        args.alert_notify_state_output,
        "--status-output",
        args.alert_notify_status_output,
        "--targets",
        args.notify_targets,
        "--min-severity",
        args.alert_notify_min_severity,
        "--risk-lock-output",
        args.alert_risk_lock_output,
        "--risk-lock-severity",
        args.alert_risk_lock_severity,
    ]
    if args.alert_notify_scan_history:
        command.append("--scan-history")
    if args.alert_webhook_url:
        command += ["--webhook-url", args.alert_webhook_url]
    if args.alert_email_to:
        command += ["--email-to", args.alert_email_to]
    if args.alert_email_from:
        command += ["--email-from", args.alert_email_from]
    if args.alert_email_subject:
        command += ["--email-subject", args.alert_email_subject]
    if args.alert_smtp_host:
        command += ["--smtp-host", args.alert_smtp_host]
    if args.alert_smtp_port:
        command += ["--smtp-port", str(args.alert_smtp_port)]
    if args.alert_smtp_user:
        command += ["--smtp-user", args.alert_smtp_user]
    if args.alert_smtp_password_env:
        command += ["--smtp-password-env", args.alert_smtp_password_env]
    if args.alert_smtp_no_starttls:
        command.append("--no-smtp-starttls")

    log(f"START alert_notifier: {command_text(command)}", log_file)
    proc = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for output_line in proc.stdout:
        log(f"alert_notifier: {output_line.rstrip()}", log_file)
    return_code = proc.wait()
    if return_code != 0:
        log(f"alert_notifier failed with exit code {return_code}", log_file)
    else:
        log("DONE alert_notifier", log_file)


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
        "current_signal_output": args.current_signal_output,
        "alert_signal_output": args.alert_signal_output,
        "daily_confirmation_enabled": not args.skip_daily_confirmation,
        "alerts_output": args.alerts_output,
        "alert_summary_output": args.alert_summary_output,
        "notify_alerts": args.notify_alerts,
        "alert_notify_status_output": args.alert_notify_status_output,
        "market_config": args.market_config_summary,
        "active_market_data_file": args.active_market_data_file,
        "regime_context": args.regime_context,
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
        run_alert_detector(args, root, log_file)
        run_alert_notifier(args, root, log_file)


def sleep_between_cycles(seconds: int, log_file: Path | None) -> None:
    if seconds <= 0:
        return
    log(f"Sleeping {seconds} second(s) before next cycle", log_file)
    time.sleep(seconds)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the macro catalyst pipeline as separate CLI stages.")
    p.add_argument("--python", default=sys.executable, help="Python executable used to launch child modules")
    p.add_argument("--market-data-config", default="market_data_config.json", help="Market data source config JSON")
    p.add_argument("--run-forever", action="store_true", help="Keep running cycles until Ctrl+C")
    p.add_argument("--max-cycles", type=int, default=0, help="Optional max cycles for --run-forever; 0 means unlimited")
    p.add_argument("--loop-seconds", type=int, default=60, help="Seconds between cycles when --run-forever is set")
    p.add_argument("--stop-on-error", action="store_true", help="Stop a forever run after a failed cycle")
    p.add_argument("--dry-run", action="store_true", help="Print commands and validate inputs without running stages")
    p.add_argument("--log-file", default="macro_pipeline_runner.log")
    p.add_argument("--status-output", default="macro_pipeline_status.json")
    p.add_argument("--skip-alerts", action="store_true", help="Do not run the separate alert detector after each cycle")
    p.add_argument("--alerts-output", default="macro_pipeline_alerts.csv")
    p.add_argument("--alert-state-output", default="macro_pipeline_alert_state.json")
    p.add_argument("--alert-summary-output", default="macro_pipeline_alert_summary.json")
    p.add_argument("--alert-probability-jump-threshold", type=float, default=0.10)
    p.add_argument("--alert-confidence-jump-threshold", type=float, default=0.15)
    p.add_argument("--emit-initial-alerts", action="store_true", help="Emit new-signal alerts on the first alert detector snapshot")
    p.add_argument("--notify-alerts", action="store_true", help="Run the separate alert notifier after alert detection")
    p.add_argument("--notify-targets", default="console", help="Comma-separated: console,bell,webhook,email,risk_lock")
    p.add_argument("--alert-notify-state-output", default="macro_alert_notify_state.json")
    p.add_argument("--alert-notify-status-output", default="macro_alert_notify_status.json")
    p.add_argument("--alert-notify-min-severity", choices=["info", "medium", "high"], default="info")
    p.add_argument("--alert-notify-scan-history", action="store_true")
    p.add_argument("--alert-webhook-url", default="")
    p.add_argument("--alert-email-to", default="")
    p.add_argument("--alert-email-from", default="")
    p.add_argument("--alert-email-subject", default="NQ macro catalyst alert")
    p.add_argument("--alert-smtp-host", default="")
    p.add_argument("--alert-smtp-port", type=int, default=587)
    p.add_argument("--alert-smtp-user", default="")
    p.add_argument("--alert-smtp-password-env", default="MACRO_ALERT_SMTP_PASSWORD")
    p.add_argument("--alert-smtp-no-starttls", action="store_true")
    p.add_argument("--alert-risk-lock-output", default="macro_alert_risk_lock.json")
    p.add_argument("--alert-risk-lock-severity", choices=["medium", "high"], default="high")

    p.add_argument("--market-preset", choices=["config", "none", "daily", "intraday", "intraday-deep"], default="config")
    p.add_argument("--market-ticker", default="", help="Ticker override for market-data refresh")

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
    p.add_argument("--profiles", default=DEFAULT_PROFILES)
    p.add_argument("--calibrated-output", default="macro_releases_calibrated.csv")
    p.add_argument("--live-signal-output", default="macro_live_signal.csv")

    p.add_argument("--refresh-performance", action="store_true")
    p.add_argument("--refresh-quality", action="store_true", help="Run data-quality report after live updates")
    p.add_argument("--refresh-timing-audit", action="store_true", help="Run release/bar timing audit after live updates")
    p.add_argument("--refresh-probability-validation", action="store_true", help="Run probability validation from signal grades")
    p.add_argument("--reaction-files", nargs="*", default=DEFAULT_REACTION_FILES)
    p.add_argument("--reaction-labels", nargs="*", default=None)
    p.add_argument("--performance-windows", default="5,15,30,60,240,390")
    p.add_argument("--performance-primary-window", type=int, default=60)
    p.add_argument("--neutral-threshold-pts", type=float, default=0.0)
    p.add_argument("--grades-output", default="macro_signal_grades.csv")
    p.add_argument("--performance-output", default="macro_signal_performance.csv")
    p.add_argument("--regime-context", default="macro_regime_context.json", help="Optional manual/news regime context JSON")
    p.add_argument("--data-quality-report-output", default="macro_data_quality_report.json")
    p.add_argument("--data-quality-summary-output", default="macro_data_quality_summary.csv")
    p.add_argument("--timing-audit-rows-output", default="macro_timing_audit.csv")
    p.add_argument("--timing-audit-report-output", default="macro_timing_audit_report.json")
    p.add_argument("--timing-tolerance-minutes", type=float, default=5.0)
    p.add_argument("--probability-validation-report-output", default="macro_probability_validation_report.json")
    p.add_argument("--probability-validation-rows-output", default="macro_probability_validation.csv")

    p.add_argument("--skip-trust", action="store_true")
    p.add_argument("--trust-weights-output", default="macro_signal_trust_weights.csv")
    p.add_argument("--adjusted-signal-output", default="macro_live_signal_adjusted.csv")
    p.add_argument("--skip-daily-confirmation", action="store_true")
    p.add_argument("--daily-confirmation-profiles", default=DEFAULT_DAILY_CONFIRMATION_PROFILES)
    p.add_argument("--daily-confirmation-source-label", default="investing_daily_clean")
    p.add_argument("--daily-confirmation-report-output", default="macro_daily_confirmation_report.json")
    p.add_argument("--current-signal-output", default="macro_live_signal_current.csv")
    return p.parse_args()


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    market_config = load_market_config(args.market_data_config)
    args.market_config = market_config
    args.market_config_summary = market_config_summary(market_config)

    if args.profiles == DEFAULT_PROFILES and market_config.get("active_profiles_file"):
        args.profiles = str(market_config["active_profiles_file"])

    args.active_market_data_file = str(market_config.get("active_market_data_file") or "NQ_5min_data.csv")

    if not args.market_ticker:
        yahoo = market_config.get("yahoo") if isinstance(market_config.get("yahoo"), dict) else {}
        args.market_ticker = str(yahoo.get("ticker") or "")

    if args.market_preset == "config":
        default_source = str(market_config.get("default_source") or "yahoo")
        yahoo = market_config.get("yahoo") if isinstance(market_config.get("yahoo"), dict) else {}
        external = market_config.get("external_api") if isinstance(market_config.get("external_api"), dict) else {}
        if default_source == "yahoo" and bool(yahoo.get("enabled", True)) and bool(yahoo.get("refresh_on_runner", False)):
            args.market_preset = str(yahoo.get("preset") or "intraday")
        elif default_source != "yahoo" and bool(external.get("enabled", False)):
            args.market_preset = "none"
        else:
            args.market_preset = "none"

    if args.reaction_labels is None:
        args.reaction_labels = DEFAULT_REACTION_LABELS if args.reaction_files == DEFAULT_REACTION_FILES else []

    config_reaction_files = market_config.get("active_reaction_files")
    if args.reaction_files == DEFAULT_REACTION_FILES and isinstance(config_reaction_files, list) and config_reaction_files:
        args.reaction_files = [str(path) for path in config_reaction_files]
        if args.reaction_labels == DEFAULT_REACTION_LABELS:
            args.reaction_labels = []

    config_reaction_labels = market_config.get("active_reaction_labels")
    if isinstance(config_reaction_labels, list) and config_reaction_labels:
        args.reaction_labels = [str(label) for label in config_reaction_labels]

    daily_confirmation = market_config.get("daily_confirmation") if isinstance(market_config.get("daily_confirmation"), dict) else {}
    if daily_confirmation:
        if not bool(daily_confirmation.get("enabled", True)):
            args.skip_daily_confirmation = True
        if args.daily_confirmation_profiles == DEFAULT_DAILY_CONFIRMATION_PROFILES and daily_confirmation.get("profiles_file"):
            args.daily_confirmation_profiles = str(daily_confirmation["profiles_file"])
        if args.current_signal_output == "macro_live_signal_current.csv" and daily_confirmation.get("output"):
            args.current_signal_output = str(daily_confirmation["output"])
        if args.daily_confirmation_source_label == "investing_daily_clean" and daily_confirmation.get("source_label"):
            args.daily_confirmation_source_label = str(daily_confirmation["source_label"])

    args.alert_signal_output = args.adjusted_signal_output if args.skip_daily_confirmation else args.current_signal_output
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
