# Phase 41B — Product Surface Documentation
Generated: 2026-09-17

## Overview

This document describes the Phase 41B product surface — what the user
sees and interacts with across all pages.

## Pages

### Public Pages

| Page | URL | Purpose | Phase 41 Content |
|------|-----|---------|-------------------|
| Home | / | Landing page | No Phase 41 content |
| Today | /today/ | Current market snapshot | Market data, evidence, AI outlook |
| Indices/NIFTY | /indices/nifty.html | NIFTY detail | Market data, evidence, AI outlook |
| Indices/BANKNIFTY | /indices/banknifty.html | BANKNIFTY detail | Market data, evidence, AI outlook |
| Strategies | /strategies.html | Strategy listing | Strategy descriptions |
| Backtest | /tools/backtest.html | Backtest results | Phase 41 replay results |
| Journal | /tools/journal.html | Trade journal | Phase 9A |
| Intelligence | /tools/intelligence.html | Personal intelligence | Phase 9C |
| Position Sizing | /tools/position-size.html | Position calculator | No Phase 41 content |
| Mutual Funds | /mutual-funds/ | MF info | No Phase 41 content |
| FAQ | /faq.html | Q&A | No Phase 41 content |
| Contact | /contact.html | Contact form | No Phase 41 content |
| Legal | /legal.html | Legal info | No Phase 41 content |
| Sitemap | /sitemap.xml | Page index | No Phase 41 content |

### Data Flow (Public Pages)

```
User Request → HTML → JS → API Call → Flask → Backend → Database
                                                ↓
                                          AI Engine (Groq)
                                                ↓
                                          External APIs (yfinance, NSE)
```

### Phase 41 Data Pipeline

```
External Data → price_5m, market_outlooks, paper_trades →
  → /api/price/{symbol} → Live price
  → /api/market → Market summary
  → /api/market-evidence/{symbol} → Evidence evaluation
  → /api/ai-outlook/5m → AI outlook (Groq)
  → /api/trade-qualification → Qualification check
  → /api/paper-trades → Paper trades
  → /api/paper-trades/active → Active trades
```

### Phase 41B User-Facing Features

#### AI Outlook Display

On today/, indices/, and strategy pages:
- Bias (BULLISH/BEARISH/RANGE/MIXED)
- Confidence (0-100)
- Regime (trending, ranging, etc.)
- Summary (AI-generated text)
- Confirmation conditions
- Invalidation conditions
- Risk level
- Timestamp

#### Market Evidence Display

On today/ and indices/:
- Trend (EMA, ADX)
- Momentum (RSI, MACD)
- VWAP relation (above/below/near)
- Structure (higher highs, lower lows)
- Volatility (ATR, range)
- Options (PCR, OI change)
- Market confirmation (breadth, advance-decline)

#### Trade Qualification Display (NEED FRONTEND WORK)

On today/ and indices/:
- Individual qualification checks (AI outlook, evidence, trend, VWAP, momentum, structure, confirmation, invalidation, risk/reward, options, data quality)
- Trade status (TRADE / WAIT / NO TRADE)
- If WAIT: missing confirmation shown
- If NO TRADE: rejection reason shown
- Strategy name
- Entry price, stop, target

#### Paper Trade Display (NEED FRONTEND WORK)

On tools/:
- Active paper trades
- Trade history
- PnL
- Entry/exit details
- Exit reason

### Frontend Status

| Page | Phase 41 Ready | Notes |
|------|---------------|-------|
| /index.html | NO | No qualification/trade content |
| /today/index.html | NO | No qualification/trade content |
| /indices/nifty.html | NO | No qualification/strategy info |
| /indices/banknifty.html | NO | No qualification info |
| /strategies.html | NO | Needs paper trade status |
| /tools/backtest.html | NO | Needs Phase 41 results display |
| /tools/position-size.html | NO | No Phase 41 content |

**FRONTEND INTEGRATION IS INCOMPLETE** (Step 1 required)

## API Endpoints Available

See `phase41b_api_integration.md` for full API specification.

## Known Limitations

1. Public pages do not show qualification status
2. No real-time paper trade display
3. Backtest page shows Phase 36 results, not Phase 41
4. Strategies page doesn't show paper trade status
5. No unified dashboard for qualification + paper trades
