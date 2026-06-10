# NQ Macro Catalyst Lab

A modular Python workspace for studying how U.S. macroeconomic releases affect
Nasdaq futures (`NQ=F`) and for validating trading results. The system keeps
each responsibility separate:

- `fetch_nq_yahoo.py` downloads market OHLC data from Yahoo Finance.
- `market_data_backfill.py` plans missing market-data ranges before download.
- `market_data_verify.py` verifies newly added market-data exports before use.
- `futures_data_adapter.py` normalizes deeper external futures CSV exports.
- `dabento_nq_adapter.py` normalizes Dabento NQ OHLCV exports.
- `catalyser_news.py` watches scheduled catalysts and live economic-calendar rows.
- `macro_reaction_study.py` learns how NQ historically reacted to macro surprises.
- `macro_signal_performance.py` grades signal predictions after releases occur.
- `macro_signal_trust.py` feeds those grades back into live signal probabilities.
- `macro_data_quality.py` checks market-data health and release coverage.
- `macro_probability_validation.py` checks probability calibration.
- `macro_timing_audit.py` checks release-time alignment to market bars.
- `macro_pipeline_runner.py` runs the separated modules in a repeatable loop.
- `macro_pipeline_alerts.py` detects release-state and runner-health changes.
- `macro_alert_notify.py` sends optional notifications for newly detected alerts.
- `macro_daily_confirmation.py` adds the temporary daily baseline confirmation.
- `macro_regime.py` separates release-rule direction from live-market regime.
- `macro_news_feed.py` fetches and interprets fast Yahoo JSON, Yahoo RSS, and
  optional TradingView headlines.
- `dashboard/` displays the current signals, performance, and trust weights.

Older validation tools, broker exports, sample files, duplicate parquet outputs,
and one-off test artifacts are archived under `extra/` so the root stays focused
on the macro catalyst engine.

This is research tooling, not financial advice. Live-market use needs monitoring,
logging, and broker/risk controls before any automation is connected to orders.

Default downloader: Yahoo. The active local research feed can also point to
verified Dabento-derived files when those are available in the workspace.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Quick Start: Repository To Live Pipeline

Use this sequence when starting from GitHub and ending with the dashboard plus
the live macro pipeline running in the background.

Clone the repository the first time:

```powershell
cd "<parent folder where you keep trading projects>"
git clone https://github.com/heelandy/catalyser_news.git "python nq Catalyst"
cd ".\python nq Catalyst"
```

If the repository already exists locally, update it instead:

```powershell
cd "<path to python nq Catalyst>"
git pull --ff-only
```

Create or refresh the Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Restore any private/local market-data files that are intentionally not committed
to Git. Large vendor files and raw exports are ignored by `.gitignore`, so a
fresh clone will not include files such as `dabento/`, `NQ_dabento_full_*data.csv`,
`Dataset_*.csv`, or `NQ_in_*.csv`. The normal live calendar pipeline can run
from the committed profile and signal files, but quality/performance refreshes
that reference full market data need those ignored files restored or
`market_data_config.json` updated.

Run a dry check before starting the live loop:

```powershell
python .\macro_pipeline_runner.py --dry-run
```

Start the dashboard HTTP server from the repository root. Keep this shell open,
or start it in the background as shown below.

```powershell
python -m http.server 8787 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8787/dashboard/
```

Optional background dashboard server:

```powershell
$server = Start-Process -FilePath "python" -ArgumentList @("-m", "http.server", "8787", "--bind", "127.0.0.1") -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
$server.Id
```

Start the live pipeline in the background. This is the command that pulls live
calendar rows, watches for actual values, recalibrates signals, updates the
dashboard CSVs, and runs the alert detector every cycle.

```powershell
$runner = Start-Process -FilePath "python" -ArgumentList @(".\macro_pipeline_runner.py", "--run-forever", "--watch-releases", "--loop-seconds", "60") -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
$runner.Id
```

Verify that it is running:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "macro_pipeline_runner.py" } |
  Select-Object ProcessId, CommandLine

Get-Content .\macro_pipeline_status.json
Get-Content .\macro_pipeline_runner.log -Tail 80
Get-Content .\macro_pipeline_alert_summary.json
```

Operational notes:

- Do not use `--dry-run` for live operation; it prints commands but does not
  fetch or update files.
- The dashboard only serves and displays local files. It does not fetch new
  release data by itself.
- `--watch-releases` polls the calendar every 15 seconds while the command is
  within its watch window. `--run-forever --loop-seconds 60` keeps restarting
  cycles so upcoming releases are picked up without manual action.
- Raw `release_time` values in the CSV are UTC timestamps without a timezone
  suffix. The dashboard displays them in ET and shows UTC in the hover title.

Live-regime override:

- The release rule and the live market regime are intentionally separate. A
  catalyst can be `Release-rule positive` because the actual value beat the
  forecast, while the trade state still blocks longs if the broader tape is
  bearish.
- The pipeline now rebuilds `macro_live_regime_context.json` from market tape,
  interpreted news, optional ORB/tape signal files, and optional news-rule
  context before the trust and daily-confirmation stages.
- The default fast headline mode is `auto`: Yahoo Finance JSON first, Yahoo RSS
  second, then TradingView news-flow as a last fallback. TradingView news-flow
  can be forced with `--news-feed-provider tradingview`; the default TradingView
  URL is `https://www.tradingview.com/news-flow/?market=stock,etf,futures`.
  The runner writes
  `macro_news_feed.csv`, `macro_news_feed_summary.json`, and
  `macro_news_context.json`; the dashboard shows source, age, bias, warnings,
  themes, risk flags, and latest interpreted headlines in the `Interpreted News`
  panel.
