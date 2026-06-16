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
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


SEVERITY_RANK = {"info": 1, "medium": 2, "high": 3}
DEFAULT_TARGETS = "console"


def option_present(argv: list[str], *names: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in argv for name in names)


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


def config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return text_value(value).lower() in {"1", "true", "yes", "on"}


def apply_config(args: argparse.Namespace, argv: list[str]) -> argparse.Namespace:
    config_path = Path(args.config) if args.config else None
    config = load_json(config_path) if config_path else {}
    if not isinstance(config, dict) or not config:
        return args

    flat: dict[str, Any] = {}
    flat.update(config)
    webhook = config.get("webhook") if isinstance(config.get("webhook"), dict) else {}
    email = config.get("email") if isinstance(config.get("email"), dict) else {}
    smtp = config.get("smtp") if isinstance(config.get("smtp"), dict) else {}
    risk_lock = config.get("risk_lock") if isinstance(config.get("risk_lock"), dict) else {}
    popup = config.get("popup") if isinstance(config.get("popup"), dict) else {}
    discord = config.get("discord") if isinstance(config.get("discord"), dict) else {}
    telegram = config.get("telegram") if isinstance(config.get("telegram"), dict) else {}

    nested_map = {
        "webhook_url": webhook.get("url"),
        "webhook_timeout": webhook.get("timeout"),
        "discord_webhook_url": discord.get("webhook_url"),
        "discord_timeout": discord.get("timeout"),
        "telegram_bot_token": telegram.get("bot_token"),
        "telegram_bot_token_env": telegram.get("bot_token_env"),
        "telegram_chat_id": telegram.get("chat_id"),
        "telegram_timeout": telegram.get("timeout"),
        "email_to": email.get("to"),
        "email_from": email.get("from"),
        "email_subject": email.get("subject"),
        "smtp_host": smtp.get("host"),
        "smtp_port": smtp.get("port"),
        "smtp_timeout": smtp.get("timeout"),
        "smtp_user": smtp.get("user"),
        "smtp_password_env": smtp.get("password_env"),
        "smtp_starttls": smtp.get("starttls"),
        "risk_lock_output": risk_lock.get("output"),
        "risk_lock_severity": risk_lock.get("severity"),
        "popup_title": popup.get("title"),
        "popup_seconds": popup.get("seconds"),
        "popup_max_chars": popup.get("max_chars"),
    }
    for key, value in nested_map.items():
        if value is not None:
            flat[key] = value

    option_names = {
        "targets": ("--targets",),
        "min_severity": ("--min-severity",),
        "scan_history": ("--scan-history",),
        "signals": ("--signals",),
        "webhook_url": ("--webhook-url",),
        "webhook_timeout": ("--webhook-timeout",),
        "discord_webhook_url": ("--discord-webhook-url",),
        "discord_timeout": ("--discord-timeout",),
        "telegram_bot_token": ("--telegram-bot-token",),
        "telegram_bot_token_env": ("--telegram-bot-token-env",),
        "telegram_chat_id": ("--telegram-chat-id",),
        "telegram_timeout": ("--telegram-timeout",),
        "email_to": ("--email-to",),
        "email_from": ("--email-from",),
        "email_subject": ("--email-subject",),
        "smtp_host": ("--smtp-host",),
        "smtp_port": ("--smtp-port",),
        "smtp_timeout": ("--smtp-timeout",),
        "smtp_user": ("--smtp-user",),
        "smtp_password_env": ("--smtp-password-env",),
        "smtp_starttls": ("--smtp-starttls", "--no-smtp-starttls"),
        "risk_lock_output": ("--risk-lock-output",),
        "risk_lock_severity": ("--risk-lock-severity",),
        "popup_title": ("--popup-title",),
        "popup_seconds": ("--popup-seconds",),
        "popup_max_chars": ("--popup-max-chars",),
    }
    int_fields = {"webhook_timeout", "discord_timeout", "telegram_timeout", "smtp_port", "smtp_timeout", "popup_seconds", "popup_max_chars"}
    bool_fields = {"scan_history", "smtp_starttls"}

    for field, names in option_names.items():
        if field not in flat or option_present(argv, *names):
            continue
        value = flat[field]
        if value is None or value == "":
            continue
        if field in int_fields:
            value = int(value)
        elif field in bool_fields:
            value = config_bool(value)
        setattr(args, field, value)
    return args


def text_value(value: Any) -> str:
    return str(value if value is not None else "").strip()


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


