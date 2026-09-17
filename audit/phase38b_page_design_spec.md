# Phase 38B — Page Design Specification
Generated: 2026-09-17

## 1. Page Purpose

TradingAI.in is a **daily evidence-based market decision terminal** for Indian intraday index-options traders, primarily NIFTY and BANKNIFTY traders.

## 2. Target User

**Primary**: Indian intraday index-options traders (NIFTY, BANKNIFTY)
**Secondary**: SENSEX intraday options traders, FINNIFTY traders (where data reliable), learning traders

Every page must answer: "How does this help an intraday index-options trader make a more informed decision today?"

## 3. Page Hierarchy

```
/index.html (HOME — fast daily summary)
  ├── /today/index.html (DEEP TERMINAL — daily workflow)
  ├── /market.html (MARKET CONTEXT — broader view)
  ├── /indices/nifty.html (NIFTY detail)
  ├── /indices/banknifty.html (BANKNIFTY detail)
  ├── /indices/sensex.html (SENSEX overview)
  ├── /indices/finnifty.html (FINNIFTY with data notice)
  ├── /options/pcr.html (OPTIONS INTELLIGENCE)
  ├── /strategies.html (STRATEGY DECISION SUPPORT)
  ├── /strategy-builder.html (CALCULATOR)
  ├── /tools/backtest.html (EVIDENCE)
  ├── /tools/position-size.html (RISK CALCULATOR)
  ├── /tools/walkforward.html (VALIDATION EVIDENCE)
  ├── /trade.html (TRADE DETAIL)
  ├── /learn/ (EDUCATION)
  └── /{about,contact,privacy,terms,disclaimer}.html (TRUST)
```

## 4. Sections Per Page

### /index.html
- Header: TradingAI logo, nav (Today, Market, NIFTY, BANKNIFTY, Options, Strategies, Tools, Learn)
- MARKET STATUS: OPEN/CLOSED, IST time, session status, last update, data age
- PRIMARY INDEX CARDS: NIFTY, BANKNIFTY (dominant), SENSEX, VIX — value, change, %, state, timestamp
- MARKET REGIME: BULLISH/BEARISH/RANGE/MIXED with confidence, evidence, invalidation
- AI OUTLOOK: bias, confidence, why, watch levels, invalidation, risk
- TRADE STATUS: NO TRADE or CONDITIONAL SETUP with status
- OPTIONS SNAPSHOT: PCR, expiry, key OI, expected move, max pain (when valid), timestamp
- TODAY CTA: "Open Today's Trading Terminal"

### /today/index.html
- Top: Market status, current time, data timestamp, data state
- NIFTY + BANKNIFTY side by side: price, change, regime, VWAP, EMA, RSI, ADX, CPR, support, resistance
- MARKET DECISION PANEL: NIFTY regime, BANKNIFTY regime, Overall
- AI OUTLOOK: bias, confidence, evidence, confirmation, invalidation, risk
- OPTIONS INTELLIGENCE: expiry, PCR, OI, strikes, expected move, max pain, timestamp
- STRATEGY PANEL: MARKET VIEW → STRATEGY → CONDITION → INVALIDATION → RISK → STATUS

### /market.html
- Major indices (NIFTY, BANKNIFTY, SENSEX)
- India VIX, breadth, sectors relevant to index movement
- Market pulse, volatility, advance/decline
- Volatility context

### /indices/nifty.html (flagship)
1. NIFTY current price
2. Change
3. Data state
4. Market regime
5. AI outlook
6. Confidence
7. Price structure (vs VWAP, EMA trend)
8. VWAP, EMA20, EMA200 (if available)
9. RSI, MACD, ADX
10. CPR, support, resistance, prev day high/low
11. Intraday conditions
12. Options intelligence
13. Conditional strategy
14. Risk/invalidation
15. Backtest/evidence link
16. Educational links

### /indices/banknifty.html
Same architecture as NIFTY. BankNIFTY is primary.

