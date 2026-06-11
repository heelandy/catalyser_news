# TradingView Pine Scripts

These scripts run on TradingView and feed the macro pipeline through their
alert text. The interpreted news feed keeps the macro context fresh so the
Pine alerts are not late to the reaction.

## Which script for which market

- `HIGHSTRIKE_ORB_OPTIONS.pine` — options trading on **SPY and QQQ**.
  Alert text suggests CALL/PUT or spread structures.
- `HIGHSTRIKE_ORB_V1_INDICATOR.pine` — opening-range-breakout futures trading
  on **NQ**.

## How the alerts feed the pipeline

Write the TradingView alert text into `macro_tape_signals.json` or
`macro_tape_signals.csv` in the workspace root (see
`macro_tape_signals.example.json`). The live regime builder
(`macro_live_regime_builder.py`) parses HIGHSTRIKE alert text as
bullish/bearish tape evidence and blends it with interpreted news and market
tape before the trust and daily-confirmation stages.