- Create a local `macro_regime_context.json` when fresh news or price action is
  overriding the generated rules. This file is ignored by Git so it can be
  changed during the session without polluting commits. Use
  `macro_regime_context.example.json` as the manual template.
- Use `macro_news_context.example.json` and `macro_tape_signals.example.json` as
  templates for generated news/tape inputs. The HIGHSTRIKE ORB Pine alert text
  is parsed as bullish/bearish when written into `macro_tape_signals.json` or
  `macro_tape_signals.csv`.
- The runner passes the manual context through `--regime-context` and the
  generated context through `--generated-regime-context`. Manual context wins
  when present and not expired; otherwise the generated context drives the live
  regime. The dashboard then shows `Release Rule`, `Live Regime`, `Trade State`,
  and conflict warnings instead of calling a bearish tape `market_positive` just
  because the release value was positive.
- Set `valid_until` in the context JSON. After it expires, the pipeline falls
  back to the inferred regime from the current release set.

Dashboard asset cache:

- After changing `dashboard/app.js` or `dashboard/styles.css`, run:

```powershell
python .\tools\update_dashboard_asset_versions.py --write
```

- Before committing or restarting the dashboard, verify:

```powershell
python .\tools\update_dashboard_asset_versions.py --check
```

The tool keeps `dashboard/index.html` pointed at hashed CSS/JS URLs so the
browser does not mix old JavaScript with new HTML.

Manual news refresh:

```powershell
python .\macro_news_feed.py --provider auto --force
python .\macro_live_regime_builder.py
```

Force the TradingView news-flow source:

```powershell
python .\macro_news_feed.py --provider tradingview --tradingview-news-url "https://www.tradingview.com/news-flow/?market=stock,etf,futures" --force
python .\macro_live_regime_builder.py
```

Use `--provider yahoo_rss` to force Yahoo RSS. Use `--provider auto` to try
Yahoo JSON, Yahoo RSS, and then TradingView if the earlier providers do not
return usable headlines.

Stop the background processes when needed:

```powershell
Stop-Process -Id <runner-pid>
Stop-Process -Id <server-pid>
```

To update later, stop the runner, pull the latest repository changes, refresh
dependencies if needed, then restart the background runner:

