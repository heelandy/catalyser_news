#!/usr/bin/env python3
"""
catalyser_news.py

Simple market-news catalyser: ingest news (CSV or plain text), score sentiment
with a lightweight lexicon, extract tickers, and produce a per-symbol impact
estimate (weighted by recency).

Usage:
  python catalyser_news.py --news-file sample_news.csv --output news_summary.csv
  python catalyser_news.py --te-calendar --as-of 2026-06-06 --lookahead-days 7

CSV input expected columns: date,title,body (date ISO format)
"""
import argparse
import csv
import math
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import time
import requests
import json

POS_WORDS = {"beat","beats","beatings","gain","gains","up","surge","surged","rally","higher","strong","outperform","outperformed","beat","positive","upgrade","buys","optimistic","booming","record"}
NEG_WORDS = {"miss","missed","misses","down","fall","drop","plunge","weak","weakness","sell","downgrade","loss","losses","negative","cut","decline","slump","fears","uncertain"}

DATE_FMT = "%Y-%m-%d"
DEFAULT_CALENDAR_SYMBOLS = ["NQ", "ES", "QQQ", "SPY"]


def _calendar_event(date, title, note="", start=None):
    return {
        "date": date,
        "start": start or date,
        "title": title,
        "note": note,
        "provider": "calendar",
    }


CATALYST_CALENDAR_2026 = [
    _calendar_event("2026-01-01", "New Year's Day", "U.S. stock markets closed."),
    _calendar_event("2026-01-05", "ISM PMI release"),
    _calendar_event("2026-01-09", "BLS Employment Report", "Non-farm Payrolls and Unemployment."),
    _calendar_event("2026-01-13", "CPI inflation report"),
    _calendar_event("2026-01-14", "PPI report"),
    _calendar_event("2026-01-15", "Q4 2025 Quarterly Estimated Taxes due"),
    _calendar_event("2026-01-19", "Martin Luther King Jr. Day", "U.S. markets closed."),
    _calendar_event("2026-01-26", "IRS begins accepting 2025 federal tax filings"),
    _calendar_event("2026-01-28", "FOMC Meeting", "Interest rate policy decision on Jan 28.", start="2026-01-27"),
    _calendar_event("2026-01-29", "PCE inflation report"),
    _calendar_event("2026-02-02", "ISM PMI release"),
    _calendar_event("2026-02-06", "BLS Employment Report"),
    _calendar_event("2026-02-11", "CPI inflation report"),
    _calendar_event("2026-02-12", "PPI report"),
    _calendar_event("2026-02-16", "Presidents' Day", "U.S. markets closed."),
    _calendar_event("2026-02-26", "PCE inflation report"),
    _calendar_event("2026-03-02", "ISM PMI release"),
    _calendar_event("2026-03-06", "BLS Employment Report"),
    _calendar_event("2026-03-11", "CPI inflation report"),
    _calendar_event("2026-03-12", "PPI report"),
    _calendar_event("2026-03-18", "FOMC Meeting", "Includes economic projections and Dot Plot.", start="2026-03-17"),
    _calendar_event("2026-03-20", "S&P 500 / 400 / 600 Quarterly Index Rebalance"),
    _calendar_event("2026-03-27", "PCE inflation report"),
    _calendar_event("2026-04-01", "ISM PMI release"),
    _calendar_event("2026-04-03", "BLS Employment Report and Good Friday", "U.S. markets closed."),
    _calendar_event("2026-04-10", "CPI inflation report"),
    _calendar_event("2026-04-14", "PPI report"),
    _calendar_event("2026-04-15", "U.S. Tax Day", "Federal income tax filing deadline."),
    _calendar_event("2026-04-15", "Q1 2026 Quarterly Estimated Taxes due"),
    _calendar_event("2026-04-29", "FOMC Meeting", "Interest rate policy decision.", start="2026-04-28"),
    _calendar_event("2026-04-30", "PCE inflation report and preliminary Russell Index additions/deletions"),
    _calendar_event("2026-05-01", "ISM PMI release"),
    _calendar_event("2026-05-08", "BLS Employment Report"),
    _calendar_event("2026-05-12", "CPI inflation report"),
    _calendar_event("2026-05-13", "PPI report"),
    _calendar_event("2026-05-15", "First-quarter corporate earnings peak season wraps up"),
    _calendar_event("2026-05-22", "Initial list of Russell Index updates published"),
    _calendar_event("2026-05-25", "Memorial Day", "U.S. markets closed."),
    _calendar_event("2026-05-28", "PCE inflation report"),
    _calendar_event("2026-06-01", "ISM PMI release"),
    _calendar_event("2026-06-05", "BLS Employment Report", "Unemployment held at 4.3%."),
    _calendar_event("2026-06-10", "CPI inflation report"),
    _calendar_event("2026-06-11", "PPI report"),
    _calendar_event("2026-06-15", "Q2 2026 Quarterly Estimated Taxes due"),
    _calendar_event("2026-06-17", "FOMC Meeting", "Next interest rate decision and updated Dot Plot.", start="2026-06-16"),
    _calendar_event("2026-06-19", "Juneteenth National Independence Day", "U.S. markets closed."),
    _calendar_event("2026-06-25", "PCE inflation report"),
    _calendar_event("2026-06-26", "Russell Index Annual Reconstitution final close"),
    _calendar_event("2026-07-01", "Start of Financial H2", "Second half of the year begins."),
    _calendar_event("2026-07-03", "BLS Employment Report"),
    _calendar_event("2026-07-03", "Independence Day observed", "U.S. markets closed; July 4 falls on Saturday in 2026."),
    _calendar_event("2026-07-14", "CPI inflation report"),
    _calendar_event("2026-07-15", "PPI report"),
    _calendar_event("2026-07-15", "Q2 Corporate Earnings season begins", "Led by major banks."),
    _calendar_event("2026-07-29", "FOMC Meeting", "Interest rate policy decision.", start="2026-07-28"),
    _calendar_event("2026-07-30", "PCE inflation report"),
    _calendar_event("2026-08-03", "ISM PMI release"),
    _calendar_event("2026-08-07", "BLS Employment Report"),
    _calendar_event("2026-08-11", "CPI inflation report"),
    _calendar_event("2026-08-12", "PPI report"),
    _calendar_event("2026-08-29", "Kansas City Fed Jackson Hole Economic Symposium", start="2026-08-27"),
    _calendar_event("2026-08-28", "PCE inflation report"),
    _calendar_event("2026-09-01", "ISM PMI release and Pension Planning Season Start"),
    _calendar_event("2026-09-04", "BLS Employment Report"),
    _calendar_event("2026-09-07", "Labor Day", "U.S. markets closed."),
    _calendar_event("2026-09-11", "CPI inflation report"),
    _calendar_event("2026-09-15", "Q3 2026 Quarterly Estimated Taxes due"),
    _calendar_event("2026-09-16", "FOMC Meeting", "Includes economic projections.", start="2026-09-15"),
    _calendar_event("2026-09-18", "S&P Quarterly Index Rebalance"),
    _calendar_event("2026-09-29", "PCE inflation report"),
    _calendar_event("2026-10-01", "ISM PMI release"),
    _calendar_event("2026-10-02", "BLS Employment Report"),
    _calendar_event("2026-10-13", "CPI inflation report"),
    _calendar_event("2026-10-14", "PPI report"),
    _calendar_event("2026-10-15", "Corporate Earnings Season Q3 reports kick off"),
    _calendar_event("2026-10-15", "Extension deadline to file 2025 individual tax returns"),
    _calendar_event("2026-10-28", "FOMC Meeting", "Interest rate policy decision.", start="2026-10-27"),
    _calendar_event("2026-10-29", "PCE inflation report"),
    _calendar_event("2026-11-02", "ISM PMI release"),
    _calendar_event("2026-11-03", "U.S. Election Day", "Markets remain open; high economic volatility."),
    _calendar_event("2026-11-06", "BLS Employment Report"),
    _calendar_event("2026-11-12", "CPI inflation report"),
    _calendar_event("2026-11-13", "PPI report"),
    _calendar_event("2026-11-26", "Thanksgiving Day", "U.S. markets closed."),
    _calendar_event("2026-11-27", "Black Friday", "U.S. markets close early at 1:00 PM EST."),
    _calendar_event("2026-11-27", "PCE inflation report"),
    _calendar_event("2026-12-01", "ISM PMI release"),
    _calendar_event("2026-12-04", "BLS Employment Report"),
    _calendar_event("2026-12-09", "FOMC Meeting", "Final interest rate decision and Dot Plot of the year.", start="2026-12-08"),
    _calendar_event("2026-12-11", "CPI inflation report and final Russell Reconstitution adjustments"),
    _calendar_event("2026-12-15", "PPI report"),
    _calendar_event("2026-12-18", "Final S&P Index Rebalance of the year"),
    _calendar_event("2026-12-24", "Christmas Eve", "U.S. markets close early at 1:00 PM EST."),
    _calendar_event("2026-12-25", "Christmas Day", "U.S. markets closed."),
    _calendar_event("2026-12-29", "PCE inflation report"),
    _calendar_event("2026-12-31", "Year-End tax planning window closes"),
]


