#!/usr/bin/env python3
"""
HIGHSTRIKE Layer 1 -- Statistical Validation Engine
====================================================
Trade-list analytics. NO backtest engine required -- operates on an exported
trade log. This is the piece that answers "is the edge real or noise" using
data you already have (the 1,296 NQ 5m trades).

Modules:
  1. Contract-aware P&L reconstruction (NQ/MNQ/ES/MES)
  2. Core performance metrics (expectancy, PF, win rate, max DD)
  3. Monte Carlo bootstrap resampling (mean/median expectancy, p5/p95,
     P(maxDD > X%), max-DD distribution)
  4. Regime stratification (ADX, VIX, time-of-day, day-of-week, days-since-event)
  5. Slippage stress test (1/2/3/5 tick adverse, PF degradation curve)

Walk-forward re-optimization is a SEPARATE phase: it requires the HIGHSTRIKE
signal logic ported to Python + raw OHLCV. This module deliberately does NOT
need that -- it validates the edge that has already been generated.

Usage:
    python3 hs_validation.py --trades my_nq_trades.csv --symbol NQ --capital 50000
    python3 hs_validation.py --market-data NQ_F_daily.csv --symbol NQ --capital 50000
    python3 hs_validation.py --demo            # runs on synthetic data to prove the harness

Required CSV columns (case-insensitive, map yours to these):
    entry_time, exit_time, direction, entry_price, exit_price
Optional columns:
    symbol, contracts, adx, vix
Optional events file (--events fomc_cpi.csv) with a single column: date
"""

from __future__ import annotations
import argparse
import os
import sys
import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Instrument specs: dollars per point and tick size
# ----------------------------------------------------------------------------
INSTRUMENT_SPECS = {
    "NQ":  {"dollars_per_point": 20.0, "tick_size": 0.25},
    "MNQ": {"dollars_per_point": 2.0,  "tick_size": 0.25},
    "ES":  {"dollars_per_point": 50.0, "tick_size": 0.25},
    "MES": {"dollars_per_point": 5.0,  "tick_size": 0.25},
}

DEFAULT_STRESS_PERIODS = {
    "2020-crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-04-30")),
    "2022-bear": (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
}


# ----------------------------------------------------------------------------
# 1. Load + reconstruct P&L
# ----------------------------------------------------------------------------
def load_trades(path: str, default_symbol: str = "NQ") -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"entry_time", "exit_time", "direction", "entry_price", "exit_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Trade file missing required columns: {sorted(missing)}")

    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["direction"] = df["direction"].astype(str).str.strip().str.lower()
    if "symbol" not in df.columns:
        df["symbol"] = default_symbol
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    if "contracts" not in df.columns:
        df["contracts"] = 1
    df = df.sort_values("entry_time").reset_index(drop=True)
    return compute_pnl(df)


def load_market_data(path: str, default_symbol: str = "NQ") -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" not in df.columns:
        raise ValueError("Market data file must contain a 'date' column.")
    if "open" not in df.columns or "close" not in df.columns:
        raise ValueError("Market data file must contain 'open' and 'close' columns.")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["entry_time"] = df["date"] + pd.Timedelta(hours=9, minutes=30)
    df["exit_time"] = df["date"] + pd.Timedelta(hours=16, minutes=0)
    df["direction"] = np.where(df["close"] >= df["open"], "long", "short")
    df["entry_price"] = df["open"]
    df["exit_price"] = df["close"]
    df["symbol"] = default_symbol
    df["contracts"] = 1
    return df[["entry_time", "exit_time", "direction", "entry_price", "exit_price", "symbol", "contracts"]]


