#!/usr/bin/env python3
"""
build_market_data_store.py
==========================
Build a DuckDB-backed market data store and partitioned Parquet dataset for the
NQ watchlist + context universe.

This script fetches Yahoo history for the symbols below, applies
corporate-action adjustments for equities, stores futures roll-adjusted close
values, and writes both:
  - a DuckDB table at market_data.duckdb
  - partitioned Parquet files under parquet_store/

Default universe:
  NVDA TSLA AVGO ORCL SPY QQQ  ES=F  NQ=F  ^VIX

Usage:
  python3 build_market_data_store.py
  python3 build_market_data_store.py --symbols NQ=F ES=F SPY QQQ NVDA TSLA AVGO ORCL ^VIX
  python3 build_market_data_store.py --db market_data.duckdb --parquet-dir parquet_store --years 10
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf

DEFAULT_SYMBOLS = [
    "NVDA", "TSLA", "AVGO", "ORCL",
    "SPY", "QQQ",
    "ES=F", "NQ=F", "^VIX"
]

DEFAULT_INTERVALS = ["1d"]

INTERVAL_MAX_DAYS = {
    "1d": None,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 60,
}

PARQUET_PARTITION_COLUMNS = ["interval", "symbol", "year"]


def safe_path_symbol(symbol: str) -> str:
    return symbol.replace("^", "_").replace("=", "_").replace("/", "_").replace(" ", "_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build DuckDB + partitioned Parquet market data store.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                        help="Symbols to fetch from Yahoo.")
    parser.add_argument("--intervals", nargs="+", default=DEFAULT_INTERVALS,
                        help="Intervals to fetch. Uses Yahoo limits for intraday intervals.")
    parser.add_argument("--db", default="market_data.duckdb",
                        help="Output DuckDB database path.")
    parser.add_argument("--parquet-dir", default="parquet_store",
                        help="Root output directory for partitioned Parquet files.")
    parser.add_argument("--years", type=int, default=10,
                        help="History length in years for daily data.")
    parser.add_argument("--start-date", type=str,
                        help="Explicit start date (YYYY-MM-DD). Overrides --years.")
    parser.add_argument("--end-date", type=str,
                        help="Explicit end date (YYYY-MM-DD). Defaults to today.")
    return parser.parse_args()


def build_date_range(start_date: str | None, end_date: str | None, years: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(end_date).normalize() if end_date else pd.Timestamp(date.today())
    if start_date:
        start = pd.Timestamp(start_date).normalize()
    else:
        start = end - pd.DateOffset(years=years)
    if start >= end:
        raise ValueError("start_date must be earlier than end_date")
    return start, end


def fetch_yahoo_history(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    max_days = INTERVAL_MAX_DAYS.get(interval)
    if max_days is not None:
        actual_period = min((end - start).days, max_days)
        if (end - start).days > max_days:
            start = end - pd.Timedelta(days=max_days)
            print(f"warning: Yahoo intraday limits ~{max_days} days for {interval}; truncating start to {start.date()}")
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start.strftime("%Y-%m-%d"),
                            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                            interval=interval, auto_adjust=False, actions=True)
    except Exception as exc:
        raise RuntimeError(f"Yahoo fetch failed for {symbol} {interval}: {exc}") from exc

    if df is None or df.empty:
        raise RuntimeError(f"No data returned for {symbol} {interval}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def canonicalize_history(df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    rename = {
        "Date": "date", "Datetime": "date", "datetime": "date", "timestamp": "date",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Adj Close": "adj_close", "Volume": "volume",
        "Dividends": "dividends", "Stock Splits": "stock_splits", "Capital Gains": "capital_gains",
    }
    df = df.rename(columns=rename)

    if "date" not in df.columns:
        raise ValueError(f"History for {symbol} does not contain a date column")

    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"History for {symbol} is missing required column '{col}'")

    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]

    df["volume"] = df.get("volume", pd.Series(np.nan, index=df.index)).fillna(np.nan)
    df["dividends"] = df.get("dividends", 0.0).fillna(0.0)
    df["stock_splits"] = df.get("stock_splits", 0.0).fillna(0.0)
    df["capital_gains"] = df.get("capital_gains", 0.0).fillna(0.0)

    df = df[["date", "open", "high", "low", "close", "adj_close", "volume",
             "dividends", "stock_splits", "capital_gains"]]
    df = df.sort_values("date").reset_index(drop=True)

    df["symbol"] = symbol
    df["interval"] = interval
    df["source"] = "yahoo"
    df["year"] = df["date"].dt.year
    return df


def apply_adjustments(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    asset_type = "futures" if df["symbol"].iloc[0].endswith("=F") else ("index" if df["symbol"].iloc[0].startswith("^") else "equity")
    df["asset_type"] = asset_type

    if asset_type == "equity":
        df["adj_factor"] = np.where(df["close"] != 0, df["adj_close"] / df["close"], 1.0)
        df["adj_open"] = df["open"] * df["adj_factor"]
        df["adj_high"] = df["high"] * df["adj_factor"]
        df["adj_low"] = df["low"] * df["adj_factor"]
        df["roll_gap"] = 0.0
        df["roll_adjusted_close"] = df["adj_close"]
        df["roll_adjusted"] = False
        df["adjustment_reason"] = np.where(df["adj_factor"] != 1.0, "corporate-action", "none")
    else:
        df["adj_factor"] = np.where(df["close"] != 0, df["adj_close"] / df["close"], 1.0)
        df["adj_open"] = df["open"] * df["adj_factor"]
        df["adj_high"] = df["high"] * df["adj_factor"]
        df["adj_low"] = df["low"] * df["adj_factor"]
        df["roll_gap"] = df["adj_close"] - df["close"]
        df["roll_adjusted_close"] = df["adj_close"]
        df["roll_adjusted"] = df["roll_gap"].abs() > 1e-12
        df["adjustment_reason"] = np.where(df["roll_adjusted"], "roll-adjusted", "none")

    df["fetched_at"] = pd.Timestamp.now().floor("s")
    return df


def build_duckdb_store(df: pd.DataFrame, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.register("incoming_bars", df)
    table_exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'bars' AND table_schema = 'main'"
    ).fetchone()[0] > 0
    if not table_exists:
        con.execute("CREATE TABLE bars AS SELECT * FROM incoming_bars")
    else:
        con.execute("INSERT INTO bars SELECT * FROM incoming_bars")
    con.close()


def write_parquet_partitions(df: pd.DataFrame, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for (symbol, interval, year), group in df.groupby(["symbol", "interval", "year"], sort=False):
        partition_dir = root / f"interval={interval}" / f"symbol={safe_path_symbol(symbol)}" / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        out_path = partition_dir / "bars.parquet"
        table = pa.Table.from_pandas(group.drop(columns=["year"]), preserve_index=False)
        pq.write_table(table, out_path)


def summarize(df: pd.DataFrame) -> None:
    print("\nSummary")
    print("-------")
    print(f"symbols: {sorted(df['symbol'].unique())}")
    print(f"intervals: {sorted(df['interval'].unique())}")
    print(f"rows: {len(df)}")
    if not df.empty:
        print(f"date range: {df['date'].min().date()} -> {df['date'].max().date()}")
    print(df.groupby(["symbol", "interval"]).size().reset_index(name="rows").to_string(index=False))


def main() -> None:
    args = parse_args()
    start, end = build_date_range(args.start_date, args.end_date, args.years)
    all_rows: list[pd.DataFrame] = []

    print(f"Fetching symbols: {args.symbols}")
    print(f"Date range: {start.date()} -> {end.date()}")
    print(f"Intervals: {args.intervals}")

    for symbol in args.symbols:
        for interval in args.intervals:
            print(f"Fetching {symbol} {interval}")
            raw = fetch_yahoo_history(symbol, interval, start, end)
            bar_df = canonicalize_history(raw, symbol, interval)
            bar_df = apply_adjustments(bar_df)
            all_rows.append(bar_df)

    if not all_rows:
        raise RuntimeError("No data was fetched for the requested symbol set.")

    store_df = pd.concat(all_rows, ignore_index=True)
    build_duckdb_store(store_df, Path(args.db))
    write_parquet_partitions(store_df, Path(args.parquet_dir))
    summarize(store_df)
    print(f"\nSaved DuckDB store: {args.db}")
    print(f"Saved partitioned Parquet store under: {args.parquet_dir}")


if __name__ == "__main__":
    main()
