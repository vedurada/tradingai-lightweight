# TradingAI — Master HTML Redesign Specification

Created: 16 September 2026
Status: AUTHORITATIVE — awaiting VM inventory before implementation
Baseline: f8b6be1 → v2b5583a-baseline-15-g23100ca
Companion docs: docs/PAGE_MANIFEST.md, docs/PHASE29_FUNCTIONAL_AUDIT.md, docs/PHASE29_API_MAP.md

This specification is the authoritative implementation guide for any TradingAI HTML redesign. It takes precedence over all previous design documents.

---

## 0. Design System

Every production page uses the same shell:

```
┌────────────────────────────────────────────────────────────┐
│ TradingAI   Home Market Today Options Strategies Tools Learn │
│                                              Market ● LIVE │
├────────────────────────────────────────────────────────────┤
│ Breadcrumb / Page context                                   │
├────────────────────────────────────────────────────────────┤
│                                                              │
│                    PAGE-SPECIFIC CONTENT                     │
│                                                              │
├────────────────────────────────────────────────────────────┤
│ Related TradingAI tools / contextual links                   │
├────────────────────────────────────────────────────────────┤
│ Data source • Last updated • Freshness                       │
├────────────────────────────────────────────────────────────┤
│ Disclaimer • Privacy • Terms • About • Contact               │
└────────────────────────────────────────────────────────────┘
```

Global rules: responsive, fast, vanilla HTML/CSS/JS, consistent header/footer, one H1, meaningful H2/H3, no duplicate nav card walls, no unrelated modules, no fake market data, visible timestamps, visible data status, accessible buttons, SEO title/meta/canonical/OG, structured data where appropriate.

Dynamic data states (exactly 5): LIVE | UPDATED | STALE | UNAVAILABLE | ERROR
Never: indefinite "Loading…" when request has failed or endpoint unavailable.

---

## 1. HOME (/index.html and canonical /)

Sections (order):
1. Market Status (NIFTY/BANKNIFTY/FINNIFTY/SENSEX/VIX + timestamp)
2. Today's AI Market Outlook (regime, direction, confidence, evidence, invalidation)
3. Live Market Snapshot (5 index cards)
4. Options Intelligence (PCR, OI, Max Pain, Call Wall, Put Wall, Expected Move)
5. Market Breadth
6. Today's Key Levels (support, resistance, opening range, important zones)
7. AI Strategy Context (setup, conditions, risk, WAIT condition)
8. Quick Actions (links: Today, NIFTY, Options, Strategies, Builder)
9. Data/Freshness
10. Footer

Remove: mutual-fund grid, stock scanner results, long educational articles, unrelated global markets, portfolio, old 52-week modules, unrelated market widgets

---

## 2. TODAY (/today/index.html)

Sections (order):
1. TODAY — Date | Market Status | Last Updated
2. Market Snapshot (NIFTY/BANKNIFTY/SENSEX/FINNIFTY/VIX)
3. AI Market Outlook (regime, direction, confidence, evidence, invalidation)
4. Key Levels (support, resistance, opening range, important zones)
5. Options Intelligence (PCR, OI, Call Wall, Put Wall, Max Pain, Expected Move)
6. Market Breadth
7. Intraday Conditions (Bullish, Bearish, Range, No Trade)
8. AI Strategy Candidates
9. Risk Conditions
10. Session Timeline (09:15 → Current → 15:30)
11. Data Status
12. Footer

Purpose: Answer "What do I need to know before trading today?"

---

## 3. MARKET (/market.html)

Sections (order):
1. Market Overview
2. Major Index Grid (NIFTY/BANKNIFTY/FINNIFTY/SENSEX/VIX)
3. Market Breadth (Advancing, Declining, Unchanged, Breadth ratio)
4. Sector/Market Condition
5. Technical Market Snapshot (Trend, Momentum, Volatility, Breadth)
6. Overall Market Regime
7. Index Deep-Dive Links (NIFTY/BANKNIFTY/FINNIFTY/SENSEX)
8. Data Status
9. Footer

Do NOT duplicate full NIFTY analysis.

---

## 4. INDEX DEEP-DIVE TEMPLATE (4 pages)

Pages: /indices/nifty.html, /indices/banknifty.html, /indices/finnifty.html, /indices/sensex.html
Only instrument-specific data changes.

