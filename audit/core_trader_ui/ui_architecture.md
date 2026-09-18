# Core Trader UI — Architecture Document

## Overview

The Core Trader UI is a collection of 9 decision-oriented HTML pages centered on the
**PRE-MARKET SCENARIO → ACTIVATION → TRADE/WAIT/NO TRADE** decision path. All pages
share a common visual system (CSS, navigation, consent, live clock) and fetch data
from the same Flask API surface.

## Page Inventory

| # | URL | File | Purpose |
|---|-----|------|---------|
| 1 | `/` | `index.html` | Homepage — market status, snapshot, AI outlook, options, qualification, paper trade, evidence, breadth |
| 2 | `/today/index.html` | `today/index.html` | Primary trader terminal — session status, snapshot, outlook, key levels, options, breadth, intraday conditions, strategy, risk, timeline |
| 3 | `/indices/nifty.html` | `indices/nifty.html` | NIFTY 50 deep decision page — snapshot, outlook, technicals, key levels, options, intraday conditions, strategy, evidence, qualification, paper trade |
| 4 | `/indices/banknifty.html` | `indices/banknifty.html` | BANKNIFTY 50 deep decision page — identical structure to NIFTY |
| 5 | `/options/index.html` | `options/index.html` | Options intelligence hub — PCR, max pain, OI, expected move, option chain (MISSING — needs creation) |
| 6 | `/strategies.html` | `strategies.html` | Options strategy engine — regime-driven strategy cards, payoff comparison, performance |
| 7 | `/tools/backtest.html` | `tools/backtest.html` | Deterministic backtest runner — form, metrics, equity curve, trade ledger, AI outlook history |
| 8 | `/ai-track-record.html` | `ai-track-record.html` | AI prediction track record — historical accuracy, verdict history (MISSING — needs creation) |
| 9 | `/research/index.html` | `research/index.html` | Research hub — market research, analysis reports (MISSING — needs creation) |

## Shared Architecture

### CSS
All pages reference `main.css` via `/assets/css/main.css` (root-relative) or `../assets/css/main.css` (relative from subdirectories). The CSS source lives at `static/css/main.css` (120 lines).

### JavaScript
Shared JS files: `live-blink.js` (price blink animations), `keep-scroll.js` (scroll position), `consent.js` (consent management), `api.js` (API helpers), `ai-outlook.js` (AI outlook rendering).

### Navigation
All pages share a common header with: TradingAI logo, tagline, live clock, nav links (Home, Today, Options, Strategies, Tools, Learn).

### Data Flow
```
HTML → fetch('/api/...') → Flask (api_server.py) → SQLite/Model → JSON → HTML render
```

### Key API Endpoints Used
- `/api/market` — Market snapshot (all indices)
- `/api/price/<symbol>` — Single index price
- `/api/market-outlook?symbol=X` — AI outlook
- `/api/key-levels?symbol=X` — Support/resistance
- `/api/intraday-conditions?symbol=X` — Bullish/bearish/no-trade conditions
- `/api/options/state/<symbol>` — Options state (PCR, OI, max pain, expected move)
- `/api/strategy/<symbol>` — Trade setup/strategy
- `/api/risk/<symbol>` — Risk guidance
- `/api/session-timeline` — Session timeline
- `/api/breadth` / `/api/index-breadth` — Market breadth
- `/api/market-evidence/<symbol>` — Market evidence
- `/api/trade-qualification` — Trade qualification
- `/api/paper-trades` — Paper trades
- `/api/vix` — VIX data
- `/api/regime/<symbol>` — Regime data
- `/api/walkforward/<symbol>/<start>/<end>` — Walk-forward validation
- `/api/evidence/<symbol>/<date>` — Historical evidence
- `/api/backtest` — Backtest execution
- `/api/journal` — Trade journal
- `/api/intelligence/*` — Personal intelligence

### Consent & Tracking
All pages include Google Tag Manager (gtag.js) with consent-default-deny pattern.
Consent defaults: ad_storage=denied, analytics_storage=denied, ad_user_data=denied, ad_personalization=denied.

### Risk Disclosure
Every page includes educational/risk disclaimer text — no page presents trading as guaranteed profit.
