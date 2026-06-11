#!/usr/bin/env python3
"""
tools/tape_signal_listener.py

Local HTTP listener that turns TradingView alert webhooks from the HIGHSTRIKE
Pine scripts into `macro_tape_signals.json`, which the live regime builder
already parses every pipeline cycle.

TradingView setup:
  1. Add HIGHSTRIKE_ORB_V1_INDICATOR to the NQ chart and
     HIGHSTRIKE_ORB_OPTIONS to the SPY/QQQ charts.
  2. Create an alert on the indicator and set the webhook URL to this
     listener. TradingView requires a public URL, so expose the local port
     with a tunnel, for example:
       cloudflared tunnel --url http://127.0.0.1:8788
  3. Use the alert message text as-is; bullish/bearish is inferred from words
     like LONG/SHORT/CALL/PUT in the message, or send JSON with explicit
     fields: {"symbol": "NQ", "message": "...", "direction": "bearish"}.

Without a tunnel you can also post alerts manually from this machine:
  curl -X POST http://127.0.0.1:8788 -d "HIGHSTRIKE ORB: SHORT breakout confirmed NQ"

Run:
  python tools/tape_signal_listener.py --port 8788 --valid-minutes 180
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BULLISH_HINTS = re.compile(r"\b(long|call|calls|buy call|bullish|breakout up|upside)\b", re.IGNORECASE)
BEARISH_HINTS = re.compile(r"\b(short|put|puts|buy put|bearish|breakdown|downside)\b", re.IGNORECASE)
SYMBOL_HINTS = re.compile(r"\b(NQ|MNQ|QQQ|SPY|MES|ES)\b", re.IGNORECASE)


def now_local() -> datetime:
    return datetime.now().astimezone()


def infer_direction(text: str) -> str:
    bullish = bool(BULLISH_HINTS.search(text))
    bearish = bool(BEARISH_HINTS.search(text))
    if bullish and not bearish:
        return "bullish"
    if bearish and not bullish:
        return "bearish"
    return "mixed"


def infer_symbol(text: str) -> str:
    match = SYMBOL_HINTS.search(text)
    return match.group(1).upper() if match else ""


def infer_source(text: str, symbol: str) -> str:
    if "option" in text.lower() or symbol in {"QQQ", "SPY"}:
        return "HIGHSTRIKE_ORB_OPTIONS"
    return "HIGHSTRIKE_ORB_V1"


def build_signal(body: str, valid_minutes: int, default_confidence: float) -> dict:
    message = body.strip()
    payload: dict = {}
    if message.startswith("{"):
        try:
            payload = json.loads(message)
            message = str(payload.get("message") or payload.get("text") or message)
        except json.JSONDecodeError:
            payload = {}

    symbol = str(payload.get("symbol") or infer_symbol(message) or "NQ").upper()
    direction = str(payload.get("direction") or infer_direction(message)).lower()
    if direction not in {"bullish", "bearish", "mixed"}:
        direction = infer_direction(message)
    confidence = payload.get("confidence")
    try:
        confidence = max(0.05, min(0.95, float(confidence)))
    except (TypeError, ValueError):
        confidence = default_confidence
    now = now_local()
    return {
        "time": now.isoformat(timespec="seconds"),
        "valid_until": (now + timedelta(minutes=valid_minutes)).isoformat(timespec="seconds"),
        "source": str(payload.get("source") or infer_source(message, symbol)),
        "symbol": symbol,
        "message": message[:400],
        "direction": direction,
        "confidence": confidence,
    }


def append_signal(output: Path, signal: dict, max_signals: int) -> int:
    signals = []
    if output.exists():
        try:
            data = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(data.get("signals"), list):
                signals = data["signals"]
        except json.JSONDecodeError:
            signals = []
    signals.append(signal)
    signals = signals[-max_signals:]
    output.write_text(json.dumps({"signals": signals}, indent=2) + "\n", encoding="utf-8")
    return len(signals)


def make_handler(args: argparse.Namespace):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            if not body.strip():
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"empty alert body\n")
                return
            signal = build_signal(body, args.valid_minutes, args.default_confidence)
            count = append_signal(Path(args.output), signal, args.max_signals)
            print(f"[{signal['time']}] {signal['source']} {signal['symbol']} {signal['direction']}: {signal['message'][:80]}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "stored_signals": count, "direction": signal["direction"]}).encode())

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"tape signal listener is running; POST TradingView alert text here\n")

        def log_message(self, fmt: str, *log_args) -> None:
            return

    return Handler


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Receive TradingView HIGHSTRIKE alerts and write macro_tape_signals.json.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8788)
    p.add_argument("--output", default=str(ROOT / "macro_tape_signals.json"))
    p.add_argument("--valid-minutes", type=int, default=180, help="How long each alert stays valid for the regime builder")
    p.add_argument("--default-confidence", type=float, default=0.70)
    p.add_argument("--max-signals", type=int, default=20)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    server = HTTPServer((args.host, args.port), make_handler(args))
    print(f"Tape signal listener on http://{args.host}:{args.port} -> {args.output}")
    print("POST TradingView alert text or JSON; Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Listener stopped.")


if __name__ == "__main__":
    main()