def simple_sentiment(text: str) -> float:
    if not text:
        return 0.0
    text = text.lower()
    pos = sum(1 for w in POS_WORDS if w in text)
    neg = sum(1 for w in NEG_WORDS if w in text)
    if pos + neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def extract_symbols(text: str):
    # crude extraction: $TICKER or ALL-CAPS tokens length 1-5
    import re
    if not text:
        return []
    syms = set()
    for m in re.findall(r"\$([A-Z]{1,5})", text):
        syms.add(m)
    for m in re.findall(r"\b([A-Z]{2,5})\b", text):
        # filter common words that are uppercased but not tickers (very simple)
        if m.isalpha() and len(m) <= 5 and m not in {"AND","THE","FOR","WITH","FROM"}:
            syms.add(m)
    return list(syms)


def _parse_date(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc_z(value):
    dt = _parse_date(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def split_symbols(value, default=None):
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        return [s.strip().upper() for s in value.split(',') if s.strip()]
    return [str(s).strip().upper() for s in value if str(s).strip()]


def _clean_empty(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.lower() in {"none", "null", "nan", "n/a", "-"}:
            return None
        return v
    return value


def parse_economic_value(value):
    value = _clean_empty(value)
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


def _first_number(row, keys):
    for key in keys:
        value = parse_economic_value(row.get(key))
        if value is not None:
            return value
    return None


def apply_value_scale(value, scale):
    value = parse_economic_value(value)
    if value is None:
        return None
    scale = str(scale or '').strip().upper()
    if scale == 'K':
        return value * 1_000
    if scale == 'M':
        return value * 1_000_000
    if scale == 'B':
        return value * 1_000_000_000
    if scale == 'T':
        return value * 1_000_000_000_000
    return value


def format_release_value(value, scale='', unit=''):
    value = _clean_empty(value)
    if value is None:
        return ''
    scale = str(scale or '').strip()
    unit = str(unit or '').strip()
    if unit == '%':
        return f"{value}%"
    return f"{value}{scale}"


def release_direction_rule(title: str, category: str = ""):
    text = f"{title} {category}".lower()

    if any(k in text for k in ("cpi", "ppi", "pce", "inflation", "prices", "price index")):
        return -1.0, "Higher inflation is usually bearish for U.S. stocks because it can lift yields and reduce rate-cut odds."
    if any(k in text for k in ("fomc", "interest rate", "fed funds", "rate decision", "dot plot")):
        return -1.0, "A higher-rate or more hawkish surprise is usually bearish for equities."
    if any(k in text for k in ("unemployment", "jobless", "claims", "layoffs")):
        return -0.35, "Higher unemployment/claims are mixed: dovish for rates, but bearish if growth fear dominates."
    if any(k in text for k in ("non farm", "nonfarm", "payroll", "employment change", "employment report", "adp", "national employment", "jolts", "job openings")):
        return -0.6, "Stronger jobs can pressure rate-sensitive stocks if the market reads it as higher-for-longer Fed policy."
    if any(k in text for k in ("pmi", "ism", "gdp", "retail sales", "industrial production", "consumer confidence")):
        return 0.7, "Stronger growth data is usually risk-on unless it also renews inflation or Fed pressure."
    return 0.0, "No reliable one-number direction rule; treat this as a volatility catalyst and wait for price confirmation."


def market_rule_direction(multiplier):
    if multiplier > 0:
        return 'higher_is_bullish'
    if multiplier < 0 and abs(multiplier) >= 0.75:
        return 'higher_is_bearish'
    if multiplier < 0:
        return 'higher_is_mixed_bearish'
    return 'unknown'


def surprise_side(value, eps=1e-12):
    value = parse_economic_value(value)
    if value is None or abs(value) <= eps:
        return 'flat'
    return 'positive' if value > 0 else 'negative'


def interpret_market_bias(title, category, surprise):
    raw_side = surprise_side(surprise)
    multiplier, note = release_direction_rule(title, category)
    sign = 1 if raw_side == 'positive' else -1 if raw_side == 'negative' else 0
    score = multiplier * sign

    if sign == 0:
        side = 'market_neutral'
        label = 'neutral'
    elif abs(multiplier) < 0.2:
        side = 'market_unknown'
        label = 'mixed'
    elif score > 0:
        side = 'market_positive'
        label = 'bullish'
    elif score < 0:
        side = 'market_negative'
        label = 'bearish'
    else:
        side = 'market_unknown'
        label = 'mixed'

    return {
        'raw_surprise_side': raw_side,
        'market_bias_side': side,
        'market_bias_label': label,
        'market_bias_score': score,
        'market_rule_direction': market_rule_direction(multiplier),
        'market_rule_confidence': abs(multiplier),
        'market_rule_note': note,
    }


def surprise_scale(title: str, category: str, unit: str, baseline):
    text = f"{title} {category}".lower()
    unit = (unit or "").strip()
    if any(k in text for k in ("non farm", "nonfarm", "payroll")):
        return 50_000.0
    if any(k in text for k in ("unemployment", "jobless", "claims")):
        return 0.2 if unit == "%" else 25_000.0
    if any(k in text for k in ("cpi", "ppi", "pce", "inflation")):
        return 0.1 if "mom" in text or unit == "%" else 0.2
    if any(k in text for k in ("pmi", "ism")):
        return 1.0
    if any(k in text for k in ("gdp", "retail sales", "industrial production")):
        return 0.5
    if baseline not in (None, 0):
        return max(abs(float(baseline)) * 0.05, 0.1)
    return 1.0


def score_macro_release(row):
    title = row.get('title') or row.get('event') or ''
    category = row.get('catalyst_category') or row.get('category') or ''
    profile = classify_catalyst(title, row.get('body') or row.get('note') or category)

    actual = _first_number(row, ('actual_value', 'ActualValue', 'actual', 'Actual'))
    previous = _first_number(row, ('previous_value', 'PreviousValue', 'previous', 'Previous'))
    forecast = _first_number(row, ('forecast_value', 'ForecastValue', 'forecast', 'Forecast', 'teforecast_value', 'TEForecastValue', 'teforecast', 'TEForecast'))
    unit = row.get('unit') or row.get('Unit') or ''
    importance_raw = row.get('importance_raw') or row.get('Importance') or row.get('importance')
    try:
        importance_num = float(importance_raw)
    except Exception:
        importance_num = {'low': 1.0, 'medium': 2.0, 'high': 3.0, 'closed': 0.0}.get(str(profile['importance']).lower(), 1.0)

    if actual is not None and forecast is not None:
        surprise = actual - forecast
        surprise_basis = 'actual_vs_forecast'
        status = 'released'
        confidence = 0.85
        baseline = forecast
    elif actual is not None and previous is not None:
        surprise = actual - previous
        surprise_basis = 'actual_vs_previous'
        status = 'released'
        confidence = 0.65
        baseline = previous
    elif forecast is not None and previous is not None:
        surprise = forecast - previous
        surprise_basis = 'forecast_vs_previous'
        status = 'waiting_actual'
        confidence = 0.35
        baseline = previous
    else:
        surprise = None
        surprise_basis = 'waiting_for_values'
        status = 'waiting_actual'
        confidence = 0.15
        baseline = forecast if forecast is not None else previous

    scale = surprise_scale(title, category, unit, baseline)
    surprise_magnitude = min(abs(surprise) / scale, 1.0) if surprise is not None and scale else 0.0
    market_bias = interpret_market_bias(title, category, surprise)
    direction_score = market_bias['market_bias_score'] * surprise_magnitude * confidence

    base_move = {'closed': 0.0, 'low': 0.25, 'medium': 0.45, 'high': 0.65}.get(str(profile['importance']).lower(), 0.35)
    base_move = max(base_move, min(importance_num / 3.0, 1.0) * 0.65)
    market_move_probability = min(0.95, max(0.05, base_move + surprise_magnitude * (0.25 if status == 'released' else 0.10)))
    bullish_probability = min(0.95, max(0.05, 0.50 + direction_score * 0.40))
    bearish_probability = 1.0 - bullish_probability

    if bullish_probability >= 0.57:
        direction_label = 'bullish'
    elif bullish_probability <= 0.43:
        direction_label = 'bearish'
    else:
        direction_label = 'mixed'

    expected_effect = (
        f"{status}; {surprise_basis}. {market_bias['market_rule_note']} "
        f"Market bias: {market_bias['market_bias_side']}. "
        f"Bullish probability {bullish_probability:.0%}, bearish probability {bearish_probability:.0%}, "
        f"market-move probability {market_move_probability:.0%}."
    )
    return {
        'release_status': status,
        'actual_value': actual,
        'previous_value': previous,
        'forecast_value': forecast,
        'surprise': surprise,
        'surprise_basis': surprise_basis,
        'surprise_magnitude': surprise_magnitude,
        'direction_score': direction_score,
        'direction_label': direction_label,
        **market_bias,
        'bullish_probability': bullish_probability,
        'bearish_probability': bearish_probability,
        'market_move_probability': market_move_probability,
        'volatility_score': max(float(profile.get('volatility_score') or 0.0), market_move_probability),
        'expected_effect': expected_effect,
    }


def classify_catalyst(title: str, note: str = ""):
    title_text = str(title or "").lower()
    text = f"{title} {note}".lower()
    profile = {
        "category": "other",
        "importance": "low",
        "direction_score": 0.0,
        "volatility_score": 0.25,
        "expected_effect": "Secondary calendar item; use live price action and actual headline surprise for direction.",
    }

    if "close early" in text:
        profile.update({
            "category": "early_close",
            "importance": "medium",
            "volatility_score": 0.35,
            "expected_effect": "Shortened cash session. Expect thinner liquidity, earlier position squaring, and less reliable late-day follow-through.",
        })
    elif "markets closed" in text or "market closed" in text or "stock markets closed" in text:
        profile.update({
            "category": "market_holiday",
            "importance": "closed",
            "volatility_score": 0.0,
            "expected_effect": "Cash equities closed. Avoid treating missing regular-session movement as a signal; futures may have modified hours.",
        })
    elif "fomc" in text or "dot plot" in text or "jackson hole" in text:
        profile.update({
            "category": "central_bank",
            "importance": "high",
            "volatility_score": 1.0,
            "expected_effect": "Rate-sensitive catalyst. Hawkish/high-for-longer messaging pressures NQ; dovish/cut-friendly messaging supports NQ. Expect whipsaw around the release.",
        })
    elif "cpi" in text or "ppi" in text or "pce" in text or "inflation" in text:
        profile.update({
            "category": "inflation",
            "importance": "high",
            "volatility_score": 0.9,
            "expected_effect": "Inflation surprise catalyst. Hotter data is usually bearish for NQ through yields; cooler data is usually bullish. Watch the first move for reversals.",
        })
    elif "ism" in title_text or "pmi" in title_text:
        profile.update({
            "category": "growth",
            "importance": "medium",
            "volatility_score": 0.55,
            "expected_effect": "Growth catalyst. Strong PMI supports risk if inflation is calm; weak PMI can pressure growth names unless it strengthens rate-cut expectations.",
        })
    elif any(k in title_text for k in ("employment", "payroll", "unemployment", "jobless", "claims", "jolts", "job openings", "adp")):
        profile.update({
            "category": "labor",
            "importance": "high",
            "volatility_score": 0.8,
            "expected_effect": "Labor surprise catalyst. Strong jobs can pressure NQ through higher yields; weaker jobs can support rate-cut hopes unless recession fear dominates.",
        })
    elif "earnings" in text:
        profile.update({
            "category": "earnings",
            "importance": "medium",
            "volatility_score": 0.6,
            "expected_effect": "Earnings-flow catalyst. Positive guidance supports NQ; margin or demand warnings pressure tech. Bank earnings can set risk tone early in season.",
        })
    elif "russell" in text or "s&p" in text or "rebalance" in text or "reconstitution" in text or "index" in text:
        profile.update({
            "category": "index_flow",
            "importance": "medium",
            "volatility_score": 0.5,
            "expected_effect": "Index-flow catalyst. Direction is unreliable; expect volume, closing imbalances, and single-name/index basket distortions.",
        })
    elif "tax" in text or "irs" in text:
        profile.update({
            "category": "tax_liquidity",
            "importance": "low",
            "direction_score": -0.05,
            "volatility_score": 0.2,
            "expected_effect": "Cash-flow/liquidity date. Usually secondary, but it can slightly dampen risk appetite near payment deadlines.",
        })
    elif "election" in text:
        profile.update({
            "category": "political",
            "importance": "high",
            "volatility_score": 0.85,
            "expected_effect": "Policy uncertainty catalyst. Expect volatility and sector rotation; durable direction usually waits for clearer results.",
        })
    elif "year-end" in text or "financial h2" in text or "pension" in text:
        profile.update({
            "category": "seasonal_flow",
            "importance": "medium",
            "volatility_score": 0.4,
            "expected_effect": "Seasonal-flow catalyst. Watch positioning, rebalancing, and liquidity more than a clean directional signal.",
        })

    return profile


def load_catalyst_csv(path, provider="calendar_file"):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            title = r.get('title') or r.get('event') or r.get('name') or ''
            note = r.get('note') or r.get('body') or r.get('summary') or ''
            date_value = r.get('date') or r.get('end_date') or r.get('datetime')
            if not date_value:
                continue
            start_value = r.get('start') or r.get('start_date') or date_value
            rows.append({
                'date': date_value,
                'start': start_value,
                'title': title,
                'note': note,
                'provider': r.get('provider') or provider,
                'category': r.get('category') or r.get('catalyst_category') or '',
                'release_time': r.get('release_time') or r.get('datetime') or date_value,
                'previous': r.get('previous') or r.get('Previous') or '',
                'forecast': r.get('forecast') or r.get('Forecast') or '',
                'actual': r.get('actual') or r.get('Actual') or '',
                'unit': r.get('unit') or r.get('Unit') or '',
                'importance_raw': r.get('importance_raw') or r.get('Importance') or '',
                'source': r.get('source') or r.get('Source') or '',
                'source_url': r.get('source_url') or r.get('SourceURL') or '',
            })
    return rows


def build_catalyst_rows(events, as_of=None, lookback_days=2, lookahead_days=14, symbols=None, include_closed=True):
    anchor = _parse_date(as_of) if as_of else utc_now()
    start_cutoff = (anchor - timedelta(days=lookback_days)).date()
    end_cutoff = (anchor + timedelta(days=lookahead_days)).date()
    symbols = split_symbols(symbols, DEFAULT_CALENDAR_SYMBOLS)
    out = []

    for event in events:
        end_dt = _parse_date(event['date'])
        start_dt = _parse_date(event.get('start') or event['date'])
        if end_dt.date() < start_cutoff or start_dt.date() > end_cutoff:
            continue

        profile = classify_catalyst(event.get('title', ''), event.get('note', '') or event.get('category', ''))
        if not include_closed and profile['category'] == 'market_holiday':
            continue

        days_from_as_of = (start_dt.date() - anchor.date()).days
        score_input = dict(event)
        score_input.update({
            'catalyst_category': profile['category'],
            'category': event.get('category') or profile['category'],
        })
        score = score_macro_release(score_input)
        has_release_values = any(_clean_empty(event.get(k)) is not None for k in ('actual', 'Actual', 'previous', 'Previous', 'forecast', 'Forecast', 'teforecast', 'TEForecast'))
        direction_score = score['direction_score'] if has_release_values else profile['direction_score']
        volatility_score = score['volatility_score'] if has_release_values else profile['volatility_score']
        expected_effect = score['expected_effect'] if has_release_values else profile['expected_effect']
        body = f"{event.get('note', '')} {expected_effect}".strip()
        out.append({
            'date': end_dt,
            'start_date': start_dt.date().isoformat(),
            'end_date': end_dt.date().isoformat(),
            'release_time': event.get('release_time') or end_dt.isoformat(),
            'title': event.get('title', ''),
            'body': body,
            'provider': event.get('provider', 'calendar'),
            'symbols': symbols,
            'catalyst_category': profile['category'],
            'importance': profile['importance'],
            'direction_score': direction_score,
            'volatility_score': volatility_score,
            'expected_effect': expected_effect,
            'days_from_as_of': days_from_as_of,
            'release_status': score['release_status'] if has_release_values else 'scheduled',
            'previous': event.get('previous') or event.get('Previous') or '',
            'forecast': event.get('forecast') or event.get('Forecast') or '',
            'actual': event.get('actual') or event.get('Actual') or '',
            'previous_value': score['previous_value'],
            'forecast_value': score['forecast_value'],
            'actual_value': score['actual_value'],
            'surprise': score['surprise'],
            'surprise_basis': score['surprise_basis'],
            'raw_surprise_side': score['raw_surprise_side'] if has_release_values else '',
            'market_bias_side': score['market_bias_side'] if has_release_values else '',
            'market_bias_label': score['market_bias_label'] if has_release_values else '',
            'market_bias_score': score['market_bias_score'] if has_release_values else '',
            'market_rule_direction': score['market_rule_direction'] if has_release_values else '',
            'market_rule_confidence': score['market_rule_confidence'] if has_release_values else '',
            'market_rule_note': score['market_rule_note'] if has_release_values else '',
            'direction_label': score['direction_label'] if has_release_values else 'scheduled',
            'bullish_probability': score['bullish_probability'] if has_release_values else '',
            'bearish_probability': score['bearish_probability'] if has_release_values else '',
            'market_move_probability': score['market_move_probability'] if has_release_values else '',
            'source': event.get('source') or '',
            'source_url': event.get('source_url') or '',
        })
    return sorted(out, key=lambda r: (r['start_date'], r['end_date'], r['title']))


def parse_news_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            date = None
            for k in ('date','published','datetime'):
                if k in r and r[k]:
                    try:
                        date = _parse_date(r[k])
                        break
                    except Exception:
                        pass
            if date is None:
                # try parsing just the first column
                try:
                    date = _parse_date(list(r.values())[0])
                except Exception:
                    date = utc_now()
            title = r.get('title','')
            body = r.get('body', r.get('summary',''))
            rows.append({'date': date, 'title': title, 'body': body})
    return rows


def fetch_yahoo_for_symbol(sym: str, max_items: int = 25, rate_limit: float = 0.5):
    """Fetch recent news for a single symbol from Yahoo Finance unofficial search endpoint.
    Returns list of dicts with date,title,body.
    """
    out = []
    base = 'https://query2.finance.yahoo.com/v1/finance/search'
    params = {'q': sym, 'newsCount': max_items, 'quotesCount': 0}
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; catalyser/1.0)'}

    attempts = 0
    j = None
    while attempts < 4:
        try:
            r = requests.get(base, params=params, headers=headers, timeout=10)
            if r.status_code == 429:
                attempts += 1
                time.sleep(1.5 ** attempts)
                continue
            r.raise_for_status()
            j = r.json()
            break
        except Exception:
            attempts += 1
            time.sleep(1.5 ** attempts)
            continue

    news = (j.get('news') if j else None) or (j.get('items') if j else None) or []
    for n in news:
        try:
            title = n.get('title') or n.get('headline') or ''
            body = n.get('summary') or n.get('content') or ''
            t = n.get('providerPublishTime') or n.get('pubDate') or n.get('published')
            date = None
            if isinstance(t, (int, float)):
                date = datetime.fromtimestamp(int(t), timezone.utc).replace(tzinfo=None)
            else:
                try:
                    date = _parse_date(t)
                except Exception:
                    date = utc_now()
            out.append({'date': date, 'title': title, 'body': body, 'provider': 'yahoo'})
        except Exception:
            continue
    time.sleep(rate_limit)
    return out


def _strip_tags(s: str) -> str:
    import re
    return re.sub(r'<[^>]+>', '', s or '')


def fetch_tradingview_news(max_items: int = 25, rate_limit: float = 0.5, symbol_hint: str = None):
    """Fetch recent top news from TradingView overview page. This scrapes the landing
    news page and extracts headline cards. If `symbol_hint` is provided, only
    return items that mention that symbol in the title.
    """
    out = []
    try:
        r = requests.get('https://www.tradingview.com/news/', timeout=10, headers={'User-Agent': 'Mozilla/5.0 (compatible; catalyser/1.0)'})
        r.raise_for_status()
        h = r.text
        # find article anchor blocks linking to /news/
        import re
        blocks = re.findall(r'<a[^>]+href="(?P<href>/news/[^"]+)"[^>]*>(?P<body>.*?)</a>', h, flags=re.I|re.S)
        seen = 0
        for href, body in blocks:
            if seen >= max_items:
                break
            # title is inside element with data-qa-id="news-headline-title"
            m = re.search(r'data-qa-id="news-headline-title">(.*?)</div>', body, flags=re.I|re.S)
            title = _strip_tags(m.group(1)).strip() if m else _strip_tags(body).strip()
            if symbol_hint:
                if symbol_hint.upper() not in title.upper():
                    continue
            # we don't fetch full article pages to avoid extra requests; use now as date
            date = utc_now()
            out.append({'date': date, 'title': title, 'body': '', 'provider': 'tradingview'})
            seen += 1
            time.sleep(rate_limit)
    except Exception:
        pass
    return out


def fetch_tradingview_calendar(countries='us', start_date=None, end_date=None, min_importance=1, timeout=15):
    """Fetch TradingView economic calendar rows.

    TradingView's public widget uses the Reuters calendar endpoint. Importance
    follows TradingView's widget scale: -1 low, 0 medium, 1 high.
    """
    anchor = utc_now()
    start_dt = _parse_date(start_date) if start_date else anchor - timedelta(days=1)
    end_dt = _parse_date(end_date) if end_date else anchor + timedelta(days=7)
    country_codes = [c.strip().upper() for c in str(countries or 'us').split(',') if c.strip()]
    if not country_codes:
        country_codes = ['US']

    url = 'https://chartevents-reuters.tradingview.com/events'
    params = {
        'minImportance': str(min_importance),
        'from': iso_utc_z(start_dt),
        'to': iso_utc_z(end_dt),
        'countries': ','.join(country_codes),
    }
    headers = {
        'accept': 'application/json',
        'origin': 'https://www.tradingview.com',
        'referer': 'https://www.tradingview.com/economic-calendar/?countries=us',
        'user-agent': 'Mozilla/5.0 (compatible; catalyser/1.0)',
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get('status') == 'error':
        raise RuntimeError(data.get('errmsg') or 'TradingView calendar returned error')
    return data.get('result') or []


def normalize_tradingview_events(events, symbols=None):
    rows = []
    symbols = split_symbols(symbols, DEFAULT_CALENDAR_SYMBOLS)
    for e in events:
        release_dt = _parse_date(str(e.get('date')))
        title = e.get('title') or e.get('indicator') or ''
        category = e.get('indicator') or title
        profile = classify_catalyst(title, e.get('comment') or category)
        scale = e.get('scale') or ''
        unit = e.get('unit') or ''
        actual_display = format_release_value(e.get('actual'), scale, unit)
        previous_display = format_release_value(e.get('previous'), scale, unit)
        forecast_display = format_release_value(e.get('forecast'), scale, unit)
        score_input = {
            'title': title,
            'category': category,
            'catalyst_category': profile['category'],
            'actual': actual_display,
            'previous': previous_display,
            'forecast': forecast_display,
            'actual_value': apply_value_scale(e.get('actual'), scale),
            'previous_value': apply_value_scale(e.get('previous'), scale),
            'forecast_value': apply_value_scale(e.get('forecast'), scale),
            'unit': unit,
            'importance_raw': e.get('importance'),
        }
        score = score_macro_release(score_input)
        body = (
            f"{e.get('country', '')} {category} {e.get('period', '')}. "
            f"Previous={previous_display}; Forecast={forecast_display}; "
            f"Actual={actual_display or 'waiting'}. {score['expected_effect']}"
        ).strip()
        rows.append({
            'date': release_dt,
            'start_date': release_dt.date().isoformat(),
            'end_date': release_dt.date().isoformat(),
            'release_time': release_dt.isoformat(),
            'title': title,
            'body': body,
            'provider': 'tradingview_calendar',
            'symbols': symbols,
            'catalyst_category': profile['category'],
            'importance': profile['importance'],
            'importance_raw': e.get('importance'),
            'direction_score': score['direction_score'],
            'volatility_score': score['volatility_score'],
            'expected_effect': score['expected_effect'],
            'release_status': score['release_status'],
            'previous': previous_display,
            'forecast': forecast_display,
            'actual': actual_display,
            'previous_value': score['previous_value'],
            'forecast_value': score['forecast_value'],
            'actual_value': score['actual_value'],
            'surprise': score['surprise'],
            'surprise_basis': score['surprise_basis'],
            'raw_surprise_side': score['raw_surprise_side'],
            'market_bias_side': score['market_bias_side'],
            'market_bias_label': score['market_bias_label'],
            'market_bias_score': score['market_bias_score'],
            'market_rule_direction': score['market_rule_direction'],
            'market_rule_confidence': score['market_rule_confidence'],
            'market_rule_note': score['market_rule_note'],
            'direction_label': score['direction_label'],
            'bullish_probability': score['bullish_probability'],
            'bearish_probability': score['bearish_probability'],
            'market_move_probability': score['market_move_probability'],
            'country': e.get('country') or '',
            'category': category,
            'reference': e.get('period') or '',
            'calendar_id': e.get('id') or '',
            'source': e.get('source') or 'TradingView/Reuters',
            'source_url': 'https://www.tradingview.com/economic-calendar/?countries=us',
            'unit': unit,
            'scale': scale,
            'last_update': '',
        })
    return sorted(rows, key=lambda r: (r['release_time'], r['title']))


def fetch_tradingview_with_watch(args):
    anchor = _parse_date(args.as_of) if args.as_of else utc_now()
    start = (anchor - timedelta(days=args.lookback_days)).date().isoformat()
    end = (anchor + timedelta(days=args.lookahead_days)).date().isoformat()
    deadline = utc_now() + timedelta(minutes=args.watch_minutes)
    target_ids = None
    rows = []

    while True:
        events = fetch_tradingview_calendar(
            countries=args.tv_countries,
            start_date=start,
            end_date=end,
            min_importance=args.tv_min_importance,
        )
        rows = normalize_tradingview_events(events, symbols=args.calendar_symbols)
        for r in rows:
            r['days_from_as_of'] = (_parse_date(r['release_time']).date() - anchor.date()).days
        if not args.watch_releases:
            return rows

        watch_rows = [r for r in rows if _parse_date(r['release_time']).date() == anchor.date()]
        row_id = lambda r: r.get('calendar_id') or f"{r.get('release_time')}|{r.get('title')}"
        if target_ids is None:
            pending = [r for r in watch_rows if r.get('release_status') == 'waiting_actual']
            target_ids = {row_id(r) for r in pending} or {row_id(r) for r in watch_rows}

        target_rows = [r for r in watch_rows if row_id(r) in target_ids]
        released = [r for r in target_rows if r.get('release_status') == 'released']
        waiting = [r for r in target_rows if r.get('release_status') == 'waiting_actual']
        if released or not waiting or utc_now() >= deadline:
            return rows
        print(f"Waiting for TradingView actual values: {len(waiting)} pending today. Polling again in {args.poll_seconds}s.")
        time.sleep(args.poll_seconds)


def fetch_tradingeconomics_calendar(country='united states', start_date=None, end_date=None, api_key=None, timeout=15):
    """Fetch economic-calendar rows with previous/forecast/actual values.

    Trading Economics supports a limited guest key (`guest:guest`) and full API
    keys via the `c` parameter. Full reliability around release time usually
    requires a paid key.
    """
    api_key = api_key or os.environ.get('TRADING_ECONOMICS_KEY') or 'guest:guest'
    country_path = quote(country.strip().lower())
    if start_date and end_date:
        base = f"https://api.tradingeconomics.com/calendar/country/{country_path}/{start_date}/{end_date}"
    else:
        base = f"https://api.tradingeconomics.com/calendar/country/{country_path}"
    params = {'c': api_key, 'f': 'json', 'values': 'true'}
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; catalyser/1.0)'}
    r = requests.get(base, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get('Message'):
        raise RuntimeError(data['Message'])
    return data if isinstance(data, list) else []


def normalize_tradingeconomics_events(events, symbols=None, min_importance=2):
    rows = []
    symbols = split_symbols(symbols, DEFAULT_CALENDAR_SYMBOLS)
    for e in events:
        try:
            importance = int(float(e.get('Importance') or 0))
        except Exception:
            importance = 0
        if importance < min_importance:
            continue

        release_dt = _parse_date(str(e.get('Date')))
        title = e.get('Event') or e.get('Category') or ''
        category = e.get('Category') or ''
        profile = classify_catalyst(title, category)
        score_input = {
            'title': title,
            'category': category,
            'catalyst_category': profile['category'],
            'actual': e.get('Actual'),
            'previous': e.get('Previous'),
            'forecast': e.get('Forecast') or e.get('TEForecast'),
            'actual_value': e.get('ActualValue'),
            'previous_value': e.get('PreviousValue'),
            'forecast_value': e.get('ForecastValue') if e.get('ForecastValue') is not None else e.get('TEForecastValue'),
            'unit': e.get('Unit'),
            'importance_raw': e.get('Importance'),
        }
        score = score_macro_release(score_input)
        body = (
            f"{e.get('Country', '')} {category} {e.get('Reference', '')}. "
            f"Previous={e.get('Previous') or ''}; Forecast={e.get('Forecast') or e.get('TEForecast') or ''}; "
            f"Actual={e.get('Actual') or 'waiting'}. {score['expected_effect']}"
        ).strip()
        rows.append({
            'date': release_dt,
            'start_date': release_dt.date().isoformat(),
            'end_date': release_dt.date().isoformat(),
            'release_time': release_dt.isoformat(),
            'title': title,
            'body': body,
            'provider': 'tradingeconomics',
            'symbols': symbols,
            'catalyst_category': profile['category'],
            'importance': profile['importance'],
            'importance_raw': importance,
            'direction_score': score['direction_score'],
            'volatility_score': score['volatility_score'],
            'expected_effect': score['expected_effect'],
            'release_status': score['release_status'],
            'previous': e.get('Previous') or '',
            'forecast': e.get('Forecast') or e.get('TEForecast') or '',
            'actual': e.get('Actual') or '',
            'previous_value': score['previous_value'],
            'forecast_value': score['forecast_value'],
            'actual_value': score['actual_value'],
            'surprise': score['surprise'],
            'surprise_basis': score['surprise_basis'],
            'raw_surprise_side': score['raw_surprise_side'],
            'market_bias_side': score['market_bias_side'],
            'market_bias_label': score['market_bias_label'],
            'market_bias_score': score['market_bias_score'],
            'market_rule_direction': score['market_rule_direction'],
            'market_rule_confidence': score['market_rule_confidence'],
            'market_rule_note': score['market_rule_note'],
            'direction_label': score['direction_label'],
            'bullish_probability': score['bullish_probability'],
            'bearish_probability': score['bearish_probability'],
            'market_move_probability': score['market_move_probability'],
            'country': e.get('Country') or '',
            'category': category,
            'reference': e.get('Reference') or '',
            'calendar_id': e.get('CalendarId') or e.get('CalendarID') or '',
            'source': e.get('Source') or '',
            'source_url': e.get('SourceURL') or '',
            'unit': e.get('Unit') or '',
            'last_update': e.get('LastUpdate') or '',
        })
    return sorted(rows, key=lambda r: (r['release_time'], r['title']))


def fetch_tradingeconomics_with_watch(args):
    anchor = _parse_date(args.as_of) if args.as_of else utc_now()
    start = (anchor - timedelta(days=args.lookback_days)).date().isoformat()
    end = (anchor + timedelta(days=args.lookahead_days)).date().isoformat()
    deadline = utc_now() + timedelta(minutes=args.watch_minutes)
    rows = []
    target_ids = None

    while True:
        events = fetch_tradingeconomics_calendar(
            country=args.te_country,
            start_date=start,
            end_date=end,
            api_key=args.te_key,
        )
        rows = normalize_tradingeconomics_events(
            events,
            symbols=args.calendar_symbols,
            min_importance=args.te_min_importance,
        )
        for r in rows:
            r['days_from_as_of'] = (_parse_date(r['release_time']).date() - anchor.date()).days
        if not args.watch_releases:
            return rows

        watch_rows = [r for r in rows if _parse_date(r['release_time']).date() == anchor.date()]
        row_id = lambda r: r.get('calendar_id') or f"{r.get('release_time')}|{r.get('title')}"
        if target_ids is None:
            pending = [r for r in watch_rows if r.get('release_status') == 'waiting_actual']
            target_ids = {row_id(r) for r in pending} or {row_id(r) for r in watch_rows}

        target_rows = [r for r in watch_rows if row_id(r) in target_ids]
        released = [r for r in target_rows if r.get('release_status') == 'released']
        waiting = [r for r in target_rows if r.get('release_status') == 'waiting_actual']
        if released or not waiting or utc_now() >= deadline:
            return rows
        print(f"Waiting for actual values: {len(waiting)} pending today. Polling again in {args.poll_seconds}s.")
        time.sleep(args.poll_seconds)


def estimate_impacts(rows, symbols_hint=None, decay_days=30):
    now = max(r['date'] for r in rows) if rows else utc_now()
    per_sym = defaultdict(lambda: {'weighted': 0.0, 'volatility': 0.0, 'count': 0, 'last_date': None, 'last_catalyst': '', 'last_catalyst_vol': -1.0})
    market = {'weighted': 0.0, 'volatility': 0.0, 'count': 0, 'last_date': None, 'last_catalyst': '', 'last_catalyst_vol': -1.0}

    for r in rows:
        text = (r.get('title','') or '') + '\n' + (r.get('body','') or '')
        s = float(r.get('direction_score')) if r.get('direction_score') is not None else simple_sentiment(text)
        volatility = float(r.get('volatility_score') or 0.0)
        days = (now - r['date']).days if r['date'] else 0
        weight = math.exp(-days / decay_days)
        syms = split_symbols(r.get('symbols')) if r.get('symbols') else extract_symbols(text)
        if not syms and symbols_hint:
            syms = symbols_hint
        catalyst = r.get('title') or r.get('catalyst_category') or ''
        if syms:
            for sym in syms:
                per_sym[sym]['weighted'] += s * weight
                per_sym[sym]['volatility'] += volatility * weight
                per_sym[sym]['count'] += 1
                prev_date = per_sym[sym]['last_date']
                is_newer = prev_date is None or r['date'] > prev_date
                is_stronger_same_day = prev_date == r['date'] and volatility > per_sym[sym]['last_catalyst_vol']
                if is_newer or is_stronger_same_day:
                    per_sym[sym]['last_date'] = r['date']
                    per_sym[sym]['last_catalyst'] = catalyst
                    per_sym[sym]['last_catalyst_vol'] = volatility
        else:
            market['weighted'] += s * weight
            market['volatility'] += volatility * weight
            market['count'] += 1
            prev_date = market['last_date']
            is_newer = prev_date is None or r['date'] > prev_date
            is_stronger_same_day = prev_date == r['date'] and volatility > market['last_catalyst_vol']
            if is_newer or is_stronger_same_day:
                market['last_date'] = r['date']
                market['last_catalyst'] = catalyst
                market['last_catalyst_vol'] = volatility

    # normalize by sqrt(count) to dampen high-frequency bias
    summary = []
    for sym, v in per_sym.items():
        denom = math.sqrt(v['count']) if v['count'] else 1
        norm = v['weighted'] / denom
        vol_norm = v['volatility'] / denom
        summary.append({
            'symbol': sym,
            'total_weighted': v['weighted'],
            'volatility_weighted': v['volatility'],
            'count': v['count'],
            'norm_score': norm,
            'volatility_score': vol_norm,
            'last_date': v['last_date'].isoformat() if v['last_date'] else '',
            'last_catalyst': v['last_catalyst'],
        })
    # market summary
    if market['count']:
        denom = math.sqrt(market['count'])
        summary.append({
            'symbol': 'MARKET',
            'total_weighted': market['weighted'],
            'volatility_weighted': market['volatility'],
            'count': market['count'],
            'norm_score': market['weighted'] / denom,
            'volatility_score': market['volatility'] / denom,
            'last_date': market['last_date'].isoformat() if market['last_date'] else '',
            'last_catalyst': market['last_catalyst'],
        })
    # sort
    summary.sort(key=lambda x: (abs(x['norm_score']), x.get('volatility_score', 0.0)), reverse=True)
    return summary


def write_summary_csv(path, rows):
    keys = ['symbol','total_weighted','volatility_weighted','count','norm_score','volatility_score','last_date','last_catalyst']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_catalyst_csv(path, rows):
    keys = [
        'start_date','end_date','release_time','title','catalyst_category','importance','importance_raw',
        'country','category','reference','calendar_id','unit','scale',
        'release_status','previous','forecast','actual','previous_value','forecast_value','actual_value',
        'surprise','surprise_basis','raw_surprise_side','market_bias_side','market_bias_label',
        'market_bias_score','market_rule_direction','market_rule_confidence','market_rule_note',
        'direction_label','bullish_probability','bearish_probability',
        'market_move_probability','direction_score','volatility_score','days_from_as_of','symbols',
        'source','source_url','expected_effect'
    ]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            out = dict(r)
            out['symbols'] = ','.join(split_symbols(r.get('symbols')))
            writer.writerow({k: out.get(k, '') for k in keys})


def prefixed_output_path(prefix, output_path):
    folder, name = os.path.split(output_path)
    return os.path.join(folder, f"{prefix}{name}")


def run_forever_from_argv(loop_seconds):
    child_args = []
    raw_args = sys.argv[1:]
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == '--run-forever':
            i += 1
            continue
        if arg == '--loop-seconds':
            i += 2
            continue
        if arg.startswith('--loop-seconds='):
            i += 1
            continue
        child_args.append(arg)
        i += 1

    script_path = os.path.abspath(__file__)
    print(f"Starting 24/7 loop. Press Ctrl+C to stop. Interval: {loop_seconds}s.")
    try:
        while True:
            started = utc_now().isoformat(timespec='seconds')
            print(f"\n[{started}] Running one catalyst poll...")
            subprocess.run([sys.executable, script_path, *child_args], cwd=os.getcwd(), check=False)
            print(f"Sleeping {loop_seconds}s before next poll.")
            time.sleep(max(1, loop_seconds))
    except KeyboardInterrupt:
        print("\nStopped 24/7 loop.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--news-file', help='CSV file of news items (date,title,body)')
    p.add_argument('--yahoo-symbols', help='Comma-separated Yahoo Finance symbols to fetch news for')
    p.add_argument('--tradingview', action='store_true', help='Fetch TradingView site news (overview)')
    p.add_argument('--tradingview-symbols', help='Comma-separated symbols to filter TradingView headlines (optional)')
    p.add_argument('--symbols', help='Comma-separated symbol hints (e.g. AAPL,MSFT)')
    p.add_argument('--calendar', action='store_true', help='Include the built-in 2026 market catalyst calendar')
    p.add_argument('--catalyst-file', help='Optional CSV catalyst calendar with date,title/note columns')
    p.add_argument('--as-of', help='Anchor date for catalyst window, YYYY-MM-DD. Defaults to today.')
    p.add_argument('--lookback-days', type=int, default=2, help='Catalyst calendar lookback window')
    p.add_argument('--lookahead-days', type=int, default=14, help='Catalyst calendar lookahead window')
    p.add_argument('--calendar-symbols', default=','.join(DEFAULT_CALENDAR_SYMBOLS), help='Symbols impacted by macro catalysts')
    p.add_argument('--calendar-output', help='CSV path for filtered catalyst events')
    p.add_argument('--skip-closed-catalysts', action='store_true', help='Exclude market-closed holidays from catalyst output')
    p.add_argument('--tv-calendar', action='store_true', help='Fetch TradingView economic calendar rows with previous/forecast/actual values')
    p.add_argument('--tv-countries', default='us', help='Comma-separated TradingView economic calendar countries, e.g. us,ca')
    p.add_argument('--tv-min-importance', type=int, default=1, help='TradingView minimum importance: -1 low, 0 medium, 1 high')
    p.add_argument('--te-calendar', action='store_true', help='Fetch Trading Economics calendar rows with previous/forecast/actual values')
    p.add_argument('--te-key', default=os.environ.get('TRADING_ECONOMICS_KEY') or 'guest:guest', help='Trading Economics API key; defaults to TRADING_ECONOMICS_KEY or guest:guest')
    p.add_argument('--te-country', default='united states', help='Trading Economics country filter')
    p.add_argument('--te-min-importance', type=int, default=2, help='Minimum Trading Economics importance: 1 low, 2 medium, 3 high')
    p.add_argument('--macro-output', default='macro_releases.csv', help='CSV path for live macro release rows')
    p.add_argument('--watch-releases', action='store_true', help='Poll the live calendar until at least one actual value appears or watch timeout is reached')
    p.add_argument('--poll-seconds', type=int, default=60, help='Seconds between live calendar polls')
    p.add_argument('--watch-minutes', type=int, default=30, help='Maximum minutes to poll for actual values')
    p.add_argument('--run-forever', action='store_true', help='Run the same catalyst poll repeatedly until Ctrl+C')
    p.add_argument('--loop-seconds', type=int, default=60, help='Seconds between repeated --run-forever polls')
    p.add_argument('--output', default='news_summary.csv')
    p.add_argument('--top', type=int, default=20)
    p.add_argument('--decay-days', type=int, default=30)
    p.add_argument('--max-yahoo', type=int, default=25)
    args = p.parse_args()

    if args.run_forever:
        run_forever_from_argv(args.loop_seconds)
        return

    rows = []
    if args.news_file:
        rows.extend(parse_news_csv(args.news_file))

    providers_used = set()
    if args.yahoo_symbols:
        syms = [s.strip().upper() for s in args.yahoo_symbols.split(',') if s.strip()]
        for s in syms:
            fetched = fetch_yahoo_for_symbol(s, max_items=args.max_yahoo)
            rows.extend(fetched)
            if fetched:
                providers_used.add('yahoo')

    if args.tradingview:
        # fetch site-wide tradingview headlines (optionally filter by symbols if provided)
        tv_syms = [s.strip().upper() for s in (args.tradingview_symbols or '').split(',') if s.strip()]
        if tv_syms:
            for ts in tv_syms:
                fetched = fetch_tradingview_news(max_items=args.max_yahoo, symbol_hint=ts)
                rows.extend(fetched)
                if fetched:
                    providers_used.add('tradingview')
        else:
            fetched = fetch_tradingview_news(max_items=args.max_yahoo)
            rows.extend(fetched)
            if fetched:
                providers_used.add('tradingview')

    if args.tv_calendar:
        try:
            tv_macro_rows = fetch_tradingview_with_watch(args)
            rows.extend(tv_macro_rows)
            if tv_macro_rows:
                tv_macro_out = prefixed_output_path('tradingview_', args.macro_output) if args.te_calendar else args.macro_output
                write_catalyst_csv(tv_macro_out, tv_macro_rows)
                print(f'Fetched {len(tv_macro_rows)} macro release rows from TradingView. Wrote releases to {tv_macro_out}.')
                print('\nTradingView macro release window:')
                for r in tv_macro_rows[:args.top]:
                    bull = r.get('bullish_probability')
                    move = r.get('market_move_probability')
                    bull_txt = f"{float(bull):.0%}" if bull != '' and bull is not None else "n/a"
                    move_txt = f"{float(move):.0%}" if move != '' and move is not None else "n/a"
                    print(f"{r['release_time'][:16]:16}  {r['release_status']:14}  bull={bull_txt:>4}  move={move_txt:>4}  {r['title']}")
            else:
                print('Fetched 0 macro release rows from TradingView in the requested window.')
        except Exception as exc:
            print(f'TradingView calendar fetch failed: {exc}')

    if args.te_calendar:
        try:
            macro_rows = fetch_tradingeconomics_with_watch(args)
            rows.extend(macro_rows)
            if macro_rows:
                te_macro_out = prefixed_output_path('tradingeconomics_', args.macro_output) if args.tv_calendar else args.macro_output
                write_catalyst_csv(te_macro_out, macro_rows)
                print(f'Fetched {len(macro_rows)} macro release rows from Trading Economics. Wrote releases to {te_macro_out}.')
                print('\nMacro release window:')
                for r in macro_rows[:args.top]:
                    bull = r.get('bullish_probability')
                    move = r.get('market_move_probability')
                    bull_txt = f"{float(bull):.0%}" if bull != '' and bull is not None else "n/a"
                    move_txt = f"{float(move):.0%}" if move != '' and move is not None else "n/a"
                    print(f"{r['release_time'][:16]:16}  {r['release_status']:14}  bull={bull_txt:>4}  move={move_txt:>4}  {r['title']}")
            else:
                print('Fetched 0 macro release rows from Trading Economics in the requested window.')
        except Exception as exc:
            print(f'Trading Economics fetch failed: {exc}')

    catalyst_events = []
    if args.calendar:
        catalyst_events.extend(CATALYST_CALENDAR_2026)
    if args.catalyst_file:
        catalyst_events.extend(load_catalyst_csv(args.catalyst_file))

    catalyst_rows = []
    if catalyst_events:
        catalyst_rows = build_catalyst_rows(
            catalyst_events,
            as_of=args.as_of,
            lookback_days=args.lookback_days,
            lookahead_days=args.lookahead_days,
            symbols=args.calendar_symbols,
            include_closed=not args.skip_closed_catalysts,
        )
        rows.extend(catalyst_rows)
        if catalyst_rows:
            catalyst_out = args.calendar_output or prefixed_output_path('catalysts_', args.output)
            write_catalyst_csv(catalyst_out, catalyst_rows)
            print(f'Loaded {len(catalyst_rows)} scheduled catalysts. Wrote catalyst calendar to {catalyst_out}.')
            print('\nCatalyst window:')
            for r in catalyst_rows[:args.top]:
                print(f"{r['start_date']:10}  {r['importance']:7}  vol={r['volatility_score']:.2f}  {r['title']}")
        else:
            print('Loaded 0 scheduled catalysts in the requested window.')

    symbols_hint = [s.strip().upper() for s in args.symbols.split(',')] if args.symbols else None

    # Group by provider and produce per-provider summaries. If multiple providers are used,
    # write separate files named {provider}_{output}; otherwise write the single output file.
    if not rows:
        print(f'Processed 0 news items. Wrote summary to {args.output}.')
        print('\nTop impacts:\n')
        return

    rows_by_provider = defaultdict(list)
    for r in rows:
        prov = r.get('provider', 'unknown')
        rows_by_provider[prov].append(r)

    multiple = len(rows_by_provider) > 1
    all_summaries = {}
    for prov, prov_rows in rows_by_provider.items():
        summary = estimate_impacts(prov_rows, symbols_hint=symbols_hint, decay_days=args.decay_days)
        out_path = args.output
        if multiple:
            out_path = f"{prov}_{args.output}"
        write_summary_csv(out_path, summary)
        all_summaries[prov] = summary
        print(f'Processed {len(prov_rows)} items from {prov}. Wrote summary to {out_path}.')
        print(f"\nTop impacts for {prov}:")
        for r in summary[:args.top]:
            print(f"{r['symbol']:8}  norm={r['norm_score']:+.3f}  vol={r.get('volatility_score', 0.0):.3f}  count={r['count']}  last={r['last_date']}  catalyst={r.get('last_catalyst', '')}")


if __name__ == '__main__':
    main()