Sections (order):
1. Breadcrumb (Market > SYMBOL)
2. Index Header (spot, change, %, VIX, regime, confidence, timestamp)
3. AI Market Outlook (direction, confidence, regime, evidence, invalidation)
4. Technical Structure (VWAP, EMA20, EMA50, EMA200, RSI, MACD, ADX, CPR)
5. Price Structure / Chart
6. Key Levels (prev high/low, S1/S2, R1/R2, opening range, important zones)
7. Options Intelligence (PCR, Call OI, Put OI, OI Change, Call Wall, Put Wall, Max Pain, Expected Move)
8. Intraday Conditions (Bullish, Bearish, Range, No-Trade)
9. AI Options Strategy Analysis (candidate, why, entry, invalidation, target, max risk, expiry)
10. Build Strategy link → Position Size link → Backtest link
11. Data/Freshness
12. Footer

AI strategy section: say what conditions justify a strategy, NOT guaranteed trade.

---

## 5. OPTIONS — /options/pcr.html

Sections (order):
1. Index Selector (NIFTY/BANKNIFTY/FINNIFTY/SENSEX)
2. Options Snapshot (PCR, PCR Trend, Expiry, ATM)
3. OI Analysis (Call OI, Put OI, Call OI Change, Put OI Change)
4. OI Concentration (Call Wall, Put Wall, Largest concentrations)
5. Max Pain (Current Max Pain, Distance from Spot)
6. Expected Move (Expected Move, Upper Range, Lower Range)
7. Option Chain Summary (ATM ± selected strikes)
8. AI Options Interpretation (what data suggests, what invalidates it)
9. Strategy Connection (→ Today, → Strategy Analysis, → Strategy Builder)
10. Data Status
11. Footer

---

## 6. STRATEGIES (/strategies.html)

This is LIVE STRATEGY ANALYSIS, not a strategy tutorial.

Sections (order):
1. Today's Market Context (regime, direction, volatility, PCR, expected move)
2. Strategy Candidates (strategy, market condition, entry, invalidation, target, max risk, expiry)
3. Strategy Comparison (risk, reward, capital, market condition)
4. AI Reasoning
5. Build This Strategy
6. Historical/Backtest Performance (if real data exists)
7. Methodology
8. Disclaimer
9. Data Status
10. Footer

Do NOT show static wall of 15 strategies unrelated to today's market.

---

## 7. STRATEGY GUIDE

EDUCATIONAL. Separate from Today's AI strategy analysis.

Sections:
1. Strategy Categories (Bullish, Bearish, Range, Volatility)
2. Strategy Cards (Bull Call Spread, Bull Put Spread, Bear Put Spread, Bear Call Spread, Iron Condor, Long Straddle, etc.)
3. Each strategy: purpose, market condition, risk, reward, breakeven, example
4. → Open Strategy Builder

---

## 8. STRATEGY BUILDER (/strategy-builder.html)

Sections (order):
1. Index selector
2. Strategy type selector
3. Expiry selector
4. Leg Builder (Buy/Sell, CE/PE, Strike, Quantity, Premium)
5. Payoff Chart
6. Results (Max Profit, Max Loss, Breakeven, Capital, Margin, Risk)
7. Scenario Analysis
8. Build / Reset
9. Risk Disclaimer

---

## 9. POSITION SIZE (/tools/position-size.html)

Sections (order):
1. Account Capital
2. Max Risk %
3. Risk Amount
4. Entry Price
5. Stop Loss
6. Lot Size
7. Calculate
8. Result (Lots, Quantity, Position Value, Maximum Loss, Risk %)
9. Risk Warning
10. Link to Strategy Builder

Simple is better.

---

## 10. BACKTEST (/tools/backtest.html)

Sections (order):
1. Settings (Instrument, Strategy, Period, Capital, Risk %, Brokerage, Slippage)
2. Run Backtest
3. Performance Summary (Trades, Win Rate, Net P&L, Profit Factor, Max Drawdown, Average R)
4. Equity Curve
5. Drawdown
6. Trade Ledger
7. Methodology
8. Disclaimer

Do NOT fabricate results. Empty state before execution: "No results yet. Configure parameters and run the backtest."

---

