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

CATEGORY_PRIORITY = {
    "central_bank": 100,
    "inflation": 90,
    "labor": 80,
    "growth": 70,
    "other": 0,
}

EVENT_FAMILY_PRIORITY = {
    "fomc_rates": 100,
    "core_cpi": 96,
    "cpi": 94,
    "pce": 90,
    "ppi": 88,
    "nonfarm_payrolls": 84,
    "adp_employment": 83,
    "unemployment_rate": 82,
    "jolts_job_openings": 80,
    "jobless_claims": 78,
    "labor": 76,
    "ism_pmi": 72,
    "gdp": 68,
    "retail_sales": 62,
    "home_sales": 56,
    "other": 0,
}


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
    if "adp" in text or "national employment" in text:
        return "adp_employment"
    if "jolts" in text or "job openings" in text:
        return "jolts_job_openings"
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
    if any(k in text for k in ("jobless", "claims")):
        return -0.7, "higher_is_bearish", "Higher jobless claims have recently behaved more like growth stress than a dovish-rate signal for NQ."
    if any(k in text for k in ("non farm", "nonfarm", "payroll", "employment change", "employment report", "adp", "national employment", "jolts", "job openings")):
        return -0.6, "higher_is_mixed_bearish", "Stronger payrolls can pressure NQ when the market reads them as higher-for-longer Fed policy."
    if any(k in text for k in ("unemployment", "layoffs")):
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


def unique_join(values, sep: str = " | ") -> str:
    seen = []
    for value in values:
        value = clean_empty(value)
        if value is None:
            continue
        text = str(value)
        if text not in seen:
            seen.append(text)
    return sep.join(seen)


def side_from_score(score, neutral_band: float = 0.15) -> tuple[str, str]:
    if score is None or pd.isna(score):
        return "market_unknown", "mixed"
    if abs(float(score)) <= neutral_band:
        return "market_neutral", "neutral"
    if float(score) > 0:
        return "market_positive", "bullish"
    return "market_negative", "bearish"


def mixed_side(values, flat_label: str = "flat", mixed_label: str = "mixed") -> str:
    sides = {str(v) for v in values if clean_empty(v) is not None}
    sides.discard("")
    if not sides:
        return flat_label
    if len(sides) == 1:
        return next(iter(sides))
    non_flat = {s for s in sides if s != flat_label}
    if len(non_flat) == 1:
        return next(iter(non_flat))
    return mixed_label


def event_priority(row: pd.Series) -> tuple[float, float, float]:
    family = str(row.get("event_family") or "")
    category = str(row.get("catalyst_category") or "")
    confidence = parse_economic_value(row.get("market_rule_confidence")) or 0.0
    return (
        EVENT_FAMILY_PRIORITY.get(family, 0),
        CATEGORY_PRIORITY.get(category, 0),
        confidence,
    )


def cluster_market_bias(group: pd.DataFrame) -> dict:
    scores = pd.to_numeric(group["market_bias_score"], errors="coerce") if "market_bias_score" in group.columns else pd.Series(dtype=float)
    confidence = pd.to_numeric(group["market_rule_confidence"], errors="coerce").fillna(0.0) if "market_rule_confidence" in group.columns else pd.Series(0.0, index=group.index)
    valid = scores.dropna()
    if valid.empty:
        score = np.nan
    else:
        weights = confidence.loc[valid.index]
        if float(weights.sum()) > 0:
            score = float((valid * weights).sum() / weights.sum())
        else:
            score = float(valid.mean())

    side, label = side_from_score(score)
    observed_sides = {str(v) for v in group["market_bias_side"] if clean_empty(v) is not None} if "market_bias_side" in group.columns else set()
    has_positive = "market_positive" in observed_sides
    has_negative = "market_negative" in observed_sides
    if has_positive and has_negative and abs(score) <= 0.35:
        side = "market_mixed"
        label = "mixed"

    return {
        "market_bias_side": side,
        "market_bias_label": label,
        "market_bias_score": score,
        "market_rule_direction": "cluster_weighted",
        "market_rule_confidence": float(confidence.max()) if len(confidence) else 0.0,
        "market_rule_note": "Cluster-level market bias from simultaneous releases.",
    }


def cluster_surprise_summary(group: pd.DataFrame) -> str:
    parts = []
    for row in group.itertuples(index=False):
        title = getattr(row, "title", "")
        surprise = getattr(row, "surprise", "")
        basis = getattr(row, "surprise_basis", "")
        if clean_empty(surprise) is None:
            continue
        parts.append(f"{title}: {surprise} ({basis})")
    return " | ".join(parts)