### /indices/sensex.html
Same architecture, lower prominence than NIFTY/BANKNIFTY.

### /indices/finnifty.html
Same architecture IF data reliable. Otherwise: "DATA UNAVAILABLE" message.

### /options/pcr.html (OPTIONS INTELLIGENCE)
- NIFTY, BANKNIFTY PCR
- Expiry, call OI, put OI
- Key strikes, OI change
- Expected move, max pain (when valid)
- Timestamp, EOD/LIVE state
- Clearly labeled EOD data

### /strategies.html
Organized by market condition:
- TRENDING BULLISH → possible structures
- TRENDING BEARISH → possible structures
- RANGE → possible structures
- HIGH VOLATILITY → possible structures
- NO TRADE → conditions where strategies shouldn't be used
Each strategy: condition, structure, rationale, entry, invalidation, risk, reward, evidence, data status

### /strategy-builder.html
Interactive calculator for NIFTY/BANKNIFTY options:
- Strikes, premiums, lots, payoff, max profit/loss, breakeven, Greeks, position size
- CALCULATED vs LIVE BROKER DATA clearly distinguished

### /tools/backtest.html
Evidence and research:
- Instrument, strategy, timeframe, period, trades, wins, losses, win rate, P&L, max DD, expectancy, equity curve
- Labeled as "Rules-based proxy / research backtest"

### /tools/position-size.html
Risk calculator:
- Capital, risk %, entry, stop, lot size, lots
- Maximum risk, quantity, capital requirement, risk/reward
- Warning: "Position sizing does not guarantee a profitable trade"

### /tools/walkforward.html
Walk-forward validation evidence (Phase 8):
- Dev/Validation/OOS metrics
- Data coverage reporting

### /learn/
Education supporting trading workflow:
- Option Chain, PCR, VWAP, CPR, Greeks, IV, OI, Support/Resistance, Risk Management, Options Spreads
- Quality > quantity

### /trade.html
Intraday trade setup detail (from /api/trade-setup):
- Entry, stop, target, strategy
- Stage, readiness, evidence
- Conditional presentation

## 5. Data Dependencies

