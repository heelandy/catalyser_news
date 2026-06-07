# NQ Macro Catalyst Lab

A modular Python workspace for studying how U.S. macroeconomic releases affect
Nasdaq futures (`NQ=F`) and for validating trading results. The system keeps
each responsibility separate:

- `fetch_nq_yahoo.py` downloads market OHLC data from Yahoo Finance.
- `catalyser_news.py` watches scheduled catalysts and live economic-calendar rows.
- `macro_reaction_study.py` learns how NQ historically reacted to macro surprises.
- `macro_signal_performance.py` grades signal predictions after releases occur.
- `macro_signal_trust.py` feeds those grades back into live signal probabilities.
- `macro_pipeline_runner.py` runs the separated modules in a repeatable loop.
- `dashboard/` displays the adjusted signals, performance, and trust weights.

Older validation tools, broker exports, sample files, duplicate parquet outputs,
and one-off test artifacts are archived under `extra/` so the root stays focused
on the macro catalyst engine.

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
- `NQ_5min_data.csv` using a 60-day 5-minute window when Yahoo allows it.

For a broader Yahoo pull:

```powershell
python .\fetch_nq_yahoo.py --preset intraday-deep
```

That adds:

- `NQ_15min_data.csv`
- `NQ_60min_data.csv`

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
python .\macro_reaction_study.py --fetch-tv-events --start-date 2026-03-26 --end-date 2026-06-05 --market-data .\NQ_5min_data.csv --symbol NQ --tv-min-importance 1 --fetched-events-output macro_events_history_2026_03_26_06_05.csv --cluster-output macro_event_clusters_5m_60d.csv --reaction-output macro_reactions_5m.csv --profile-output macro_reaction_profiles_5m.csv --min-events 1
```

Outputs:

- `macro_events_history_2026_03_26_06_05.csv`: fetched macro events.
- `macro_event_clusters_5m_60d.csv`: same-timestamp release clusters.
- `macro_reactions_5m.csv`: each release moment matched to price reaction windows.
- `macro_reaction_profiles_5m.csv`: learned probabilities by catalyst family
  and surprise side.

The reaction learner keeps two separate surprise interpretations:

- `surprise_side`: the raw number direction, such as actual above forecast.
- `market_bias_side`: the market-adjusted interpretation, such as hotter CPI
  becoming `market_negative` for NQ while stronger PMI can become
  `market_positive`.

New profile groups prefer `event_family_market_bias` and
`category_market_bias`, then fall back to the older raw-surprise groups.

Profiles use Bayesian smoothing by default, so small samples no longer report
overconfident raw probabilities. Both raw and smoothed columns are kept:

- `raw_bullish_probability`
- `bullish_probability`
- `raw_market_move_probability`
- `market_move_probability`
- `sample_confidence`
- `confidence_label`

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
python .\macro_reaction_study.py --calibrate-live macro_releases.csv --profiles macro_reaction_profiles_5m.csv --calibrated-output macro_releases_calibrated.csv --live-signal-output macro_live_signal.csv
```

Calibrated output includes the live rule fields:

- `raw_surprise_side`
- `market_bias_side`
- `market_bias_label`
- `market_bias_score`
- `market_rule_direction`
- `market_rule_confidence`
- `market_rule_note`

The compact UI contract is `macro_live_signal.csv`. It includes:

- `release_time`
- `title`
- `actual`, `forecast`, `previous`
- `surprise`
- `market_bias_side`
- `historical_sample_size`
- `historical_bullish_probability`
- `calibrated_bullish_probability`
- `expected_direction`
- `confidence`
- `warning`

## 4. Grade Signal Performance

After releases have occurred and reaction files exist, grade predictions against
actual NQ movement:

```powershell
python .\macro_signal_performance.py --signals .\macro_live_signal.csv --reactions .\macro_reactions_1m.csv .\macro_reactions_5m.csv .\macro_reactions_60m.csv --reaction-labels 1m 5m 60m --windows-minutes 5,15,30,60,240,390 --primary-window-minutes 60 --grades-output macro_signal_grades.csv --performance-output macro_signal_performance.csv
```

