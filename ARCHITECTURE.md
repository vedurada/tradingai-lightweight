# TradingAI Architecture

## System Overview

TradingAI is a deterministic market-intelligence and paper-trading system for Indian index options.

## Core Pipeline

```
PREVIOUS SESSIONS → HISTORICAL ANALYSIS → SCENARIO CANDIDATES → TODAY'S MARKET
    ↓                                                      ↓
SCENARIO MAP ← SCENARIO MATCHING ← CURRENT MARKET STATE
    ↓
CONFIRMATION CHECK
    ↓
OPTIONS ANALYSIS
    ↓
STRATEGY SELECTION
    ↓
RISK QUALIFICATION
    ↓
DAILY TRADE LOCK CHECK
    ↓
TRADE DECISION (QUALIFIED or NO TRADE)
    ↓
AI EXPLANATION (downstream)
    ↓
PAPER TRADE (if qualified)
    ↓
MONITORING & EXIT
```

## Components

### app/api/app.py
Flask REST API serving all endpoints under `/api/`.

### app/core/
- **db.py**: SQLite connection with foreign keys and Row factory.
- **config.py**: Loads JSON config files (instruments, settings).
- **qualification.py**: Master qualification engine — checks all conditions for a trade.

### app/market/
- **provider.py**: Market data provider using yfinance for NIFTY, BANKNIFTY, INDIA_VIX.

### app/scenarios/
- **engine.py**: Scenario candidate generation and match evaluation (WATCH/PARTIALLY_MATCHED/CONFIRMED/INVALIDATED).

### app/strategies/
- **engine.py**: Strategy selection based on scenario type, direction, volatility.

### app/risk/
- **engine.py**: Risk validation — entry/stop/target levels, reward:risk ratio, max risk.

### app/paper_trade/
- **engine.py**: Paper trade creation, monitoring (stop/target/scenario), exit handling.

### app/research/
- **backtest.py**: Historical replay engine with no-look-ahead validation.

### app/ai/
- **explanation.py**: AI explanation layer — downstream, non-authoritative.

## Database

SQLite at `database/tradingai.db`. Schema at `database/schema.sql`.

Key tables:
- `instruments` — NIFTY, BANKNIFTY, INDIA_VIX
- `market_candles_5m` — 5-minute OHLCV data
- `market_snapshots` — Market state snapshots
- `scenario_definitions` — Scenario rule definitions
- `scenario_candidates` — Historical candidates per session
- `scenario_matches` — Current scenario match states
- `qualified_trades` — Qualified trade records
- `daily_trade_locks` — One-trade-per-day enforcement
- `paper_trades` — Active/closed paper trades
- `backtest_runs`, `backtest_decisions`, `backtest_trades`, `backtest_outcomes` — Backtest data
- `system_health` — Health check history

## Data Flow

All market data flows: FETCH → VALIDATE → NORMALIZE → STORE → QUALITY CHECK → ENGINE.

## Deterministic Hierarchy

```
Market Data → Deterministic Engine → Trade Decision → AI Explanation
```

AI cannot override: entry, stop, target, risk, daily limit, or convert NO_TRADE to TRADE.

## No-Look-Ahead

Every backtest decision records:
- `latest_allowed_data_timestamp` (the candle used)
- `actual_latest_data_timestamp` (must be ≤ decision timestamp)

## Timezone

All trading logic uses Asia/Kolkata (IST). UTC used internally where convenient, IST for all display.
