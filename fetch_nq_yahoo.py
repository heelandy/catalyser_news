#!/usr/bin/env python3
"""
fetch_nq_yahoo.py

Yahoo market-data downloader for the separate data-acquisition layer.

Default behavior preserves the old daily NQ=F download. For intraday reaction
studies, use the intraday preset or pass a dynamic interval/period.

Examples:
  python fetch_nq_yahoo.py
  python fetch_nq_yahoo.py --preset intraday
  python fetch_nq_yahoo.py --preset intraday-deep
  python fetch_nq_yahoo.py --ticker NQ=F --interval 15m --period 60d --out-csv NQ_15min_data.csv
  python fetch_nq_yahoo.py --ticker ES=F --interval 5m --period 30d --out-csv ES_5min_data.csv

CAVEATS:
  * NQ=F is Yahoo's continuous front-month futures stitch.
  * Yahoo limits intraday history. Common caps are about 7 days for 1m and
    about 60 days for 2m/5m/15m/30m. 60m/1h may reach farther, though
    availability can vary.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


DEFAULT_TICKER = "NQ=F"
DEFAULT_DAILY_YEARS = 10

DEFAULT_PERIOD_BY_INTERVAL = {
    "1m": "7d",
    "2m": "60d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "90m": "60d",
    "1h": "730d",
    "1d": "10y",
    "5d": "10y",
    "1wk": "10y",
    "1mo": "10y",
}


@dataclass
class DownloadJob:
    ticker: str
    interval: str
    period: str | None
    start_date: str | None
    end_date: str | None
    out_csv: str
    out_clean: str | None = None
    out_parquet: str | None = None


def safe_ticker_name(ticker: str) -> str:
    return ticker.replace("^", "_").replace("=", "_").replace("/", "_").replace(" ", "_")


def make_start_date(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(month=2, day=28, year=today.year - years)


def default_output_name(ticker: str, interval: str, period: str | None) -> str:
    period_part = period or "custom"
    return f"data/{safe_ticker_name(ticker)}_{interval}_{period_part}.csv"


def intraday_preset_output_name(ticker: str, interval: str) -> str:
    if ticker == DEFAULT_TICKER:
        label = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "60m": "60min",
            "1h": "1h",
        }.get(interval, interval)
        return f"data/NQ_{label}_data.csv"
    return f"data/{safe_ticker_name(ticker)}_{interval}_data.csv"


def default_period(interval: str) -> str:
    return DEFAULT_PERIOD_BY_INTERVAL.get(interval, "30d")


def canonicalize_yahoo_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("No data returned.")

    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if isinstance(df.index, pd.DatetimeIndex):
        df.index.name = "date"
        df = df.reset_index()

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    rename = {
        "datetime": "date",
        "timestamp": "date",
        "adj_close": "adj_close",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "date" not in df.columns:
        raise ValueError("Downloaded data does not contain a date/datetime column.")
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Downloaded data is missing required column: {col}")

    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = pd.NA

    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(None)
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    return df[["date", "open", "high", "low", "close", "adj_close", "volume"]].reset_index(drop=True)


def download_job(job: DownloadJob) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance not installed. Run: pip install yfinance pandas pyarrow")

    kwargs = {
        "tickers": job.ticker,
        "interval": job.interval,
        "auto_adjust": False,
        "progress": False,
    }
    if job.period:
        kwargs["period"] = job.period
    else:
        kwargs["start"] = job.start_date
        kwargs["end"] = job.end_date

    raw = yf.download(**kwargs)
    df = canonicalize_yahoo_frame(raw)
    if df.empty:
        raise ValueError(f"No usable rows returned for {job.ticker} {job.interval}.")
    return df


def write_outputs(job: DownloadJob, df: pd.DataFrame) -> None:
    df.to_csv(job.out_csv, index=False)
    print(f"saved {job.out_csv}")

    if job.out_clean:
        df.to_csv(job.out_clean, index=False)
        print(f"saved {job.out_clean}")

    if job.out_parquet:
        try:
            df.to_parquet(job.out_parquet, index=False)
            print(f"saved {job.out_parquet}")
        except ImportError:
            print("pyarrow/fastparquet not installed; skipped parquet output.")

    print(f"rows : {len(df)}")
    print(f"range: {df.date.min()} -> {df.date.max()}")
    print(df.head(3).to_string(index=False))
    print("...")
    print(df.tail(3).to_string(index=False))


def build_jobs(args: argparse.Namespace) -> list[DownloadJob]:
    ticker = args.ticker

    if args.preset == "intraday":
        return [
            DownloadJob(ticker=ticker, interval="1m", period="7d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "1m")),
            DownloadJob(ticker=ticker, interval="5m", period="60d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "5m")),
        ]

    if args.preset == "intraday-deep":
        return [
            DownloadJob(ticker=ticker, interval="1m", period="7d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "1m")),
            DownloadJob(ticker=ticker, interval="5m", period="60d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "5m")),
            DownloadJob(ticker=ticker, interval="15m", period="60d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "15m")),
            DownloadJob(ticker=ticker, interval="60m", period="730d", start_date=None, end_date=None, out_csv=intraday_preset_output_name(ticker, "60m")),
        ]

    if args.preset == "daily" or not any([args.interval, args.period, args.start_date, args.end_date, args.out_csv, args.out_parquet]):
        today = date.today()
        start = make_start_date(today, args.years).isoformat()
        end = (today + timedelta(days=1)).isoformat()
        return [
            DownloadJob(
                ticker=ticker,
                interval="1d",
                period=None,
                start_date=start,
                end_date=end,
                out_csv="data/NQ_F_daily.csv",
                out_clean="data/NQ_F_daily_clean.csv",
                out_parquet="data/NQ_F_daily.parquet",
            )
        ]

    interval = args.interval or "1d"
    period = args.period
    start_date = args.start_date
    end_date = args.end_date
    if not period and not start_date:
        period = default_period(interval)
    if start_date and not end_date:
        end_date = (date.today() + timedelta(days=1)).isoformat()

    return [
        DownloadJob(
            ticker=ticker,
            interval=interval,
            period=period,
            start_date=start_date,
            end_date=end_date,
            out_csv=args.out_csv or default_output_name(ticker, interval, period),
            out_parquet=args.out_parquet,
        )
    ]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download Yahoo OHLC data for NQ/ES/SPY/etc.")
    p.add_argument("--ticker", default=DEFAULT_TICKER, help="Yahoo ticker, e.g. NQ=F, ES=F, SPY")
    p.add_argument("--preset", choices=["daily", "intraday", "intraday-deep"], help="daily preserves old output; intraday downloads 1m/5m; intraday-deep adds 15m/60m")
    p.add_argument("--interval", help="Yahoo interval, e.g. 1m, 5m, 15m, 1h, 1d")
    p.add_argument("--period", help="Yahoo period, e.g. 7d, 30d, 60d, 10y")
    p.add_argument("--start-date", help="Explicit start date, YYYY-MM-DD. Alternative to --period.")
    p.add_argument("--end-date", help="Explicit end date, YYYY-MM-DD. Defaults to tomorrow when --start-date is used.")
    p.add_argument("--out-csv", help="Output CSV path for custom single download")
    p.add_argument("--out-parquet", help="Optional parquet output path for custom single download")
    p.add_argument("--years", type=int, default=DEFAULT_DAILY_YEARS, help="Years for default daily preset")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    jobs = build_jobs(args)

    for i, job in enumerate(jobs, start=1):
        print(f"\n[{i}/{len(jobs)}] Downloading {job.ticker} interval={job.interval} period={job.period or 'custom-date-range'}")
        df = download_job(job)
        write_outputs(job, df)

    print("\nDownloads complete!")


if __name__ == "__main__":
    main()