Outputs:

- `macro_signal_grades.csv`: one row per signal/reaction source with actual
  5m, 15m, 30m, 60m, 240m, and 390m outcomes where available.
- `macro_signal_performance.csv`: dashboard-ready accuracy summaries by source,
  family, category, bias, confidence, and family+bias.

## 5. Apply Trust Calibration

Turn the performance summary into probability trust weights, then create the
UI-ready adjusted signal contract:

```powershell
python .\macro_signal_trust.py --signals .\macro_live_signal.csv --performance .\macro_signal_performance.csv --weights-output macro_signal_trust_weights.csv --adjusted-output macro_live_signal_adjusted.csv
```

Outputs:

- `macro_signal_trust_weights.csv`: reusable trust weights by event family,
  category, market bias, confidence, and fallback groups.
- `macro_live_signal_adjusted.csv`: live signals with original probabilities
  preserved and final trust-adjusted fields appended.

The UI should prefer these final fields when they are present:

- `final_bullish_probability`
- `final_bearish_probability`
- `final_expected_direction`
- `final_confidence`
- `final_confidence_label`
- `final_warning`

Strong historical groups can boost an edge. Weak, low-sample, or whippy groups
pull the probability back toward neutral. Broad fallback groups such as
`market_bias_side`, `confidence_label`, and `overall` can discount weak signals,
but their boosts are capped so unrelated history does not over-strengthen a
new event type.

## 6. Run The Pipeline

Run one complete live cycle:

```powershell
python .\macro_pipeline_runner.py
```

Default cycle:

- fetch current live macro rows into `macro_releases.csv`
- calibrate them into `macro_live_signal.csv`
- apply trust weights into `macro_live_signal_adjusted.csv`

For release-time polling and continuous operation:

```powershell
python .\macro_pipeline_runner.py --run-forever --watch-releases --loop-seconds 60
```

Optional switches:

- `--market-preset intraday` refreshes Yahoo data before the live cycle.
- `--refresh-performance` rebuilds signal grades and performance summaries when
  reaction files are already current.
- `--dry-run` prints the stage commands without executing them.
- `--stop-on-error` exits a forever run after a failed cycle.

The runner writes `macro_pipeline_runner.log` and `macro_pipeline_status.json`
for monitoring. These local runtime files are not included in the GitHub upload
allowlist.

### When Direction Probability Updates

The system can show a preliminary direction probability before the actual number
is released when it has a forecast/previous value and matching history. That
pre-release probability is based on `forecast_vs_previous`.

The stronger signal appears after the actual value is published by the calendar
source and the pipeline runs:

- `catalyser_news.py` sees the actual value on the next poll.
- `macro_reaction_study.py` calibrates the release against historical profiles.
- `macro_signal_trust.py` applies the feedback weights.
- `macro_live_signal_adjusted.csv` receives the final UI fields.

With `--watch-releases --poll-seconds 15`, expect the local CSV/dashboard to
update about 15-30 seconds after TradingView exposes the actual number, plus a
few seconds for processing. If the runner is using `--loop-seconds 60` without
release polling, the update can take up to the next loop cycle.

## 7. Start The Dashboard Locally

Serve the workspace root and open the dashboard:

```powershell
cd "C:\Users\heela\OneDrive\Área de Trabalho\python nq"
python -m http.server 8787 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:8787/dashboard/
```

The dashboard reads:

- `macro_live_signal_adjusted.csv`
- `macro_signal_performance.csv`
- `macro_signal_trust_weights.csv`
- `macro_pipeline_status.json` when the runner has created it locally

Views:

- Signals: live catalyst table, final probabilities, filters, and detail panel.
- Performance: accuracy, whipsaw summaries, and event-family performance chart.
- Trust: feedback weights and trust-weight chart used by the adjusted signal
  contract.

