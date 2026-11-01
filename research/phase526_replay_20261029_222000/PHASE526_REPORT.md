# Phase 5.26 — Live-Style HLC Backtest vs Existing Paper Trades and Signals

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Report directory: `/opt/tradingai/research/phase526_replay_20261029_222000/`

## Database Analysis

- paper_trades: 94 rows (30 SCALP_HLC + 64 CPR)
- scalp_signals: 29 rows (18 TRADED + 10 EXPIRED + 1 IGNORED)
- HLC-specific: 30 paper trades, 29 signals

## Historical Replay

- 729 trades (382 NIFTY + 347 BANKNIFTY) over 81 sessions
- 72.43% win rate, 19,210.95 points, PF 3.47
- No-lookahead: 14/14 tests PASS

## Reconciliation

- 30 SCALP_HLC paper trades exist (Sep 25 - Oct 28)
- Replay generates 729 trades (Jul 6 - Oct 29)
- Only overlapping period can be compared
- Live paper trades use entry guard (5-min window) which filters some signals

## Final Classification

**PARTIAL — REPLAY WORKS BUT COVERAGE AND MATCHING LIMITATIONS EXIST**

Reasons:
1. Only 3.5 months of data
2. Live paper trades use entry guard filtering (not in replay)
3. 245-row CSV discrepancy unresolved
4. No option-level data
5. No production changes made
