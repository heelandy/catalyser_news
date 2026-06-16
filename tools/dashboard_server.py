#!/usr/bin/env python3
"""Serve the dashboard and local-only notification API endpoints."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from email.utils import parseaddr
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "macro_alert_notify_config.json"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def user_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if value or os.name != "nt":
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            stored, _ = winreg.QueryValueEx(key, name)
            return str(stored or "")
    except (FileNotFoundError, OSError):
        return ""


def valid_email(value: str) -> bool:
    value = value.strip()
    _, address = parseaddr(value)
    return address == value and bool(EMAIL_PATTERN.fullmatch(address)) and "\r" not in value and "\n" not in value


def email_status(config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_json(config_path)
    email = config.get("email") if isinstance(config.get("email"), dict) else {}
    smtp = config.get("smtp") if isinstance(config.get("smtp"), dict) else {}
    password_env = str(smtp.get("password_env") or "MACRO_ALERT_SMTP_PASSWORD")
    host = str(smtp.get("host") or os.environ.get("MACRO_ALERT_SMTP_HOST", "")).strip()
    sender = str(email.get("from") or os.environ.get("MACRO_ALERT_EMAIL_FROM", "")).strip()
    recipient = str(email.get("to") or os.environ.get("MACRO_ALERT_EMAIL_TO", "")).strip()
    user = str(smtp.get("user") or os.environ.get("MACRO_ALERT_SMTP_USER", "")).strip()
    password_present = bool(user_environment(password_env))
    raw_targets = config.get("targets", "")
    if isinstance(raw_targets, list):
        targets = {str(value).strip().lower() for value in raw_targets if str(value).strip()}
    else:
        targets = {value.strip().lower() for value in str(raw_targets).split(",") if value.strip()}
    min_severity = str(config.get("min_severity") or "info").strip().lower()
    automatic_enabled = "email" in targets
    return {
        "configured": bool(host and sender and recipient and (not user or password_present)),
        "automatic_enabled": automatic_enabled,
        "mirrors_dashboard_alerts": automatic_enabled and min_severity == "info",
        "min_severity": min_severity,
        "recipient": recipient,
        "sender": sender,
        "smtp_host": host,
        "smtp_port": int(smtp.get("port") or os.environ.get("MACRO_ALERT_SMTP_PORT", "587")),
        "smtp_user": user,
        "password_env": password_env,
        "password_present": password_present,
        "starttls": bool(smtp.get("starttls", True)),
    }


def run_email_test(recipient: str, config_path: Path = DEFAULT_CONFIG) -> tuple[bool, str]:
    status = email_status(config_path)
    if not status["configured"]:
        return False, "Email is not fully configured. Run tools\\setup_email_alert.ps1, then restart the dashboard."

    env = os.environ.copy()
    password_env = status["password_env"]
    if not env.get(password_env):
        env[password_env] = user_environment(password_env)

    command = [
        sys.executable,
        str(ROOT / "macro_alert_notify.py"),
        "--config",
        str(config_path),
        "--targets",
        "email",
        "--test-email",
        "--test-recipient",
        recipient,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=creationflags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "SMTP test timed out after 45 seconds."
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return False, output or f"Email test failed with exit code {result.returncode}."
    return True, output or f"Email test sent to {recipient}."


class DashboardHandler(SimpleHTTPRequestHandler):
    config_path = DEFAULT_CONFIG

    def _write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return True
        parsed = urlsplit(origin)
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.hostname == host

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._write_json({"ok": True, "service": "nq-catalyst-dashboard"})
            return
        if path == "/api/email-status":
            self._write_json(email_status(self.config_path))
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path != "/api/test-email":
            self._write_json({"ok": False, "error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        if not self._same_origin():
            self._write_json({"ok": False, "error": "Local dashboard origin required."}, HTTPStatus.FORBIDDEN)
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._write_json({"ok": False, "error": "JSON request required."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 8192:
            self._write_json({"ok": False, "error": "Invalid request size."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json({"ok": False, "error": "Invalid JSON."}, HTTPStatus.BAD_REQUEST)
            return
        recipient = str(payload.get("recipient") or email_status(self.config_path).get("recipient") or "").strip()
        if not valid_email(recipient):
            self._write_json({"ok": False, "error": "Enter one valid recipient email address."}, HTTPStatus.BAD_REQUEST)
            return
        ok, message = run_email_test(recipient, self.config_path)
        self._write_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"dashboard_server: {self.address_string()} - {fmt % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the NQ Catalyst dashboard and local API.")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    handler = lambda *handler_args, **handler_kwargs: DashboardHandler(  # noqa: E731
        *handler_args,
        directory=str(root),
        **handler_kwargs,
    )
    DashboardHandler.config_path = config_path
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"Dashboard server listening at http://{args.bind}:{args.port}/dashboard/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
