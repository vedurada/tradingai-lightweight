# TradingAI — Authoritative Page Manifest

Created: 16 September 2026
Baseline: v2b5583a-baseline (commit 35decaf)

This is the source of truth for what TradingAI production should contain. Every retained page must appear here. Every page not here must have a specific classification (ARCHIVE, DELETE, REDIRECT).

---

## Classification Key

| Status | Meaning |
|--------|---------|
| CORE | Primary trading product pages |
| SECONDARY | Supporting but retained |
| TOOL | Functional tool pages |
| TRUST | Legal/trust/info pages |
| EDUCATION | Learn/SEO pages |
| AUXILIARY | Supporting pages (alerts, portfolio, etc.) |
| LEGACY | Redirect-only, not production content |

---

## Approved Scope

### HOME

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| / | Daily AI Market Outlook command center | Intraday index-options traders | Core | Market Status, NIFTY, BANKNIFTY, FINNIFTY, SENSEX, INDIA VIX, AI Outlook, Market Regime, Key Levels, Options Intelligence, Trade Conditions, Strategy, Risk, Related Tools | NSE APIs, options data |

### MARKET

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /market.html | Broad market monitoring | Intraday index-options traders | Core | Market Overview, Index Grid, Market Breadth, Sector/Condition, Technical Snapshot, Market Regime, Links to Index Deep Dives | NSE APIs |
| /indices/nifty.html | NIFTY 50 deep analysis | Intraday index-options traders | CORE | NIFTY 50 (Spot/Change/VIX/Regime/Confidence), AI Outlook (Direction/Evidence/Drivers), Technical Structure (VWAP/EMA/RSI/MACD/ADX/CPR), Key Levels (Support/Resistance/Opening Range/Zones), Options Intelligence (PCR/OI/Call Wall/Put Wall/Max Pain/Expected Move), Intraday Conditions (Bullish/Bearish/No-trade), AI Options Strategy (Structure/Entry/Risk/Target/Invalidation), Tools links | NSE APIs, options data |
| /indices/banknifty.html | BANKNIFTY deep analysis | Intraday index-options traders | CORE | Same template as NIFTY | NSE APIs, options data |
| /indices/finnifty.html | FINNIFTY deep analysis | Intraday index-options traders | CORE | Same template as NIFTY | NSE APIs, options data |
| /indices/sensex.html | SENSEX deep analysis | Intraday index-options traders | CORE | Same template as NIFTY | NSE APIs, options data |

### TODAY

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /today/index.html | Daily repeat-visit trading terminal | Intraday index-options traders | CORE | Date, Market Status, Last Updated, Market Snapshot (NIFTY/BANKNIFTY/SENSEX/FINNIFTY/VIX), AI Outlook (Regime/Direction/Confidence/Explanation), Key Levels, Options Intelligence (PCR/OI/Max Pain/Expected Move), Market Breadth, Intraday Conditions (Bullish/Bearish/No Trade), AI Strategy Candidates, Risk Management, Session Timeline | NSE APIs, options data |

### OPTIONS

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /options/pcr.html | PCR/OI/Max Pain/PCR intelligence | Intraday index-options traders | CORE | Options Intelligence header, Index Selector (NIFTY/BANKNIFTY/FINNIFTY/SENSEX), PCR (Current/Trend/Interpretation), Open Interest (Call OI/Put OI/Change/Concentration), Max Pain, Call Wall, Put Wall, Expected Move, Option Chain Summary, AI Interpretation, Related links | Options data (bhavcopy) |
| /options/ | Options intelligence hub | Intraday index-options traders | CORE | Links to PCR, Option Chain, OI, Max Pain | Options data |

### STRATEGIES

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /strategies.html | AI options strategy engine | Intraday index-options traders | CORE | Today's Market Context, Market Regime, Options Intelligence, AI Strategy Analysis, Strategy Candidates, Risk/Reward, Strategy Comparison, Strategy Performance, Build This Strategy | NSE APIs, options data, deterministic engine |
| /strategy-builder.html | Interactive payoff calculator | Intraday index-options traders | TOOL | Instrument, Template, Lots, Lot Size, Generate, Payoff, Max Profit, Max Loss, Breakeven, Margin/Capital, Risk | Deterministic calculation |

### TOOLS

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /tools/backtest.html | Historical strategy validation | Intraday index-options traders | TOOL | Instrument, Strategy, Period, Capital, Risk, Brokerage, Slippage, Run, Results (Trades/Win Rate/P&L/Profit Factor/Max Drawdown/Avg R), Equity Curve, Drawdown, Trade Ledger | Deterministic engine |
| /tools/position-size.html | Risk/position sizing | Intraday index-options traders | TOOL | Capital, Risk %, Risk Amount, Entry, Stop, Lot Size, Lots, Position Size, Maximum Loss | Deterministic calculation |

