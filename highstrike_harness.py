#!/usr/bin/env python3
"""
HIGHSTRIKE backtest / replay harness — CHUNK 1: indicator + regime + structure engine.

Ports the core of HIGHSTRIKE_V39_UNIFIED.pine to Python so it can run over raw OHLCV
bars. This is the foundation of the standing backtest harness (the #1 roadmap gap) and
the eventual ML training-set generator. Timeframe-agnostic: built/checked on 10yr daily
NQ here, repointable at 30m/5m once intraday data is added.

WHAT IS FAITHFUL TO V39:
  * ADX/DMI(14,14) and ATR(14) use Wilder smoothing (ta.rma): alpha=1/n, SMA-seeded.
  * EMA uses recursive ewm (adjust=False), matching Pine ta.ema.
  * Pivots use ta.pivothigh/low(left,right) semantics, CONFIRMED right-bars later
    (non-repainting), value = the pivot bar's high/low.
  * Pivot tracking (st_ph/pl_last/prev with the struct_tol_pct=0.10% filter), HH/HL/LH/LL,
    the st_state machine (1 up / 2 down / 3 range / 0 after CHoCH), BOS and CHoCH all
    mirror V39 lines 548-619 bar-by-bar (a loop, to match Pine's `var` semantics exactly).

KNOWN SIMPLIFICATIONS (flagged, to reconcile against Pine later):
  * Fixed pivot lookback = 5 (struct_adaptive=false path). V39 default is adaptive
    (vol-scaled per-bar window) -> match in the Python==Pine step.
  * Volume-divergence and multi-degree structure (opt-in extras) not ported in Chunk 1.

V39 DEFAULT PARAMS USED:
  trend EMA 21/50, HTF EMA 50/200, ADX 14/14, ATR 14, local ADX min 20,
  volatile ATR% 2.5, pivot lookback 5, pivot tolerance 0.10%.
"""
import sys
import os
import numpy as np
import pandas as pd

PARAMS = dict(
    ema_trend_fast=21, ema_trend_slow=50,
    ema_htf_fast=50, ema_htf_slow=200,
    adx_len=14, adx_smooth=14, atr_len=14,
    local_adx_min=20.0, local_atr_hi=2.5,
    pivot_lb=5, pivot_tol_pct=0.10,
)


# ----------------------------------------------------------------------------- indicators
def wilder_rma(arr, n):
    """Pine ta.rma: alpha=1/n, recursive, seeded with SMA(n)."""
    arr = np.asarray(arr, dtype=float)
    out = np.full(len(arr), np.nan)
    if len(arr) < n:
        return out
    out[n - 1] = np.nanmean(arr[:n])
    a = 1.0 / n
    for i in range(n, len(arr)):
        prev = out[i - 1]
        out[i] = a * arr[i] + (1 - a) * prev if not np.isnan(prev) else arr[i]
    return out