```powershell
git pull --ff-only
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$runner = Start-Process -FilePath "python" -ArgumentList @(".\macro_pipeline_runner.py", "--run-forever", "--watch-releases", "--loop-seconds", "60") -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
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

Before requesting old data, create a backfill plan:

```powershell
python .\market_data_backfill.py --desired-start 2020-01-01 --desired-end 2026-06-07 --as-of 2026-06-07 --intervals 1m 5m 15m 60m
```

That writes:

- `market_data_backfill_plan.csv`
- `market_data_backfill_report.json`

Use `--execute-yahoo` only for ranges marked `yahoo_eligible`. Ranges marked
`external_required` need a broker/platform/API export and should then flow
through `futures_data_adapter.py`.

Verify a newly added external 1-minute dataset before use:

```powershell
python .\market_data_verify.py --input .\extra\local_market_data\raw_exports\Dataset_NQ_1min_2022_2025.csv --datetime-column "timestamp ET" --input-timezone America/New_York --reference-intraday .\NQ_60min_data.csv --reference-daily .\NQ_F_daily.csv --report-output .\market_data_verification_report.json --summary-output .\market_data_verification_summary.csv --canonical-output .\extra\local_market_data\candidates_and_archived_adapter_outputs\NQ_external_1min_2022_2025_candidate.csv
```

Verify a TradingView-style export such as `NQ_in_1_hour.csv`:

```powershell
python .\market_data_verify.py --input .\extra\local_market_data\raw_exports\NQ_in_1_hour.csv --datetime-column datetime --input-timezone UTC --expected-interval-seconds 3600 --reference-intraday .\NQ_60min_data.csv --reference-daily .\NQ_F_daily.csv --report-output .\market_data_verification_NQ_in_1_hour_report.json --summary-output .\market_data_verification_NQ_in_1_hour_summary.csv
```

Do not merge the candidate file into the active model until
`market_data_verification_report.json` says it is approved for model use.

Verify an Investing.com daily export such as
`Nasdaq 100 Futures Historical Data.csv`:

```powershell
python .\market_data_verify.py --input ".\Nasdaq 100 Futures Historical Data.csv" --datetime-column Date --open-column Open --high-column High --low-column Low --close-column Price --volume-column Vol. --input-timezone America/New_York --expected-interval-seconds 86400 --reference-daily .\NQ_F_daily.csv --report-output .\market_data_verification_investing_nq_daily_report.json --summary-output .\market_data_verification_investing_nq_daily_summary.csv
```

Reconcile that daily source against Yahoo and create a clean candidate:

```powershell
python .\market_data_source_reconcile.py --candidate ".\Nasdaq 100 Futures Historical Data.csv" --reference .\NQ_F_daily.csv --source-name investing --round-to-tick
```

Build separate daily reaction profiles and compare them:

```powershell
python .\macro_reaction_study.py --events-file .\macro_events_history_2024_2026_high.csv --market-data .\NQ_investing_daily_clean_candidate.csv --symbol NQ_INVESTING_DAILY --cluster-output .\macro_event_clusters_investing_daily.csv --reaction-output .\macro_reactions_investing_daily.csv --profile-output .\macro_reaction_profiles_investing_daily.csv --min-events 3 --daily-max-session-gap-days 0
python .\macro_reaction_study.py --events-file .\macro_events_history_2024_2026_high.csv --market-data .\NQ_F_daily.csv --symbol NQ_YAHOO_DAILY --cluster-output .\macro_event_clusters_yahoo_daily.csv --reaction-output .\macro_reactions_yahoo_daily.csv --profile-output .\macro_reaction_profiles_yahoo_daily.csv --min-events 3 --daily-max-session-gap-days 0
python .\macro_daily_source_compare.py --left-reactions .\macro_reactions_yahoo_daily.csv --right-reactions .\macro_reactions_investing_daily.csv --left-name yahoo_daily --right-name investing_daily --neutral-threshold-pts 10
```

Normalize Dabento NQ OHLCV exports when those files exist locally:

```powershell
python .\dabento_nq_adapter.py --input .\dabento\glbx-mdp3-20100606-20260607.ohlcv-1m.csv --source-interval 1m --out-1m .\NQ_dabento_full_1min_data.csv --out-5m .\NQ_dabento_full_5min_data.csv --out-60m .\NQ_dabento_full_60min_data.csv --roll-map-output .\NQ_dabento_full_roll_map.csv --report-output .\dabento_nq_full_adapter_report.json
python .\dabento_nq_adapter.py --input .\dabento\glbx-mdp3-20200101-20251231.ohlcv-1m.csv --source-interval 1m --out-1m .\extra\local_market_data\candidates_and_archived_adapter_outputs\NQ_dabento_1min_data.csv --out-5m .\extra\local_market_data\candidates_and_archived_adapter_outputs\NQ_dabento_5min_data.csv --out-60m .\extra\local_market_data\candidates_and_archived_adapter_outputs\NQ_dabento_60min_data.csv
python .\dabento_nq_adapter.py --input .\dabento\1hour_glbx-mdp3-20100606-20260607.ohlcv-1h.csv --source-interval 1h --out-60m .\extra\local_market_data\candidates_and_archived_adapter_outputs\NQ_dabento_60min_long_data.csv --roll-map-output .\NQ_dabento_60min_long_roll_map.csv --report-output .\dabento_nq_60min_long_adapter_report.json
```

The full-range 1-minute Dabento file creates canonical 1m, derived 5m, and
derived 60m outputs. The separate 1-hour file remains an independent validation
source for the 60m output.

Build Dabento reaction profiles the same way as Yahoo or Investing.com:

```powershell
python .\macro_reaction_study.py --events-file .\macro_events_history_2024_2026_high.csv --market-data .\NQ_dabento_full_1min_data.csv --symbol NQ_DABENTO_FULL_1M --cluster-output .\macro_event_clusters_dabento_full_1m.csv --reaction-output .\macro_reactions_dabento_full_1m.csv --profile-output .\macro_reaction_profiles_dabento_full_1m.csv --min-events 3
python .\macro_reaction_study.py --events-file .\macro_events_history_2024_2026_high.csv --market-data .\NQ_dabento_full_5min_data.csv --symbol NQ_DABENTO_FULL_5M --cluster-output .\macro_event_clusters_dabento_full_5m.csv --reaction-output .\macro_reactions_dabento_full_5m.csv --profile-output .\macro_reaction_profiles_dabento_full_5m.csv --min-events 3
python .\macro_reaction_study.py --events-file .\macro_events_history_2024_2026_high.csv --market-data .\NQ_dabento_full_60min_data.csv --symbol NQ_DABENTO_FULL_60M --cluster-output .\macro_event_clusters_dabento_full_60m.csv --reaction-output .\macro_reactions_dabento_full_60m.csv --profile-output .\macro_reaction_profiles_dabento_full_60m.csv --min-events 3
```

The default command still preserves the older daily NQ files:

```powershell
python .\fetch_nq_yahoo.py
```

The current default source config is:

```text
market_data_config.json
```

It keeps Yahoo available as the default fetcher with `NQ=F`, leaves
`external_api.enabled` as `false`, and points the active local research feed to
the verified Dabento artifacts now present in this workspace.

The active live calibration profile is currently
`macro_reaction_profiles_dabento_full_1m.csv`. Performance grading uses the
full Dabento 1m, derived 5m, and derived 60m reaction files. Data-quality and
timing checks use `NQ_dabento_full_5min_data.csv`.

When Yahoo's intraday limit is not enough, export deeper futures data from a
broker, charting platform, or paid feed into `external_market_data/`, then
normalize it:

```powershell
python .\futures_data_adapter.py --input .\external_market_data\nq_2024_2026_1m.csv --out-csv .\NQ_external_1min_data.csv --input-timezone America/New_York --resample 1min --summary-output futures_data_adapter_summary.json
```

For exports with separate date/time columns or unusual column names:

```powershell
python .\futures_data_adapter.py --input .\external_market_data\nq_export.csv --out-csv .\NQ_external_5min_data.csv --date-column TradeDate --time-column TradeTime --open-column O --high-column H --low-column L --close-column C --volume-column V --input-timezone America/New_York --resample 5min
```

The adapter writes the same canonical columns expected by
`macro_reaction_study.py`:

- `date`
- `open`
- `high`
- `low`
- `close`
- `adj_close`
- `volume`

External raw exports are ignored by Git because paid/vendor data may be private
or licensed.

External/API data is optional for later. When you have a provider or export,
start with `MARKET_DATA_SOURCES.md`, then update `market_data_config.json` and
normalize the data with `futures_data_adapter.py`.

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
python .\macro_signal_performance.py --signals .\macro_live_signal.csv --reactions .\macro_reactions_dabento_full_1m.csv .\macro_reactions_dabento_full_5m.csv .\macro_reactions_dabento_full_60m.csv --reaction-labels dabento_full_1m dabento_full_5m dabento_full_60m --windows-minutes 5,15,30,60,240,390 --primary-window-minutes 60 --grades-output macro_signal_grades.csv --performance-output macro_signal_performance.csv
```

