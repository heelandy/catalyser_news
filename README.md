# NQ Macro Catalyst Lab

A modular Python workspace for studying how U.S. macroeconomic releases affect
Nasdaq futures (`NQ=F`) and for validating trading results. The system keeps
each responsibility separate:

- `fetch_nq_yahoo.py` downloads market OHLC data from Yahoo Finance.
- `catalyser_news.py` watches scheduled catalysts and live economic-calendar rows.
- `macro_reaction_study.py` learns how NQ historically reacted to macro surprises.
- `hs_validation.py` and the fill converters validate trade logs separately.

This is research tooling, not financial advice. Live-market use needs monitoring,
logging, and broker/risk controls before any automation is connected to orders.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 1. Fetch Market Data

Download the current intraday NQ inputs used by the reaction study:

```powershell
python .\fetch_nq_yahoo.py --preset intraday
```

That creates:

- `NQ_1min_data.csv` using Yahoo's 7-day 1-minute window.
- `NQ_5min_data.csv` using a 30-day 5-minute window.

Use custom ticker, interval, period, or date ranges when you want a different
timeframe:

```powershell
python .\fetch_nq_yahoo.py --ticker NQ=F --interval 15m --period 60d --out-csv NQ_15min_data.csv
python .\fetch_nq_yahoo.py --ticker ES=F --interval 5m --period 30d --out-csv ES_5min_data.csv
python .\fetch_nq_yahoo.py --ticker NQ=F --interval 5m --start-date 2026-05-01 --end-date 2026-06-05 --out-csv NQ_custom_5m.csv
```

The default command still preserves the older daily NQ files:

```powershell
python .\fetch_nq_yahoo.py
```

## 2. Build Macro Reaction Profiles

Fetch historical U.S. TradingView economic-calendar rows and align them to NQ
bars:

```powershell
python .\macro_reaction_study.py --fetch-tv-events --start-date 2026-05-01 --end-date 2026-06-05 --market-data .\NQ_5min_data.csv --symbol NQ --tv-min-importance 1 --fetched-events-output macro_events_history_2026_05_06.csv --reaction-output macro_reactions_5m.csv --profile-output macro_reaction_profiles_5m.csv --min-events 1
```

Outputs:

- `macro_events_history_2026_05_06.csv`: fetched macro events.
- `macro_reactions_5m.csv`: each event matched to price reaction windows.
- `macro_reaction_profiles_5m.csv`: learned probabilities by catalyst family
  and surprise side.

The reaction learner keeps two separate surprise interpretations:

- `surprise_side`: the raw number direction, such as actual above forecast.
- `market_bias_side`: the market-adjusted interpretation, such as hotter CPI
  becoming `market_negative` for NQ while stronger PMI can become
  `market_positive`.

New profile groups prefer `event_family_market_bias` and
`category_market_bias`, then fall back to the older raw-surprise groups.

For stronger probabilities, expand the history window and use more observations:

```powershell
python .\macro_reaction_study.py --fetch-tv-events --start-date 2025-01-01 --end-date 2026-06-05 --market-data .\NQ_5min_data.csv --symbol NQ --tv-min-importance 0 --min-events 5
```

Yahoo limits intraday history, so deeper 1-minute or 5-minute studies may need a
dedicated futures data source.

## 3. Watch Live Catalysts

Pull the built-in 2026 catalyst calendar plus TradingView economic-calendar rows:

```powershell
python .\catalyser_news.py --calendar --tv-calendar --tv-countries us --tv-min-importance 1 --macro-output macro_releases.csv --output catalyst_scores.csv
```

Poll around release time until actual values appear:

```powershell
python .\catalyser_news.py --tv-calendar --watch-releases --poll-seconds 15 --watch-minutes 30 --macro-output macro_releases.csv
```

For 24/7 operation:

```powershell
python .\catalyser_news.py --calendar --tv-calendar --watch-releases --run-forever --loop-seconds 60 --macro-output macro_releases.csv --output catalyst_scores.csv
```

Calibrate live releases with learned reaction profiles:

```powershell
python .\macro_reaction_study.py --calibrate-live macro_releases.csv --profiles macro_reaction_profiles_5m.csv --calibrated-output macro_releases_calibrated.csv
```

Calibrated output includes the live rule fields:

- `raw_surprise_side`
- `market_bias_side`
- `market_bias_label`
- `market_bias_score`
- `market_rule_direction`
- `market_rule_confidence`
- `market_rule_note`

## 4. Validate Trades

Convert broker/exported fills into round-trip trades:

```powershell
python .\tradovate_fills_to_trades.py --fills Orders.csv --out nq_trades.csv
python .\tradingview_fills_to_trades.py --fills Fills.csv --out nq_trades.csv
```

Run the statistical validation engine:

```powershell
python .\hs_validation.py --trades nq_trades.csv --symbol NQ --capital 50000
python .\hs_validation.py --market-data NQ_F_daily.csv --symbol NQ --capital 50000 --walkforward --walkforward-output walkforward_folds.csv --stress-periods default --stress-output stress_periods.csv --cost-per-contract 2
```

Synthetic sample data is included for pipeline tests:

```powershell
python .\make_nq_sample.py --n 400 --out nq_sample_trades.csv
python .\hs_validation.py --trades nq_sample_trades.csv --symbol NQ --capital 50000
```

## Important Files

| File | Purpose |
| --- | --- |
| `fetch_nq_yahoo.py` | Dynamic Yahoo market-data downloader. |
| `catalyser_news.py` | Catalyst calendar, news, live macro release watcher, probability scoring. |
| `macro_reaction_study.py` | Historical event-to-price reaction study and live-release calibration. |
| `hs_validation.py` | Trade-list validation, Monte Carlo, walk-forward, stress tests. |
| `build_market_data_store.py` | Optional DuckDB/Parquet market-data store builder. |
| `tradovate_fills_to_trades.py` | Tradovate fills to round-trip trades. |
| `tradingview_fills_to_trades.py` | TradingView fills to round-trip trades. |
| `make_nq_sample.py` | Synthetic NQ trades for validation tests. |
| `requirements.txt` | Python dependencies. |

## Data Notes

Generated market files such as `NQ_1min_data.csv`, `NQ_5min_data.csv`, and
`macro_reaction_profiles_5m.csv` are reproducible research artifacts. Private
broker exports such as raw fills, order-history exports, and account journals
should stay local unless you intentionally want them in a public repository.

## Current Pipeline Status

As of the latest local run:

- `NQ_1min_data.csv`: 7,860 rows from 2026-05-29 04:09 to 2026-06-05 20:59.
- `NQ_5min_data.csv`: 6,652 rows from 2026-05-01 04:05 to 2026-06-05 20:55.
- `macro_reaction_study.py` matched 27 TradingView U.S. macro events to NQ
  5-minute bars and produced 36 reaction-profile rows.

## GitHub Upload Checklist

The repo target for this workspace is:

```text
https://github.com/heelandy/catalyser_news.git
```

Preferred path if Git is installed:

```powershell
git init
git add .
git commit -m "Initial macro catalyst lab"
git branch -M main
git remote add origin https://github.com/heelandy/catalyser_news.git
git push -u origin main
```

Fallback path without Git:

```powershell
$env:GITHUB_TOKEN = "YOUR_TOKEN_WITH_CONTENTS_WRITE"
python .\upload_to_github.py
```

`upload_to_github.py` uses an explicit file allowlist so private broker exports
do not accidentally upload to a public repository.