## 8. Archived Extras

The `extra/` folder contains side tools and old generated artifacts that are not
part of the current catalyst engine workflow. Examples include:

- trade/fill converters
- HIGHSTRIKE validation scripts
- broker export CSVs
- old test outputs
- duplicate parquet files
- local upload zip/cache material

Those files are kept for reference, not deleted.

## Important Files

| File | Purpose |
| --- | --- |
| `fetch_nq_yahoo.py` | Dynamic Yahoo market-data downloader. |
| `catalyser_news.py` | Catalyst calendar, news, live macro release watcher, probability scoring. |
| `macro_reaction_study.py` | Historical event-to-price reaction study and live-release calibration. |
| `macro_signal_performance.py` | Post-release prediction grading and performance summaries. |
| `macro_signal_trust.py` | Performance feedback layer for trust-adjusted live probabilities. |
| `macro_pipeline_runner.py` | 24/7 orchestration layer that calls the separate modules in order. |
| `dashboard/index.html` | Local browser dashboard for adjusted macro signals. |
| `dashboard/app.js` | CSV loader, filters, tables, and detail panel for the dashboard. |
| `dashboard/styles.css` | Dashboard visual system and responsive layout. |
| `macro_live_signal.csv` | Compact UI-ready live signal contract. |
| `macro_live_signal_adjusted.csv` | UI-ready trust-adjusted live signal contract. |
| `macro_reaction_profiles_5m.csv` | Smoothed historical reaction probabilities. |
| `macro_reaction_profiles_60m.csv` | Deeper 2024-2026 hourly reaction probabilities. |
| `macro_event_clusters_5m_60d.csv` | Same-timestamp macro release clusters. |
| `macro_signal_grades.csv` | Per-signal outcome grade rows. |
| `macro_signal_performance.csv` | Dashboard-ready model accuracy summary. |
| `macro_signal_trust_weights.csv` | Accuracy/whipsaw-based trust weights used by `macro_signal_trust.py`. |
| `extra/` | Archived side tools, private exports, and old generated artifacts. |
| `requirements.txt` | Python dependencies. |

## Data Notes

Generated market files such as `NQ_1min_data.csv`, `NQ_5min_data.csv`, and
`macro_reaction_profiles_5m.csv` are reproducible research artifacts. Private
broker exports such as raw fills, order-history exports, and account journals
should stay local unless you intentionally want them in a public repository.

## Current Pipeline Status

As of the latest local run:

- `NQ_1min_data.csv`: 7,860 rows from 2026-05-29 04:09 to 2026-06-05 20:59.
- `NQ_5min_data.csv`: 13,552 rows from 2026-03-26 04:05 to 2026-06-05 20:55.
- `NQ_15min_data.csv`: 4,537 rows from 2026-03-26 04:00 to 2026-06-05 20:45.
- `NQ_60min_data.csv`: 13,680 rows from 2024-01-12 05:00 to 2026-06-05 20:00.
- Yahoo rejected 30 days of 1-minute NQ data and reported that only about 8
  days of 1m granularity are available per request.
- `macro_reaction_study.py` clustered 51 TradingView U.S. macro event rows into
  37 release moments and produced smoothed 5-minute reaction profiles.
- The deeper 60-minute study fetched 381 high-importance TradingView event rows,
  clustered them into 282 release moments, and produced 85 profile rows.
- `macro_signal_performance.py` produced 24 graded signal/source rows and 51
  performance summary rows from the current 1m, 5m, and 60m reaction sets.
- `macro_signal_trust.py` produced 51 trust-weight rows and 14 trust-adjusted
  live signal rows.
- `macro_pipeline_runner.py --dry-run` verified the default stage order:
  live fetch, calibration, and trust adjustment.
- `dashboard/` serves from the workspace root and loads the adjusted signal,
  performance, and trust CSVs over HTTP.
- The dashboard now includes probability timeline, event-family performance,
  and trust-weight charts.

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
