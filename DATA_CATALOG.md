# TradingAI Data Catalog — every number on the site, and where it comes from

> Rule: **NSE first, yfinance fallback, never empty.** Every row lists the
> display field, API, DB table(s), and fetcher chain (primary → fallback).
> Fields marked UNAVAILABLE have no reachable source and are shown as "—"
> rather than invented. Last audited: 2026-09-10.

## Quote block (every page): price, change, change_pct, open, high, low, previous_close, volume, timestamp, source

- API: `/api/<symbol>` → `quote`, `/api/market` → `instruments.*.quote`
- DB: `live_quotes` (fresh < 25 min) → `price_1m` latest candle
- Fetcher: NSE `allIndices` → Yahoo 1m history → NSE synth candle (flat OHLC at live price, vol 0)
- Notes: stocks/ETFs/SENSEX are yfinance-first (NSE blocks stock quotes, SENSEX is BSE).
  `source` field tells the page which feed served the quote.

## Indicators: VWAP, RSI, MACD/signal/histogram, ADX, ATR, EMA9/20/50/100/200, SMA20/50/200, Bollinger U/M/L, pivot+R1-R3/S1-S3, CPR, support/resistance, day/prev-day OHLC

- API: `/api/indicators[/<symbol>]`, embedded in symbol payloads
- DB: `indicators` (support_resistance as JSON)
- Fetcher: computed locally from daily candles + quote (no external dependency, cannot be empty when candles exist)

## Regime, scenarios, strategies, AI outlook (bias, confidence, evidence, summaries)

- API: `/api/regime`, `/api/strategy`, `/api/scenarios`, `/api/outlook`, symbol payloads
- DB: `market_regime`, `scenarios`, `strategies` (9:30 `daily_strategy` lock preferred), `ai_outlooks` (full JSON)
- Fetcher: computed locally from indicators + quote (rule-based AI; LLM providers removed)

## Stock investment views: SHORT rating/target/stop, LONG rating/fair value, scores, reasons

- API: `/api/investment/<symbol>`, embedded `investment` block for stocks
- DB: `investment_views` (per symbol/date/horizon)
- Fetcher: computed from `price_1d` + stored fundamentals (zero extra Yahoo calls)

## VIX: price, change, change_pct

- API: `/api/vix`
- DB: `vix_data` ← NSE INDIA VIX preferred, Yahoo `^INDIAVIX` fallback

## Breadth & market internals: advances, declines, A/D ratio, snapshots

- API: `/api/breadth`, `/api/index-breadth` (official per-index A/D), `/api/snapshot`
- DB: `market_breadth` (computed), `index_breadth` (NSE), `market_snapshots`
- Fetcher: NSE `allIndices` → computed from 1m closes (fallback)

## Options: expiries, lots, chains, PCR, OI, Max Pain, IV

- Expiries: NSE `option-chain-contract-info` → `option_expiries`, API `expiry` block with `source: NSE`, computed weekday math as fallback. SENSEX always computed (BSE).
- Lot sizes: NSE `fo_mktlots.csv` → `symbols.lot_size` (`source` NSE/config), API `lot` block; SENSEX default 20 (config).
- Chains/PCR/OI/MaxPain/IV: **UNAVAILABLE** — Yahoo has no NSE chain, NSE chain endpoint dead. Shown as "—" with reason. Never synthesized.

## Company data: fundamentals, analyst views, financials, news, dividends/splits

- API: `/api/fundamentals`, `/api/company`, `/api/news[/<symbol>]`, `/api/actions/<symbol>`
- DB: `fundamentals` (merged info+analyst+statements JSON), `news`, `corporate_actions`
- Fetcher: yfinance info/extras (15-min tier), statements (weekly). Indices return 404 → skipped gracefully.

## P&L history: entry/exit time+price, direction, points, result, outlook, strategy

- API: `/api/history` (live + archive merged, 365d)
- DB: `history` (1-year live) + `history_archive` (monthly archival, permanent)
- Fetcher: `pnl_tracker.py lock` 9:30 / `close` 15:20 IST; direction-aware math (SHORT = entry − exit).

## Expiry countdowns, targets/stops, performance stats, scanner values

- All derived client-side or API-side from the rows above (targets from S/R+ATR, performance from history, scanner from symbol payloads). No separate feeds.