Outputs:

- `macro_signal_grades.csv`: one row per signal/reaction source with actual
  5m, 15m, 30m, 60m, 240m, and 390m outcomes where available.
- `macro_signal_performance.csv`: dashboard-ready accuracy summaries by source,
  family, category, bias, confidence, and family+bias.

## 5. Apply Trust Calibration

Turn the performance summary into probability trust weights, then create the
trust-adjusted signal contract:

```powershell
python .\macro_signal_trust.py --signals .\macro_live_signal.csv --performance .\macro_signal_performance.csv --weights-output macro_signal_trust_weights.csv --adjusted-output macro_live_signal_adjusted.csv
```

Outputs:

- `macro_signal_trust_weights.csv`: reusable trust weights by event family,
  category, market bias, confidence, and fallback groups.
- `macro_live_signal_adjusted.csv`: live signals with original probabilities
  preserved and final trust-adjusted fields appended.

Keep the separate daily confirmation layer as a slower baseline cross-check for
the current dashboard feed:

```powershell
python .\macro_daily_confirmation.py --signals .\macro_live_signal_adjusted.csv --daily-profiles .\macro_reaction_profiles_investing_daily.csv --output .\macro_live_signal_current.csv --summary-output .\macro_daily_confirmation_report.json
```

- `macro_live_signal_current.csv`: trust-adjusted signals with daily baseline
  confirmation fields and final current probabilities.
- `macro_daily_confirmation_report.json`: count of daily confirmations,
  disagreements, and probability adjustment size.

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
- apply daily confirmation into `macro_live_signal_current.csv`

For release-time polling and continuous operation:

```powershell
python .\macro_pipeline_runner.py --run-forever --watch-releases --loop-seconds 60
```

Optional switches:

- `--market-preset intraday` refreshes Yahoo data before the live cycle.
- `--news-feed-provider auto` fetches and interprets headlines before the
  live-regime context is built. Auto tries Yahoo JSON, Yahoo RSS, then
  TradingView.
- `--news-feed-tradingview-url` controls the TradingView news-flow page used
  when the news provider is `tradingview` or `auto`; the default is
  `https://www.tradingview.com/news-flow/?market=stock,etf,futures`.
- `--skip-news-feed` disables the interpreted headline fetch.
- `--refresh-performance` rebuilds signal grades and performance summaries when
  reaction files are already current.
