# Core Trader UI — Master Report

## Status

| Category | Count | Details |
|----------|-------|---------|
| Pages that exist | 6 | `/`, `/today/index.html`, `/indices/nifty.html`, `/indices/banknifty.html`, `/strategies.html`, `/tools/backtest.html` |
| Pages that exist but also have walkforward | 1 | `/tools/walkforward.html` |
| Pages that are MISSING | 3 | `/options/index.html`, `/ai-track-record.html`, `/research/index.html` |
| Bugs found | 5 | Duplicate nav links (4 pages), CSS path mismatch (89 files) |
| API endpoints validated | 25 | All referenced endpoints exist and respond correctly |
| Responsive breakpoints | 2 | 768px tablet, 480px mobile — applied consistently |
| SEO elements | Mostly OK | Canonical, og tags, ld+json present on all existing pages |

## Decision Path Coverage

The 9 pages cover the PRE-MARKET SCENARIO → ACTIVATION → TRADE/WAIT/NO TRADE path as follows:

```
PRE-MARKET:
  / → Market Status, Data Status, Session State indicator
  /today/index.html → Session Status, Pre-Market conditions
  /indices/nifty.html → Snapshot with regime detection

ACTIVATION:
  /today/index.html → Intraday Conditions (Bullish/Bearish/No-Trade)
  /indices/nifty.html → Intraday Conditions, Key Levels
  /today/index.html → Market Evidence, Trade Qualification
  /indices/nifty.html → Market Evidence, Trade Qualification

TRADE/WAIT/NO TRADE:
  /today/index.html → Trade Qualification (GO/WAIT/NO_SETUP), Strategy Candidates, Paper Trade
  /today/index.html → Risk Management, Session Timeline
  /indices/nifty.html → AI Strategy, Paper Trade
  /strategies.html → Strategy Engine (ACTIVE/CONDITIONAL/NO TRADE)
  /tools/backtest.html → Deterministic backtest (trade outcomes)

CROSS-CUTTING:
  / → Quick Actions, AI Outlook, Options Intelligence
  /options/index.html → Options hub (MISSING)
  /ai-track-record.html → AI accuracy history (MISSING)
  /research/index.html → Research hub (MISSING)
```

## Issues Requiring Immediate Action

### CRITICAL (must fix)
1. **Create `/options/index.html`** — Options intelligence hub page (PCR, max pain, OI, expected move, chain, strategy recommendations)
2. **Create `/ai-track-record.html`** — AI prediction track record page (historical accuracy, verdict history)
3. **Create `/research/index.html`** — Research hub page (market research, analysis reports)

### HIGH (significant impact)
4. **Fix CSS path** — `/assets/css/main.css` doesn't exist in workspace; 89 files reference it. Need to verify nginx maps this correctly OR fix references to `/static/css/main.css`
5. **Remove duplicate nav links** — `/options/pcr.html` appears twice in nav on nifty.html, banknifty.html, sensex.html, finnifty.html

### MEDIUM (improvements)
6. **Add responsive testing** for the 3 new pages
7. **Add SEO elements** for the 3 new pages (canonical, og tags, ld+json)
8. **Ensure consistency** of data sections across all 9 pages

## Pages Already Implemented (6/9)

### `/` (index.html) — 488 lines, 24KB
- MARKET STATUS, MARKET SNAPSHOT (5 cards), AI MARKET OUTLOOK, Trade Qualification, Paper Trade, Market Evidence, Advance/Decline, Data Status, Options Intelligence (4 cards), Quick Actions, Disclaimers
- **Strengths**: Comprehensive, good data density, clear CTAs
- **Weakness**: Duplicate nav Options link

### `/today/index.html` — 367 lines, 25KB  
- Session Status, Market Snapshot, AI Outlook, Key Levels, Options Intelligence, Market Breadth, Intraday Conditions, Market Evidence, Trade Qualification, Paper Trade, Strategy Candidates, Risk Management, Session Timeline
- **Strengths**: Most complete trader terminal, excellent decision-path coverage
- **Weakness**: References /assets/css/main.css (line 16)

### `/indices/nifty.html` — 408 lines, 28KB
- Snapshot, AI Outlook, Technical Structure (6 indicators), Key Levels, Options Intelligence, Intraday Conditions, AI Strategy, Market Evidence, Trade Qualification, Paper Trade
- **Strengths**: Deep index-specific decision page
- **Weakness**: Duplicate nav Options link

### `/indices/banknifty.html` — 385 lines, 26KB
- Identical structure to NIFTY with BANKNIFTY-specific data
- **Weakness**: 2x duplicate nav Options links

### `/strategies.html` — 293 lines, 22KB
- Strategy engine with ACTIVE/CONDITIONAL/NO TRADE labels, payoff comparison, performance table
- **Strengths**: Clear strategy categorization, good UX

### `/tools/backtest.html` — 408 lines, 31KB
- Backtest form, metrics grid, equity curve, drawdown curve, trade ledger, AI outlook history
- **Strengths**: Excellent deterministic backtest UI, good documentation

## Pages To Create (3/9)

### `/options/index.html` — Required sections
- Options Hub header with index selector (NIFTY/BANKNIFTY/FINNIFTY/SENSEX)
- PCR card, Max Pain card, OI Concentration card, Expected Move card
- Option Chain table (ATM strikes, OI, IV, delta, gamma)
- Strategy recommendations based on regime
- PCR Trend, Max Pain History, IV Percentile
- Links to PCR detail page, strategy builder, today terminal
- Consistent with other index pages (same CSS, nav, consent, loading states)

### `/ai-track-record.html` — Required sections
- AI Prediction Accuracy Summary (overall accuracy, by symbol, by period)
- Verdict History Table (date, symbol, verdict, confidence, outcome)
- Regime Prediction Accuracy
- Trade Qualification Accuracy
- AI vs No-AI comparison
- Walk-forward evidence summary
- Historical consistency metrics
- Links to walkforward page, journal, intelligence

### `/research/index.html` — Required sections
- Market Research Hub header with index selector
- Research Reports (market outlook, regime analysis, strategy reports)
- Educational Content (strategy guides, indicator explanations)
- Market Analysis (technical analysis, fundamental analysis)
- Study Materials (PDFs, guides, tutorials)
- Research Methodology documentation
- Links to strategies, walkforward, journal, intelligence pages