def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def dmi_adx(df, n=14, adx_n=14):
    h, l, c = df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float)
    up = np.empty(len(h)); up[0] = 0.0; up[1:] = h[1:] - h[:-1]
    dn = np.empty(len(l)); dn[0] = 0.0; dn[1:] = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    prev_c = np.empty(len(c)); prev_c[0] = c[0]; prev_c[1:] = c[:-1]
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    atr = wilder_rma(tr, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * wilder_rma(plus_dm, n) / atr
        minus_di = 100.0 * wilder_rma(minus_dm, n) / atr
        denom = plus_di + minus_di
        dx = 100.0 * np.abs(plus_di - minus_di) / np.where(denom == 0, np.nan, denom)
    adx = wilder_rma(np.nan_to_num(dx, nan=0.0), adx_n)
    return plus_di, minus_di, adx


def add_indicators(df, p=PARAMS):
    df = df.copy()
    df["ema_f"] = ema(df.close, p["ema_trend_fast"])      # trnd_f (21)
    df["ema_s"] = ema(df.close, p["ema_trend_slow"])      # trnd_s (50)
    df["ema50"] = ema(df.close, p["ema_htf_fast"])        # 50
    df["ema200"] = ema(df.close, p["ema_htf_slow"])       # 200
    tr = np.maximum.reduce([
        (df.high - df.low).to_numpy(float),
        (df.high - df.close.shift()).abs().to_numpy(float),
        (df.low - df.close.shift()).abs().to_numpy(float),
    ])
    df["atr14"] = wilder_rma(tr, p["atr_len"])
    df["atr_pct"] = np.where(df.close > 0, df.atr14 / df.close * 100.0, 0.0)
    dip, dim, adx = dmi_adx(df, p["adx_len"], p["adx_smooth"])
    df["di_plus"], df["di_minus"], df["adx"] = dip, dim, adx
    return df


# -------------------------------------------------------------------------------- regime
def add_regime(df, p=PARAMS):
    df = df.copy()
    amin, ahi = p["local_adx_min"], p["local_atr_hi"]
    # V39: local_regime = atr_pct>=hi ? 3(vol) : adx>=min ? 1(trend) : 2(range)
    df["local_regime"] = np.where(df.atr_pct >= ahi, 3,
                          np.where(df.adx >= amin, 1, 2))
    df["trend_up"] = (df.close > df.ema_s) & (df.ema_f > df.ema_s)
    df["trend_down"] = (df.close < df.ema_s) & (df.ema_f < df.ema_s)
    # regime_dir (directional): EMA50/200 stack + ADX gate -> 1/-1/0
    up = (df.adx >= amin) & (df.ema50 > df.ema200) & (df.close > df.ema50)
    dn = (df.adx >= amin) & (df.ema50 < df.ema200) & (df.close < df.ema50)
    df["regime_dir"] = np.where(up, 1, np.where(dn, -1, 0))
    return df


# ----------------------------------------------------------------------------- structure
def _pivots_confirmed(values, lb):
    """ta.pivot semantics: bar i is a pivot if strictly extreme in [i-lb, i+lb];
    returned (confirmed) at bar i+lb with the pivot bar's value. high=True -> pivot high."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    out = np.full(n, np.nan)
    for i in range(lb, n - lb):
        c = v[i]
        left = v[i - lb:i]
        right = v[i + 1:i + lb + 1]
        if c > left.max() and c > right.max():      # strict on both sides
            out[i + lb] = c                          # confirmed lb bars later
    return out


def add_structure(df, p=PARAMS):
    df = df.copy()
    lb, tol = p["pivot_lb"], p["pivot_tol_pct"]
    ph_conf = _pivots_confirmed(df.high.to_numpy(float), lb)        # pivot HIGH
    pl_conf = -_pivots_confirmed(-df.low.to_numpy(float), lb)       # pivot LOW (min)
    h, l, c = df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float)
    n = len(df)

    st_ph_last = st_ph_prev = st_pl_last = st_pl_prev = np.nan
    st_state = 0
    A = {k: np.zeros(n, dtype=int) for k in
         ["st_state", "is_hh", "is_hl", "is_lh", "is_ll", "bos_bull", "bos_bear", "choch_bull", "choch_bear"]}

    def nn(x):
        return not np.isnan(x)

    for t in range(n):
        ph, pl = ph_conf[t], pl_conf[t]
        if nn(ph):
            if np.isnan(st_ph_last) or abs(ph - st_ph_last) / st_ph_last * 100.0 >= tol:
                st_ph_prev, st_ph_last = st_ph_last, ph
        if nn(pl):
            if np.isnan(st_pl_last) or abs(pl - st_pl_last) / st_pl_last * 100.0 >= tol:
                st_pl_prev, st_pl_last = st_pl_last, pl

        is_hh = nn(st_ph_last) and nn(st_ph_prev) and st_ph_last > st_ph_prev
        is_lh = nn(st_ph_last) and nn(st_ph_prev) and st_ph_last < st_ph_prev
        is_hl = nn(st_pl_last) and nn(st_pl_prev) and st_pl_last > st_pl_prev
        is_ll = nn(st_pl_last) and nn(st_pl_prev) and st_pl_last < st_pl_prev

        st_state_prev = st_state
        if is_hh and is_hl:
            st_state = 1
        elif is_ll and is_lh:
            st_state = 2
        elif (is_hh and is_ll) or (is_hl and is_lh):
            st_state = 3
        # else: unchanged (matches Pine — no else branch)

        bos_bull = st_state == 1 and nn(st_ph_last) and t > 0 and h[t] > st_ph_last and h[t - 1] <= st_ph_last
        bos_bear = st_state == 2 and nn(st_pl_last) and t > 0 and l[t] < st_pl_last and l[t - 1] >= st_pl_last

        choch_bull = choch_bear = False
        if st_state_prev == 2 and nn(st_ph_last) and t > 0 and c[t] > st_ph_last and c[t - 1] <= st_ph_last:
            choch_bull = True; st_state = 0
        if st_state_prev == 1 and nn(st_pl_last) and t > 0 and c[t] < st_pl_last and c[t - 1] >= st_pl_last:
            choch_bear = True; st_state = 0

        A["st_state"][t] = st_state
        A["is_hh"][t], A["is_hl"][t], A["is_lh"][t], A["is_ll"][t] = is_hh, is_hl, is_lh, is_ll
        A["bos_bull"][t], A["bos_bear"][t] = bos_bull, bos_bear
        A["choch_bull"][t], A["choch_bear"][t] = choch_bull, choch_bear

    for k, v in A.items():
        df[k] = v
    df["ph_conf"], df["pl_conf"] = ph_conf, pl_conf
    return df


# ------------------------------------------------------------------------------- pipeline
def build(df, p=PARAMS):
    return add_structure(add_regime(add_indicators(df, p), p), p)


def characterize(df):
    n = len(df)
    reg = {1: "TREND", 2: "RANGE", 3: "VOLATILE"}
    st = {0: "neutral/postCHoCH", 1: "UP", 2: "DOWN", 3: "RANGE"}
    print(f"\nbars: {n} | {df.date.min().date()} -> {df.date.max().date()}")
    print("\nlocal_regime (V39 trend/range/vol):")
    for k, c in df.local_regime.value_counts().sort_index().items():
        print(f"  {reg.get(k,k):9s} {c:5d}  {c/n*100:5.1f}%")
    print("\nst_state (structure state machine):")
    for k, c in df.st_state.value_counts().sort_index().items():
        print(f"  {st.get(k,k):18s} {c:5d}  {c/n*100:5.1f}%")
    print("\nregime_dir (directional EMA50/200+ADX):")
    for k, c in df.regime_dir.value_counts().sort_index().items():
        nm = {1: "UP", -1: "DOWN", 0: "neutral"}.get(k, k)
        print(f"  {nm:8s} {c:5d}  {c/n*100:5.1f}%")
    print(f"\ntrend_up: {df.trend_up.sum()} ({df.trend_up.mean()*100:.1f}%) | "
          f"trend_down: {df.trend_down.sum()} ({df.trend_down.mean()*100:.1f}%)")
    print(f"BOS bull: {df.bos_bull.sum()} | BOS bear: {df.bos_bear.sum()} | "
          f"CHoCH bull: {df.choch_bull.sum()} | CHoCH bear: {df.choch_bear.sum()}")
    print(f"\nADX mean {df.adx.mean():.1f} | ATR% mean {df.atr_pct.mean():.2f}")


def main():
    candidates = [
        "NQ_F_daily.parquet",
        "NQ_F_daily_clean.csv",
        "NQ_F_daily.csv",
        "/mnt/user-data/outputs/NQ_F_daily.parquet",
        "/mnt/user-data/outputs/NQ_F_daily_clean.csv",
    ]
    df = None
    for c in candidates:
        if os.path.exists(c):
            try:
                if c.lower().endswith('.parquet'):
                    df = pd.read_parquet(c)
                else:
                    df = pd.read_csv(c, parse_dates=["date"])
                print(f"Loaded data from {c}")
                break
            except Exception as e:
                print(f"Failed to load {c}: {e}")
    if df is None:
        raise FileNotFoundError("No input data file found. Checked: " + ", ".join(candidates))
    # ensure there's a `date` column — accept common alternatives or a DatetimeIndex
    if "date" not in df.columns:
        alt_found = False
        for alt in ["Date", "DATE", "datetime", "Datetime", "timestamp", "time", "TIMESTAMP"]:
            if alt in df.columns:
                df["date"] = pd.to_datetime(df[alt])
                alt_found = True
                print(f"Using column {alt} as date")
                break
        if not alt_found:
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index()
                if "index" in df.columns:
                    df = df.rename(columns={"index": "date"})
                df["date"] = pd.to_datetime(df["date"])
                print("Using DatetimeIndex as date (reset index)")
            else:
                raise KeyError("No 'date' column found in data; checked common alternatives and index.")
    else:
        df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    out = build(df)
    characterize(out)
    out.to_parquet("NQ_F_daily_engine.parquet", index=False)
    print("\nsaved engine output -> NQ_F_daily_engine.parquet")
    cols = ["date", "close", "ema_s", "adx", "atr_pct", "local_regime", "regime_dir",
            "st_state", "bos_bull", "bos_bear", "choch_bull", "choch_bear"]
    print("\ntail sample:")
    print(out[cols].tail(6).to_string(index=False))


if __name__ == "__main__":
    main()