| Page | APIs | JS | Update | State |
|------|------|-----|--------|-------|
| /index.html | /api/price/{NIFTY,BANKNIFTY,SENSEX}, /api/vix, /api/market-outlook, /api/trade-setup/NIFTY | frontend refresh | 30s | LIVE/STALE |
| /today/index.html | /api/price/*, /api/market-outlook, /api/trade-setup/*, /api/pcr, /api/maxpain | frontend refresh | 15s | LIVE/STALE |
| /market.html | /api/price/*, /api/vix, /api/market-outlook | frontend refresh | 60s | LIVE/STALE |
| /indices/*.html | /api/price/{SYM}, /api/NIFTY, /api/market-outlook | frontend refresh | 30s | LIVE/STALE |
| /options/pcr.html | /api/pcr, /api/maxpain, /api/expected-move | frontend refresh | 300s | LIVE/EOD |
| /strategies.html | /api/market-outlook, /api/trade-setup | static | manual | CALCULATED |
| /tools/backtest.html | static JSON | static | manual | EOD |
| /tools/position-size.html | none | calculator | on-input | CALCULATED |
| /learn/* | none | static | manual | STATIC |
| /{about,contact...} | none | static | manual | STATIC |

## 6. CTA Flow

```
/index.html → /today/index.html (primary CTA: "Open Today's Trading Terminal")
/today/index.html → /indices/nifty.html, /indices/banknifty.html (detailed analysis)
/indices/nifty.html → /options/pcr.html, /strategies.html, /tools/position-size.html
/options/pcr.html → /strategies.html, /tools/backtest.html
/strategies.html → /strategy-builder.html, /tools/position-size.html
/tools/position-size.html → /strategies.html (after sizing)
/learn/* → /indices/*.html, /options/pcr.html (back to trading)
```

## 7. Mobile Priority

1. Market status
2. NIFTY/BANKNIFTY
3. Regime
4. AI outlook
5. Trade status
6. Options intelligence
7. Levels
8. Strategy
9. Detailed indicators

No decorative content before market information.

## 8. SEO Purpose

| Page | SEO Keywords |
|------|-------------|
| /index.html | NIFTY intraday outlook, BANKNIFTY outlook, Indian market today |
| /today/index.html | NIFTY today trading, intraday NIFTY strategy, today outlook |
| /market.html | NIFTY market context, India VIX, market breadth |
| /indices/nifty.html | NIFTY intraday, NIFTY support resistance, NIFTY VWAP |
| /indices/banknifty.html | BANKNIFTY intraday, BANKNIFTY outlook |
| /options/pcr.html | NIFTY PCR, options OI, implied move |
| /strategies.html | intraday options strategy, NIFTY strategy, options spread |
| /strategy-builder.html | options calculator, payoff calculator |
| /tools/backtest.html | NIFTY backtest, options backtest |
| /tools/position-size.html | position sizing calculator, risk management |
| /learn/* | learn options trading, option chain explained |

## 9. Data State Implementation

Every dynamic page supports:
- LIVE: Real-time data from API
- DELAYED: Data older than threshold but still useful
- STALE: Last EOD data, market closed
- UNAVAILABLE: Required data not available
- CALCULATED: Computed values
- EOD: End-of-day data

## 10. Components to Create

### Shared Header
- TradingAI logo
- Navigation: Today, Market, NIFTY, BANKNIFTY, Options, Strategies, Tools, Learn
- Market status badge (OPEN/CLOSED)
- Data freshness indicator

### Shared Market Status Badge
```
MARKET OPEN | Updated 10:42:31 IST | Data age: 8 sec
```

### Shared Index Card
```
NIFTY
25,XXX.XX
+XXX (+X.XX%)
BULLISH
Updated ...
```

### Shared Regime Display
```
MARKET REGIME
BULLISH
Confidence: 72%
Evidence: VWAP, EMA, ADX
```

### Shared AI Outlook Panel
```
AI MARKET OUTLOOK
BEARISH
Confidence: 68%
Why: ...
Watch: ...
Invalidation: ...
```

### Shared Trade Status Panel
```
TRADE STATUS
NO TRADE
Reason: Signals conflict. Wait for confirmation.
```
or:
```
TRADE STATUS
CONDITIONAL SETUP
BEAR PUT SPREAD
Trigger: ...
Invalidation: ...
Risk: Defined
```

### Shared Options Panel
```
OPTIONS INTELLIGENCE
PCR: 1.23
Expiry: 2026-09-22
Key Strikes: 25000, 25100, 25200
Expected Move: ±120 pts
```

## 11. Design System Rules

- Professional, fast, trading-focused
- High information density without clutter
- No excessive gradients, stock photos, giant banners
- Strong visual hierarchy
- Important states instantly recognizable (text + icon + label, not just color)
- NO TRADE must be visually distinct from TRADE
- STALE/UNAVAILABLE clearly labeled
- Mobile responsive (375px, 390px, 768px, desktop)

## 12. Reuse Existing Components

- Shared CSS from static/css/main.css
- Shared JS from static/js/
- Existing API endpoints (no new backend needed)
- Existing data pipeline (price_5m, indicators, market_outlooks, etc.)
- Existing frontend refresh architecture

## 13. Do NOT Change

- Frozen AI model files (outlook.py, ai_outlook.py)
- Trading logic (Phase 4-8 modules)
- Backtest methodology
- Data fetching architecture
- Historical backtest results

## 14. Implementation Order

1. Shared components (header, nav, market status, cards, panels)
2. /index.html redesign
3. /today/index.html redesign
4. /market.html update
5. Index pages update
6. /options/pcr.html update
7. /strategies.html update
8. Tools pages update
9. Learn pages update
10. Validation (functional, UX, mobile, SEO, perf)
