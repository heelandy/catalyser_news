#!/usr/bin/env python3
"""
macro_reaction_study.py

Historical macro-release reaction learner.

This module stays separate from catalyser_news.py:
  - catalyser_news.py watches/fetches live catalysts and scores the current release.
  - macro_reaction_study.py studies past releases against market OHLC data.

It can:
  1. Fetch historical TradingView economic-calendar rows.
  2. Align release times to NQ/ES/SPY OHLC bars.
  3. Measure where price went after the release.
  4. Build reaction profiles by event family and surprise direction.
  5. Calibrate a live macro_releases.csv using those historical profiles.

Daily bars are supported now. Intraday bars are supported when the market-data
file has multiple timestamps per day.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests


DEFAULT_WINDOWS_MINUTES = [5, 15, 30, 60, 390]
DEFAULT_CALENDAR_URL = "https://www.tradingview.com/economic-calendar/?countries=us"


def parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso_utc_z(value) -> str:
    dt = parse_dt(value).replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_empty(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.lower() in {"none", "null", "nan", "n/a", "-"}:
            return None
        return v
    return value


def parse_economic_value(value):
    value = clean_empty(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    import re

    text = str(value).strip().replace(",", "")
    sign = -1.0 if text.startswith("(") and text.endswith(")") else 1.0
    text = text.strip("()")
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        return None
    number = float(match.group(0)) * sign
    suffix = text[match.end():].strip().upper()
    if suffix.startswith("K"):
        number *= 1_000
    elif suffix.startswith("M"):
        number *= 1_000_000
    elif suffix.startswith("B"):
        number *= 1_000_000_000
    elif suffix.startswith("T"):
        number *= 1_000_000_000_000
    return number


def apply_value_scale(value, scale):
    value = parse_economic_value(value)
    if value is None:
        return None
    scale = str(scale or "").strip().upper()
    if scale == "K":
        return value * 1_000
    if scale == "M":
        return value * 1_000_000
    if scale == "B":
        return value * 1_000_000_000
    if scale == "T":
        return value * 1_000_000_000_000
    return value


def release_numeric_value(value, scale):
    value = clean_empty(value)
    if value is None:
        return None
    text = str(value).strip().upper()
    scale = str(scale or "").strip().upper()
    if scale and text.endswith(scale):
        return parse_economic_value(value)
    if text.endswith("%"):
        return parse_economic_value(value)
    return apply_value_scale(value, scale)


def format_release_value(value, scale="", unit=""):
    value = clean_empty(value)
    if value is None:
        return ""
    scale = str(scale or "").strip()
    unit = str(unit or "").strip()
    if unit == "%":
        return f"{value}%"
    return f"{value}{scale}"


def classify_event(title: str, category: str = "") -> str:
    text = f"{title} {category}".lower()
    if any(k in text for k in ("cpi", "ppi", "pce", "inflation", "prices", "price index")):
        return "inflation"
    if any(k in text for k in ("fomc", "fed", "rate decision", "interest rate", "dot plot")):
        return "central_bank"
    if any(k in text for k in ("payroll", "employment", "unemployment", "jobless", "claims", "jolts")):
        return "labor"
    if any(k in text for k in ("pmi", "ism", "gdp", "retail sales", "consumer confidence", "home sales")):
        return "growth"
    return "other"


def event_family(title: str, category: str = "") -> str:
    text = f"{title} {category}".lower()
    if "core cpi" in text:
        return "core_cpi"
    if "cpi" in text:
        return "cpi"
    if "ppi" in text:
        return "ppi"
    if "pce" in text:
        return "pce"
    if "non farm" in text or "nonfarm" in text or "payroll" in text:
        return "nonfarm_payrolls"
    if "unemployment" in text:
        return "unemployment_rate"
    if "jobless" in text or "claims" in text:
        return "jobless_claims"
    if "fomc" in text or "fed" in text or "interest rate" in text:
        return "fomc_rates"
    if "ism" in text or "pmi" in text:
        return "ism_pmi"
    if "gdp" in text:
        return "gdp"
    if "retail sales" in text:
        return "retail_sales"
    if "home sales" in text:
        return "home_sales"
    return classify_event(title, category)


def surprise_side(value, eps=1e-12) -> str:
    value = parse_economic_value(value)
    if value is None or abs(value) <= eps:
        return "flat"
    return "positive" if value > 0 else "negative"


def release_direction_rule(title: str, category: str = "") -> tuple[float, str, str]:
    text = f"{title} {category}".lower()

    if any(k in text for k in ("cpi", "ppi", "pce", "inflation", "prices", "price index")):
        return -1.0, "higher_is_bearish", "Higher inflation is usually bearish for NQ because it can lift yields and reduce rate-cut odds."
    if any(k in text for k in ("fomc", "interest rate", "fed funds", "rate decision", "dot plot")):
        return -1.0, "higher_is_bearish", "Higher rates or hawkish guidance are usually bearish for rate-sensitive equities."
    if any(k in text for k in ("non farm", "nonfarm", "payroll", "employment change", "employment report")):
        return -0.6, "higher_is_mixed_bearish", "Stronger payrolls can pressure NQ when the market reads them as higher-for-longer Fed policy."
    if any(k in text for k in ("unemployment", "jobless", "claims", "layoffs")):
        return -0.35, "higher_is_mixed_bearish", "Higher unemployment or claims are mixed: dovish for rates, but bearish if growth fear dominates."
    if any(k in text for k in ("pmi", "ism", "gdp", "retail sales", "industrial production", "consumer confidence", "home sales")):
        return 0.7, "higher_is_bullish", "Stronger growth data is usually risk-on unless it renews inflation or Fed pressure."
    return 0.0, "unknown", "No reliable one-number market direction rule; treat as a volatility catalyst."


def interpret_market_bias(title: str, category: str, surprise) -> dict:
    raw_side = surprise_side(surprise)
    direction, rule, note = release_direction_rule(title, category)
    sign = 1 if raw_side == "positive" else -1 if raw_side == "negative" else 0
    score = direction * sign

    if sign == 0:
        side = "market_neutral"
        label = "neutral"
    elif abs(direction) < 0.2:
        side = "market_unknown"
        label = "mixed"
    elif score > 0:
        side = "market_positive"
        label = "bullish"
    elif score < 0:
        side = "market_negative"
        label = "bearish"
    else:
        side = "market_unknown"
        label = "mixed"

    return {
        "raw_surprise_side": raw_side,
        "market_bias_side": side,
        "market_bias_label": label,
        "market_bias_score": score,
        "market_rule_direction": rule,
        "market_rule_confidence": abs(direction),
        "market_rule_note": note,
    }


def first_number(row: dict, keys: list[str]):
    for key in keys:
        if key in row:
            value = parse_economic_value(row.get(key))
            if value is not None:
                return value
    return None


def normalize_event_row(row: dict) -> dict:
    release_time = row.get("release_time") or row.get("date") or row.get("datetime") or row.get("published")
    if not release_time:
        raise ValueError("event row is missing release_time/date")

    title = row.get("title") or row.get("indicator") or row.get("event") or row.get("name") or ""
    category = row.get("category") or row.get("catalyst_category") or ""
    scale = row.get("scale") or ""
    unit = row.get("unit") or ""

    actual = row.get("actual") or row.get("Actual") or ""
    previous = row.get("previous") or row.get("Previous") or ""
    forecast = row.get("forecast") or row.get("Forecast") or row.get("TEForecast") or ""

    actual_value = first_number(row, ["actual_value", "ActualValue"])
    previous_value = first_number(row, ["previous_value", "PreviousValue"])
    forecast_value = first_number(row, ["forecast_value", "ForecastValue", "teforecast_value", "TEForecastValue"])

    if actual_value is None:
        actual_value = release_numeric_value(actual, scale)
    if previous_value is None:
        previous_value = release_numeric_value(previous, scale)
    if forecast_value is None:
        forecast_value = release_numeric_value(forecast, scale)

    if actual_value is not None and forecast_value is not None:
        surprise = actual_value - forecast_value
        surprise_basis = "actual_vs_forecast"
    elif actual_value is not None and previous_value is not None:
        surprise = actual_value - previous_value
        surprise_basis = "actual_vs_previous"
    elif forecast_value is not None and previous_value is not None:
        surprise = forecast_value - previous_value
        surprise_basis = "forecast_vs_previous"
    else:
        surprise = None
        surprise_basis = "unknown"

    family = event_family(title, category)
    catalyst_category = row.get("catalyst_category") or classify_event(title, category)
    market_bias = interpret_market_bias(title, catalyst_category, surprise)
    return {
        "release_time": parse_dt(release_time),
        "title": title,
        "event_family": family,
        "catalyst_category": catalyst_category,
        "country": row.get("country") or row.get("Country") or "",
        "source": row.get("source") or row.get("Source") or "",
        "calendar_id": row.get("calendar_id") or row.get("id") or row.get("CalendarId") or "",
        "unit": unit,
        "scale": scale,
        "previous": previous,
        "forecast": forecast,
        "actual": actual,
        "previous_value": previous_value,
        "forecast_value": forecast_value,
        "actual_value": actual_value,
        "surprise": surprise,
        "surprise_basis": surprise_basis,
        "surprise_side": market_bias["raw_surprise_side"],
        **market_bias,
    }


def fetch_tradingview_events(
    start_date: str,
    end_date: str,
    countries: str = "us",
    min_importance: int = 1,
    chunk_days: int = 30,
    rate_limit: float = 0.2,
) -> list[dict]:
    start = parse_dt(start_date)
    end = parse_dt(end_date)
    if start > end:
        raise ValueError("start-date must be before end-date")

    country_codes = [c.strip().upper() for c in countries.split(",") if c.strip()]
    all_events: list[dict] = []
    seen = set()
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=max(1, chunk_days) - 1))
        from_dt = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        to_dt = chunk_end.replace(hour=23, minute=59, second=59, microsecond=999000)
        params = {
            "minImportance": str(min_importance),
            "from": iso_utc_z(from_dt),
            "to": iso_utc_z(to_dt),
            "countries": ",".join(country_codes),
        }
        headers = {
            "accept": "application/json",
            "origin": "https://www.tradingview.com",
            "referer": DEFAULT_CALENDAR_URL,
            "user-agent": "Mozilla/5.0 (compatible; macro-reaction-study/1.0)",
        }
        r = requests.get("https://chartevents-reuters.tradingview.com/events", params=params, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            raise RuntimeError(data.get("errmsg") or "TradingView returned an error")
        for event in data.get("result") or []:
            key = event.get("id") or f"{event.get('date')}|{event.get('title')}"
            if key in seen:
                continue
            seen.add(key)
            scale = event.get("scale") or ""
            unit = event.get("unit") or ""
            event = dict(event)
            previous_raw = event.get("previous")
            forecast_raw = event.get("forecast")
            actual_raw = event.get("actual")
            event["release_time"] = event.get("date")
            event["previous"] = format_release_value(previous_raw, scale, unit)
            event["forecast"] = format_release_value(forecast_raw, scale, unit)
            event["actual"] = format_release_value(actual_raw, scale, unit)
            event["previous_value"] = apply_value_scale(previous_raw, scale)
            event["forecast_value"] = apply_value_scale(forecast_raw, scale)
            event["actual_value"] = apply_value_scale(actual_raw, scale)
            event["calendar_id"] = key
            all_events.append(event)
        cur = chunk_end + timedelta(days=1)
        if rate_limit:
            time.sleep(rate_limit)
    return all_events


def load_events_file(path: str) -> pd.DataFrame:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return pd.DataFrame([normalize_event_row(r) for r in rows])


def load_market_data(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)

    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    rename = {
        "datetime": "date",
        "timestamp": "date",
        "time": "date",
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" not in df.columns:
        raise ValueError("market data must contain date/datetime/timestamp column")
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"market data is missing required column: {col}")

    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(None)
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df


def has_intraday_bars(bars: pd.DataFrame) -> bool:
    normalized = bars["date"].dt.normalize()
    has_time = (bars["date"] != normalized).any()
    has_multiple_per_day = normalized.duplicated().any()
    return bool(has_time or has_multiple_per_day)


def market_return_pct(points, pre_price):
    if pre_price in (None, 0) or pd.isna(pre_price):
        return np.nan
    return float(points) / float(pre_price) * 100.0


def compute_daily_reactions(events: pd.DataFrame, bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    bars = bars.copy()
    bars["session_date"] = bars["date"].dt.date
    rows = []
    session_dates = list(bars["session_date"])

    for event in events.itertuples(index=False):
        release_date = event.release_time.date()
        idx = next((i for i, d in enumerate(session_dates) if d >= release_date), None)
        if idx is None or idx == 0:
            continue
        prev_bar = bars.iloc[idx - 1]
        event_bar = bars.iloc[idx]
        next_bar = bars.iloc[idx + 1] if idx + 1 < len(bars) else None
        pre = float(prev_bar.close)
        ret = float(event_bar.close) - pre
        mfe = float(event_bar.high) - pre
        mae = float(event_bar.low) - pre
        row = event._asdict()
        row.update({
            "symbol": symbol,
            "reaction_mode": "daily",
            "market_session": event_bar.session_date.isoformat(),
            "pre_price": pre,
            "event_open": float(event_bar.open),
            "event_high": float(event_bar.high),
            "event_low": float(event_bar.low),
            "event_close": float(event_bar.close),
            "gap_pts": float(event_bar.open) - pre,
            "gap_pct": market_return_pct(float(event_bar.open) - pre, pre),
            "open_to_close_pts": float(event_bar.close) - float(event_bar.open),
            "reaction_return_pts": ret,
            "reaction_return_pct": market_return_pct(ret, pre),
            "mfe_pts": mfe,
            "mfe_pct": market_return_pct(mfe, pre),
            "mae_pts": mae,
            "mae_pct": market_return_pct(mae, pre),
            "next_close_return_pts": float(next_bar.close) - pre if next_bar is not None else np.nan,
            "next_close_return_pct": market_return_pct(float(next_bar.close) - pre, pre) if next_bar is not None else np.nan,
            "window_label": "same_day_close",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def compute_intraday_reactions(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    symbol: str,
    windows_minutes: list[int],
    primary_window_minutes: int,
) -> pd.DataFrame:
    rows = []
    bars = bars.sort_values("date").reset_index(drop=True)

    for event in events.itertuples(index=False):
        rt = pd.Timestamp(event.release_time)
        prior = bars[bars["date"] <= rt]
        if prior.empty:
            continue
        pre = float(prior.iloc[-1].close)
        row = event._asdict()
        row.update({
            "symbol": symbol,
            "reaction_mode": "intraday",
            "market_session": rt.date().isoformat(),
            "pre_price": pre,
            "window_label": f"{primary_window_minutes}m",
        })

        primary_ret = np.nan
        primary_mfe = np.nan
        primary_mae = np.nan
        for minutes in windows_minutes:
            end = rt + pd.Timedelta(minutes=minutes)
            window = bars[(bars["date"] > rt) & (bars["date"] <= end)]
            if window.empty:
                row[f"return_{minutes}m_pts"] = np.nan
                row[f"return_{minutes}m_pct"] = np.nan
                row[f"mfe_{minutes}m_pts"] = np.nan
                row[f"mfe_{minutes}m_pct"] = np.nan
                row[f"mae_{minutes}m_pts"] = np.nan
                row[f"mae_{minutes}m_pct"] = np.nan
                continue
            ret = float(window.iloc[-1].close) - pre
            mfe = float(window.high.max()) - pre
            mae = float(window.low.min()) - pre
            row[f"return_{minutes}m_pts"] = ret
            row[f"return_{minutes}m_pct"] = market_return_pct(ret, pre)
            row[f"mfe_{minutes}m_pts"] = mfe
            row[f"mfe_{minutes}m_pct"] = market_return_pct(mfe, pre)
            row[f"mae_{minutes}m_pts"] = mae
            row[f"mae_{minutes}m_pct"] = market_return_pct(mae, pre)
            if minutes == primary_window_minutes:
                primary_ret = ret
                primary_mfe = mfe
                primary_mae = mae

        row["reaction_return_pts"] = primary_ret
        row["reaction_return_pct"] = market_return_pct(primary_ret, pre)
        row["mfe_pts"] = primary_mfe
        row["mfe_pct"] = market_return_pct(primary_mfe, pre)
        row["mae_pts"] = primary_mae
        row["mae_pct"] = market_return_pct(primary_mae, pre)
        rows.append(row)
    return pd.DataFrame(rows)


def compute_reactions(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    symbol: str,
    windows_minutes: list[int],
    primary_window_minutes: int,
) -> pd.DataFrame:
    events = events.dropna(subset=["release_time"]).sort_values("release_time").reset_index(drop=True)
    if has_intraday_bars(bars):
        return compute_intraday_reactions(events, bars, symbol, windows_minutes, primary_window_minutes)
    return compute_daily_reactions(events, bars, symbol)


def summarize_group(group: pd.DataFrame, move_threshold_pct: float) -> dict:
    returns = pd.to_numeric(group["reaction_return_pts"], errors="coerce")
    returns_pct = pd.to_numeric(group["reaction_return_pct"], errors="coerce")
    mfe = pd.to_numeric(group["mfe_pts"], errors="coerce")
    mae = pd.to_numeric(group["mae_pts"], errors="coerce")
    market_bias_score = pd.to_numeric(group["market_bias_score"], errors="coerce") if "market_bias_score" in group.columns else pd.Series(dtype=float)
    valid = returns.dropna()
    if valid.empty:
        return {}
    bullish_probability = float((valid > 0).mean())
    abs_move = returns_pct.abs().dropna()
    market_move_probability = float((abs_move >= move_threshold_pct).mean()) if len(abs_move) else np.nan
    return {
        "sample_size": int(len(valid)),
        "bullish_probability": bullish_probability,
        "bearish_probability": 1.0 - bullish_probability,
        "market_move_probability": market_move_probability,
        "avg_return_pts": float(valid.mean()),
        "median_return_pts": float(valid.median()),
        "avg_return_pct": float(returns_pct.mean()),
        "median_return_pct": float(returns_pct.median()),
        "avg_mfe_pts": float(mfe.mean()),
        "avg_mae_pts": float(mae.mean()),
        "avg_abs_surprise": float(pd.to_numeric(group["surprise"], errors="coerce").abs().mean()),
        "avg_market_bias_score": float(market_bias_score.mean()) if len(market_bias_score.dropna()) else np.nan,
        "window_label": group["window_label"].dropna().iloc[0] if group["window_label"].notna().any() else "",
    }


def build_profiles(reactions: pd.DataFrame, min_events: int, move_threshold_pct: float) -> pd.DataFrame:
    profile_rows = []
    group_specs = [
        ("event_family_market_bias", ["event_family", "market_bias_side"]),
        ("category_market_bias", ["catalyst_category", "market_bias_side"]),
        ("event_family_side", ["event_family", "surprise_side"]),
        ("category_side", ["catalyst_category", "surprise_side"]),
        ("event_family_all", ["event_family"]),
        ("category_all", ["catalyst_category"]),
    ]
    for group_type, keys in group_specs:
        if any(key not in reactions.columns for key in keys):
            continue
        for key_values, group in reactions.groupby(keys, dropna=False):
            stats = summarize_group(group, move_threshold_pct)
            if not stats or stats["sample_size"] < min_events:
                continue
            if not isinstance(key_values, tuple):
                key_values = (key_values,)
            row = {
                "group_type": group_type,
                "event_family": "",
                "catalyst_category": "",
                "surprise_side": "",
                "market_bias_side": "",
            }
            for key, value in zip(keys, key_values):
                row[key] = value
            row.update(stats)
            profile_rows.append(row)
    if not profile_rows:
        return pd.DataFrame(
            columns=[
                "group_type",
                "event_family",
                "catalyst_category",
                "surprise_side",
                "market_bias_side",
                "sample_size",
                "bullish_probability",
                "bearish_probability",
                "market_move_probability",
                "avg_return_pts",
                "median_return_pts",
                "avg_market_bias_score",
                "window_label",
            ]
        )
    return pd.DataFrame(profile_rows).sort_values(["group_type", "sample_size"], ascending=[True, False])


def get_row_value(row: pd.Series, key: str, default=""):
    return row[key] if key in row.index else default


def profile_candidate(profiles: pd.DataFrame, group_type: str, filters: dict[str, object]) -> pd.DataFrame:
    required = {"group_type", *filters.keys()}
    if any(col not in profiles.columns for col in required):
        return pd.DataFrame()
    mask = profiles["group_type"] == group_type
    for key, value in filters.items():
        mask &= profiles[key] == value
    return profiles[mask]


def find_profile(row: pd.Series, profiles: pd.DataFrame):
    candidates = [
        profile_candidate(
            profiles,
            "event_family_market_bias",
            {"event_family": get_row_value(row, "event_family"), "market_bias_side": get_row_value(row, "market_bias_side")},
        ),
        profile_candidate(
            profiles,
            "category_market_bias",
            {"catalyst_category": get_row_value(row, "catalyst_category"), "market_bias_side": get_row_value(row, "market_bias_side")},
        ),
        profile_candidate(
            profiles,
            "event_family_side",
            {"event_family": get_row_value(row, "event_family"), "surprise_side": get_row_value(row, "surprise_side")},
        ),
        profile_candidate(
            profiles,
            "category_side",
            {"catalyst_category": get_row_value(row, "catalyst_category"), "surprise_side": get_row_value(row, "surprise_side")},
        ),
        profile_candidate(profiles, "event_family_all", {"event_family": get_row_value(row, "event_family")}),
        profile_candidate(profiles, "category_all", {"catalyst_category": get_row_value(row, "catalyst_category")}),
    ]
    for candidate in candidates:
        if not candidate.empty:
            return candidate.sort_values("sample_size", ascending=False).iloc[0]
    return None


def calibrate_live_rows(live_path: str, profiles_path: str, out_path: str) -> None:
    raw = pd.read_csv(live_path)
    normalized = pd.DataFrame([normalize_event_row(r) for r in raw.to_dict("records")])
    profiles = pd.read_csv(profiles_path)
    out = raw.copy()

    normalized_cols = [
        "raw_surprise_side",
        "market_bias_side",
        "market_bias_label",
        "market_bias_score",
        "market_rule_direction",
        "market_rule_confidence",
        "market_rule_note",
    ]
    hist_cols = [
        "historical_group_type",
        "historical_sample_size",
        "historical_market_bias_side",
        "historical_bullish_probability",
        "historical_bearish_probability",
        "historical_market_move_probability",
        "historical_avg_return_pts",
        "historical_avg_mfe_pts",
        "historical_avg_mae_pts",
        "calibrated_bullish_probability",
        "calibrated_bearish_probability",
    ]
    for col in normalized_cols + hist_cols:
        out[col] = ""

    for idx, row in normalized.iterrows():
        for col in normalized_cols:
            if col in normalized.columns:
                out.loc[idx, col] = normalized.loc[idx, col]

        profile = find_profile(row, profiles)
        if profile is None:
            continue

        existing = parse_economic_value(raw.iloc[idx].get("bullish_probability")) if "bullish_probability" in raw.columns else None
        if existing is None:
            existing = 0.5
        hist_bull = float(profile["bullish_probability"])
        sample_size = int(profile["sample_size"])
        weight = min(0.75, sample_size / 20.0)
        calibrated = existing * (1.0 - weight) + hist_bull * weight

        out.loc[idx, "historical_group_type"] = profile["group_type"]
        out.loc[idx, "historical_sample_size"] = sample_size
        out.loc[idx, "historical_market_bias_side"] = profile["market_bias_side"] if "market_bias_side" in profile.index else ""
        out.loc[idx, "historical_bullish_probability"] = hist_bull
        out.loc[idx, "historical_bearish_probability"] = float(profile["bearish_probability"])
        out.loc[idx, "historical_market_move_probability"] = float(profile["market_move_probability"])
        out.loc[idx, "historical_avg_return_pts"] = float(profile["avg_return_pts"])
        out.loc[idx, "historical_avg_mfe_pts"] = float(profile["avg_mfe_pts"])
        out.loc[idx, "historical_avg_mae_pts"] = float(profile["avg_mae_pts"])
        out.loc[idx, "calibrated_bullish_probability"] = calibrated
        out.loc[idx, "calibrated_bearish_probability"] = 1.0 - calibrated

    out.to_csv(out_path, index=False)
    print(f"Wrote calibrated live releases to {out_path}")


def parse_windows(value: str) -> list[int]:
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Learn historical market reactions to macro release surprises.")
    p.add_argument("--events-file", help="CSV of macro release rows, for example macro_releases.csv")
    p.add_argument("--fetch-tv-events", action="store_true", help="Fetch historical TradingView economic events")
    p.add_argument("--start-date", help="Start date for TradingView historical events, YYYY-MM-DD")
    p.add_argument("--end-date", help="End date for TradingView historical events, YYYY-MM-DD")
    p.add_argument("--tv-countries", default="us", help="TradingView countries, comma-separated")
    p.add_argument("--tv-min-importance", type=int, default=1, help="TradingView importance: -1 low, 0 medium, 1 high")
    p.add_argument("--tv-chunk-days", type=int, default=30, help="Days per TradingView historical request chunk")
    p.add_argument("--fetched-events-output", default="macro_events_history.csv", help="Where to save fetched event history")
    p.add_argument("--market-data", help="Market OHLC CSV/Parquet, daily or intraday")
    p.add_argument("--symbol", default="NQ", help="Symbol label for reaction output")
    p.add_argument("--windows-minutes", default=",".join(map(str, DEFAULT_WINDOWS_MINUTES)), help="Intraday reaction windows")
    p.add_argument("--primary-window-minutes", type=int, default=60, help="Primary intraday window used for profiles")
    p.add_argument("--move-threshold-pct", type=float, default=0.25, help="Abs return percent threshold for market_move_probability")
    p.add_argument("--min-events", type=int, default=3, help="Minimum events required for a profile row")
    p.add_argument("--reaction-output", default="macro_reactions.csv")
    p.add_argument("--profile-output", default="macro_reaction_profiles.csv")
    p.add_argument("--calibrate-live", help="Live macro_releases.csv to calibrate using --profiles")
    p.add_argument("--profiles", help="Reaction profile CSV created by this module")
    p.add_argument("--calibrated-output", default="macro_releases_calibrated.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.calibrate_live:
        if not args.profiles:
            raise SystemExit("--calibrate-live requires --profiles")
        calibrate_live_rows(args.calibrate_live, args.profiles, args.calibrated_output)
        return

    if args.fetch_tv_events:
        if not args.start_date or not args.end_date:
            raise SystemExit("--fetch-tv-events requires --start-date and --end-date")
        fetched = fetch_tradingview_events(
            args.start_date,
            args.end_date,
            countries=args.tv_countries,
            min_importance=args.tv_min_importance,
            chunk_days=args.tv_chunk_days,
        )
        events = pd.DataFrame([normalize_event_row(r) for r in fetched])
        events.to_csv(args.fetched_events_output, index=False)
        print(f"Fetched {len(events)} TradingView events. Wrote {args.fetched_events_output}.")
    elif args.events_file:
        events = load_events_file(args.events_file)
    else:
        raise SystemExit("Provide --events-file or --fetch-tv-events.")

    if not args.market_data:
        raise SystemExit("Provide --market-data.")

    bars = load_market_data(args.market_data)
    windows = parse_windows(args.windows_minutes)
    reactions = compute_reactions(events, bars, args.symbol, windows, args.primary_window_minutes)
    reactions.to_csv(args.reaction_output, index=False)
    print(f"Wrote {len(reactions)} event reaction rows to {args.reaction_output}.")

    profiles = build_profiles(reactions, args.min_events, args.move_threshold_pct)
    profiles.to_csv(args.profile_output, index=False)
    print(f"Wrote {len(profiles)} reaction profile rows to {args.profile_output}.")

    if not profiles.empty:
        cols = ["group_type", "event_family", "catalyst_category", "surprise_side", "market_bias_side", "sample_size", "bullish_probability", "avg_return_pts", "market_move_probability"]
        print("\nTop profiles:")
        print(profiles[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