def compute_pnl(df: pd.DataFrame, adverse_ticks: float = 0.0,
                commission_per_contract: float = 0.0,
                fixed_cost_per_trade: float = 0.0) -> pd.DataFrame:
    """Reconstruct points and dollar P&L.

    adverse_ticks applies symmetric slippage to BOTH entry and exit (always
    against you). commission_per_contract and fixed_cost_per_trade model
    real execution costs.
    """
    out = df.copy()

    long_mask = out["direction"].isin(["long", "buy", "l", "1"])
    raw_points = np.where(
        long_mask,
        out["exit_price"] - out["entry_price"],
        out["entry_price"] - out["exit_price"],
    )

    dpp = out["symbol"].map(lambda s: INSTRUMENT_SPECS.get(s, INSTRUMENT_SPECS["NQ"])["dollars_per_point"])
    tick = out["symbol"].map(lambda s: INSTRUMENT_SPECS.get(s, INSTRUMENT_SPECS["NQ"])["tick_size"])

    # adverse slippage hits entry AND exit -> 2x ticks of point loss per round trip
    slip_points = 2.0 * adverse_ticks * tick
    commission_cost = out["contracts"] * commission_per_contract + fixed_cost_per_trade
    net_points = raw_points - slip_points

    out["points"] = net_points
    out["pnl"] = net_points * dpp * out["contracts"] - commission_cost
    out["hour"] = out["entry_time"].dt.hour + out["entry_time"].dt.minute / 60.0
    out["dow"] = out["entry_time"].dt.dayofweek  # 0=Mon
    out["commission_cost"] = commission_cost
    out["slippage_ticks"] = adverse_ticks
    return out


# ----------------------------------------------------------------------------
# 2. Core metrics
# ----------------------------------------------------------------------------
def equity_drawdown(pnl: np.ndarray, starting_capital: float):
    equity = starting_capital + np.cumsum(pnl)
    running_max = np.maximum.accumulate(equity)
    dd_dollars = running_max - equity
    dd_pct = np.where(running_max > 0, dd_dollars / running_max, 0.0)
    return equity, dd_dollars.max(), dd_pct.max()


def core_metrics(pnl: np.ndarray, starting_capital: float) -> dict:
    pnl = np.asarray(pnl, dtype=float)
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    pf = gross_win / gross_loss if gross_loss > 0 else np.inf
    _, max_dd_dollars, max_dd_pct = equity_drawdown(pnl, starting_capital)
    return {
        "n": n,
        "total_pnl": pnl.sum(),
        "expectancy": pnl.mean(),
        "win_rate": len(wins) / n,
        "avg_win": wins.mean() if len(wins) else 0.0,
        "avg_loss": losses.mean() if len(losses) else 0.0,
        "profit_factor": pf,
        "max_dd_dollars": max_dd_dollars,
        "max_dd_pct": max_dd_pct,
    }


