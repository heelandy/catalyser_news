#!/usr/bin/env python3
"""
tradingview_fills_to_trades.py
==============================
Pair a TradingView paper/live ORDER-HISTORY export into round-trip trades in the
exact schema hs_validation.py expects:

    entry_time, exit_time, direction, entry_price, exit_price, symbol, contracts

TradingView exports one row per ORDER (entries, protective stops, targets, and
every cancelled bracket leg). hs_validation needs round-trip TRADES, so this
reconstructs them.

Pairing model (matches bracket-style trading: enter at market, protect with a
stop, take profit with a limit):
  - Keep only Status == Filled.
  - A MARKET fill while flat OPENS a position (direction = its side).
  - Any opposite-side fill REDUCES/closes; when the position returns to flat a
    round trip is recorded (size-weighted entry & exit, so scaling in/out works).
  - A same-side fill while in a position scales in.
  - A STOP/LIMIT fill while flat is an ORPHAN exit (its entry predates the export
    window) -> skipped and counted, not invented.
  - A fill that flips through zero closes the old leg and opens the remainder.
  Fill time = 'Closing time' (when the order reached Filled), else 'Placing time'.

NOTE: assumes entries are market orders and exits are stop/limit (the common
bracket pattern). If you place stop/limit ENTRIES, tell me and I'll add an
entry/exit tag column instead of inferring from order type.

Usage:
    python3 tradingview_fills_to_trades.py <order_history.csv> [out.csv] [SYMBOL]
Then:
    python3 hs_validation.py --trades <out.csv> --symbol NQ --capital 50000
"""
import sys
from pathlib import Path

import pandas as pd
import numpy as np


REQUIRED_COLUMNS = {
    "status", "closing time", "placing time", "fill price", "quantity",
    "side", "type", "order id",
}


def _order_history_candidates(base_dir: Path) -> list[Path]:
    candidates = []
    for pattern in ("paper-trading-order-history*.csv", "*order-history*.csv"):
        candidates.extend(base_dir.glob(pattern))
    return sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)


def _default_input(base_dir: Path) -> Path | None:
    candidates = _order_history_candidates(base_dir)
    return candidates[0] if candidates else None


def convert(in_path: str, out_path: str, symbol: str = "NQ"):
    in_file = Path(in_path)
    if not in_file.exists():
        candidates = _order_history_candidates(Path.cwd())
        hint = ""
        if candidates:
            hint = f' Try: python tradingview_fills_to_trades.py "{candidates[0]}"'
        raise FileNotFoundError(f"input CSV not found: {in_path}.{hint}")

    df = pd.read_csv(in_file, on_bad_lines="skip")
    df.columns = [c.strip().lower() for c in df.columns]
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(
            f"{in_path} does not look like a TradingView order-history CSV. "
            f"Missing columns: {', '.join(missing)}. "
            "If this is already a trade CSV like paper_real_trades.csv, run it "
            "with hs_validation.py instead of this converter."
        )

    df = df[df["status"].astype(str).str.strip().str.lower() == "filled"].copy()

    df["fill_time"] = pd.to_datetime(df["closing time"], errors="coerce")
    m = df["fill_time"].isna()
    df.loc[m, "fill_time"] = pd.to_datetime(df.loc[m, "placing time"], errors="coerce")
    df["price"] = pd.to_numeric(df["fill price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["side"] = df["side"].astype(str).str.strip().str.lower()
    df["otype"] = df["type"].astype(str).str.strip().str.lower()
    df["oid"] = pd.to_numeric(df["order id"], errors="coerce")
    df = df.dropna(subset=["fill_time", "price", "qty"]).sort_values(
        ["fill_time", "oid"]).reset_index(drop=True)

    pos = 0.0
    e_qty = e_cost = x_qty = x_cost = 0.0
    e_time = None
    e_dir = 0
    trades = []
    orphans = 0

    def record(exit_time):
        trades.append(dict(
            entry_time=e_time, exit_time=exit_time,
            direction="long" if e_dir > 0 else "short",
            entry_price=round(e_cost / e_qty, 2),
            exit_price=round(x_cost / x_qty, 2),
            symbol=symbol, contracts=int(round(e_qty))))

    for _, r in df.iterrows():
        sq = r["qty"] if r["side"] in ("buy", "b") else -r["qty"]
        p = r["price"]
        if abs(pos) < 1e-9:                       # flat
            if r["otype"] != "market":            # stop/limit while flat = orphan exit
                orphans += 1
                continue
            e_dir = 1 if sq > 0 else -1
            e_time = r["fill_time"]
            e_qty, e_cost = abs(sq), p * abs(sq)
            x_qty = x_cost = 0.0
            pos = sq
        elif (sq > 0) == (pos > 0):               # scale in
            e_qty += abs(sq)
            e_cost += p * abs(sq)
            pos += sq
        else:                                     # opposite -> reduce / close / flip
            old = pos
            close_q = min(abs(sq), abs(old))
            x_qty += close_q
            x_cost += p * close_q
            pos = old + sq
            remainder = abs(sq) - close_q
            if abs(pos) < 1e-9 or remainder > 1e-9:   # original leg fully closed
                record(r["fill_time"])
                e_qty = e_cost = x_qty = x_cost = 0.0
                e_dir = 0
                if remainder > 1e-9:                  # opened opposite leg with remainder
                    e_dir = 1 if sq > 0 else -1
                    e_time = r["fill_time"]
                    e_qty, e_cost = remainder, p * remainder
                    pos = (1 if sq > 0 else -1) * remainder

    out = pd.DataFrame(trades)
    out.to_csv(out_path, index=False)
    leftover = pos if abs(pos) > 1e-9 else 0
    return out, orphans, leftover


if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    if len(sys.argv) > 1:
        inp = sys.argv[1]
    else:
        inp = _default_input(script_dir)
        if inp is None:
            print(
                "ERROR: no TradingView order-history CSV found. Expected a file "
                "like paper-trading-order-history-all-....csv",
                file=sys.stderr,
            )
            sys.exit(1)

    outp = sys.argv[2] if len(sys.argv) > 2 else str(script_dir / "paper_real_trades.csv")
    sym = sys.argv[3] if len(sys.argv) > 3 else "NQ"
    try:
        t, orphans, leftover = convert(inp, outp, sym)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"round-trip trades reconstructed: {len(t)}   (skipped {orphans} orphan exit(s); leftover net {leftover})")
    if len(t):
        d = t.copy()
        d["points"] = np.where(d.direction == "long",
                               d.exit_price - d.entry_price,
                               d.entry_price - d.exit_price)
        wins = d.points[d.points > 0].sum()
        loss = abs(d.points[d.points < 0].sum())
        print(f"date range  : {pd.to_datetime(d.entry_time).min()} -> {pd.to_datetime(d.exit_time).max()}")
        print(f"long/short  : {(d.direction=='long').sum()}/{(d.direction=='short').sum()}")
        print(f"total points: {d.points.sum():+.2f}   avg/trade: {d.points.mean():+.2f}   win rate: {(d.points>0).mean()*100:.1f}%")
        print(f"PF (points) : {wins/loss:.2f}" if loss > 0 else "PF (points) : inf")
        print()
        print(d.to_string(index=False))
        print(f"\nsaved -> {outp}")
