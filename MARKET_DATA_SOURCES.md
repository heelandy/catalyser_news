# Market Data Source Options

As of 2026-06-07, Yahoo is the default market-data source. The project has two
market-data paths:

- Yahoo via `fetch_nq_yahoo.py` for quick, free, limited intraday history.
- External CSV normalization via `futures_data_adapter.py` for deeper futures
  history from a broker, charting platform, or paid feed.

Keep using Yahoo until a provider/API key or export source is actually selected.
The external path is ready, but it is not required for the current workflow.

## Recommendation

Use this order:

1. Keep Yahoo as the default source for now.
2. If you later have a charting/broker platform that can export historical
   NQ or MNQ bars, export CSV first and run it through
   `futures_data_adapter.py`.
3. If you later need an API provider, evaluate Databento first for CME futures
   history because it supports CME Globex futures, OHLCV bar schemas, and
   futures continuous-contract symbology.
4. Use Interactive Brokers only if you already have the account/data
   entitlement and only need recent data. IBKR is a broker API, not a dedicated
   historical data archive.
5. Use CME DataMine when you want an official exchange historical dataset and
   are comfortable with one-off dataset ordering rather than a lightweight API
   workflow.
6. Re-check Polygon later. Its futures REST documentation currently describes
   the product as beta/coming soon.

`market_data_config.json` currently reflects this decision:

```json
{
  "default_source": "yahoo",
  "external_api": {
    "enabled": false
  }
}
```

## Minimum Dataset

For the current macro engine, the first useful purchase/export is not tick data.
Start with:

- Symbol: NQ or MNQ continuous/front contract.
- Bar size: 1-minute if affordable, otherwise 5-minute.
- History: at least 2024-01-01 to current date.
- Fields: timestamp, open, high, low, close, volume.
- Timezone: exchange time, New York time, Central time, or UTC is fine as long
  as it is known.

Tick data can come later if we decide to study spread, slippage, liquidity, or
the exact first seconds after a release.

## Provider Notes

### Databento

Best first API candidate.

- Supports CME Globex futures and options on futures.
- Offers historical data over API and flat files.
- Supports OHLCV schemas.
- Supports futures continuous-contract symbology on CME Globex.
- Requires an API key.

Useful official pages:

- https://databento.com/
- https://databento.com/docs
- https://databento.com/docs/standards-and-conventions/symbology
- https://databento.com/docs/examples/basics-historical/historical-introduction

### Interactive Brokers

Useful if you already have IBKR and recent futures permissions, but not the best
archive source.

- Historical API has pacing rules.
- IBKR states it is not a specialized market data provider.
- Expired futures data older than two years from expiration is not available
  through the API.
- Continuous futures can be requested for historical data through TWS API.

Useful official pages:

- https://interactivebrokers.github.io/tws-api/historical_limitations.html
- https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/

### CME DataMine

Best official exchange archive path.

- CME's self-service platform for historical futures/options data.
- Good when official source quality matters more than lightweight automation.
- Likely heavier operationally than an API workflow for routine refreshes.

Useful official pages:

- https://www.cmegroup.com/market-data/datamine-historical-data/index.html
- https://www.cmegroup.com/market-data/browse-data.html.html

### Polygon

Watchlist candidate, not first choice right now.

- Official futures REST docs describe the product as beta and coming soon.
- Revisit once the futures product is generally available and pricing/limits are
  clear.

Useful official page:

- https://www.polygon.io/docs/rest/futures/overview

## How This Fits The Current Pipeline

After getting any export/API file later:

```powershell
python .\futures_data_adapter.py --input .\external_market_data\nq_raw.csv --out-csv .\NQ_external_1min_data.csv --input-timezone America/New_York --resample 1min
```

Then run the reaction study with the normalized file:

```powershell
python .\macro_reaction_study.py --fetch-tv-events --start-date 2024-01-01 --end-date 2026-06-07 --market-data .\NQ_external_1min_data.csv --symbol NQ --tv-min-importance 1 --reaction-output macro_reactions_external_1m.csv --profile-output macro_reaction_profiles_external_1m.csv --min-events 5
```

Keep raw vendor exports under `external_market_data/`. That folder is ignored
because vendor data can be private, licensed, or too large for the public repo.
