# TradingAI Database Documentation

## Database Location
`/opt/tradingai_new/database/tradingai.db` (SQLite)

## Schema
Schema SQL at `database/schema.sql`. Generated from live database.

## Table Categories

### Market Data
| Table | Purpose |
|-------|---------|
| `instruments` | NIFTY, BANKNIFTY, INDIA_VIX master data |
| `trading_sessions` | Daily session summaries |
| `market_candles_5m` | 5-minute OHLCV candles |
| `market_snapshots` | Market state snapshots with indicators |
| `market_levels` | Support/resistance/pivot levels |
| `market_indicators` | Named indicator values |
| `volatility_snapshots` | IV, HV, PCR, OI data |

### Historical Engine
| Table | Purpose |
|-------|---------|
| `historical_sessions` | Completed session features |
| `scenario_definitions` | Scenario rule definitions |
| `scenario_candidates` | Candidate scenarios per session |
| `scenario_matches` | Current scenario match states |
| `scenario_confirmations` | Confirmation/invalidation events |

### Trading
| Table | Purpose |
|-------|---------|
| `trade_candidates` | Potential trades before qualification |
| `qualified_trades` | Passed qualification checks |
| `daily_trade_locks` | One-trade-per-day enforcement |
| `paper_trades` | Active/closed paper trades |
| `paper_trade_events` | Trade event log (entry, exit, triggers) |

### Backtest
| Table | Purpose |
|-------|---------|
| `backtest_runs` | Backtest run metadata |
| `backtest_decisions` | Per-candle decision records |
| `backtest_trades` | Simulated trades |
| `backtest_outcomes` | Aggregated backtest metrics |

### System
| Table | Purpose |
|-------|---------|
| `ai_explanations` | AI explanation log |
| `data_quality_events` | Data quality checks |
| `pipeline_runs` | Pipeline execution log |
| `system_health` | Health check history |
| `research_daily_decisions` | Daily decision audit trail |

## Data States
Market data states: LIVE, STALE, LAST_VALID, PARTIAL, UNAVAILABLE, INSUFFICIENT_DATA, API_ERROR, WAITING

Trading states: NOT_ACTIVE, WATCH, PARTIALLY_MATCHED, CONFIRMED, INVALIDATED, EXPIRED, QUALIFIED, NO_TRADE, ACTIVE, CLOSED