- `--refresh-quality` rebuilds the market-data quality report.
- `--refresh-timing-audit` rebuilds the release/bar timing audit.
- `--refresh-probability-validation` rebuilds probability calibration reports.
- `--skip-alerts` disables the separate alert detector for that runner cycle.
- `--skip-daily-confirmation` leaves the dashboard/alerts on the trust-adjusted
  file instead of the daily-confirmed current file.
- `--alert-probability-jump-threshold 0.10` controls how large a probability
  change must be before an alert is logged.
- `--emit-initial-alerts` logs new-signal alerts on the first alert snapshot.
- `--notify-alerts` sends newly detected alerts after each runner cycle.
- `--notify-targets console,bell` chooses delivery targets. Available targets
  are `console`, `bell`, `popup`, `webhook`, `email`, and `risk_lock`.
- `--dry-run` prints the stage commands without executing them.
- `--stop-on-error` exits a forever run after a failed cycle.

The runner writes `macro_pipeline_runner.log` and `macro_pipeline_status.json`
for monitoring. These local runtime files are not included in the GitHub upload
allowlist.

After each non-dry-run cycle, the runner also calls the separate alert detector:

```powershell
python .\macro_pipeline_alerts.py --signals macro_live_signal_current.csv --status macro_pipeline_status.json
```

Alert outputs are local runtime files and are ignored by Git:

- `macro_pipeline_alerts.csv`: append-only alert history.
- `macro_pipeline_alert_summary.json`: latest alert-check summary.
- `macro_pipeline_alert_state.json`: previous snapshot used to detect changes.

The detector watches for actual values appearing, release-status changes,
direction changes, large probability/confidence jumps, runner failures, and
runner recovery.

Run the validation reports manually:

```powershell
python .\macro_data_quality.py --market-data .\NQ_5min_data.csv --events-file .\macro_releases.csv
python .\macro_timing_audit.py --market-data .\NQ_5min_data.csv --events-file .\macro_releases.csv
python .\macro_probability_validation.py --grades .\macro_signal_grades.csv
```

Run them through the pipeline:

```powershell
python .\macro_pipeline_runner.py --refresh-quality --refresh-timing-audit --refresh-probability-validation
```

Send notifications for alerts:

```powershell
python .\macro_alert_notify.py --targets console,bell --min-severity medium
```

The notifier can also read `macro_alert_notify_config.json`. The committed
`macro_alert_notify_config.example.json` shows webhook, email, and risk-lock
settings. The local config is ignored by Git so private webhook URLs and SMTP
details stay on the machine. A safe local default is `risk_lock,popup`, which
writes `macro_alert_risk_lock.json` and shows a Windows desktop popup. The
risk-lock target also scans the current signal CSV for release-rule/live-regime
conflicts, so a `no_long_wait_for_reclaim` state remains visible even after the
first alert has already been delivered.

Run the 24/7 loop with local notification output:

```powershell
python .\macro_pipeline_runner.py --run-forever --watch-releases --notify-alerts
```

Optional delivery examples:

```powershell
$env:MACRO_ALERT_WEBHOOK_URL = "https://example.com/webhook"
python .\macro_alert_notify.py --targets webhook --min-severity high

$env:MACRO_ALERT_SMTP_PASSWORD = "YOUR_SMTP_PASSWORD"
python .\macro_alert_notify.py --targets email --email-to you@example.com --email-from bot@example.com --smtp-host smtp.example.com --smtp-user bot@example.com

python .\macro_alert_notify.py --targets risk_lock --risk-lock-output macro_alert_risk_lock.json
python .\macro_alert_notify.py --targets popup --min-severity medium
```

Notifier outputs are also local runtime files and ignored by Git:

- `macro_alert_notify_state.json`: delivered-alert fingerprints.
- `macro_alert_notify_status.json`: latest notification run status.
- `macro_alert_risk_lock.json`: local handoff file for downstream risk tools.

### When Direction Probability Updates

The system can show a preliminary direction probability before the actual number
is released when it has a forecast/previous value and matching history. That
pre-release probability is based on `forecast_vs_previous`.

The stronger signal appears after the actual value is published by the calendar
source and the pipeline runs:

- `catalyser_news.py` sees the actual value on the next poll.
- `macro_reaction_study.py` calibrates the release against historical profiles.
- `macro_signal_trust.py` applies the feedback weights.
- `macro_daily_confirmation.py` applies the daily baseline confirmation.
- `macro_live_signal_current.csv` receives the final UI fields.

With `--watch-releases --poll-seconds 15`, expect the local CSV/dashboard to
update about 15-30 seconds after TradingView exposes the actual number, plus a
few seconds for processing. If the runner is using `--loop-seconds 60` without
release polling, the update can take up to the next loop cycle.

## 7. Start The Dashboard Locally

Serve the repository root and open the dashboard:

```powershell
cd "<path to python nq Catalyst>"
python -m http.server 8787 --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:8787/dashboard/
```

For the full startup sequence from `git pull` through a background live runner,
use [Quick Start: Repository To Live Pipeline](#quick-start-repository-to-live-pipeline).

The dashboard reads:

- `macro_live_signal_current.csv`
- `macro_signal_performance.csv`
- `macro_signal_trust_weights.csv`
- `macro_pipeline_status.json` when the runner has created it locally
- `macro_pipeline_alert_summary.json` when alert detection has created it

Views:

- Signals: live catalyst table, final probabilities, filters, range cards, and
  detail panel. The top alert panel appears only when recent backend alerts
  exist.
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
- `extra/local_market_data/raw_exports/` for unapproved raw/export inputs
- `extra/local_market_data/candidates_and_archived_adapter_outputs/` for
  normalized candidates and superseded adapter data

Those files are kept for reference, not deleted.

## Important Files

| File | Purpose |
| --- | --- |
| `market_data_config.json` | Current market-data source selection; Yahoo fetcher plus active local Dabento research files. |
| `market_data_backfill.py` | Separate missing-range planner for Yahoo/API backfills. |
| `market_data_verify.py` | Separate verifier for newly added market-data exports. |
| `market_data_source_reconcile.py` | Daily source reconciliation and clean candidate builder. |
| `MARKET_DATA_SOURCES.md` | Source-selection guide for deeper futures history. |
| `fetch_nq_yahoo.py` | Dynamic Yahoo market-data downloader. |
| `futures_data_adapter.py` | External futures CSV normalizer for deeper intraday data. |
| `dabento_nq_adapter.py` | Dabento NQ OHLCV normalizer, dominant-contract selector, resampler, and roll-map writer. |
| `catalyser_news.py` | Catalyst calendar, news, live macro release watcher, probability scoring. |
| `macro_reaction_study.py` | Historical event-to-price reaction study and live-release calibration. |
| `macro_daily_source_compare.py` | Daily source-to-source reaction comparison report. |
| `macro_daily_confirmation.py` | Temporary daily baseline confirmation layer for current live signals. |
| `macro_news_feed.py` | Fast Yahoo JSON/Yahoo RSS/TradingView headline fetcher and interpreter. |
| `macro_live_regime_builder.py` | Generated market-tape/news live-regime context builder. |
| `macro_regime.py` | Release-rule versus live-regime conflict layer and trade-state labeling. |
| `macro_regime_context.example.json` | Template for a local manual/news regime override. |
| `macro_news_context.example.json` | Template for rule-based news context input. |
| `macro_tape_signals.example.json` | Template for ORB/tape signal input from TradingView alerts. |
| `macro_signal_performance.py` | Post-release prediction grading and performance summaries. |
| `macro_signal_trust.py` | Performance feedback layer for trust-adjusted live probabilities. |
| `macro_data_quality.py` | Market-data health, gap, OHLC, and release-coverage report. |
| `macro_probability_validation.py` | Probability reliability, calibration, and Brier-score report. |
| `macro_timing_audit.py` | Release-time alignment audit against market bars. |
| `macro_pipeline_runner.py` | 24/7 orchestration layer that calls the separate modules in order. |
| `macro_pipeline_alerts.py` | Separate local alert detector for release changes and runner health. |
| `macro_alert_notify.py` | Optional notification sender for alert summaries/history. |
| `macro_alert_notify_config.example.json` | Template for webhook/email/risk-lock notification settings. |
| `dashboard/index.html` | Local browser dashboard for adjusted macro signals. |
| `dashboard/app.js` | CSV loader, filters, tables, and detail panel for the dashboard. |
| `dashboard/styles.css` | Dashboard visual system and responsive layout. |
| `macro_live_signal.csv` | Compact UI-ready live signal contract. |
| `macro_live_signal_adjusted.csv` | Trust-adjusted live signal contract. |
| `macro_live_signal_current.csv` | Current dashboard signal contract with daily confirmation applied. |
| `macro_news_feed.csv` | Runtime interpreted headline feed loaded by the dashboard. |
| `macro_news_feed_summary.json` | Latest news-fetch counts, titles, and fetch warnings. |
| `macro_reaction_profiles_5m.csv` | Smoothed historical reaction probabilities. |
| `macro_reaction_profiles_60m.csv` | Deeper 2024-2026 hourly reaction probabilities. |
| `macro_reaction_profiles_dabento_full_1m.csv` | Active full-range 1m Dabento calibration profile. |
| `macro_reaction_profiles_dabento_full_5m.csv` | Active full-range derived 5m Dabento reaction profile. |
| `macro_reaction_profiles_dabento_full_60m.csv` | Active full-range derived 60m Dabento reaction profile. |
| `macro_event_clusters_5m_60d.csv` | Same-timestamp macro release clusters. |
| `macro_signal_grades.csv` | Per-signal outcome grade rows. |
| `macro_signal_performance.csv` | Dashboard-ready model accuracy summary. |
| `macro_signal_trust_weights.csv` | Accuracy/whipsaw-based trust weights used by `macro_signal_trust.py`. |
| `macro_data_quality_report.json` | Latest market-data quality report. |
| `macro_probability_validation_report.json` | Latest probability validation summary. |
| `macro_timing_audit_report.json` | Latest release/bar timing audit summary. |
| `market_data_backfill_report.json` | Latest missing market-data range report. |
| `market_data_verification_report.json` | Latest candidate market-data verification report. |
| `extra/` | Archived side tools, private exports, and old generated artifacts. |
| `requirements.txt` | Python dependencies. |

## Data Notes

Generated market files such as `NQ_1min_data.csv`, `NQ_5min_data.csv`, and
`macro_reaction_profiles_5m.csv` are reproducible research artifacts. Private
broker exports such as raw fills, order-history exports, and account journals
should stay local unless you intentionally want them in a public repository.
Large vendor/export datasets such as `Dataset_*.csv`, `NQ_in_*.csv`,
`*Historical Data.csv`, raw `dabento/` files, `NQ_dabento_*data.csv`, and
candidate normalized files such as `NQ_external_*candidate.csv` are ignored by
Git. Small reports, roll maps, and reaction/profile artifacts are allowed so
the research state can be reproduced without publishing the vendor bars.
Most unapproved local exports now live under `extra/local_market_data/` to keep
the root focused on the runnable pipeline.

## Current Pipeline Status

As of the latest local run:

- `NQ_1min_data.csv`: 7,860 rows from 2026-05-29 04:09 to 2026-06-05 20:59.
- `NQ_5min_data.csv`: 13,552 rows from 2026-03-26 04:05 to 2026-06-05 20:55.
- `NQ_15min_data.csv`: 4,537 rows from 2026-03-26 04:00 to 2026-06-05 20:45.
- `NQ_60min_data.csv`: 13,680 rows from 2024-01-12 05:00 to 2026-06-05 20:00.
- `NQ_F_daily.csv`: 2,515 rows from 2016-06-07 to 2026-06-05.
- Yahoo rejected 30 days of 1-minute NQ data and reported that only about 8
  days of 1m granularity are available per request.
- `extra/catalyser_news_github_upload.zip` contained archived Yahoo intraday
  files. Those were extracted to `extra/archived_yahoo_intraday/` and merged
  into the active root NQ CSVs.
- No 2020 intraday OHLC file was found in `extra/`; the only 2020-capable NQ
  market file there is daily data.
- `market_data_backfill.py` confirms that the useful 2020-to-current intraday
  gaps are `external_required`: Yahoo cannot backfill 1m/5m/15m/60m data that
  old.
- `extra/local_market_data/raw_exports/Dataset_NQ_1min_2022_2025.csv` was
  verified but is not approved for model
  use yet. The file has 1,048,575 rows from 2022-12-26 23:01 UTC to
  2025-12-12 01:52 UTC, clean OHLC structure, no duplicate timestamps, and
  60-second interval mode. It failed Yahoo 60m and daily reference comparisons,
  and the row count is at Excel's worksheet limit, so it may be truncated or
  differently adjusted.
- `extra/local_market_data/raw_exports/NQ_in_*` TradingView-style exports were
  verified separately and are not approved for active model use yet. The files
  have clean OHLC structure, valid
  0.25-point ticks, and no duplicate timestamps, but every file failed the
  strict Yahoo reference gate. The best-aligned intraday candidates were
  `NQ_in_1_hour.csv` with 7,300 of 9,981 overlapping hourly bars within 0.25
  points, `NQ_in_30_minute.csv` with 3,168 of 4,464, and
  `NQ_in_15_minute.csv` with 1,224 of 1,623. Treat them as a separate
  TradingView/NQ1! source until roll and session-close differences are modeled.
  See `market_data_verification_nq_in_batch_summary.csv` for the full matrix.
- `Nasdaq 100 Futures Historical Data.csv` from Investing.com was verified as a
  separate daily 2020-2025 source. It has 1,570 rows, no duplicate dates, and
  1,481 of 1,510 overlapping Yahoo daily rows matched all OHLC fields within
  0.25 points. It is still marked `do_not_use_yet` because it has two OHLC
  anomalies, several non-0.25 tick values, and mismatch outliers clustered near
  futures roll periods. Use it as a separate Investing.com daily baseline until
  roll/session differences are modeled.
- `market_data_source_reconcile.py` produced
  `NQ_investing_daily_clean_candidate.csv` with 1,481 clean daily rows from
  2020-01-02 to 2025-12-31. The clean candidate excludes no-reference rows,
  source OHLC anomalies, and roll/session mismatch rows.
- Same-session daily reaction studies were built for Yahoo and the clean
  Investing.com source. Yahoo produced 280 daily reaction rows and 85 profile
  rows; Investing.com produced 200 daily reaction rows and 82 profile rows.
  On the 200 matched release days, `macro_daily_source_compare.py` reports
  100.0% daily direction agreement, effectively 1.000 return correlation, and
  only 0.0004 points average absolute return difference.
- `futures_data_adapter.py` can now normalize deeper external futures exports
  into the same OHLC schema used by the reaction study.
- `dabento_nq_adapter.py` normalized the full 2010-2026 1-minute Dabento file
  into 5,418,395 1m rows, 1,122,828 derived 5m rows, and 95,308 derived 60m
  rows from 2010-06-06 22:00 to 2026-06-05 20:59. It found no duplicate
  selected timestamps and no OHLC consistency issues.
- The full 1m-derived 60m file passed verification against the independent
  1h-derived long 60m file. The full 1m and full 5m files also passed
  same-source verification against the full 60m reference before use.
- Yahoo comparison remains a source/roll sanity check, not a strict approval
  gate for Dabento because continuous-contract roll and session construction can
  differ across vendors.
- Full-range Dabento reaction studies were built for 1m, derived 5m, and
  derived 60m. Each study clustered 282 release moments and produced 85 profile
  rows.
- `market_data_config.json` now points live calibration to
  `macro_reaction_profiles_dabento_full_1m.csv`, active quality/timing checks
  to `NQ_dabento_full_5min_data.csv`, and active performance grading to
  `macro_reactions_dabento_full_1m.csv`,
  `macro_reactions_dabento_full_5m.csv`, and
  `macro_reactions_dabento_full_60m.csv`.
- `macro_signal_performance.py` now skips out-of-coverage unknown reactions and
  produced 24 valid graded rows plus 51 performance summary rows from the
  active full-range Dabento reaction set.
- `macro_signal_trust.py` produced 51 trust-weight rows and 14 trust-adjusted
  live signal rows.
- `macro_daily_confirmation.py` now produces `macro_live_signal_current.csv`
  from the trust-adjusted signal plus `macro_reaction_profiles_investing_daily.csv`.
  The latest run matched all 14 live rows: 1 with-signal confirmation,
  11 daily leans, and 2 neutral confirmations. The average absolute probability
  adjustment was 0.0016, with no direction changes.
- `macro_probability_validation.py` now reports 20.8% primary directional
  accuracy, 0.219 Brier score, and 50.0% actual bullish rate on the current 24
  valid graded rows.
- `macro_data_quality.py` now rates the active full 5m data as watch quality at
  80/100. `macro_timing_audit.py` reports 8 aligned next bars and 6 releases
  after the latest available market data.
- Confidence scoring now caps weak, low-sample, whipsaw-heavy, fallback, or
  low-reliability signals more strictly before they reach the dashboard.
- `macro_data_quality.py`, `macro_probability_validation.py`, and
  `macro_timing_audit.py` provide validation reports for data health,
  probability reliability, and release/bar alignment.
- `macro_pipeline_runner.py --dry-run` verified the default stage order:
  live fetch, calibration, and trust adjustment.
- `macro_pipeline_alerts.py` is wired into the runner after each normal cycle
  and can be run manually against the adjusted signal CSV and status JSON.
- `macro_alert_notify.py` can deliver newly detected alerts to console, bell,
  webhook, email, or a local risk-lock JSON handoff when enabled.
- `dashboard/` serves from the workspace root and loads the adjusted signal,
  performance, and trust CSVs over HTTP.
- The dashboard now includes probability timeline, event-family performance,
  trust-weight charts, and min/max range summaries for signal, performance, and
  trust components.

## Next Project Tasks

These are deferred operational hardening items. They are not required for the
current manual/background workflow, but they should be added before relying on
the system unattended.

1. Add `start_live_pipeline.ps1`, `stop_live_pipeline.ps1`, and
   `status_live_pipeline.ps1` so the live runner can be managed without typing
   long `Start-Process` and process-inspection commands.
2. Add a Windows Task Scheduler setup script so the dashboard server and live
   pipeline restart after reboot or login.
3. Add duplicate-runner protection in `macro_pipeline_runner.py`, such as a PID
   or lock file, so two live runners cannot overwrite the same output files.
4. Add a dashboard stale-data warning when `macro_pipeline_status.json` is older
   than the expected loop interval.
5. Add log rotation for `macro_pipeline_runner.log` so long-running use does not
   grow the log indefinitely.
6. Add focused tests for UTC/ET handling, `--watch-releases`, and actual-value
   detection, because release timing is the highest-risk behavior.
7. Decide which refreshed runtime CSVs should be committed and which should stay
   local-only, since live runs update dashboard signal files frequently.
8. Configure and document real notification targets, such as webhook, email, or
   a local risk-lock file, instead of relying only on console output.

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