def chunk_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks or [text]


def discord_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    url = args.discord_webhook_url or os.environ.get("MACRO_ALERT_DISCORD_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("discord target requires --discord-webhook-url or MACRO_ALERT_DISCORD_WEBHOOK_URL")

    import requests

    text = "\n\n".join(format_alert(alert) for alert in alerts)
    for chunk in chunk_text(text, 1900):
        response = requests.post(url, json={"content": chunk}, timeout=args.discord_timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"discord webhook returned {response.status_code}: {response.text[:300]}")


def telegram_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    token = args.telegram_bot_token or os.environ.get(args.telegram_bot_token_env, "")
    chat_id = args.telegram_chat_id or os.environ.get("MACRO_ALERT_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError(
            "telegram target requires a bot token (--telegram-bot-token or env "
            f"{args.telegram_bot_token_env}) and a chat id (--telegram-chat-id or MACRO_ALERT_TELEGRAM_CHAT_ID)"
        )

    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = "\n\n".join(format_alert(alert) for alert in alerts)
    for chunk in chunk_text(text, 3900):
        response = requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=args.telegram_timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"telegram api returned {response.status_code}: {response.text[:300]}")


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


def signal_risk_locks(path: Path) -> list[dict[str, Any]]:
    locks: list[dict[str, Any]] = []
    for row in read_csv_rows(path):
        conflict = clean(row.get("market_regime_conflict"), "none").lower()
        trade_state = clean(row.get("trade_state"), "").lower()
        release_direction = clean(row.get("release_rule_direction") or row.get("release_rule_side"), "").lower()
        regime_direction = clean(row.get("live_market_regime_direction"), "").lower()
        final_warning = clean(row.get("final_warning") or row.get("trust_warning") or row.get("warning"), "")
        reason = clean(row.get("trade_state_reason") or row.get("live_market_regime_reason") or final_warning, "")

        release_positive = release_direction in {"bullish", "positive", "long", "market_positive"}
        live_bearish = regime_direction in {"bearish", "risk_off", "negative"}
        no_long_state = trade_state.startswith("no_long") or "no_long" in trade_state
        warning_lock = "avoid long" in final_warning.lower() or "no long" in final_warning.lower()

        if conflict == "none" and not no_long_state and not (release_positive and live_bearish) and not warning_lock:
            continue

        locks.append(
            {
                "release_time": clean(row.get("release_time") or row.get("date")),
                "title": clean(row.get("title"), "macro signal"),
                "event_family": clean(row.get("event_family")),
                "severity": "high" if no_long_state or (release_positive and live_bearish) else "medium",
                "market_regime_conflict": conflict,
                "trade_state": trade_state,
                "release_rule_direction": release_direction,
                "live_market_regime_direction": regime_direction,
                "live_market_regime": clean(row.get("live_market_regime")),
                "reason": reason or "Release rule and live regime require risk lock review.",
            }
        )
    return locks


def risk_lock_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    threshold = severity_value(args.risk_lock_severity)
    lock_alerts = [alert for alert in alerts if severity_value(clean(alert.get("severity")).lower()) >= threshold]
    signal_locks = signal_risk_locks(Path(args.signals))
    payload = {
        "updated_at": now_iso(),
        "active": bool(lock_alerts or signal_locks),
        "severity_threshold": args.risk_lock_severity,
        "alert_count": len(lock_alerts),
        "signal_lock_count": len(signal_locks),
        "alerts": lock_alerts,
        "signal_locks": signal_locks,
        "note": "Local handoff only. Trading systems must decide how to consume this file.",
    }
    write_json(Path(args.risk_lock_output), payload)


