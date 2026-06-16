#!/usr/bin/env python3
"""
macro_web_ingest.py

Build and send signed Market Catalyst web-ingestion payloads from the existing
Python macro signal CSVs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DISCLAIMER = "Educational and informational use only. This is not financial advice."
MARKET_BIASES = {"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
SIGNATURE_HEADER = "x-market-catalyst-signature"
TIMESTAMP_HEADER = "x-market-catalyst-timestamp"


def clean(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text if text else fallback


def first_clean(row: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = clean(row.get(key))
        if value:
            return value
    return fallback


def parse_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def percent_value(value: Any) -> int:
    number = parse_float(value)
    if number is None:
        return 0
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def probability_value(value: Any) -> float | None:
    number = parse_float(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        number *= 100
    return max(0.0, min(100.0, round(number, 4)))


def parse_engine_time(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bias_from_text(value: Any) -> str:
    text = clean(value).lower()
    if text == "bullish":
        return "BULLISH"
    if text == "bearish":
        return "BEARISH"
    if text == "neutral":
        return "NEUTRAL"
    return "MIXED"


def risk_level(row: dict[str, Any]) -> str:
    warning = first_clean(row, "final_warning", "trust_warning", "warning").lower()
    trade_state = first_clean(row, "trade_state").lower()
    conflict = first_clean(row, "market_regime_conflict", fallback="none").lower()
    confidence = percent_value(first_clean(row, "final_confidence", "trust_adjusted_confidence", "confidence"))

    if conflict not in {"", "none", "--"} or trade_state.startswith("no_long"):
        return "HIGH"
    if "risk_lock" in warning or "avoid long" in warning or "no long" in warning:
        return "HIGH"
    if confidence >= 75:
        return "MEDIUM"
    return "LOW"


def stable_digest(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def source_event_id(row: dict[str, Any]) -> str:
    digest = stable_digest(
        [
            first_clean(row, "source", fallback="python_engine"),
            first_clean(row, "release_time", "date"),
            first_clean(row, "title", fallback="untitled"),
        ]
    )
    return f"macro-event:{digest[:48]}"


def idempotency_key(row: dict[str, Any]) -> str:
    digest = stable_digest(
        [
            source_event_id(row),
            first_clean(row, "actual", "actual_value"),
            first_clean(row, "final_expected_direction", "trust_adjusted_direction", "expected_direction"),
            first_clean(row, "trade_state"),
            first_clean(row, "market_regime_conflict"),
        ]
    )
    return f"python-engine:{digest[:48]}"


def alertable(row: dict[str, Any], include_waiting: bool) -> bool:
    if include_waiting:
        return True
    status = first_clean(row, "release_status", fallback="unknown").lower()
    actual = first_clean(row, "actual", "actual_value")
    conflict = first_clean(row, "market_regime_conflict", fallback="none").lower()
    trade_state = first_clean(row, "trade_state").lower()
    return (
        status == "released"
        or bool(actual)
        or conflict not in {"", "none", "--"}
        or trade_state.startswith("no_long")
    )


def build_payload(row: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or now_iso()
    title = first_clean(row, "title", fallback="Macro catalyst")
    event_family = first_clean(row, "event_family", fallback="other")
    source = first_clean(row, "source", fallback="python_engine")
    release_time = parse_engine_time(first_clean(row, "release_time", "date"))
    final_bias = bias_from_text(first_clean(row, "final_expected_direction", "trust_adjusted_direction", "expected_direction"))
    release_rule_bias = bias_from_text(first_clean(row, "release_rule_direction", "market_rule_direction"))
    live_regime_bias = bias_from_text(first_clean(row, "live_market_regime_direction"))
    confidence = percent_value(first_clean(row, "final_confidence", "trust_adjusted_confidence", "confidence"))
    bullish_probability = probability_value(
        first_clean(
            row,
            "final_bullish_probability",
            "trust_adjusted_bullish_probability",
            "calibrated_bullish_probability",
            "historical_bullish_probability",
        )
    )
    trade_state = first_clean(row, "trade_state", fallback="watch_only")
    warning = first_clean(
        row,
        "final_warning",
        "trust_warning",
        "warning",
        fallback="Wait for confirmation before acting on this signal.",
    )
    expected_reaction = first_clean(
        row,
        "trade_state_reason",
        "market_rule_note",
        fallback=f"{title} points to a {final_bias.lower()} NQ reaction, pending tape confirmation.",
    )
    reasoning = "; ".join(
        part
        for part in [
            first_clean(row, "market_rule_note"),
            first_clean(row, "live_market_regime_reason"),
            first_clean(row, "daily_confirmation_note"),
        ]
        if part
    ) or expected_reaction
    expires_at = None
    if release_time:
        try:
            base = datetime.fromisoformat(release_time.replace("Z", "+00:00"))
            expires_at = base.replace(tzinfo=timezone.utc).timestamp() + 2 * 60 * 60
            expires_at = datetime.fromtimestamp(expires_at, timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            expires_at = None

    key = idempotency_key(row)
    fingerprint = f"python-engine:{stable_digest([key])[:64]}"

    return {
        "version": 1,
        "idempotencyKey": key,
        "generatedAt": generated_at,
        "newsEvent": {
            "source": source,
            "sourceEventId": source_event_id(row),
            "publisher": source,
            "symbol": "NQ",
            "eventFamily": event_family,
            "headline": title,
            "url": first_clean(row, "source_url") or None,
            "summary": first_clean(row, "message", "market_rule_note", fallback=warning),
            "occurredAt": release_time,
            "fetchedAt": generated_at,
            "rawPayload": {
                "release_status": first_clean(row, "release_status"),
                "source": source,
            },
        },
        "marketReaction": {
            "eventFamily": event_family,
            "symbol": "NQ",
            "releaseTime": release_time,
            "actualValue": first_clean(row, "actual", "actual_value") or None,
            "forecastValue": first_clean(row, "forecast", "forecast_value") or None,
            "previousValue": first_clean(row, "previous", "previous_value") or None,
            "releaseRuleBias": release_rule_bias,
            "liveRegimeBias": live_regime_bias,
            "finalBias": final_bias,
            "bullishProbability": bullish_probability,
            "confidence": confidence,
            "riskLevel": risk_level(row),
            "tradeState": trade_state,
            "expectedReaction": expected_reaction,
            "reasoning": reasoning,
            "riskWarning": warning,
            "watchLevels": {
                "source": "python_engine",
                "release_time": release_time,
                "trade_state": trade_state,
            },
            "invalidation": "Signal invalidates if live tape/regime no longer confirms the stated bias.",
            "expiresAt": expires_at,
        },
        "alert": {
            "state": "PENDING",
            "headline": title,
            "summary": first_clean(row, "message", "market_rule_note", fallback=expected_reaction),
            "bias": final_bias,
            "expectedReaction": expected_reaction,
            "confidence": confidence,
            "riskLevel": risk_level(row),
            "reasoning": reasoning,
            "riskWarning": warning,
            "watchLevels": {
                "source": "python_engine",
                "release_time": release_time,
                "trade_state": trade_state,
            },
            "invalidation": "Signal invalidates if live tape/regime no longer confirms the stated bias.",
            "disclaimer": DISCLAIMER,
            "sourceFingerprint": fingerprint,
            "expiresAt": expires_at,
        },
    }


def validate_payload(payload: dict[str, Any]) -> None:
    required_top = ["version", "idempotencyKey", "generatedAt", "marketReaction", "alert"]
    for key in required_top:
        if key not in payload:
            raise ValueError(f"missing required payload field: {key}")
    if payload["version"] != 1:
        raise ValueError("payload version must be 1")
    if len(clean(payload["idempotencyKey"])) < 12:
        raise ValueError("idempotencyKey must be at least 12 characters")

    reaction = payload["marketReaction"]
    alert = payload["alert"]
    for section_name, section in [("marketReaction", reaction), ("alert", alert)]:
        for key in ["confidence", "riskLevel"]:
            if key not in section:
                raise ValueError(f"{section_name}.{key} is required")
        confidence = section["confidence"]
        if not isinstance(confidence, int) or not 0 <= confidence <= 100:
            raise ValueError(f"{section_name}.confidence must be 0-100 integer")
        if section["riskLevel"] not in RISK_LEVELS:
            raise ValueError(f"{section_name}.riskLevel is invalid")
    for key in ["releaseRuleBias", "liveRegimeBias", "finalBias"]:
        if reaction.get(key) not in MARKET_BIASES:
            raise ValueError(f"marketReaction.{key} is invalid")
    if alert.get("bias") not in MARKET_BIASES:
        raise ValueError("alert.bias is invalid")
    for key in ["headline", "summary", "expectedReaction", "reasoning", "riskWarning", "disclaimer"]:
        if not clean(alert.get(key)):
            raise ValueError(f"alert.{key} is required")


def sign_body(secret: str, timestamp: int, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def send_payload(endpoint: str, secret: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    timestamp = int(time.time())
    request = urllib.request.Request(
        endpoint,
        data=body.encode("utf-8"),
        headers={
            "content-type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign_body(secret, timestamp, body),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ingestion failed with HTTP {exc.code}: {detail}") from exc


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send signed Python macro signals to the web ingestion API.")
    parser.add_argument("--signals", default="macro_live_signal_current.csv")
    parser.add_argument("--endpoint", default=os.environ.get("MARKET_CATALYST_INGEST_URL", "http://127.0.0.1:3000/api/engine/alerts"))
    parser.add_argument("--secret-env", default="ENGINE_INGEST_SECRET")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--include-waiting", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [row for row in read_rows(Path(args.signals)) if alertable(row, args.include_waiting)]
    payloads = [build_payload(row) for row in rows[: max(0, args.limit)]]
    for payload in payloads:
        validate_payload(payload)

    if args.dry_run:
        print(json.dumps(payloads, indent=2, sort_keys=True))
        return

    secret = os.environ.get(args.secret_env, "")
    if len(secret) < 32:
        raise SystemExit(f"{args.secret_env} must contain at least 32 characters.")
    if not payloads:
        print("No alertable rows to ingest.")
        return

    for payload in payloads:
        result = send_payload(args.endpoint, secret, payload)
        print(f"{payload['idempotencyKey']}: {json.dumps(result, sort_keys=True)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"macro_web_ingest: {exc}", file=sys.stderr)
        raise
