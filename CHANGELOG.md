# Changelog

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

- Add richer historical futures data when Yahoo's intraday limits are not enough.
- Add notification targets for alerts, such as sound, email, webhook, or broker
  risk-lock hooks.
- Add alert display inside the dashboard for newly released actual values.
