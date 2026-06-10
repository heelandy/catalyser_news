#!/usr/bin/env python3
"""
Fetch and interpret fast market news for the NQ macro catalyst dashboard.

Default source is Yahoo Finance because it is faster and simpler than scraping
TradingView news pages. Auto mode tries Yahoo's search endpoint first, then
Yahoo RSS, then TradingView news-flow as a last fallback. TradingView may return
only browser-side placeholders when requested from a background script.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except Exception:  # pragma: no cover - dependency is optional at runtime
    SentimentIntensityAnalyzer = None


YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
TRADINGVIEW_NEWS_FLOW_URL = "https://www.tradingview.com/news-flow/?market=stock,etf,futures"
DEFAULT_SYMBOLS = "NQ=F,QQQ,SPY,^NDX,^IXIC,NVDA,AMD,SMH"

CSV_FIELDS = [
    "published_at",
    "provider",
    "source",
    "symbol",
    "symbols",
    "title",
    "summary",
    "url",
    "valid_until",
    "sentiment_score",
    "macro_score",
    "direction",
    "confidence",
    "categories",
    "themes",
    "risk_flags",
    "reason",
]

BEARISH_TERMS = {
    "payrolls jumped": 0.45,
    "nonfarm payrolls jumped": 0.50,
    "hawkish": 0.45,
    "rate hike": 0.45,
    "rate hikes": 0.45,
    "fed rate hike bets": 0.55,
    "fed-rate hike bets": 0.55,
    "higher yields": 0.35,
    "yield spike": 0.35,
    "higher inflation": 0.45,
    "hot inflation": 0.45,
    "sticky inflation": 0.40,
    "hot jobs": 0.40,
    "hot nfp": 0.45,
    "fed hike": 0.45,
    "fed-rate hike": 0.45,
    "selloff": 0.35,
    "sell-off": 0.35,
    "futures fall": 0.35,
    "futures drop": 0.35,
    "market whipsaw": 0.25,
    "market whipsaws": 0.25,
    "whipsaw": 0.20,
    "worst stretch": 0.30,
    "geopolitical": 0.25,
    "iran news": 0.25,
    "slump": 0.30,
    "plunge": 0.35,
    "risk-off": 0.45,
    "hammered": 0.35,
    "steepest decline": 0.40,
    "erased more than": 0.35,
    "market value": 0.20,
    "semiconductor selloff": 0.45,
    "chip selloff": 0.45,
    "chip stocks": 0.25,
    "ai unwind": 0.40,
    "unwind positions": 0.35,
    "ai boom": 0.20,
    "growth scare": 0.35,
    "dow jones should perform better": 0.25,
    "nasdaq underperform": 0.30,
}

BULLISH_TERMS = {
    "dovish": 0.45,
    "rate cut": 0.40,
    "rate cuts": 0.40,
    "lower yields": 0.35,
    "cooler inflation": 0.45,
    "soft inflation": 0.40,
    "soft jobs": 0.35,
    "risk-on": 0.45,
    "rally": 0.30,
    "rebound": 0.25,
    "relief": 0.25,
    "buying opportunity": 0.22,
    "surge": 0.25,
    "upgrade": 0.25,
    "beat estimates": 0.25,
}

CATEGORY_TERMS = {
    "rates": ("fed", "rate", "yields", "treasury", "powell", "fomc"),
    "inflation": ("inflation", "cpi", "ppi", "pce", "prices"),
    "labor": ("jobs", "payroll", "nfp", "unemployment", "jobless"),
    "chips_ai": ("chip", "semiconductor", "nvidia", "amd", "ai", "smh"),
    "index": ("nasdaq", "qqq", "nq", "technology", "growth stocks"),
    "geopolitical": ("iran", "war", "geopolitical", "middle east"),
    "risk": ("selloff", "slump", "plunge", "whipsaw", "risk-off", "volatility"),
}

NEWS_RULES = [
    ("nonfarm payrolls jumped", -0.50, "labor", "hot_labor"),
    ("payrolls jumped", -0.45, "labor", "hot_labor"),
    ("way higher than", -0.22, "labor", "upside_surprise"),
    ("fed rate hike bets", -0.55, "rates", "hawkish_fed"),
    ("fed-rate hike bets", -0.55, "rates", "hawkish_fed"),
    ("higher inflation", -0.45, "inflation", "inflation_pressure"),
    ("hot jobs", -0.40, "labor", "hot_labor"),
    ("hot nfp", -0.45, "labor", "hot_labor"),
    ("hawkish", -0.42, "rates", "hawkish_fed"),
    ("higher yields", -0.34, "rates", "yield_pressure"),
    ("chip stocks", -0.28, "chips_ai", "chip_pressure"),
    ("semiconductor sector", -0.25, "chips_ai", "chip_pressure"),
    ("semiconductor selloff", -0.48, "chips_ai", "chip_selloff"),
    ("chip selloff", -0.48, "chips_ai", "chip_selloff"),
    ("steepest decline", -0.40, "risk", "selloff_pressure"),
    ("hammered", -0.35, "risk", "selloff_pressure"),
    ("erased more than", -0.35, "risk", "market_cap_loss"),
    ("unwind positions", -0.35, "risk", "position_unwind"),
    ("ai boom", -0.20, "chips_ai", "ai_unwind_risk"),
    ("risk-off", -0.45, "risk", "risk_off"),
    ("futures fall", -0.35, "index", "futures_weak"),
    ("futures drop", -0.35, "index", "futures_weak"),
    ("dow jones should perform better", -0.25, "index", "growth_underperformance"),
    ("nasdaq underperform", -0.30, "index", "growth_underperformance"),
    ("cooler inflation", 0.45, "inflation", "cooling_inflation"),
    ("soft jobs", 0.35, "labor", "soft_labor"),
    ("rate cut", 0.38, "rates", "dovish_fed"),
    ("rate cuts", 0.38, "rates", "dovish_fed"),
    ("dovish", 0.42, "rates", "dovish_fed"),
    ("risk-on", 0.45, "risk", "risk_on"),
    ("rebound", 0.25, "index", "rebound"),
    ("rally", 0.30, "index", "rally"),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    text = re.sub(r"\s+", " ", html.unescape(text))
    return text


def parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = clean(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = parsedate_to_datetime(text)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def split_symbols(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def source_symbol(symbol: str) -> str:
    return symbol.upper().replace("^", "").replace("=F", "")


def request_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; nq-macro-catalyst/1.0)"}
    response = requests.get(url, params=params, timeout=timeout, headers=headers)
    response.raise_for_status()
    return response.json()


def request_text(url: str, params: dict[str, Any], timeout: int) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; nq-macro-catalyst/1.0)"}
    response = requests.get(url, params=params, timeout=timeout, headers=headers)
    response.raise_for_status()
    return response.text


def fetch_yahoo_symbol(symbol: str, max_items: int, timeout: int) -> list[dict[str, Any]]:
    data = request_json(
        YAHOO_SEARCH_URL,
        {"q": symbol, "newsCount": max_items, "quotesCount": 0},
        timeout,
    )
    rows = []
    for item in data.get("news", []) or []:
        title = clean(item.get("title"))
        if not title:
            continue
        rows.append(
            {
                "provider": "yahoo",
                "source": clean(item.get("publisher") or "Yahoo Finance"),
                "symbol": symbol,
                "symbols": source_symbol(symbol),
                "title": title,
                "summary": clean(item.get("summary") or ""),
                "url": clean(item.get("link") or ""),
                "published_at": parse_time(item.get("providerPublishTime")) or utc_now(),
            }
        )
    return rows


def fetch_yahoo_rss_symbol(symbol: str, max_items: int, timeout: int) -> list[dict[str, Any]]:
    xml_text = request_text(
        YAHOO_RSS_URL,
        {"s": symbol, "region": "US", "lang": "en-US"},
        timeout,
    )
    root = ET.fromstring(xml_text)
    rows = []
    for item in root.findall(".//item"):
        title = clean(item.findtext("title"))
        if not title:
            continue
        source = clean(item.findtext("source") or item.findtext("{*}source") or "Yahoo Finance RSS")
        rows.append(
            {
                "provider": "yahoo_rss",
                "source": source,
                "symbol": symbol,
                "symbols": source_symbol(symbol),
                "title": title,
                "summary": clean(item.findtext("description") or ""),
                "url": clean(item.findtext("link") or ""),
                "published_at": parse_time(item.findtext("pubDate")) or utc_now(),
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def normalize_tradingview_url(url: str) -> str:
    parsed = urlsplit(url or TRADINGVIEW_NEWS_FLOW_URL)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "market":
            markets = ["futures" if part.strip() == "future" else part.strip() for part in value.split(",")]
            value = ",".join(part for part in markets if part)
        query.append((key, value))
    if parsed.path.rstrip("/") == "/news-flow" and not any(key == "market" for key, _ in query):
        query.append(("market", "stock,etf,futures"))
    return urlunsplit(
        (
            parsed.scheme or "https",
            parsed.netloc or "www.tradingview.com",
            parsed.path or "/news-flow/",
            urlencode(query, safe=","),
            "",
        )
    )


def fetch_tradingview(max_items: int, timeout: int, url: str) -> list[dict[str, Any]]:
    feed_url = normalize_tradingview_url(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; nq-macro-catalyst/1.0)"}
    response = requests.get(feed_url, timeout=timeout, headers=headers)
    response.raise_for_status()
    page = response.text
    rows = []
    blocks = re.findall(r'<a[^>]+href="(?P<href>/news/[^"]+)"[^>]*>(?P<body>.*?)</a>', page, flags=re.I | re.S)
    seen = set()
    for href, body in blocks:
        text = re.sub(r"<[^>]+>", " ", body)
        title = clean(text)
        if len(title) < 20 or title in seen:
            continue
        seen.add(title)
        rows.append(
            {
                "provider": "tradingview_news_flow",
                "source": "TradingView",
                "symbol": "",
                "symbols": "",
                "title": title,
                "summary": "",
                "url": f"https://www.tradingview.com{href}",
                "published_at": utc_now(),
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def article_key(row: dict[str, Any]) -> str:
    return (clean(row.get("url")) or clean(row.get("title"))).lower()


def news_analysis(text: str) -> tuple[float, list[str], list[str], list[str]]:
    lowered = text.lower()
    score = 0.0
    hits: list[str] = []
    themes: set[str] = set()
    risk_flags: set[str] = set()
    matched_terms: set[str] = set()
    for term, weight, theme, flag in NEWS_RULES:
        if term in lowered:
            score += weight
            hits.append(term)
            matched_terms.add(term)
            themes.add(theme)
            risk_flags.add(flag)
    for term, weight in BEARISH_TERMS.items():
        if term not in matched_terms and term in lowered:
            score -= weight
            hits.append(term)
            matched_terms.add(term)
    for term, weight in BULLISH_TERMS.items():
        if term not in matched_terms and term in lowered:
            score += weight
            hits.append(term)
            matched_terms.add(term)

    if "hot_labor" in risk_flags and ("hawkish_fed" in risk_flags or "inflation_pressure" in risk_flags):
        score -= 0.18
        risk_flags.add("macro_policy_pressure")
    if {"chip_selloff", "position_unwind"} & risk_flags and {"selloff_pressure", "market_cap_loss"} & risk_flags:
        score -= 0.12
        risk_flags.add("nq_growth_pressure")
    if {"growth_underperformance", "chip_pressure", "chip_selloff"} & risk_flags:
        themes.add("index")
        risk_flags.add("nq_relative_weakness")

    return max(-1.0, min(1.0, score)), hits, sorted(themes), sorted(risk_flags)


def macro_score(text: str) -> tuple[float, list[str]]:
    score, hits, _, _ = news_analysis(text)
    return score, hits


def categories(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for category, terms in CATEGORY_TERMS.items():
        if any(term in lowered for term in terms):
            found.append(category)
    return found or ["market"]


def sentiment_score(text: str) -> float:
    if not text:
        return 0.0
    if SentimentIntensityAnalyzer is not None:
        return float(SentimentIntensityAnalyzer().polarity_scores(text)["compound"])
    words = re.findall(r"[a-zA-Z]+", text.lower())
    pos = sum(1 for word in words if word in {"rally", "gain", "surge", "beat", "strong", "upgrade"})
    neg = sum(1 for word in words if word in {"selloff", "drop", "slump", "miss", "weak", "downgrade"})
    return 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)


def interpret(row: dict[str, Any]) -> dict[str, Any]:
    text = " ".join([clean(row.get("title")), clean(row.get("summary"))])
    sent = sentiment_score(text)
    macro, hits, themes, risk_flags = news_analysis(text)
    blended = (macro * 0.85) + (sent * 0.15)
    if blended >= 0.18:
        direction = "bullish"
    elif blended <= -0.18:
        direction = "bearish"
    else:
        direction = "mixed"
    confidence = max(0.10, min(0.92, abs(blended) + min(0.20, len(hits) * 0.03)))
    cats = sorted(set(categories(text)) | set(themes))
    reason_parts = []
    if hits:
        reason_parts.append("terms=" + "|".join(hits[:5]))
    if themes:
        reason_parts.append("themes=" + "|".join(themes[:5]))
    if risk_flags:
        reason_parts.append("flags=" + "|".join(risk_flags[:5]))
    reason_parts.append(f"macro={macro:.2f}")
    reason_parts.append(f"sentiment={sent:.2f}")
    return {
        **row,
        "sentiment_score": sent,
        "macro_score": macro,
        "direction": direction,
        "confidence": confidence,
        "categories": ";".join(cats),
        "themes": ";".join(themes),
        "risk_flags": ";".join(risk_flags),
        "reason": ", ".join(reason_parts),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            out = {field: row.get(field, "") for field in CSV_FIELDS}
            if isinstance(out["published_at"], datetime):
                out["published_at"] = iso_z(out["published_at"])
            writer.writerow(out)


def split_field(value: Any) -> list[str]:
    return [part.strip() for part in clean(value).split(";") if part.strip()]


def news_bias(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("direction") in {"bullish", "bearish"}]
    score = sum(float(row.get("confidence") or 0.0) * (1 if row.get("direction") == "bullish" else -1) for row in scored)
    score = max(-1.0, min(1.0, score / max(1, len(scored))))
    if score >= 0.18:
        direction = "bullish"
    elif score <= -0.18:
        direction = "bearish"
    else:
        direction = "mixed"
    confidence = max(0.0, min(0.80, abs(score) + min(0.20, len(scored) * 0.03)))
    top = sorted(scored, key=lambda row: float(row.get("confidence") or 0.0), reverse=True)[:3]
    reason = "; ".join(f"{row['direction']} {row['title']}" for row in top) or "No directional news interpretation"
    themes = sorted({theme for row in rows for theme in split_field(row.get("themes") or row.get("categories"))})
    risk_flags = sorted({flag for row in rows for flag in split_field(row.get("risk_flags"))})
    return {
        "direction": direction,
        "confidence": confidence,
        "score": score,
        "reason": reason,
        "headline": clean(top[0].get("title")) if top else "",
        "themes": themes,
        "risk_flags": risk_flags,
        "article_count": len(rows),
        "directional_count": len(scored),
    }


def context_payload(rows: list[dict[str, Any]], now: datetime, valid_minutes: int) -> dict[str, Any]:
    bias = news_bias(rows)
    return {
        "items": [
            {
                "valid_until": iso_z(now + timedelta(minutes=valid_minutes)),
                "source": "macro_news_feed",
                "direction": bias["direction"],
                "confidence": bias["confidence"],
                "headline": bias["headline"],
                "reason": bias["reason"],
                "themes": bias["themes"],
                "risk_flags": bias["risk_flags"],
                "article_count": bias["article_count"],
                "directional_count": bias["directional_count"],
            }
        ]
    }


def summary_payload(
    rows: list[dict[str, Any]],
    errors: list[str],
    attempts: list[dict[str, Any]],
    source_used: str,
    now: datetime,
) -> dict[str, Any]:
    counts = {"bullish": 0, "bearish": 0, "mixed": 0}
    for row in rows:
        counts[row.get("direction", "mixed")] = counts.get(row.get("direction", "mixed"), 0) + 1
    bias = news_bias(rows)
    return {
        "checked_at": iso_z(now),
        "source_used": source_used,
        "provider_attempts": attempts,
        "rows": len(rows),
        "direction_counts": counts,
        "news_bias": bias["direction"],
        "news_bias_score": bias["score"],
        "news_bias_confidence": bias["confidence"],
        "themes": bias["themes"],
        "risk_flags": bias["risk_flags"],
        "latest_titles": [clean(row.get("title")) for row in rows[:5]],
        "errors": errors,
    }


def is_fresh(path: Path, minutes: int) -> bool:
    if minutes <= 0 or not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age <= minutes * 60


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch and interpret fast NQ-relevant market news.")
    p.add_argument("--provider", choices=["yahoo", "yahoo_rss", "tradingview", "auto"], default="auto")
    p.add_argument("--tradingview-news-url", default=TRADINGVIEW_NEWS_FLOW_URL)
    p.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    p.add_argument("--max-per-symbol", type=int, default=8)
    p.add_argument("--max-items", type=int, default=40)
    p.add_argument("--lookback-hours", type=float, default=12.0)
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--cache-minutes", type=int, default=10)
    p.add_argument("--force", action="store_true")
    p.add_argument("--output", default="macro_news_feed.csv")
    p.add_argument("--context-output", default="macro_news_context.json")
    p.add_argument("--summary-output", default="macro_news_feed_summary.json")
    p.add_argument("--context-valid-minutes", type=int, default=45)
    return p.parse_args()


def fetch_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], str]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    source_used = ""
    providers = ["yahoo", "yahoo_rss", "tradingview"] if args.provider == "auto" else [args.provider]
    for provider in providers:
        try:
            if provider == "yahoo":
                before = len(rows)
                for symbol in split_symbols(args.symbols):
                    rows.extend(fetch_yahoo_symbol(symbol, args.max_per_symbol, args.timeout))
                attempts.append({"provider": provider, "ok": True, "rows": len(rows) - before})
            elif provider == "yahoo_rss":
                before = len(rows)
                for symbol in split_symbols(args.symbols):
                    rows.extend(fetch_yahoo_rss_symbol(symbol, args.max_per_symbol, args.timeout))
                attempts.append({"provider": provider, "ok": True, "rows": len(rows) - before})
            else:
                before = len(rows)
                rows.extend(fetch_tradingview(args.max_items, args.timeout, args.tradingview_news_url))
                if len(rows) == before:
                    normalized = normalize_tradingview_url(args.tradingview_news_url)
                    warning = (
                        "tradingview: no static headlines found at "
                        f"{normalized}; TradingView may be serving this feed through browser-side JavaScript"
                    )
                    errors.append(warning)
                    attempts.append({"provider": provider, "ok": True, "rows": 0, "warning": warning})
                else:
                    attempts.append({"provider": provider, "ok": True, "rows": len(rows) - before})
            if rows:
                source_used = provider
                break
        except Exception as exc:
            error = f"{provider}: {exc}"
            errors.append(error)
            attempts.append({"provider": provider, "ok": False, "rows": 0, "error": str(exc)})
    return rows, errors, attempts, source_used


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    context_output = Path(args.context_output)
    summary_output = Path(args.summary_output)
    if not args.force and is_fresh(output, args.cache_minutes) and context_output.exists():
        print(f"News feed cache is fresh: {output}")
        return

    now = utc_now()
    raw_rows, errors, attempts, source_used = fetch_rows(args)
    cutoff = now - timedelta(hours=args.lookback_hours)
    deduped: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        published = row.get("published_at")
        if not isinstance(published, datetime):
            published = parse_time(published) or now
            row["published_at"] = published
        if published < cutoff:
            continue
        key = article_key(row)
        if key and key not in deduped:
            interpreted = interpret(row)
            interpreted["valid_until"] = iso_z(now + timedelta(minutes=args.context_valid_minutes))
            deduped[key] = interpreted

    rows = sorted(deduped.values(), key=lambda row: row.get("published_at") or now, reverse=True)[: args.max_items]
    write_csv(output, rows)
    context_output.write_text(json.dumps(context_payload(rows, now, args.context_valid_minutes), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_output.write_text(json.dumps(summary_payload(rows, errors, attempts, source_used, now), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} interpreted news rows to {output}.")
    if errors:
        print("News fetch warnings: " + "; ".join(errors))


if __name__ == "__main__":
    main()