def popup_text(alerts: list[dict[str, Any]], max_chars: int) -> str:
    if not alerts:
        return ""
    text = format_alert(alerts[0])
    if len(alerts) > 1:
        text += f"\n\nPlus {len(alerts) - 1} more alert(s)."
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def popup_notify(alerts: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if not alerts:
        return
    if os.name != "nt":
        console_notify(alerts)
        return

    title = clean(args.popup_title, "NQ Macro Catalyst")
    text = popup_text(alerts, args.popup_max_chars)
    seconds = max(3, int(args.popup_seconds))
    ms = seconds * 1000

    # NotifyIcon is standard Windows/.NET and avoids extra Python packages.
    title = title.replace("'@", "' @")
    text = text.replace("'@", "' @")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = @'
{title}
'@
$notify.BalloonTipText = @'
{text}
'@
$notify.Visible = $true
$notify.ShowBalloonTip({ms})
Start-Sleep -Seconds {seconds}
$notify.Dispose()
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


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
            elif target == "discord":
                discord_notify(alerts, args)
            elif target == "telegram":
                telegram_notify(alerts, args)
            elif target == "email":
                email_notify(alerts, args)
            elif target == "risk_lock":
                risk_lock_notify(alerts, args)
            elif target == "popup":
                popup_notify(alerts, args)
            else:
                raise RuntimeError(f"unknown notify target: {target}")
        except Exception as exc:
            errors.append(f"{target}: {exc}")
    return errors


def test_email_alert(recipient: str) -> dict[str, Any]:
    return {
        "alert_time": now_iso(),
        "severity": "info",
        "alert_type": "email_test",
        "title": "NQ Macro Catalyst",
        "message": (
            "Test email delivered successfully from the local dashboard. "
            "Future pipeline alerts can use this same SMTP configuration."
        ),
        "release_time": "",
        "recipient": recipient,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send configured notifications for new macro pipeline alerts.")
    p.add_argument("--config", default="macro_alert_notify_config.json", help="Optional notification config JSON")
    p.add_argument("--summary", default="macro_pipeline_alert_summary.json")
    p.add_argument("--alerts-csv", default="macro_pipeline_alerts.csv")
    p.add_argument("--signals", default="macro_live_signal_current.csv")
    p.add_argument("--state", default="macro_alert_notify_state.json")
    p.add_argument("--status-output", default="macro_alert_notify_status.json")
    p.add_argument("--targets", default=DEFAULT_TARGETS, help="Comma-separated: console,bell,popup,webhook,discord,telegram,email,risk_lock")
    p.add_argument("--min-severity", choices=["info", "medium", "high"], default="info")
    p.add_argument("--scan-history", action="store_true", help="Scan the full alert CSV instead of only the latest summary alerts")
    p.add_argument("--dry-run", action="store_true")

    p.add_argument("--webhook-url", default="")
    p.add_argument("--webhook-timeout", type=int, default=10)

    p.add_argument("--discord-webhook-url", default="", help="Discord channel webhook URL (or MACRO_ALERT_DISCORD_WEBHOOK_URL)")
    p.add_argument("--discord-timeout", type=int, default=10)

    p.add_argument("--telegram-bot-token", default="", help="Telegram bot token; prefer the env var for secrecy")
    p.add_argument("--telegram-bot-token-env", default="MACRO_ALERT_TELEGRAM_BOT_TOKEN")
    p.add_argument("--telegram-chat-id", default="", help="Telegram chat id (or MACRO_ALERT_TELEGRAM_CHAT_ID)")
    p.add_argument("--telegram-timeout", type=int, default=10)

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
    p.add_argument("--test-email", action="store_true", help="Send one synthetic email immediately and exit")
    p.add_argument("--test-recipient", default="", help="Optional recipient override for --test-email")

    p.add_argument("--risk-lock-output", default="macro_alert_risk_lock.json")
    p.add_argument("--risk-lock-severity", choices=["medium", "high"], default="high")

    p.add_argument("--popup-title", default=os.environ.get("MACRO_ALERT_POPUP_TITLE", "NQ Macro Catalyst"))
    p.add_argument("--popup-seconds", type=int, default=int(os.environ.get("MACRO_ALERT_POPUP_SECONDS", "12")))
    p.add_argument("--popup-max-chars", type=int, default=int(os.environ.get("MACRO_ALERT_POPUP_MAX_CHARS", "500")))
    argv = sys.argv[1:]
    return apply_config(p.parse_args(argv), argv)


def main() -> None:
    args = parse_args()
    targets = parse_targets(args.targets)
    if args.test_email:
        if args.test_recipient:
            args.email_to = args.test_recipient
        recipient = clean(args.email_to or os.environ.get("MACRO_ALERT_EMAIL_TO", ""))
        test_alert = test_email_alert(recipient)
        if args.dry_run:
            console_notify([test_alert])
            print("Email test dry run complete.")
            return
        errors = send_to_targets([test_alert], ["email"], args)
        if errors:
            for error in errors:
                print(f"ERROR {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"Email test sent to {recipient}.")
        return

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
    elif "risk_lock" in targets and not args.dry_run:
        try:
            risk_lock_notify([], args)
        except Exception as exc:
            errors.append(f"risk_lock: {exc}")

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
