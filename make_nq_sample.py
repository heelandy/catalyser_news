#!/usr/bin/env python3
"""
make_nq_sample.py -- Synthetic NQ trade generator (CALIBRATED FICTION)
======================================================================
Produces a trade list shaped like J's documented HIGHSTRIKE scalp profile so
hs_validation.py can be exercised end-to-end before real Tradovate Fills exist.

Calibration anchors (from system docs, NOT measured edge):
  - NQ: $20/pt, 0.25 tick
  - Avg win ~ $400-500  -> ~20-25 pts
  - Trend-only (RANGE gated out) -> ADX skewed > 20
  - RTH futures windows: 09:30-10:00, 10:30-11:30, 13:30-14:30, 14:30-15:30
  - <=4 trades/day, mostly with-trend longs
  - Edge intentionally concentrated in trending + open session so the
    stratification module has signal to surface.

THE NUMBERS ARE INVENTED. This validates the code path, not your edge.

    python3 make_nq_sample.py --n 400 --out nq_sample_trades.csv
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

WINDOWS = [(9.5, 10.0), (10.5, 11.5), (13.5, 14.5), (14.5, 15.5)]


def gen(n: int, seed: int, start: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    day = pd.Timestamp(start)
    vix = 16.0
    price = 20000.0

    while len(rows) < n:
        if day.dayofweek < 5:  # weekday
            vix = float(np.clip(vix + rng.normal(0, 1.4), 11, 34))  # slow VIX walk
            n_trades = min(int(rng.poisson(2.6)), 4)  # <=4/day rule
            wins_windows = rng.choice(len(WINDOWS), size=n_trades, replace=True)
            for wi in wins_windows:
                if len(rows) >= n:
                    break
                lo, hi = WINDOWS[wi]
                h = rng.uniform(lo, hi)
                ts = day.normalize() + pd.Timedelta(hours=h)

                # ADX skewed high (RANGE is gated out of the system)
                adx = float(np.clip(rng.normal(26, 7), 12, 48))
                is_open = h <= 10.5

                # win probability: edge concentrates in trend + open
                p = 0.50
                p += 0.13 if adx > 25 else (0.03 if adx > 20 else -0.06)
                p += 0.06 if is_open else 0.0
                p += 0.03 if vix > 22 else 0.0
                p = float(np.clip(p, 0.30, 0.80))

                win = rng.random() < p
                if win:
                    pts = abs(rng.normal(22, 8))            # ~ $440 avg win
                else:
                    pts = -min(abs(rng.normal(16, 7)), 35)  # mental-stop capped

                direction = "long" if rng.random() < 0.65 else "short"
                price = float(np.clip(price + rng.normal(0, 12), 17500, 22500))
                entry = round(price, 2)
                exit_ = round(entry + pts if direction == "long" else entry - pts, 2)
                contracts = int(rng.choice([1, 1, 1, 2]))
                grade = rng.choice(["B7", "B8", "A9", "A10"], p=[0.35, 0.30, 0.22, 0.13])

                rows.append({
                    "entry_time": ts,
                    "exit_time": ts + pd.Timedelta(minutes=int(rng.integers(4, 35))),
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": exit_,
                    "symbol": "NQ",
                    "contracts": contracts,
                    "adx": round(adx, 1),
                    "vix": round(vix, 1),
                    "grade": grade,
                })
        day += pd.Timedelta(days=1)

    return pd.DataFrame(rows[:n]).sort_values("entry_time").reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--start", default="2025-11-03")
    ap.add_argument("--out", default="nq_sample_trades.csv")
    a = ap.parse_args()
    df = gen(a.n, a.seed, a.start)
    df.to_csv(a.out, index=False)
    print(f"Wrote {len(df)} synthetic NQ trades -> {a.out}")
    print(f"Range: {df['entry_time'].min()} .. {df['entry_time'].max()}")
    print("\nFirst 6 rows:")
    print(df.head(6).to_string(index=False))
