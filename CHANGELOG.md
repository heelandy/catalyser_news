# Changelog

## 1.1.1 - Operational Hardening and Notifications

- Added size-based log rotation: when `macro_pipeline_runner.log` passes
  `--log-max-mb` (default 10 MB) it is moved to `macro_pipeline_runner.log.1`
  and a fresh log starts, so disk use stays bounded at roughly twice the cap
  while the most recent history is always preserved.
- Added a PID lock (`macro_pipeline_runner.lock`): a second live runner now
  exits immediately instead of silently overwriting the same output files;
  stale locks from dead processes are cleared automatically.
- Accuracy tracking for the new deep-history profiles:
  `macro_signal_performance.py` now appends every graded release to
  `macro_signal_grades_history.csv` (deduped per release/source), probability
  validation runs on that accumulating history, and the start script enables
  `--refresh-performance --refresh-probability-validation` in the live loop so
  grading happens automatically as releases print.
- Added Discord and Telegram notification targets to `macro_alert_notify.py`
  alongside webhook/email/popup/risk-lock. Configure in
  `macro_alert_notify_config.json` (`discord.webhook_url`,
  `telegram.bot_token`/`chat_id`) or via env vars
  `MACRO_ALERT_DISCORD_WEBHOOK_URL`, `MACRO_ALERT_TELEGRAM_BOT_TOKEN`,
  `MACRO_ALERT_TELEGRAM_CHAT_ID`. Long messages are chunked to each
  platform's limit.
- Added focused UTC release-timing tests (the fast news window math), plus
  lock, rotation, and notifier chunking tests.
- Added `tools/tape_signal_listener.py`: receives TradingView HIGHSTRIKE Pine
  alert webhooks (ORB on NQ, options on SPY/QQQ) and writes
  `macro_tape_signals.json` for the live regime builder. Repaired two example
  JSON files that contained patch artifacts.
- Master-detail dashboard polish: selection no longer resets table scroll,
  double-click/Enter opens the expanded popup card, Arrow keys navigate rows,
  the detail panel scrolls independently, and surprise values display as
  signed thousands (`+100,000`).

## 1.1.0 - Deep History, Live Tape, News Quality

- Rebuilt the macro reaction studies on the full 2010-2026 TradingView
  high-importance release history (3,824 events, 2,784 clustered release
  moments vs 282 before) against the full-range Dabento 1m/5m/60m data. Live
  calibration now runs on profile groups with hundreds of samples (for
  example 334 jobless-claims releases) instead of single digits.
- Added a Yahoo recent-window reaction file
  (`studies/macro_reactions_yahoo_recent_5m.csv`) so releases after the static
  Dabento cutoff can still be graded; the runner rebuilds it automatically
  before performance grading (`--refresh-performance`), and
  `macro_signal_performance.py` now keeps its previous outputs instead of
  crashing when no current signal has graded reactions yet.
- Re-enabled the live market tape: the runner now refreshes Yahoo 5m data in a
  throttled, non-fatal `market_data_refresh` stage (`--market-refresh-minutes`,
  default 5) and `active_market_data_file` points at `data/NQ_5min_data.csv`,
  so the regime builder's tape component is no longer stale-weighted to zero.