## 11. SCANNER (/scanner.html)

Secondary feature.

Sections (order):
1. Filters (Market, Trend, RSI, VWAP, EMA, MACD, Volume)
2. Scan
3. Results Table (Stock, Price, Change, Regime, Trend, RSI, VWAP, Signal)
4. Stock Detail
5. Optional → Stock analysis

Do NOT let Scanner dominate homepage.

---

## 12. MUTUAL FUNDS (/mutual-funds/)

Secondary research/SEO.

Sections (order):
1. Category Selector
2. Fund Table (Fund, Category, NAV, 1Y, 3Y, 5Y, Expense ratio)
3. Category Comparison
4. Fund Details
5. Methodology
6. Data Date
7. Disclaimer

SPELL: "Annualised" not "Anualised".
Do NOT mix with options trading content.

---

## 13. LEARN

/learn/ — Education → live tool workflow
Sections: Option Chain, PCR, VWAP, CPR, Greeks, Strategies, Learning Path (Beginner → Intermediate → Practical), Live Tool Links

Each lesson links to live tool where concept is used:
Learn PCR → Live PCR → NIFTY Options → Strategy Analysis

---

## 14-18. TRUST PAGES

/about.html — What we do, who it's for, how it works, data sources, AI role, limitations, what it is not, contact
/contact.html — Feedback, data issue reporting, general enquiries, contact method, FAQ
/privacy.html — Information collected, usage, cookies, analytics, third-party, retention, security, user rights, contact
/terms.html — Acceptance, service use, market data, AI info, user responsibility, third-party, limitations, IP, changes, contact
/disclaimer.html — Not financial advice, data limitations, AI output limitations, no guarantee of returns, options/leverage risks, backtest limitations, user responsibility, data sources, contact
/404.html — Page not found, links: Home, Today's Outlook, Market, Options, Strategies, Learn. No dashboard.

All trust pages: NO Market Grid, Scanner, Backtest, Today cards, trading recommendations.

---

## 19. Legacy Pages (REDIRECT-ONLY)

/home.html → 301 → /
/stocks.html → 301 → /scanner.html
/fixed-loss-options.html → 301 → /options/pcr.html
/index-option-risk-management.html → 301 → /learn/option-greeks.html
/etf-index-fund-investor-guide.html → 301 → /mutual-funds/

No standalone content. No templates.

---

## Implementation Order (7 Batches)

**Batch 1**: Global shell (CSS + common.js + data-state.js) + Home + Today
**Batch 2**: Market + Four index pages (nifty/banknifty/finnifty/sensex)
**Batch 3**: Options (pcr) + Strategies
**Batch 4**: Builder + Position Size + Backtest
**Batch 5**: Scanner + Mutual Funds
**Batch 6**: Learn + Trust pages
**Batch 7**: Remove unplanned content + Link/SEO/regression audit

---

## Quality Gate

A page is complete ONLY when:
- [ ] Layout matches this specification
- [ ] Every visible section has a defined purpose
- [ ] No unplanned cards remain
- [ ] No unplanned links remain
- [ ] No obsolete modules remain
- [ ] Dynamic data has a defined state (LIVE/UPDATED/STALE/UNAVAILABLE/ERROR)
- [ ] Timestamps are visible
- [ ] Errors are handled
- [ ] Mobile layout works
- [ ] Internal links work
- [ ] SEO metadata is correct
- [ ] Existing 75 tests continue to pass

---

## Pre-Implementation Checklist

Before redesign begins:
1. Read docs/PAGE_MANIFEST.md as page-scope authority
2. Read docs/PHASE29_FUNCTIONAL_AUDIT.md for runtime findings
3. Work from a new branch (preserve f8b6be1)
4. Compare every HTML file against PAGE_MANIFEST.md
5. Classify every element: KEEP / MOVE / RESTRUCTURE / REMOVE / REPLACE
6. Preserve backend/API hooks until dependency analysis confirms they're obsolete
7. Keep legacy URLs as redirects where required
8. Run 75 tests before any changes
9. Add page/layout/link regression tests with changes
10. Do NOT deploy to VM until runtime/API verification completed
11. Do NOT create /api/key-levels, /api/risk, etc. blindly — inspect existing backend first
12. Do NOT fabricate market data, AI results, or backtest performance
