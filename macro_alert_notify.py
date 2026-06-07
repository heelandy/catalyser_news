#!/usr/bin/env python3
"""
macro_alert_notify.py

Optional notification sender for macro pipeline alerts.

The alert detector writes alert history and a latest-summary JSON file. This
module reads those local artifacts, filters alerts it has already delivered,
and sends the new alerts to explicitly configured targets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


SEVERITY_RANK = {"info": 1, "medium": 2, "high": 3}
DEFAULT_TARGETS = "console"


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text if text else fallback


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def normalize_target(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def parse_targets(value: str) -> list[str]:
    targets = [normalize_target(part) for part in value.split(",") if part.strip()]
    return targets or ["console"]


def severity_value(value: str) -> int:
    return SEVERITY_RANK.get(clean(value).lower(), 0)


def min_severity_filter(alerts: list[dict[str, Any]], min_severity: str) -> list[dict[str, Any]]:
    threshold = severity_value(min_severity)
    return [alert for alert in alerts if severity_value(clean(alert.get("severity")).lower()) >= threshold]


def alert_fingerprint(alert: dict[str, Any]) -> str:
    parts = [
        clean(alert.get("alert_time")),
        clean(alert.get("alert_type")),
        clean(alert.get("release_time")),
        clean(alert.get("title")),
        clean(alert.get("message")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def latest_alerts(summary_path: Path, history_path: Path, scan_history: bool) -> list[dict[str, Any]]:
    if scan_history:
        return read_csv_rows(history_path)

    summary = load_json(summary_path)
    alerts = summary.get("latest_alerts")
    if isinstance(alerts, list):
        return [alert for alert in alerts if isinstance(alert, dict)]
    return []


def new_alerts(alerts: list[dict[str, Any]], delivered: set[str], min_severity: str) -> list[dict[str, Any]]:
    filtered = min_severity_filter(alerts, min_severity)
    return [alert for alert in filtered if alert_fingerprint(alert) not in delivered]


def format_alert(alert: dict[str, Any]) -> str:
    severity = clean(alert.get("severity"), "info").upper()
    alert_type = clean(alert.get("alert_type"), "alert")
    title = clean(alert.get("title"), "Pipeline")
    message = clean(alert.get("message"))
    release_time = clean(alert.get("release_time"))
    prefix = f"[{severity}] {alert_type}: {title}"
    if release_time:
        prefix += f" @ {release_time}"
    return f"{prefix}\n{message}" if message else prefix


def console_notify(alerts: list[dict[str, Any]]) -> None:
    for alert in alerts:
        print(format_alert(alert))


def bell_notify(alerts: list[dict[str, Any]]) -> None:
    if alerts:
        print("\a", end="", flush=True)


def webhook_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    url = args.webhook_url or os.environ.get("MACRO_ALERT_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("webhook target requires --webhook-url or MACRO_ALERT_WEBHOOK_URL")

    import requests

    payload = {
        "source": "nq_macro_catalyst",
        "sent_at": now_iso(),
        "alert_count": len(alerts),
        "alerts": alerts,
    }
    response = requests.post(url, json=payload, timeout=args.webhook_timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"webhook returned {response.status_code}: {response.text[:300]}")


def email_body(alerts: list[dict[str, Any]]) -> str:
    return "\n\n".join(format_alert(alert) for alert in alerts)


def email_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    host = args.smtp_host or os.environ.get("MACRO_ALERT_SMTP_HOST", "")
    to_text = args.email_to or os.environ.get("MACRO_ALERT_EMAIL_TO", "")
    from_addr = args.email_from or os.environ.get("MACRO_ALERT_EMAIL_FROM", "")
    user = args.smtp_user or os.environ.get("MACRO_ALERT_SMTP_USER", "")
    password = os.environ.get(args.smtp_password_env, "")

    recipients = [part.strip() for part in to_text.split(",") if part.strip()]
    if not host or not recipients or not from_addr:
        raise RuntimeError("email target requires SMTP host, email sender, and recipient")

    msg = EmailMessage()
    msg["Subject"] = args.email_subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(email_body(alerts))

    with smtplib.SMTP(host, args.smtp_port, timeout=args.smtp_timeout) as smtp:
        if args.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def risk_lock_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    threshold = severity_value(args.risk_lock_severity)
    lock_alerts = [alert for alert in alerts if severity_value(clean(alert.get("severity")).lower()) >= threshold]
    payload = {
        "updated_at": now_iso(),
        "active": bool(lock_alerts),
        "severity_threshold": args.risk_lock_severity,
        "alert_count": len(lock_alerts),
        "alerts": lock_alerts,
        "note": "Local handoff only. Trading systems must decide how to consume this file.",
    }
    write_json(Path(args.risk_lock_output), payload)


def send_to_targets(alerts: list[dict[str, Any]], targets: list[str], args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    for target in targets:
        try:
            if target == "console":
                console_notify(alerts)
            elif target == "bell":
                bell_notify(alerts)
            elif target == "webhook":
                webhook_notify(alerts, args)
            elif target == "email":
                email_notify(alerts, args)
            elif target == "risk_lock":
                risk_lock_notify(alerts, args)
            else:
                raise RuntimeError(f"unknown notify target: {target}")
        except Exception as exc:
            errors.append(f"{target}: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send configured notifications for new macro pipeline alerts.")
    p.add_argument("--summary", default="macro_pipeline_alert_summary.json")
    p.add_argument("--alerts-csv", default="macro_pipeline_alerts.csv")
    p.add_argument("--state", default="macro_alert_notify_state.json")
    p.add_argument("--status-output", default="macro_alert_notify_status.json")
    p.add_argument("--targets", default=DEFAULT_TARGETS, help="Comma-separated: console,bell,webhook,email,risk_lock")
    p.add_argument("--min-severity", choices=["info", "medium", "high"], default="info")
    p.add_argument("--scan-history", action="store_true", help="Scan the full alert CSV instead of only the latest summary alerts")
    p.add_argument("--dry-run", action="store_true")

    p.add_argument("--webhook-url", default="")
    p.add_argument("--webhook-timeout", type=int, default=10)

    p.add_argument("--email-to", default="")
    p.add_argument("--email-from", default="")
    p.add_argument("--email-subject", default="NQ macro catalyst alert")
    p.add_argument("--smtp-host", default="")
    p.add_argument("--smtp-port", type=int, default=int(os.environ.get("MACRO_ALERT_SMTP_PORT", "587")))
    p.add_argument("--smtp-timeout", type=int, default=20)
    p.add_argument("--smtp-user", default="")
    p.add_argument("--smtp-password-env", default="MACRO_ALERT_SMTP_PASSWORD")
    p.add_argument("--smtp-starttls", dest="smtp_starttls", action="store_true", default=True)
    p.add_argument("--no-smtp-starttls", dest="smtp_starttls", action="store_false")

    p.add_argument("--risk-lock-output", default="macro_alert_risk_lock.json")
    p.add_argument("--risk-lock-severity", choices=["medium", "high"], default="high")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    targets = parse_targets(args.targets)
    state_path = Path(args.state)
    state = load_json(state_path)
    delivered = set(state.get("delivered_fingerprints", []))

    alerts = latest_alerts(Path(args.summary), Path(args.alerts_csv), args.scan_history)
    pending = new_alerts(alerts, delivered, args.min_severity)

    errors: list[str] = []
    if pending and not args.dry_run:
        errors = send_to_targets(pending, targets, args)
    elif pending:
        console_notify(pending)

    delivered_now = [] if errors else [alert_fingerprint(alert) for alert in pending]
    delivered.update(delivered_now)
    next_state = {
        "created_at": state.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "targets": targets,
        "min_severity": args.min_severity,
        "delivered_fingerprints": sorted(delivered),
    }
    if not args.dry_run:
        write_json(state_path, next_state)

    status = {
        "checked_at": now_iso(),
        "targets": targets,
        "min_severity": args.min_severity,
        "alerts_seen": len(alerts),
        "alerts_pending": len(pending),
        "alerts_delivered": len(delivered_now),
        "dry_run": args.dry_run,
        "errors": errors,
    }
    if not args.dry_run:
        write_json(Path(args.status_output), status)

    print(
        f"Notify check complete: {len(pending)} pending, "
        f"{len(delivered_now)} delivered, {len(errors)} error(s)."
    )
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
