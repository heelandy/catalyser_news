# Changelog

## 0.2.0 - Clustered Signals and Live Contract

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

- Cluster simultaneous releases so one price move is not double-counted.
- Add smoothed probabilities for small sample sizes.
- Expand Yahoo pulls dynamically where the provider allows it.
- Emit a compact `macro_live_signal.csv` contract for the future UI.
