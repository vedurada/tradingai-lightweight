# PHASE 2 AUDIT - TradingAI.in

Date: 2026-09-09

## Architecture
Static HTML + Vanilla JS + Python + SQLite + Nginx + Cron + yfinance

## Working Components (DO NOT REMOVE)

### Backend
- fetch_market.py - yfinance data fetching with cache
- indicators.py - EMA, VWAP, RSI, MACD, ADX, ATR, Bollinger, Pivot, CPR, Support/Resistance
- regime.py - Market regime scoring (TRENDING_BULLISH/BEARISH, RANGE_BOUND, HIGH_VOLATILITY)
- scenarios.py - Bullish/bearish/range scenarios
- strategies.py - Strategy selection by regime
- ai_outlook.py - LLM + rule-based fallback
- database.py - SQLite with instruments, prices, indicators, regimes, strategies, history, history_archive
- history_logger.py - Stores outlook data in SQLite
- generate_data.py - Generates per-symbol JSON
- generate_json.py - Generates market.json + history.json + health.json
- monitor.py - Health checks

### Frontend
- index.html - Homepage with market condition + AI outlook
- market.html - Market overview grid
- indices/nifty.html - NIFTY dedicated page
- indices/banknifty.html - Bank NIFTY dedicated page
- scanner.html - Stock scanner with filters
- strategies.html - Strategy library
- history.html - P&L + AI outlook history table
- stocks/reliance.html - Stock page

### Features
- Auto-refresh every 30s during market hours (9:30-15:30 IST)
- P&L tracking: 9:30 AM lock, 3:20 PM close, WIN/LOSS/FLAT
- AI outlook history on index pages
- Timestamp bar on all pages
- Cache busting (version params + timestamp)
- Staleness detection (price==0)
- Weekly archive (7+ days → history_archive)
- 13 instruments with stale=false, quality=GOOD
- Cron: every 1min, 9:30 AM, 3:20 PM
- GitHub repo: https://github.com/vedurada/tradingai-lightweight

## Incomplete / Needs Improvement

### Data Model
- No evidence_strength field (0-100)
- No multi-timeframe analysis (daily/1H/15M/5M)
- No explicit market structure (prev high/low, day high/low)
- No volatility classification (LOW/NORMAL/HIGH)
- No no-trade engine
- No strategy matrix (regime + volatility → strategy)
- No historical validation statistics
- No CPR classification in frontend (NARROW/NORMAL/WIDE)
- No breakout/breakdown detection
- No higher high / higher low / lower high / lower low detection

### AI Prompt
- Prompt is basic, needs improvement per Phase 2 spec
- No evidence/conflicting evidence display
- Strategy output doesn't state "verify live option prices"

### JSON Contract
- Not standardized per Phase 2 spec
- Missing: evidence_strength, trend, momentum, volatility, market_structure, strategy_environment, invalidation, no_trade_conditions

### Homepage
- No market radar (breakout/breakdown/bullish/bearish/range/high_vol/no_trade)
- No evidence strength display
- No key level display

### Index Pages
- Correct layout but needs evidence strength, market structure, no-trade conditions
- Need: why, key levels, invalidation, strategy environment

### History Page
- No filter by asset/regime/bias/month/year
- No historical validation statistics
- No results by evidence-strength bucket

### Monitoring
- health.json missing: db status, disk usage, memory, last successful yfinance, last AI gen, last history snapshot
- No cron job locking
- No log rotation

### Database
- No indexes on frequently queried columns
- No migration mechanism for schema changes

### Performance
- Sequential processing OK for 13 instruments
- yfinance cache working
- No unnecessary multiprocessing

## Regime Classification
Current: TRENDING_BULLISH, TRENDING_BEARISH, RANGE_BOUND, HIGH_VOLATILITY
Missing: BREAKOUT, BREAKDOWN, LOW_VOLATILITY, REVERSAL, UNCONFIRMED

## Strategy Environments
Current: Bull Call Spread, Bull Put Spread, Bear Put Spread, Bear Call Spread, Iron Condor, Defined-risk premium selling, NO TRADE
Needs: Strategy matrix by regime + volatility

## Phase 2 Priority Order
PHASE A: Audit (this document)
PHASE B: Improve data model (add missing fields)
PHASE C: Improve regime engine (add evidence, BREAKOUT, BREAKDOWN, REVERSAL, UNCONFIRMED)
PHASE D: Improve scenario engine (add triggers, confirmations, invalidations)
PHASE E: Improve strategy environment (add strategy matrix, volatility classification)
PHASE F: Improve AI prompt/output (improve prompt, add evidence/conflicting)
PHASE G: Improve JSON (standardize contract, extend compatibly)
PHASE H: Improve homepage (add market radar, evidence strength, key levels)
PHASE I: Improve index pages (add evidence, structure, invalidation, no-trade)
PHASE J: Improve stock scanner/pages
PHASE K: Improve history analytics (add filters, validation stats)
PHASE L: Improve monitoring (health.json, cron locking, log rotation)
PHASE M: Performance testing
PHASE N: Final production testing