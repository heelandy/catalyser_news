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

The live regime builder (`macro_live_regime_builder.py`) reads
`macro_tape_signals.json` / `macro_tape_signals.csv` every pipeline cycle and
parses HIGHSTRIKE alert text as bullish/bearish tape evidence, blending it
with interpreted news and market tape before the trust and daily-confirmation
stages. There are three ways to get alerts into that file:

1. **Automatic (webhook listener).** Run the local listener and point
   TradingView alert webhooks at it:

   ```powershell
   python .\tools\tape_signal_listener.py --port 8788
   ```

   TradingView webhooks need a public URL, so expose the port with a tunnel
   (for example `cloudflared tunnel --url http://127.0.0.1:8788`) and paste
   the tunnel URL into the TradingView alert's webhook field. The listener
   infers bullish/bearish and the symbol from the alert text (LONG/SHORT/
   CALL/PUT, NQ/QQQ/SPY) and writes `macro_tape_signals.json` in the format
   the regime builder expects. Each alert stays valid for `--valid-minutes`
   (default 180).

2. **Manual post from this machine** (no tunnel needed):

   ```powershell
   Invoke-WebRequest -Method POST -Uri http://127.0.0.1:8788 -Body "HIGHSTRIKE ORB: SHORT breakout confirmed NQ"
   ```

3. **Edit the file by hand** using `macro_tape_signals.example.json` as the
   template.

## TradingView alert setup

- NQ chart: add `HIGHSTRIKE_ORB_V1_INDICATOR`, create alerts on its
  LONG/SHORT breakout conditions.
- SPY and QQQ charts: add `HIGHSTRIKE_ORB_OPTIONS`, create alerts on its
  CALL/PUT structure suggestions.
- Keep the default alert message text - the words LONG/SHORT/CALL/PUT and the
  ticker are what the listener and regime parser key on.
