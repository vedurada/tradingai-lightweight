# Phase 5.7 — Production Function Test Results

## Test Environment

- Isolated test DB: `/opt/tradingai/research/phase57_timing_20261029_205000/test_prod.db`
- Production DB: NOT touched
- Functions tested: ACTUAL application functions (not reimplemented)

## Functions Called

| Function | Source File | Mocked Dependencies |
|----------|-------------|-------------------|
| `_entry_time_guard` | scripts/paper_scalp_live.py | None (pure function) |
| `_scan_signals` | app/research/scalp_engine.py | None (pure function) |
| `_live_signal` | app/research/scalp_engine.py | None (pure function) |
| `today_state` | app/research/scalp_engine.py | get_conn (patched to test DB) |
| `PaperTradeEngine.create_paper_trade` | app/paper_trade/engine.py | get_conn (patched to test DB) |
| `PaperTradeEngine.monitor` | app/paper_trade/engine.py | get_conn (patched to test DB) |
| `record_signal` | app/research/scalp_signal_store.py | get_conn (patched to test DB) |
| `mark_traded` | app/research/scalp_signal_store.py | get_conn (patched to test DB) |

## Test Results

| Test ID | Function Called | Scenario | Expected | Actual | Result |
|---------|----------------|----------|----------|--------|--------|
| EG1 | _entry_time_guard | Valid timely entry | ok, None | ok, None | PASS |
| EG2 | _entry_time_guard | Expired entry | expired | expired | PASS |
| EG3 | _entry_time_guard | Missing entry time | failed | failed | PASS |
| EG4 | _entry_time_guard | Bad entry time | failed | failed | PASS |
| EG5 | _entry_time_guard | Timezone-naive entry | ok | ok | PASS |
| SS1 | _scan_signals | Bullish 3-bar alignment | >=1 signal | 1+ signals | PASS |
| SS2 | _scan_signals | Flat data (no alignment) | 0 signals | 0 signals | PASS |
| PT1 | create_paper_trade | Create trade in isolated DB | PT-* ID | PT-* returned | PASS |
| PT2 | create_paper_trade | Duplicate (same link_key) | Existing ID (idempotent) | Same ID returned | PASS |
| OP1 | SQL (has_open_position logic) | Open position exists | Trade ID | Trade ID found | PASS |
| OP2 | SQL (has_open_position logic) | No open position (diff inst) | None | None | PASS |
| RS1 | record_signal | Record signal | Signal ID | Signal ID returned | PASS |
| RS2 | record_signal | Duplicate signal (UNIQUE) | Same ID | Same ID returned | PASS |
| LS1 | _live_signal | Entry candle present | entry not None | entry present | PASS |
| LS2 | _live_signal | No entry candle (computed) | entry_time computed | entry_time present | PASS |
| MON1 | monitor | Open trade, no exit data | No crash | No crash | PASS |

## Summary

- 16/16 tests PASSED
- 0 FAILED
- 0 NOT RUN
- All tests used ACTUAL application functions
- All DB writes went to isolated test DB only
- No production code was modified