- Improved news interpretation quality: listicle/evergreen headlines ("N stocks
  to buy", "worth a closer look") are flagged `low_signal_content` and heavily
  discounted, publishers are weighted (Reuters/Bloomberg > Motley Fool/Insider
  Monkey), the aggregate news bias now decays headlines with a 90-minute
  half-life, and duplicate stories fetched under different symbols dedupe by
  normalized title.
- Sped up reaction time around releases: within 15 minutes of a scheduled
  release the background news refresher tightens to 60 seconds with a 1-minute
  cache (`--news-fast-window-minutes`).
- Clustered duplicate alerts: a live-regime flip now produces one alert listing
  the affected catalysts instead of one alert per signal row, and bulk signal
  loads collapse into a single `new_signal` alert. Regime reasons are truncated
  in alert messages.
- Dashboard: alert rows are clickable (selects the signal and opens the detail
  popup), alert text wraps responsively instead of overflowing, the signals
  table got a sticky first column and narrower minimum width, and clicking a
  row on small screens scrolls the detail panel into view.

## 1.0.9 - Timely News, Alert Popup Card, Daily Schedule

- Fixed news not updating on time: the `news_feed` stage now runs first in
  every pipeline cycle instead of after the calendar fetch, and a background
  refresher re-runs it every `--news-feed-refresh-seconds` (default 180) so
  headlines stay fresh while `--watch-releases` blocks a cycle for up to 30
  minutes. The news cache default dropped from 10 to 3 minutes.
- Added a dashboard alert popup card styled like the trading-app reference:
  direction badge, alert-type pill, category chip, large bull-probability
  readout, `Mixed Bias — Use Caution` banner, message box, and Release
  Rule / Live Regime / Trade State bias tiles. New alerts younger than 30
  minutes pop up once each (tracked in `localStorage`);
  `?popupPreview=1` previews the card with the latest alert.
- The dashboard now auto-reloads data every 30 seconds, keeps the selected
  signal across reloads, and shows a stale-data banner when the pipeline
  status is older than expected or the last cycle failed.
- Added `--stop-at HH:MM` to `macro_pipeline_runner.py` so the runner exits
  cleanly at a daily stop time.
- Added `tools/start_live_pipeline.ps1`, `tools/stop_live_pipeline.ps1`,
  `tools/status_live_pipeline.ps1`, and `tools/setup_schedule.ps1`. The
  schedule script registers Windows Task Scheduler tasks that start the
  pipeline daily at 7:00 AM and stop it at 6:00 PM so it does not run around
  the clock.
- Added runner schedule/stage-order tests and dashboard popup contract tests.
- Sorted the workspace by use: Pine scripts in `pine/` (options script for
  SPY/QQQ, ORB V1 for NQ), market OHLC history in `data/`, reaction studies
  and profiles in `studies/`, verification/reconciliation reports in
  `reports/`. Runtime files and modules stay at the root;
  `market_data_config.json`, module defaults, the README, and the GitHub
  upload allowlist now point at the new paths.

## 1.0.8 - Full-Range Dabento 1m Source

- Added and normalized `glbx-mdp3-20100606-20260607.ohlcv-1m.csv` into full
  canonical Dabento 1m, derived 5m, and derived 60m local OHLC files.
- Verified the full 1m, 5m, and 60m outputs with same-source checks before
  using them. The 60m output passed against the independent 1h-derived long
  60m file.
- Rebuilt full-range Dabento 1m, 5m, and 60m macro reaction/profile artifacts.
- Switched `market_data_config.json` to use the full 1m profile for live
  calibration, full 1m/5m/60m reactions for performance grading, and full 5m
  market data for quality/timing checks.
- Regenerated current performance, trust, quality, timing, probability
  validation, and dashboard signal artifacts from the verified full-range
  Dabento source.

## 1.0.7 - Dabento Intraday History

- Added `dabento_nq_adapter.py` to normalize Dabento NQ OHLCV exports while
  keeping the source adapter separate from the reaction, trust, and dashboard
  modules.
- Built canonical Dabento 1-minute, derived 5-minute, derived 60-minute, and
  long 2010-2026 60-minute NQ datasets locally.
- Verified the long 60-minute Dabento file against the 1-minute-derived
  Dabento 60-minute file: 35,431 of 35,432 overlapping hourly bars matched
  within 0.25 points, with 0.999996 close-delta correlation.
- Rebuilt Dabento reaction/profile artifacts and switched active performance
  grading to `macro_reactions_dabento_60m_long.csv` so current 2026 releases
  have valid post-release outcomes while the 1m/5m data remains available for
  higher-resolution studies.
- Updated `macro_signal_performance.py` to skip out-of-coverage reactions where
  the primary actual direction is unknown instead of counting blank reactions
  in accuracy/trust statistics.
- Kept raw Dabento files and large derived OHLC CSVs local-only while allowing
  small reports, roll maps, and reaction/profile artifacts into the GitHub
  upload list.

## 1.0.6 - Daily Confirmation Current Signal

- Added `macro_daily_confirmation.py` as a separate temporary confirmation
  layer while deeper 1m/5m NQ history is unavailable.
- Generated `macro_live_signal_current.csv` from the trust-adjusted signal plus
  `macro_reaction_profiles_investing_daily.csv`.
- Updated `macro_pipeline_runner.py` so daily confirmation runs after trust
  adjustment by default and alerts use the current signal file.
- Updated the dashboard to load `macro_live_signal_current.csv` and show daily
  confirmation in the detail panel.
- Kept Yahoo 60m profiles as the primary calibration source and Investing.com
  daily profiles as confirmation only.

## 1.0.5 - Daily Source Reconciliation

- Added `market_data_source_reconcile.py` to compare Investing.com daily NQ
  futures data against Yahoo daily data and create a clean canonical candidate.
- Generated `NQ_investing_daily_clean_candidate.csv` with 1,481 clean rows after
  excluding no-reference, invalid OHLC, and roll/session mismatch dates.
- Added `--daily-max-session-gap-days` to `macro_reaction_study.py` so daily
  experiments can skip events when cleaned data removes the release session.
- Built separate Yahoo and Investing.com daily reaction/profile artifacts.
- Added `macro_daily_source_compare.py` and confirmed that the 200 matched
  same-session daily release rows have 100% direction agreement between Yahoo
  and the clean Investing.com source.

## 1.0.4 - Multi-Timeframe Export Verification

- Verified the new `NQ_in_*` TradingView-style CSV exports without merging them
  into active model data.
- Generated per-file verification reports and summaries for the intraday,
  daily, weekly, and monthly exports.
- Marked the new exports `do_not_use_yet` for active Yahoo-based modeling
  because they failed the strict Yahoo reference gate, even though several
  intraday files showed strong overlapping movement alignment.
- Updated the verifier timestamp alignment after dropped rows and kept raw
  platform exports out of Git while allowing small verification reports.
- Added Investing.com numeric parsing for comma-formatted prices and K/M/B
  volumes, then verified `Nasdaq 100 Futures Historical Data.csv` as a separate
  daily source. It is not approved for active model use until roll/session
  differences are modeled.

## 1.0.3 - Market Data Verification

- Added `market_data_verify.py` as a separate verification layer for newly
  added market-data exports.
- Verified `Dataset_NQ_1min_2022_2025.csv` without merging it into active
  model data.
- Generated `market_data_verification_report.json` and
  `market_data_verification_summary.csv`.
- Marked the candidate dataset `do_not_use_yet` because it failed Yahoo 60m and
  daily reference comparisons and has an Excel-row-limit truncation warning.

## 1.0.2 - Backfill Planner

- Added `market_data_backfill.py` as a separate missing-range planner for
  Yahoo/API backfills.
- Generated `market_data_backfill_plan.csv` and
  `market_data_backfill_report.json` for the desired 2020-to-current intraday
  coverage.
- Confirmed that the useful 2020 intraday gaps are outside Yahoo's 1m, 5m,
  15m, and 60m lookback limits and require an external futures export/API.

## 1.0.1 - Deeper Yahoo History Feed

- Refreshed Yahoo NQ datasets with the intraday-deep preset and daily history.
- Extracted archived Yahoo intraday files from `extra/catalyser_news_github_upload.zip`
  and merged the older rows back into the active NQ CSVs.
- Rebuilt 1-minute, 5-minute, and 60-minute macro reaction/profile artifacts.
- Switched live calibration to `macro_reaction_profiles_60m.csv` so current
  signals use the deeper 2024-2026 release sample.
- Regenerated performance, trust, data-quality, timing, probability validation,
  and alert artifacts from the refreshed historical set.
- Updated the dashboard timestamp display to show release times in New York
  market time (`ET`).

## 1.0.0 - Validation and Timing Controls

- Activated `market_data_config.json` inside the pipeline runner for source,
  ticker, active market-data file, and active profile defaults.
- Added `macro_data_quality.py` for market-data health, OHLC checks, gaps, and
  release coverage.
- Added `macro_probability_validation.py` for calibration, Brier score, and
  probability-band reliability reporting.
- Added `macro_timing_audit.py` for release-to-bar timing precision checks.
- Added a compact dashboard alert panel backed by
  `macro_pipeline_alert_summary.json`.
- Tightened confidence scoring and caps for low-sample, whippy, fallback, and
  weak-edge signals.

## 0.9.1 - Yahoo Default Source

- Added `market_data_config.json` with Yahoo as the default market-data source.
- Updated source-selection docs so external APIs are treated as future optional
  upgrades, not current requirements.

## 0.9.0 - External Futures Data Adapter

- Added `futures_data_adapter.py` to normalize broker/platform/paid-feed
  futures CSV exports into the canonical OHLC format used by the reaction
  study.
- Added timezone conversion, optional resampling, multi-file combine, column
  auto-detection, and JSON import summaries.
- Added local ignore rules for external market-data exports.
- Added `MARKET_DATA_SOURCES.md` to compare source choices before committing to
  a vendor/API.

## 0.8.0 - Alert Notifications

- Added `macro_alert_notify.py` as a separate optional alert delivery module.
- Added console, bell, webhook, email, and local risk-lock notification targets.
- Added runner flags to notify after alert detection without changing the
  dashboard.

## 0.7.0 - Pipeline Alerting

- Added `macro_pipeline_alerts.py` as a separate backend alert detector.
- The runner now calls the alert detector after each non-dry-run cycle so
  release state changes and pipeline failures are logged outside the dashboard.
- Added local alert outputs for alert history, latest summary, and detector
  state.

## 0.6.2 - Dashboard Range Fix

- Fixed the probability chart range chips so they no longer shadow the numeric
  point formatter and block dashboard data loading.
- Versioned the dashboard script tag so browsers fetch the fixed JavaScript on
  refresh.

## 0.6.1 - Dashboard Ranges

- Added min/max range cards for signal, performance, and trust dashboard
  components.
- Added min/max chips to the probability, performance, and trust chart headers.
- Adjusted desktop table viewports so lower rows remain reachable inside the
  table scroll area.

## 0.6.0 - Dashboard Charts and Timing Notes

- Added dashboard charts for final probability timeline, event-family
  performance, and trust weights.
- Added README timing notes for when pre-release and post-actual direction
  probabilities become available.
- Expanded local dashboard startup instructions with the workspace-root command.

## 0.5.0 - Local Dashboard

- Added `dashboard/index.html`, `dashboard/styles.css`, and `dashboard/app.js`.
- Added a local operational dashboard for adjusted live signals, performance
  summaries, and trust weights.
- Added signal search, category/status/direction filters, sortable signal table,
  and a detail panel using the `final_*` signal fields.
- Added dashboard documentation and GitHub upload allowlist entries.

## 0.4.0 - Pipeline Runner

- Added `macro_pipeline_runner.py` as a separate orchestration layer for live
  operation.
- Added one-cycle and `--run-forever` modes for the live fetch, calibration, and
  trust-adjustment chain.
- Added optional Yahoo market-data refresh, release-time polling,
  post-release performance refresh, status JSON, and runtime logging.
- Added `--dry-run` support so the stage order can be verified without touching
  live data files.

## 0.3.0 - Trust-Adjusted Live Signals

- Added `macro_signal_trust.py` as a separate feedback calibration layer.
- Added `macro_signal_trust_weights.csv` from accuracy, whipsaw, and sample-size
  history in `macro_signal_performance.csv`.
- Added `macro_live_signal_adjusted.csv` with original probabilities preserved
  and UI-ready `final_*` fields appended.
- Added trust warnings for low-sample, whipsaw-heavy, discounted, and faded
  signal groups.
- Capped boosts from broad fallback groups so generic bias history cannot
  over-strengthen unrelated event types.
- Confirmed the current feedback run boosts clean PMI signals while pulling weak
  labor and whippy inflation signals closer to neutral.

## 0.2.0 - Clustered Signals and Live Contract

- Added `macro_signal_performance.py` for post-release outcome grading.
- Added `macro_signal_grades.csv` and `macro_signal_performance.csv`.
- Added deeper 60-minute NQ reaction study from 2024-01-12 through 2026-06-05.
- Added 60-minute historical outputs:
  - `macro_events_history_2024_2026_high.csv`
  - `macro_event_clusters_60m_2024_2026.csv`
  - `macro_reactions_60m.csv`
  - `macro_reaction_profiles_60m.csv`
- Split ADP and JOLTS into more specific event families.
- Tightened jobless-claims rule after deeper history showed higher claims have recently behaved more like growth stress for NQ.
- Added same-timestamp release clustering so CPI/core CPI or payrolls/unemployment do not double-count the same NQ price move.
- Added `event_cluster_id`, `event_count`, `cluster_titles`, `cluster_event_families`, `cluster_market_bias_sides`, and primary-event fields.
- Added Bayesian-smoothed probabilities:
  - `raw_bullish_probability`
  - smoothed `bullish_probability`
  - `raw_market_move_probability`
  - smoothed `market_move_probability`
  - `sample_confidence`
  - `confidence_label`
- Expanded Yahoo data acquisition:
  - 1m remains limited to about 8 days by Yahoo.
  - 5m and 15m successfully reached back to 2026-03-26.
  - 60m successfully reached back to 2024-01-12.
- Added `intraday-deep` Yahoo preset for 1m, 5m, 15m, and 60m NQ pulls.
- Added compact `macro_live_signal.csv` output for the future UI.
- Tightened classification for PMI, JOLTS, ADP, and job-openings releases.

## 0.1.0 - Macro Catalyst Pipeline Baseline

- Added dynamic Yahoo market-data downloader for `NQ=F`, `ES=F`, `SPY`, and other Yahoo tickers.
- Added TradingView economic-calendar fetch support with previous, forecast, and actual values.
- Added macro reaction study that aligns releases to OHLC bars and measures 5m, 15m, 30m, 60m, and session-window reactions.
- Added market-aware surprise interpretation:
  - raw `surprise_side`
  - adjusted `market_bias_side`
  - `market_rule_direction`
  - `market_rule_confidence`
- Added reaction profiles for event family/category and market-bias direction.
- Added initial 1-minute and 5-minute NQ reaction datasets.
- Added GitHub-ready README, requirements, `.gitignore`, and API uploader fallback.

## Next

- Add alert display inside the dashboard for newly released actual values.
- Add provider-specific download connectors once a futures data vendor/API is
  selected.
