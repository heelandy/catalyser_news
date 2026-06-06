#!/usr/bin/env python3
"""
journal_reconstruct.py
======================
Reconstruct round-trip trades with CORRECT direction by combining two
TradingView/Tradovate paper exports:

  --orders   order-history CSV  (precise fill prices, times, Order IDs)
  --journal  trading-journal CSV (ground-truth direction: buy/sell intent + SL/TP)

Why both: the order-history alone cannot tell an entry from an exit -- a
"Buy Stop" is both a breakout long ENTRY and a short's stop-loss EXIT. The
journal disambiguates: it logs "place order to buy/sell N units" (entry side)
and "with SL X and TP Y" (SL<TP => long, SL>TP => short). Order IDs join the
two files.

Method:
  1. Walk the journal oldest->newest. The first order PLACED after a
     "place order to buy/sell" line is the ENTRY; tag its direction.
  2. Every other executed order is an EXIT (the bracket SL/TP that filled).
  3. Pair entries->exits FIFO per symbol. Pull fill price/time from the
     order-history by Order ID (authoritative), falling back to journal price.
  4. Report coverage honestly: orphan exits (entry not in journal) and still-
     open entries are flagged, not silently guessed.

    python3 journal_reconstruct.py --orders OrderHistory.csv \
            --journal Journal.csv --out nq_trades.csv
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import deque, defaultdict
import pandas as pd

MONTH_CODE = re.compile(r"([FGHJKMNQUVXZ]\d{1,2})$")

RE_INTENT = re.compile(
    r"place\s+(?:a\s+)?(?:market|limit|stop)\s+order\s+to\s+(buy|sell)\s+(\d+)\s+units?"
    r"\s+of\s+symbol\s+(\S+)"
    r"(?:.*?with\s+SL\s+([\d.]+)\s+and\s+TP\s+([\d.]+))?",
    re.IGNORECASE)
RE_PLACED = re.compile(r"Order\s+(\d+)\s+successfully\s+placed", re.IGNORECASE)
RE_EXEC = re.compile(
    r"Order\s+(\d+)\s+for\s+symbol\s+(\S+)\s+has\s+been\s+executed\s+at\s+price"
    r"\s+([\d.]+)\s+for\s+(\d+)\s+units", re.IGNORECASE)


def normalize_symbol(raw: str) -> str:
    s = str(raw).upper().strip().split(":")[-1].lstrip("/")
    s = re.sub(r"\d+!$", "", s)      # NQ1! -> NQ
    s = s.rstrip("!")
    s = MONTH_CODE.sub("", s)        # NQM6 -> NQ
    return s


def load_orders(path: str) -> dict:
    """order_id -> {fill_price, time, qty, symbol} for FILLED orders."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    need = {"order id", "status", "fill price"}
    missing = need - set(df.columns)
    if missing:
        sys.exit(f"order-history missing columns {sorted(missing)}; saw {list(df.columns)}")
    df = df[df["status"].astype(str).str.strip().str.lower() == "filled"]
    tcol = "closing time" if "closing time" in df.columns else (
        "placing time" if "placing time" in df.columns else None)
    out = {}
    for _, r in df.iterrows():
        oid = str(r["order id"]).strip()
        out[oid] = {
            "price": float(r["fill price"]),
            "time": pd.to_datetime(r[tcol]) if tcol else pd.NaT,
            "qty": float(r.get("quantity", 1)),
            "symbol": normalize_symbol(r.get("symbol", "NQ")),
        }
    return out


def parse_journal(path: str):
    """Return executions (ordered oldest->newest) and entry-direction map."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "text" not in df.columns or "time" not in df.columns:
        sys.exit(f"journal needs Time,Text columns; saw {list(df.columns)}")
    # Export is newest-first; reverse to true event order (preserves intra-second order)
    rows = list(df.iloc[::-1].itertuples(index=False))

    entry_dir = {}          # order_id -> 'long'/'short'
    executions = []         # (time, order_id, price, qty, symbol) oldest->newest
    pending = None          # direction awaiting its first PLACED order

    for row in rows:
        t, text = row.time, str(row.text)

        m = RE_INTENT.search(text)
        if m:
            side, _qty, _sym, sl, tp = m.groups()
            d = "long" if side.lower() == "buy" else "short"
            if sl and tp:                       # SL/TP confirm/override
                d = "long" if float(sl) < float(tp) else "short"
            pending = d
            continue

        m = RE_PLACED.search(text)
        if m and pending is not None:
            entry_dir[m.group(1)] = pending     # first placed after intent = entry
            pending = None
            continue

        m = RE_EXEC.search(text)
        if m:
            oid, sym, price, qty = m.groups()
            executions.append((pd.to_datetime(t), oid, float(price),
                               float(qty), normalize_symbol(sym)))

    return executions, entry_dir


def reconstruct(executions, entry_dir, orders) -> tuple[pd.DataFrame, dict]:
    trades = []
    open_lots = defaultdict(deque)   # symbol -> deque of open entries
    orphan_exits = 0

    for t, oid, jprice, jqty, sym in executions:
        info = orders.get(oid, {})
        price = info.get("price", jprice)
        time = info.get("time", t) or t
        qty = info.get("qty", jqty)

        if oid in entry_dir:                       # ENTRY
            open_lots[sym].append({"dir": entry_dir[oid], "price": price,
                                   "time": time, "qty": qty})
        else:                                      # EXIT
            book = open_lots[sym]
            if not book:
                orphan_exits += 1                  # entry not covered by journal
                continue
            remaining = qty
            while remaining > 1e-9 and book:
                lot = book[0]
                matched = min(lot["qty"], remaining)
                trades.append({
                    "entry_time": lot["time"], "exit_time": time,
                    "direction": lot["dir"],
                    "entry_price": lot["price"], "exit_price": price,
                    "symbol": sym,
                    "contracts": int(matched) if float(matched).is_integer() else matched,
                })
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 1e-9:
                    book.popleft()

    open_left = sum(len(b) for b in open_lots.values())
    cov = {"trades": len(trades), "orphan_exits": orphan_exits,
           "open_unclosed": open_left, "executions": len(executions)}
    res = pd.DataFrame(trades)
    if not res.empty:
        res = res.sort_values("entry_time").reset_index(drop=True)
    return res, cov


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--out", default="nq_trades.csv")
    a = ap.parse_args()

    orders = load_orders(a.orders)
    executions, entry_dir = parse_journal(a.journal)
    print(f"order-history: {len(orders)} filled orders")
    print(f"journal: {len(executions)} executions, {len(entry_dir)} entries identified")

    trades, cov = reconstruct(executions, entry_dir, orders)
    if trades.empty:
        sys.exit("No round trips reconstructed -- journal likely doesn't cover "
                 "the entry intents for these fills. Export a journal spanning "
                 "the same period as the orders.")

    trades.to_csv(a.out, index=False)
    nlong = (trades.direction == "long").sum()
    nshort = (trades.direction == "short").sum()
    print(f"\nReconstructed {len(trades)} round trips ({nlong} long, {nshort} short) -> {a.out}")
    print(f"Coverage: {cov['orphan_exits']} orphan exit(s) [entry not in journal], "
          f"{cov['open_unclosed']} still-open entry(ies).")
    if cov["orphan_exits"] or cov["open_unclosed"]:
        print("  -> journal does not fully span the order history; uncovered "
              "fills were skipped, NOT guessed.")
    print("\nAll trades:")
    print(trades.to_string(index=False))
    print(f"\nNext: python3 hs_validation.py --trades {a.out} --symbol NQ --capital 50000")