# ----------------------------------------------------------------------------
# 3. Monte Carlo bootstrap
# ----------------------------------------------------------------------------
def monte_carlo(pnl: np.ndarray, starting_capital: float, n_sims: int = 10_000,
                dd_threshold_pct: float = 0.20, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    pnl = np.asarray(pnl, dtype=float)
    n = len(pnl)

    expectancies = np.empty(n_sims)
    totals = np.empty(n_sims)
    max_dds_pct = np.empty(n_sims)

    for i in range(n_sims):
        sample = rng.choice(pnl, size=n, replace=True)
        expectancies[i] = sample.mean()
        totals[i] = sample.sum()
        _, _, dd_pct = equity_drawdown(sample, starting_capital)
        max_dds_pct[i] = dd_pct

    return {
        "n_sims": n_sims,
        "exp_mean": expectancies.mean(),
        "exp_median": np.median(expectancies),
        "exp_p5": np.percentile(expectancies, 5),
        "exp_p95": np.percentile(expectancies, 95),
        "total_p5": np.percentile(totals, 5),
        "total_p95": np.percentile(totals, 95),
        "prob_negative": (totals < 0).mean(),
        "prob_dd_exceed": (max_dds_pct > dd_threshold_pct).mean(),
        "dd_threshold_pct": dd_threshold_pct,
        "dd_p50": np.percentile(max_dds_pct, 50),
        "dd_p95": np.percentile(max_dds_pct, 95),
        "dd_p99": np.percentile(max_dds_pct, 99),
    }


# ----------------------------------------------------------------------------
# 4. Regime stratification
# ----------------------------------------------------------------------------
def _bucket_stats(df: pd.DataFrame, label_col: str, starting_capital: float) -> pd.DataFrame:
    rows = []
    for label, grp in df.groupby(label_col, observed=True):
        m = core_metrics(grp["pnl"].values, starting_capital)
        rows.append({
            "bucket": label,
            "n": m["n"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "total_pnl": m["total_pnl"],
        })
    res = pd.DataFrame(rows).sort_values("expectancy", ascending=False)
    return res


def stratify(df: pd.DataFrame, starting_capital: float,
             events: pd.Series | None = None) -> dict:
    out = {}

    if "adx" in df.columns and df["adx"].notna().any():
        bins = [-np.inf, 20, 25, np.inf]
        labels = ["chop (<20)", "transitional (20-25)", "trending (>25)"]
        d = df.copy()
        d["adx_bucket"] = pd.cut(d["adx"], bins=bins, labels=labels)
        out["ADX"] = _bucket_stats(d.dropna(subset=["adx_bucket"]), "adx_bucket", starting_capital)

    if "vix" in df.columns and df["vix"].notna().any():
        bins = [-np.inf, 15, 25, np.inf]
        labels = ["calm (<15)", "normal (15-25)", "stressed (>25)"]
        d = df.copy()
        d["vix_bucket"] = pd.cut(d["vix"], bins=bins, labels=labels)
        out["VIX"] = _bucket_stats(d.dropna(subset=["vix_bucket"]), "vix_bucket", starting_capital)

    # Time of day (NY): open / mid / close
    bins = [0, 10.5, 14.0, 24]
    labels = ["open (<=10:30)", "mid (10:30-14:00)", "close (>14:00)"]
    d = df.copy()
    d["tod_bucket"] = pd.cut(d["hour"], bins=bins, labels=labels, include_lowest=True)
    out["TimeOfDay"] = _bucket_stats(d.dropna(subset=["tod_bucket"]), "tod_bucket", starting_capital)

    dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    d = df.copy()
    d["dow_label"] = d["dow"].map(dow_map)
    out["DayOfWeek"] = _bucket_stats(d, "dow_label", starting_capital)

    if events is not None and len(events) > 0:
        ev = pd.to_datetime(events).sort_values().values
        d = df.copy()
        entry_dates = d["entry_time"].values.astype("datetime64[ns]")
        days_since = []
        for t in entry_dates:
            prior = ev[ev <= t]
            if len(prior) == 0:
                days_since.append(np.nan)
            else:
                days_since.append((t - prior[-1]) / np.timedelta64(1, "D"))
        d["days_since_event"] = days_since
        bins = [-0.01, 1, 3, 7, np.inf]
        labels = ["0-1d", "2-3d", "4-7d", "8d+"]
        d["event_bucket"] = pd.cut(d["days_since_event"], bins=bins, labels=labels)
        out["DaysSinceEvent"] = _bucket_stats(d.dropna(subset=["event_bucket"]),
                                              "event_bucket", starting_capital)
    return out


# ----------------------------------------------------------------------------
# 5. Slippage stress
# ----------------------------------------------------------------------------
def slippage_stress(df: pd.DataFrame, starting_capital: float,
                    commission_per_contract: float = 0.0,
                    fixed_cost_per_trade: float = 0.0,
                    tick_levels=(0, 1, 2, 3, 5)) -> pd.DataFrame:
    base = compute_pnl(df, adverse_ticks=0,
                       commission_per_contract=commission_per_contract,
                       fixed_cost_per_trade=fixed_cost_per_trade).copy()
    base_pf = core_metrics(base["pnl"].values, starting_capital)["profit_factor"]
    rows = []
    for t in tick_levels:
        stressed = compute_pnl(df, adverse_ticks=t,
                               commission_per_contract=commission_per_contract,
                               fixed_cost_per_trade=fixed_cost_per_trade)
        m = core_metrics(stressed["pnl"].values, starting_capital)
        pf = m["profit_factor"]
        rows.append({
            "adverse_ticks": t,
            "expectancy": m["expectancy"],
            "profit_factor": pf,
            "total_pnl": m["total_pnl"],
            "pf_vs_clean_pct": (pf / base_pf - 1) * 100 if np.isfinite(base_pf) and base_pf > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def commission_sensitivity(df: pd.DataFrame, starting_capital: float,
                           fixed_cost_per_trade: float = 0.0,
                           levels=(0.0, 2.0, 4.0, 8.0)) -> pd.DataFrame:
    rows = []
    for commission in levels:
        stressed = compute_pnl(df, commission_per_contract=commission,
                               fixed_cost_per_trade=fixed_cost_per_trade)
        m = core_metrics(stressed["pnl"].values, starting_capital)
        rows.append({
            "commission_per_contract": commission,
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "total_pnl": m["total_pnl"],
        })
    return pd.DataFrame(rows)


def stress_period_metrics(df: pd.DataFrame, starting_capital: float,
                          periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    rows = []
    for name, (start, end) in periods.items():
        window = df[(df["entry_time"] >= start) & (df["exit_time"] <= end)]
        if len(window) == 0:
            rows.append({
                "period": name,
                "start": start.date(),
                "end": end.date(),
                "n": 0,
                "expectancy": np.nan,
                "profit_factor": np.nan,
                "win_rate": np.nan,
                "total_pnl": np.nan,
            })
            continue
        m = core_metrics(window["pnl"].values, starting_capital)
        rows.append({
            "period": name,
            "start": start.date(),
            "end": end.date(),
            "n": m["n"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "total_pnl": m["total_pnl"],
        })
    return pd.DataFrame(rows)


def build_walkforward_folds(df: pd.DataFrame, train_days: int,
                             test_days: int, embargo_days: int,
                             starting_capital: float,
                             min_train_trades: int = 10,
                             min_test_trades: int = 5,
                             anchor_start: pd.Timestamp | None = None,
                             anchor_end: pd.Timestamp | None = None) -> tuple[pd.DataFrame, list[dict]]:
    periods = []
    attempts: list[dict] = []
    # anchor the start/end of fold generation if requested
    first_entry = df["entry_time"].min()
    start_anchor = pd.Timestamp(anchor_start) if anchor_start is not None else first_entry
    start_anchor = max(first_entry, start_anchor)
    current_train_end = start_anchor + pd.Timedelta(days=train_days)
    final_date = df["exit_time"].max()
    if anchor_end is not None:
        final_date = min(final_date, pd.Timestamp(anchor_end))

    while current_train_end + pd.Timedelta(days=embargo_days + test_days) <= final_date:
        test_start = current_train_end + pd.Timedelta(days=embargo_days)
        test_end = test_start + pd.Timedelta(days=test_days)

        train_window = df[df["exit_time"] <= current_train_end]
        test_window = df[(df["entry_time"] >= test_start) & (df["exit_time"] <= test_end)]
        attempts.append({
            "train_end": current_train_end.date(),
            "test_start": test_start.date(),
            "test_end": test_end.date(),
            "train_n": len(train_window),
            "test_n": len(test_window),
        })

        if len(train_window) >= min_train_trades and len(test_window) >= min_test_trades:
            train_metrics = core_metrics(train_window["pnl"].values, starting_capital)
            test_metrics = core_metrics(test_window["pnl"].values, starting_capital)
            periods.append({
                "fold": len(periods) + 1,
                "train_start": train_window["entry_time"].min().date() if len(train_window) else None,
                "train_end": current_train_end.date(),
                "test_start": test_start.date(),
                "test_end": test_end.date(),
                "train_n": train_metrics["n"],
                "test_n": test_metrics["n"],
                "train_pf": train_metrics["profit_factor"],
                "test_pf": test_metrics["profit_factor"],
                "test_expectancy": test_metrics["expectancy"],
                "test_win_rate": test_metrics["win_rate"],
                "test_total_pnl": test_metrics["total_pnl"],
                "oos_pf_ratio": test_metrics["profit_factor"] / train_metrics["profit_factor"] if train_metrics["profit_factor"] > 0 else np.nan,
            })
        current_train_end = test_end
    return pd.DataFrame(periods), attempts


def walkforward_report(df: pd.DataFrame, starting_capital: float,
                       train_days: int, test_days: int, embargo_days: int,
                       output_path: str | None = None,
                       anchor_start: pd.Timestamp | None = None,
                       anchor_end: pd.Timestamp | None = None) -> pd.DataFrame:
    folds, attempts = build_walkforward_folds(df, train_days, test_days, embargo_days, starting_capital,
                                             anchor_start=anchor_start, anchor_end=anchor_end)
    print("\n--- WALK-FORWARD OUT-OF-SAMPLE METRICS ---")
    if folds.empty:
        first_entry = df["entry_time"].min()
        last_exit = df["exit_time"].max()
        required_end = first_entry + pd.Timedelta(days=train_days + embargo_days + test_days)
        print("  Not enough data to generate walk-forward folds with the requested parameters.")
        print(f"  Data range available  : {first_entry.date()} -> {last_exit.date()}")
        print(f"  Required history through: {required_end.date()}")
        if attempts:
            print("  Attempted fold windows and counts:")
            for a in attempts[:5]:
                print(f"    train_end={a['train_end']} test={a['test_start']}..{a['test_end']} "
                      f"train_n={a['train_n']} test_n={a['test_n']}")
            if len(attempts) > 5:
                print(f"    ... plus {len(attempts)-5} more attempted windows")
            first_gap = next((a for a in attempts if a["train_n"] < 10 or a["test_n"] < 5), None)
            if first_gap is not None:
                print("  First insufficient window:")
                print(f"    train_end={first_gap['train_end']} test={first_gap['test_start']}..{first_gap['test_end']} "
                      f"train_n={first_gap['train_n']} test_n={first_gap['test_n']}")
        print("  Reduce --train-days/--test-days/--embargo-days or provide longer history.")
        return folds
    disp = folds.copy()
    disp["train_pf"] = disp["train_pf"].map(lambda x: "inf" if np.isinf(x) else f"{x:.2f}")
    disp["test_pf"] = disp["test_pf"].map(lambda x: "inf" if np.isinf(x) else f"{x:.2f}")
    disp["test_expectancy"] = disp["test_expectancy"].map(lambda x: f"${x:,.2f}" if pd.notna(x) else "nan")
    disp["test_win_rate"] = disp["test_win_rate"].map(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "nan")
    disp["test_total_pnl"] = disp["test_total_pnl"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "nan")
    disp["oos_pf_ratio"] = disp["oos_pf_ratio"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "nan")
    print(disp[["fold", "train_start", "train_end", "test_start", "test_end",
               "train_n", "test_n", "train_pf", "test_pf", "oos_pf_ratio",
               "test_expectancy", "test_win_rate", "test_total_pnl"]].to_string(index=False))
    if output_path:
        folds.to_csv(output_path, index=False)
        print(f"\n  Walk-forward fold results saved to: {output_path}")
    overall_test = pd.concat([
        df[(df["entry_time"] >= pd.Timestamp(row["test_start"])) &
           (df["exit_time"] <= pd.Timestamp(row["test_end"]))]
        for _, row in folds.iterrows()], ignore_index=True)
    if len(overall_test):
        overall = core_metrics(overall_test["pnl"].values, starting_capital)
        print(f"\n  Aggregated OOS test trades: {overall['n']}  PF: {overall['profit_factor']:.2f}  Expectancy: ${overall['expectancy']:.2f}")
    return folds


def load_stress_periods_from_csv(path: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    df = pd.read_csv(path)
    cols = [c.strip().lower() for c in df.columns]
    if "period" not in cols or "start" not in cols or "end" not in cols:
        raise ValueError("Stress periods CSV must contain columns: period, start, end")
    df.columns = cols
    periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for _, row in df.iterrows():
        if pd.isna(row["period"]) or pd.isna(row["start"]) or pd.isna(row["end"]):
            continue
        periods[str(row["period"]).strip()] = (
            pd.Timestamp(str(row["start"]).strip()),
            pd.Timestamp(str(row["end"]).strip()),
        )
    return periods


def parse_stress_periods(arg: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    if os.path.exists(arg):
        return load_stress_periods_from_csv(arg)
    periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for part in arg.split(";"):
        name, dates = part.split("=", 1)
        start_str, end_str = dates.split(":", 1)
        periods[name.strip()] = (pd.Timestamp(start_str.strip()), pd.Timestamp(end_str.strip()))
    return periods


def _fmt(x, money=True):
    if isinstance(x, float) and np.isinf(x):
        return "inf"
    return f"${x:,.2f}" if money else f"{x:.3f}"


def report(df: pd.DataFrame, starting_capital: float, n_sims: int,
           dd_threshold: float, events: pd.Series | None,
           commission_per_contract: float = 0.0,
           fixed_cost_per_trade: float = 0.0):
    line = "=" * 70
    print(line)
    print("HIGHSTRIKE LAYER 1 -- STATISTICAL VALIDATION")
    print(line)
    print(f"Trades: {len(df)}   Symbols: {sorted(df['symbol'].unique())}   "
          f"Starting capital: ${starting_capital:,.0f}")
    print(f"Window: {df['entry_time'].min()} -> {df['exit_time'].max()}")

    # Core
    m = core_metrics(df["pnl"].values, starting_capital)
    print("\n--- CORE METRICS (in-sample, clean fills) ---")
    print(f"  Total P&L      : {_fmt(m['total_pnl'])}")
    print(f"  Expectancy/tr  : {_fmt(m['expectancy'])}")
    print(f"  Win rate       : {m['win_rate']*100:.1f}%")
    print(f"  Avg win/loss   : {_fmt(m['avg_win'])} / {_fmt(m['avg_loss'])}")
    print(f"  Profit factor  : {_fmt(m['profit_factor'], money=False)}")
    print(f"  Max drawdown   : {_fmt(m['max_dd_dollars'])} ({m['max_dd_pct']*100:.1f}%)")
    if np.isfinite(m["profit_factor"]) and m["profit_factor"] >= 4.0:
        print("  [!] PF >= 4.0 -- curve-fit warning. Treat as suspect until walk-forward confirms.")

    # Monte Carlo
    mc = monte_carlo(df["pnl"].values, starting_capital, n_sims=n_sims,
                     dd_threshold_pct=dd_threshold)
    print(f"\n--- MONTE CARLO BOOTSTRAP ({mc['n_sims']:,} resamples) ---")
    print(f"  Expectancy mean   : {_fmt(mc['exp_mean'])}   median: {_fmt(mc['exp_median'])}")
    print(f"  Expectancy 90% CI : [{_fmt(mc['exp_p5'])} , {_fmt(mc['exp_p95'])}]")
    print(f"  Total P&L 90% CI  : [{_fmt(mc['total_p5'])} , {_fmt(mc['total_p95'])}]")
    print(f"  P(total < 0)      : {mc['prob_negative']*100:.2f}%")
    print(f"  P(maxDD > {int(mc['dd_threshold_pct']*100)}%)    : {mc['prob_dd_exceed']*100:.2f}%")
    print(f"  MaxDD p50/p95/p99 : {mc['dd_p50']*100:.1f}% / {mc['dd_p95']*100:.1f}% / {mc['dd_p99']*100:.1f}%")
    if mc["exp_p5"] <= 0:
        print("  [!] Lower CI bound <= 0 -- edge not statistically distinguishable from noise.")

    # Stratification
    print("\n--- REGIME STRATIFICATION (expectancy per bucket) ---")
    strat = stratify(df, starting_capital, events=events)
    for name, tbl in strat.items():
        print(f"\n  [{name}]")
        disp = tbl.copy()
        disp["expectancy"] = disp["expectancy"].map(lambda v: f"${v:,.2f}")
        disp["profit_factor"] = disp["profit_factor"].map(lambda v: "inf" if np.isinf(v) else f"{v:.2f}")
        disp["win_rate"] = disp["win_rate"].map(lambda v: f"{v*100:.1f}%")
        disp["total_pnl"] = disp["total_pnl"].map(lambda v: f"${v:,.0f}")
        print(disp.to_string(index=False))

    # Slippage
    print("\n--- SLIPPAGE STRESS (adverse ticks on entry+exit) ---")
    ss = slippage_stress(df, starting_capital,
                         commission_per_contract=commission_per_contract,
                         fixed_cost_per_trade=fixed_cost_per_trade)
    disp = ss.copy()
    disp["expectancy"] = disp["expectancy"].map(lambda v: f"${v:,.2f}")
    disp["profit_factor"] = disp["profit_factor"].map(lambda v: "inf" if np.isinf(v) else f"{v:.2f}")
    disp["total_pnl"] = disp["total_pnl"].map(lambda v: f"${v:,.0f}")
    disp["pf_vs_clean_pct"] = disp["pf_vs_clean_pct"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "--")
    print(disp.to_string(index=False))
    print("\n  Rule of thumb: NQ liquid hours 1-2 ticks; news/fast 5-10. If PF at")
    print("  2 ticks < 1.3, the paper edge likely does not survive live execution.")
    print(line)


# ----------------------------------------------------------------------------
# Synthetic data generator (proves the harness; replace with your export)
# ----------------------------------------------------------------------------
def make_demo(n: int = 1296, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2021-01-04 09:30:00")
    # entries on weekdays during RTH, ~5 per day
    times = []
    d = start
    while len(times) < n:
        if d.dayofweek < 5:
            for _ in range(rng.integers(2, 7)):
                h = rng.uniform(9.75, 15.5)
                times.append(d.normalize() + pd.Timedelta(hours=h))
        d += pd.Timedelta(days=1)
    times = sorted(times[:n])

    adx = rng.uniform(10, 40, n)
    vix = rng.uniform(11, 35, n)
    # synthetic edge that CONCENTRATES in trending + open (so stratification shows something)
    base_points = rng.normal(2.0, 18.0, n)
    edge = np.where(adx > 25, 6.0, -1.0) + np.where(np.array([t.hour + t.minute/60 for t in times]) <= 10.5, 4.0, 0.0)
    points = base_points + edge

    entry_price = 13000 + np.cumsum(rng.normal(0, 5, n))
    direction = rng.choice(["long", "short"], n, p=[0.6, 0.4])
    exit_price = np.where(direction == "long", entry_price + points, entry_price - points)

    return pd.DataFrame({
        "entry_time": times,
        "exit_time": [t + pd.Timedelta(minutes=int(rng.integers(5, 45))) for t in times],
        "direction": direction,
        "entry_price": entry_price.round(2),
        "exit_price": exit_price.round(2),
        "symbol": "NQ",
        "contracts": 1,
        "adx": adx.round(1),
        "vix": vix.round(1),
    })


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="HIGHSTRIKE Layer 1 statistical validation")
    ap.add_argument("--trades", help="CSV of trades")
    ap.add_argument("--symbol", default="NQ", help="default symbol if column absent")
    ap.add_argument("--capital", type=float, default=50_000, help="starting capital for DD%%")
    ap.add_argument("--sims", type=int, default=10_000, help="Monte Carlo resamples")
    ap.add_argument("--dd", type=float, default=0.20, help="DD threshold (fraction) for P(maxDD>X)")
    ap.add_argument("--events", help="optional CSV with a 'date' column (FOMC/CPI)")
    ap.add_argument("--demo", action="store_true", help="run on synthetic data")
    ap.add_argument("--market-data", help="optional daily CSV market data path to derive proxy trades")
    ap.add_argument("--walkforward", action="store_true", help="run purged/embargoed walk-forward evaluation")
    ap.add_argument("--walkforward-output", help="optional CSV path to export walk-forward fold metrics")
    ap.add_argument("--train-days", type=int, default=180, help="walk-forward training window in calendar days")
    ap.add_argument("--test-days", type=int, default=90, help="walk-forward test window in calendar days")
    ap.add_argument("--embargo-days", type=int, default=5, help="embargo gap between train and test windows")
    ap.add_argument("--walkforward-start", help="optional ISO date to anchor walk-forward start (e.g. 2020-01-01)")
    ap.add_argument("--walkforward-end", help="optional ISO date to anchor walk-forward end (e.g. 2021-12-31)")
    ap.add_argument("--cost-per-contract", type=float, default=0.0, help="commission cost per contract")
    ap.add_argument("--cost-per-trade", type=float, default=0.0, help="fixed commission cost per trade")
    ap.add_argument("--stress-periods", default="default",
                    help="Stress periods in name=start:end;... format, or 'default' to use 2020-crash and 2022-bear")
    ap.add_argument("--stress-periods-file", help="CSV path with stress periods: period,start,end")
    ap.add_argument("--stress-output", help="optional CSV path to export stress period metrics")
    args = ap.parse_args()

    if args.demo:
        df = compute_pnl(make_demo(), commission_per_contract=args.cost_per_contract,
                         fixed_cost_per_trade=args.cost_per_trade)
        print(">> DEMO MODE: synthetic 1,296-trade NQ set (replace with your export)\n")
    elif args.trades:
        df = load_trades(args.trades, default_symbol=args.symbol)
        df = compute_pnl(df, commission_per_contract=args.cost_per_contract,
                         fixed_cost_per_trade=args.cost_per_trade)
    elif args.market_data:
        df = load_market_data(args.market_data, default_symbol=args.symbol)
        df = compute_pnl(df, commission_per_contract=args.cost_per_contract,
                         fixed_cost_per_trade=args.cost_per_trade)
        print(f">> MARKET DATA MODE: derived {len(df)} proxy trades from {args.market_data}\n")
    else:
        ap.error("provide --trades FILE, --market-data FILE, or --demo")

    events = None
    if args.events:
        ev = pd.read_csv(args.events)
        ev.columns = [c.lower() for c in ev.columns]
        events = pd.to_datetime(ev["date"])

    report(df, args.capital, args.sims, args.dd, events,
           commission_per_contract=args.cost_per_contract,
           fixed_cost_per_trade=args.cost_per_trade)

    stress_periods = None
    if args.stress_periods_file:
        stress_periods = load_stress_periods_from_csv(args.stress_periods_file)
    elif args.stress_periods and args.stress_periods.strip().lower() != "none":
        if args.stress_periods.strip().lower() == "default":
            stress_periods = DEFAULT_STRESS_PERIODS
        else:
            stress_periods = parse_stress_periods(args.stress_periods)
    if stress_periods:
        stress_df = stress_period_metrics(df, args.capital, stress_periods)
        print("\n--- STRESS PERIOD METRICS ---")
        disp = stress_df.copy()
        disp["expectancy"] = disp["expectancy"].map(lambda v: f"${v:,.2f}" if pd.notna(v) else "nan")
        disp["profit_factor"] = disp["profit_factor"].map(lambda v: "inf" if np.isinf(v) else (f"{v:.2f}" if pd.notna(v) else "nan"))
        disp["win_rate"] = disp["win_rate"].map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "nan")
        disp["total_pnl"] = disp["total_pnl"].map(lambda v: f"${v:,.0f}" if pd.notna(v) else "nan")
        print(disp.to_string(index=False))
        if args.stress_output:
            stress_df.to_csv(args.stress_output, index=False)
            print(f"\n  Stress period metrics saved to: {args.stress_output}")

    if args.walkforward:
        wf_start = pd.Timestamp(args.walkforward_start) if args.walkforward_start else None
        wf_end = pd.Timestamp(args.walkforward_end) if args.walkforward_end else None
        walkforward_report(df, args.capital, args.train_days, args.test_days,
                           args.embargo_days, output_path=args.walkforward_output,
                           anchor_start=wf_start, anchor_end=wf_end)

    if args.cost_per_contract or args.cost_per_trade:
        print("\n--- COMMISSION SENSITIVITY ---")
        comm_df = commission_sensitivity(df, args.capital,
                                        fixed_cost_per_trade=args.cost_per_trade)
        disp = comm_df.copy()
        disp["expectancy"] = disp["expectancy"].map(lambda v: f"${v:,.2f}" if pd.notna(v) else "nan")
        disp["profit_factor"] = disp["profit_factor"].map(lambda v: "inf" if np.isinf(v) else (f"{v:.2f}" if pd.notna(v) else "nan"))
        disp["total_pnl"] = disp["total_pnl"].map(lambda v: f"${v:,.0f}" if pd.notna(v) else "nan")
        print(disp.to_string(index=False))


if __name__ == "__main__":
    main()