### SCANNER

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /scanner.html | Stock discovery (secondary) | All investors | SCANNER | Stock Scanner, Filters, Market Regime, Technical Signals, Stock Results, Stock Detail | NSE data |

### RESEARCH

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /mutual-funds/ | Mutual fund research (SEO/secondary) | All investors | SECONDARY | Best Mutual Funds, AMFI data | AMFI/mfapi |

### LEARN

| URL | Purpose | Audience | Type | Required Sections | Data Source |
|-----|---------|----------|------|-------------------|-------------|
| /learn/ | Education hub | All traders | EDUCATION | Links to all education pages | — |
| /learn/option-chain.html | Option chain education | Traders | EDUCATION | How to read option chain | — |
| /learn/pcr.html | PCR education | Traders | EDUCATION | PCR explained | — |
| /learn/vwap.html | VWAP education | Traders | EDUCATION | VWAP explained | — |
| /learn/cpr.html | CPR education | Traders | EDUCATION | CPR explained | — |
| /learn/option-greeks.html | Greeks education | Traders | EDUCATION | Option Greeks explained | — |

### TRUST

| URL | Purpose | Type |
|-----|---------|------|
| /about.html | About TradingAI | TRUST |
| /contact.html | Contact | TRUST |
| /privacy.html | Privacy Policy | TRUST |
| /terms.html | Terms of Service | TRUST |
| /disclaimer.html | Disclaimer | TRUST |
| /404.html | 404 error page | TRUST |

### LEGACY (Redirect Only)

| URL | Redirects To | Status |
|-----|-------------|--------|
| /home.html | / | 301 active |
| /stocks.html | /scanner.html | 301 active |
| /fixed-loss-options.html | /options/pcr.html | 301 active |
| /index-option-risk-management.html | /learn/option-greeks.html | 301 active |
| /etf-index-fund-investor-guide.html | /mutual-funds/ | 301 active |

---

## Pages Requiring Classification

These HTML files exist in the workspace but are NOT in the approved manifest. They require KEEP/ARCHIVE/DELETE/REDIRECT classification:

| File | Current Status |
|------|----------------|
| index.html | PENDING — likely duplicate of / (PHASE 9 pending) |
| alerts.html | PENDING — not in manifest, may be AUXILIARY |
| etfs/holdings.html | PENDING — ETFS section not in approved scope |
| etfs/top-etfs.html | PENDING — ETFS section not in approved scope |
| evidence/historical.html | PENDING — Phase 8 evidence tool |
| global/markets.html | PENDING — Global markets, not Indian index focus |
| history.html | PENDING — may be Phase 5/8 replay related |
| history/replay.html | PENDING — Phase 8 replay tool |
| market/outlook-nifty-2026-09-13.html | PENDING — single dated outlook page |
| news/index.html | PENDING — news section not in approved scope |
| options-mobile.html | PENDING — mobile variant of options |
| portfolio.html | PENDING — portfolio tracker, not in approved scope |
| queries/index.html | PENDING — query library, not in approved scope |
| sectors/top.html | PENDING — sector data, not in approved scope |
| stock.html | PENDING — single stock outlook, may overlap scanner |
| stocks/52-week.html | PENDING — stock data, may overlap scanner |
| stocks/reliance.html | PENDING — single stock page |
| stocks/top-large-cap.html | PENDING — stock data |
| stocks/top-mid-small.html | PENDING — stock data |
| stocks/top-performers.html | PENDING — stock data |
| stocks/undervalued.html | PENDING — stock data |
| tools/intelligence.html | PENDING — Phase 9C tool, may be TOOL |
| tools/journal.html | PENDING — Phase 9A tool, may be TOOL |
| tools/walkforward.html | PENDING — Phase 8 tool |
| trade.html | PENDING — trade setup, may be CORE or AUXILIARY |

---

## Navigation Architecture (Approved)

```
TRADINGAI
├── Market → /market.html
│   └── NIFTY → /indices/nifty.html
│   └── BANKNIFTY → /indices/banknifty.html
│   └── FINNIFTY → /indices/finnifty.html
│   └── SENSEX → /indices/sensex.html
├── Today → /today/index.html
├── Options → /options/pcr.html
├── Strategies → /strategies.html
│   └── Strategy Builder → /strategy-builder.html
├── Tools → /tools/backtest.html, /tools/position-size.html
├── Scanner → /scanner.html
├── Research → /mutual-funds/
├── Learn → /learn/
└── Trust → /about.html, /contact.html, /privacy.html, /terms.html, /disclaimer.html, /404.html
```

---

## Duplicate Navigation Rule

The following 4-card block:

📊 Market Grid | 🔍 Scanner | 📈 Backtest | 🕘 Today LIVE

SHOULD appear on pages with product context (market, scanner, strategies, today, etc.)

SHOULD NOT appear on trust/legal pages (about, contact, terms, privacy, disclaimer, 404)

SHOULD NOT appear on education pages (learn/*) unless contextually relevant