def cluster_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()

    working = events.copy()
    working["release_time"] = pd.to_datetime(working["release_time"], errors="coerce")
    working = working.dropna(subset=["release_time"]).sort_values(["release_time", "title"]).reset_index(drop=True)
    rows = []

    for release_time, group in working.groupby("release_time", sort=True):
        group = group.reset_index(drop=True)
        priorities = group.apply(event_priority, axis=1)
        primary_idx = sorted(range(len(group)), key=lambda i: priorities.iloc[i], reverse=True)[0]
        primary = group.iloc[primary_idx].to_dict()
        bias = cluster_market_bias(group)
        event_count = int(len(group))
        cluster_id = pd.Timestamp(release_time).strftime("%Y%m%dT%H%M%S")

        row = dict(primary)
        row.update(
            {
                "event_cluster_id": cluster_id,
                "event_count": event_count,
                "is_event_cluster": event_count > 1,
                "cluster_titles": unique_join(group["title"]),
                "cluster_event_families": unique_join(group["event_family"], sep=","),
                "cluster_categories": unique_join(group["catalyst_category"], sep=","),
                "cluster_surprise_sides": unique_join(group["surprise_side"], sep=","),
                "cluster_market_bias_sides": unique_join(group["market_bias_side"], sep=","),
                "cluster_surprise_summary": cluster_surprise_summary(group),
                "primary_title": primary.get("title", ""),
                "primary_event_family": primary.get("event_family", ""),
                "primary_catalyst_category": primary.get("catalyst_category", ""),
                "title": unique_join(group["title"]),
                "event_family": primary.get("event_family", ""),
                "catalyst_category": primary.get("catalyst_category", ""),
                "surprise_side": mixed_side(group["surprise_side"], flat_label="flat", mixed_label="mixed"),
                "raw_surprise_side": mixed_side(group["raw_surprise_side"], flat_label="flat", mixed_label="mixed"),
                **bias,
            }
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values("release_time").reset_index(drop=True)


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


def smoothed_probability(successes: int, trials: int, prior: float = 0.5, strength: float = 4.0) -> float:
    if trials <= 0:
        return float(prior)
    strength = max(float(strength), 0.0)
    return float((successes + prior * strength) / (trials + strength))


def confidence_label(value: float) -> str:
    if value >= 0.70:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"


def summarize_group(
    group: pd.DataFrame,
    move_threshold_pct: float,
    probability_prior: float,
    smoothing_strength: float,
    move_prior: float,
) -> dict:
    returns = pd.to_numeric(group["reaction_return_pts"], errors="coerce")
    returns_pct = pd.to_numeric(group["reaction_return_pct"], errors="coerce")
    mfe = pd.to_numeric(group["mfe_pts"], errors="coerce")
    mae = pd.to_numeric(group["mae_pts"], errors="coerce")
    market_bias_score = pd.to_numeric(group["market_bias_score"], errors="coerce") if "market_bias_score" in group.columns else pd.Series(dtype=float)
    valid = returns.dropna()
    if valid.empty:
        return {}
    sample_size = int(len(valid))
    bullish_wins = int((valid > 0).sum())
    raw_bullish_probability = float(bullish_wins / sample_size)
    bullish_probability = smoothed_probability(bullish_wins, sample_size, probability_prior, smoothing_strength)
    abs_move = returns_pct.abs().dropna()
    raw_market_move_probability = float((abs_move >= move_threshold_pct).mean()) if len(abs_move) else np.nan
    move_hits = int((abs_move >= move_threshold_pct).sum()) if len(abs_move) else 0
    market_move_probability = smoothed_probability(move_hits, len(abs_move), move_prior, smoothing_strength) if len(abs_move) else np.nan
    sample_confidence = min(1.0, sample_size / max(1.0, smoothing_strength * 3.0))
    return {
        "sample_size": sample_size,
        "raw_bullish_probability": raw_bullish_probability,
        "bullish_probability": bullish_probability,
        "bearish_probability": 1.0 - bullish_probability,
        "raw_market_move_probability": raw_market_move_probability,
        "market_move_probability": market_move_probability,
        "sample_confidence": sample_confidence,
        "confidence_label": confidence_label(sample_confidence),
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


def build_profiles(
    reactions: pd.DataFrame,
    min_events: int,
    move_threshold_pct: float,
    probability_prior: float,
    smoothing_strength: float,
    move_prior: float,
) -> pd.DataFrame:
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
            stats = summarize_group(group, move_threshold_pct, probability_prior, smoothing_strength, move_prior)
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
                "raw_bullish_probability",
                "bullish_probability",
                "bearish_probability",
                "raw_market_move_probability",
                "market_move_probability",
                "sample_confidence",
                "confidence_label",
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


def safe_profile_value(profile: pd.Series, key: str, default=""):
    return profile[key] if key in profile.index and not pd.isna(profile[key]) else default


def probability_from_row(row: pd.Series, key: str, default=0.5) -> float:
    if key not in row.index:
        return float(default)
    value = parse_economic_value(row.get(key))
    if value is None:
        return float(default)
    if value > 1.0 and value <= 100.0:
        return float(value) / 100.0
    return float(value)


def expected_direction(probability: float, bullish_threshold: float = 0.57, bearish_threshold: float = 0.43) -> str:
    if probability >= bullish_threshold:
        return "bullish"
    if probability <= bearish_threshold:
        return "bearish"
    return "mixed"


def build_warning(row: pd.Series) -> str:
    warnings = []
    sample_size = parse_economic_value(row.get("historical_sample_size"))
    if sample_size is None:
        warnings.append("no_historical_profile")
    elif sample_size < 5:
        warnings.append("low_sample")

    market_bias_side = str(row.get("market_bias_side") or "")
    if market_bias_side in {"market_unknown", "market_mixed", ""}:
        warnings.append("unclear_market_bias")

    calibrated = probability_from_row(row, "calibrated_bullish_probability", probability_from_row(row, "bullish_probability", 0.5))
    if abs(calibrated - 0.5) < 0.08:
        warnings.append("weak_direction_edge")

    if str(row.get("release_status") or "") == "waiting_actual":
        warnings.append("waiting_actual")
    return ";".join(warnings)


def build_live_signal_frame(calibrated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in calibrated.iterrows():
        calibrated_bull = probability_from_row(row, "calibrated_bullish_probability", probability_from_row(row, "bullish_probability", 0.5))
        calibrated_bear = 1.0 - calibrated_bull
        sample_confidence = probability_from_row(row, "historical_sample_confidence", 0.0)
        rule_confidence = probability_from_row(row, "market_rule_confidence", 0.0)
        edge_confidence = min(1.0, abs(calibrated_bull - 0.5) * 2.0)
        confidence = min(1.0, sample_confidence * 0.50 + rule_confidence * 0.20 + edge_confidence * 0.30)

        rows.append(
            {
                "release_time": row.get("release_time", ""),
                "title": row.get("title", ""),
                "catalyst_category": row.get("catalyst_category", ""),
                "event_family": row.get("event_family", ""),
                "release_status": row.get("release_status", ""),
                "previous": row.get("previous", ""),
                "forecast": row.get("forecast", ""),
                "actual": row.get("actual", ""),
                "previous_value": row.get("previous_value", ""),
                "forecast_value": row.get("forecast_value", ""),
                "actual_value": row.get("actual_value", ""),
                "surprise": row.get("surprise", ""),
                "surprise_basis": row.get("surprise_basis", ""),
                "raw_surprise_side": row.get("raw_surprise_side", row.get("surprise_side", "")),
                "market_bias_side": row.get("market_bias_side", ""),
                "market_bias_label": row.get("market_bias_label", ""),
                "market_bias_score": row.get("market_bias_score", ""),
                "market_rule_direction": row.get("market_rule_direction", ""),
                "market_rule_confidence": row.get("market_rule_confidence", ""),
                "historical_group_type": row.get("historical_group_type", ""),
                "historical_sample_size": row.get("historical_sample_size", ""),
                "historical_confidence_label": row.get("historical_confidence_label", ""),
                "historical_bullish_probability": row.get("historical_bullish_probability", ""),
                "historical_raw_bullish_probability": row.get("historical_raw_bullish_probability", ""),
                "historical_market_move_probability": row.get("historical_market_move_probability", ""),
                "historical_avg_return_pts": row.get("historical_avg_return_pts", ""),
                "calibrated_bullish_probability": calibrated_bull,
                "calibrated_bearish_probability": calibrated_bear,
                "expected_direction": expected_direction(calibrated_bull),
                "confidence": confidence,
                "confidence_label": confidence_label(confidence),
                "warning": build_warning(row),
                "market_rule_note": row.get("market_rule_note", ""),
                "source": row.get("source", ""),
                "source_url": row.get("source_url", ""),
            }
        )
    return pd.DataFrame(rows)


def calibrate_live_rows(live_path: str, profiles_path: str, out_path: str, signal_output: str | None = None) -> None:
    raw = pd.read_csv(live_path)
    normalized = pd.DataFrame([normalize_event_row(r) for r in raw.to_dict("records")])
    profiles = pd.read_csv(profiles_path)
    out = pd.DataFrame(raw.to_dict("records"), dtype=object)

    normalized_cols = [
        "event_family",
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
        "historical_raw_bullish_probability",
        "historical_bullish_probability",
        "historical_bearish_probability",
        "historical_raw_market_move_probability",
        "historical_market_move_probability",
        "historical_sample_confidence",
        "historical_confidence_label",
        "historical_avg_return_pts",
        "historical_avg_mfe_pts",
        "historical_avg_mae_pts",
        "calibrated_bullish_probability",
        "calibrated_bearish_probability",
    ]
    for col in normalized_cols + hist_cols:
        out[col] = pd.Series([""] * len(out), dtype=object)

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
        out.loc[idx, "historical_market_bias_side"] = safe_profile_value(profile, "market_bias_side")
        out.loc[idx, "historical_raw_bullish_probability"] = safe_profile_value(profile, "raw_bullish_probability")
        out.loc[idx, "historical_bullish_probability"] = hist_bull
        out.loc[idx, "historical_bearish_probability"] = float(profile["bearish_probability"])
        out.loc[idx, "historical_raw_market_move_probability"] = safe_profile_value(profile, "raw_market_move_probability")
        out.loc[idx, "historical_market_move_probability"] = float(profile["market_move_probability"])
        out.loc[idx, "historical_sample_confidence"] = safe_profile_value(profile, "sample_confidence")
        out.loc[idx, "historical_confidence_label"] = safe_profile_value(profile, "confidence_label")
        out.loc[idx, "historical_avg_return_pts"] = float(profile["avg_return_pts"])
        out.loc[idx, "historical_avg_mfe_pts"] = float(profile["avg_mfe_pts"])
        out.loc[idx, "historical_avg_mae_pts"] = float(profile["avg_mae_pts"])
        out.loc[idx, "calibrated_bullish_probability"] = calibrated
        out.loc[idx, "calibrated_bearish_probability"] = 1.0 - calibrated

    out.to_csv(out_path, index=False)
    print(f"Wrote calibrated live releases to {out_path}")
    if signal_output:
        signal = build_live_signal_frame(out)
        signal.to_csv(signal_output, index=False)
        print(f"Wrote live signal contract to {signal_output}")


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
    p.add_argument("--no-cluster-events", action="store_true", help="Disable same-timestamp event clustering")
    p.add_argument("--cluster-output", default="macro_event_clusters.csv", help="Where to save same-timestamp event clusters")
    p.add_argument("--market-data", help="Market OHLC CSV/Parquet, daily or intraday")
    p.add_argument("--symbol", default="NQ", help="Symbol label for reaction output")
    p.add_argument("--windows-minutes", default=",".join(map(str, DEFAULT_WINDOWS_MINUTES)), help="Intraday reaction windows")
    p.add_argument("--primary-window-minutes", type=int, default=60, help="Primary intraday window used for profiles")
    p.add_argument("--move-threshold-pct", type=float, default=0.25, help="Abs return percent threshold for market_move_probability")
    p.add_argument("--probability-prior", type=float, default=0.5, help="Bayesian prior for bullish probability smoothing")
    p.add_argument("--move-prior", type=float, default=0.25, help="Bayesian prior for market-move probability smoothing")
    p.add_argument("--smoothing-strength", type=float, default=4.0, help="Prior sample strength for probability smoothing")
    p.add_argument("--min-events", type=int, default=3, help="Minimum events required for a profile row")
    p.add_argument("--reaction-output", default="macro_reactions.csv")
    p.add_argument("--profile-output", default="macro_reaction_profiles.csv")
    p.add_argument("--calibrate-live", help="Live macro_releases.csv to calibrate using --profiles")
    p.add_argument("--profiles", help="Reaction profile CSV created by this module")
    p.add_argument("--calibrated-output", default="macro_releases_calibrated.csv")
    p.add_argument("--live-signal-output", help="Optional compact UI-ready live signal CSV")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.calibrate_live:
        if not args.profiles:
            raise SystemExit("--calibrate-live requires --profiles")
        calibrate_live_rows(args.calibrate_live, args.profiles, args.calibrated_output, signal_output=args.live_signal_output)
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

    if not args.no_cluster_events:
        raw_count = len(events)
        events = cluster_events(events)
        events.to_csv(args.cluster_output, index=False)
        print(f"Clustered {raw_count} event rows into {len(events)} release moments. Wrote {args.cluster_output}.")

    if not args.market_data:
        raise SystemExit("Provide --market-data.")

    bars = load_market_data(args.market_data)
    windows = parse_windows(args.windows_minutes)
    reactions = compute_reactions(events, bars, args.symbol, windows, args.primary_window_minutes)
    reactions.to_csv(args.reaction_output, index=False)
    print(f"Wrote {len(reactions)} event reaction rows to {args.reaction_output}.")

    profiles = build_profiles(
        reactions,
        args.min_events,
        args.move_threshold_pct,
        args.probability_prior,
        args.smoothing_strength,
        args.move_prior,
    )
    profiles.to_csv(args.profile_output, index=False)
    print(f"Wrote {len(profiles)} reaction profile rows to {args.profile_output}.")

    if not profiles.empty:
        cols = ["group_type", "event_family", "catalyst_category", "surprise_side", "market_bias_side", "sample_size", "raw_bullish_probability", "bullish_probability", "confidence_label", "avg_return_pts", "market_move_probability"]
        print("\nTop profiles:")
        print(profiles[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
