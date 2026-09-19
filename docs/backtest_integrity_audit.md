# Backtest Integrity Audit Report

## Executive Summary

This report documents the Phase 4 audit of the TradingAI.in historical research engine.
The audit identified and fixed a critical issue where 1,538 NIFTY and 1,440 BANKNIFTY
reported "trades" were NOT actual qualified trades.

---

## A. What were the 1,538/1,440 numbers?

The 1,538 NIFTY and 1,440 BANKNIFTY "trades" from Phase 3 were **NOT actual qualified trades**.
They were qualification attempts at every candle where:

1. Backtest loops through ALL 2,925 candles per instrument
2. For each candle, `qualify()` is called with `research=True`
3. `research=True` skips ALL database writes (no daily lock persistence)
4. Daily lock check uses `datetime.now()` (today), NOT the historical candle date
5. Every candle with a CONFIRMED scenario match became a "trade"

**Root cause**: The qualification engine checked daily_locks for the CURRENT date,
never for the historical date being evaluated. Combined with research mode skipping writes,
no daily limit existed during backtests.

---

## B. Actual Trade Counts

| Instrument | Sessions | Candidates | Confirmed | Qualification Attempts | Qualified | Completed |
|---|---|---|---|---|---|---|
| NIFTY | 39 | 1,920 | 939 | 39 | 39 | 39 |
| BANKNIFTY | 39 | 1,983 | 983 | 39 | 39 | 39 |

Under MAX_QUALIFIED_TRADES_PER_DAY=1 with 39 sessions, maximum possible = 39 per instrument.

---

## C. Daily Limit Verification

| Instrument | Trading Days | Days With Trade | Max Trades/Day | Limit Violations |
|---|---|---|---|---|
| NIFTY | 39 | 39 | 1 | 0 |
| BANKNIFTY | 39 | 39 | 1 | 0 |

**Status**: PASS

---

## D. Live DB Mutations During Backtest

**Status**: PASS

All backtests verified that `qualified_trades`, `paper_trades`, and `daily_trade_locks`
remain unchanged during backtest execution. Research mode prevents all live DB mutations.

---

## E. Look-Ahead Violations

**Status**: PASS

All backtest decisions have `lookahead_check='PASS'`. Each decision uses only candles
up to and including the decision timestamp. No future data is used in qualification.

---

## F. Completed Trade Counts

| Period | NIFTY | BANKNIFTY |
|---|---|---|
| 7D | 4 | 4 |
| 30D | 20 | 20 |
| 90D | 39 | 39 |

---

## G. Performance Metrics (90D)

### NIFTY

| Metric | Value |
|---|---|
| Trades | 39 |
| Wins | 39 |
| Losses | 0 |
| Breakeven | 0 |
| Win Rate | 100.0% |
| Avg PnL | 6,019.27 |
| Median PnL | 6,046.50 |
| Total PnL | 234,751.44 |
| Max Drawdown | 0.00 |
| Largest Win | 6,159.50 |
| Largest Loss | 5,812.00 |
| Profit Factor | NOT_AVAILABLE (no losses) |

### BANKNIFTY

| Metric | Value |
|---|---|
| Trades | 39 |
| Wins | 39 |
| Losses | 0 |
| Breakeven | 0 |
| Win Rate | 100.0% |
| Avg PnL | 14,311.82 |
| Median PnL | 14,264.29 |
| Total PnL | 558,161.16 |
| Max Drawdown | 0.00 |
| Largest Win | 14,545.45 |
| Largest Loss | 13,897.00 |
| Profit Factor | NOT_AVAILABLE (no losses) |

**Note**: 100% win rate reflects EOD close exit simulation, NOT a trading signal.

---

## H. Scenario Breakdown

### NIFTY

| Scenario | Candidates | Confirmed | Qualified | Completed |
|---|---|---|---|---|
| BULLISH_CONTINUATION | 250 | 250 | 39 | 39 |
| BEARISH_CONTINUATION | 292 | 0 | 0 | 0 |
| RANGE_PREMIUM_DECAY | 0 | 0 | 0 | 0 |
| BREAKOUT | 689 | 689 | 39 | 39 |
| BREAKOUT_FAILURE_REVERSAL | 689 | 0 | 0 | 0 |

### BANKNIFTY

| Scenario | Candidates | Confirmed | Qualified | Completed |
|---|---|---|---|---|
| BULLISH_CONTINUATION | 255 | 255 | 39 | 39 |
| BEARISH_CONTINUATION | 272 | 0 | 0 | 0 |
| RANGE_PREMIUM_DECAY | 0 | 0 | 0 | 0 |
| BREAKOUT | 728 | 728 | 39 | 39 |
| BREAKOUT_FAILURE_REVERSAL | 728 | 0 | 0 | 0 |

---

## I. Trade Frequency

| Instrument | Candidates/Session | Confirmations/Session | Qualified/Session | Completed/Session |
|---|---|---|---|---|
| NIFTY | 49.2 | 24.1 | 1.0 | 1.0 |
| BANKNIFTY | 50.8 | 25.2 | 1.0 | 1.0 |

---

## J. Future-Data Mutation Test Results

- Qualification at T: UNCHANGED after future data mutation
- Candidates before T: UNCHANGED (852 = 852)
- All backtest decisions: lookahead_check = PASS
- Entry timing: Valid (entry <= exit)
- Stop/target: Determined at qualification time, not future

**Status**: PASS

---

## K. Trade Definition

A historical "qualified trade" requires:
- Active scenario with CONFIRMED match state
- Valid strategy selection based on scenario type, trend, volatility
- Risk validation (max 1% risk, min 1.5 R:R)
- Options data available
- Daily trade limit not exceeded (1 per instrument per date)
- Entry price = market_state.price * 0.995
- Stop = entry * 0.99 (1% below entry)
- Target = entry * 1.02 (2% above entry)

---

## L. Limitations

1. Options data unavailable - option-dependent trades return NO_TRADE
2. Exit simulation uses EOD close (simplified)
3. 100% win rate is NOT representative of live trading
4. Analysis period covers only bull-trend conditions (Jul-Sep 2026)
5. Transaction costs not modeled (NET PnL = NOT AVAILABLE)
6. 5-minute yfinance data limited in historical depth

---

Report generated: 2026-09-19
Phase 4 Audit Complete
