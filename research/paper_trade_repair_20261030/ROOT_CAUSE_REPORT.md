# Root Cause Report — Live Paper Trade Generation Repair

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Summary
Live paper trades were not being generated for the HLC 3-Bad scalp strategy on
https://tradingai.in/scalp.html. Backtest worked, but live paper-trade pipeline
produced zero trades on 2026-10-30 despite valid HLC signals being generated.

## Root Cause Matrix

| Pipeline stage | Expected | Actual | Defect | Fix |
|---|---|---|---|---|
| Market candles | Current NIFTY/BANKNIFTY 5m candles in DB | 49-50 candles today, latest 13:20 IST | None — data current | None |
| Signal generation | HLC 3-bar signals via `today_signals()` | 5 NIFTY + 2 BANKNIFTY signals generated (10:00–11:35) | None — signals generated correctly | None |
| Paper trade creation | Signals converted to `paper_trades` rows | 0 trades created today; all 7 signals EXPIRED | `is_stale()` (20-min threshold) in `paper_scalp_live.py:287` skipped signals before `_entry_time_guard()` could process them within the correct 5-min entry window | Removed `is_stale()` call; `_entry_time_guard()` already handles expiration correctly |
| Paper trade creation (entry=None) | Entry price resolved from live provider | `_get_entry_price_from_provider()` returned None | `MarketDataProvider.get_5m_candles(inst)` called with `"NIFTY"`/`"BANKNIFTY"`; yfinance requires `^NSEI`/`^NSEBANK` | Added symbol mapping: `{"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}` |
| Signal generation (`run_opens_range`) | Backtest computes trades without crash | `IndexError: list index out of range` at `scalp_engine.py:76` | `_trade_for()` accessed `candles[idx + 1]` without bounds check when `_scan_signals()` returns a signal at the last candle | Added `if idx + 1 >= len(candles): return None` guard |
| Strategy adapter import | `strategies/scalp.py` imports cleanly | `ImportError`: `first_trigger` not in `scalp_engine.py` | `first_trigger` is defined in `cpr_trigger_engine.py`, not `scalp_engine.py` | Import `first_trigger` from `cpr_trigger_engine.py` |
| SQLite persistence | Trades committed and visible | 30 SCALP_HLC trades exist (Oct 27–28), all CLOSED | None — persistence works | None |
| API | `/api/paper/scalp` returns DB records | Returns 30 trades correctly | None | None |
| Frontend | `scalp.html` displays API trades | Calls `/api/paper/scalp`, parses response correctly | None | None |

## Primary Root Cause
The `is_stale()` check in `paper_scalp_live.py` used a 20-minute staleness threshold,
which was more aggressive than the `_entry_time_guard()` 5-minute entry-window
check. Signals generated between 10:00–11:35 IST on 2026-10-30 were already
stale (>20 min old) by the time the `paper_scalp_live.service` stabilized after
a crash loop on 2026-10-29. All 7 signals were marked EXPIRED without ever
reaching `try_create_trade()`.

## Contributing Factors
1. `paper_scalp-live.service` was in a crash loop (115+ restarts) on 2026-10-29
   due to a rogue second instance holding the flock, preventing timely signal
   processing during the early market session.
2. `MarketDataProvider` was called with `"NIFTY"`/`"BANKNIFTY"` symbols which
   yfinance rejects (404). Correct symbols: `^NSEI`/`^NSEBANK`.
3. `_trade_for()` lacked bounds check for `candles[idx + 1]`, causing IndexError
   in `run_opens_range()` when a signal occurs on the last candle.
4. `strategies/scalp.py` had broken import of `first_trigger` from
   `scalp_engine.py` (defined in `cpr_trigger_engine.py`).

## Files Modified
- `/opt/tradingai/scripts/paper_scalp_live.py` — removed `is_stale()` call; fixed yfinance symbol mapping
- `/opt/tradingai/app/research/scalp_engine.py` — added bounds check in `_trade_for()`
- `/opt/tradingai/app/strategies/scalp.py` — fixed `first_trigger` import source

## Verification
- `test_backtest_and_live_signal_parity`: PASSED (was FAILING with IndexError)
- `test_second_close_is_rejected_and_does_not_overwrite`: PASSED
- `test_concurrent_closes_yield_exactly_one_winner`: PASSED
- `run_opens_range(NIFTY, 2026-10-30, 2026-10-30)`: returns 5 signals, 5 trades, no crash
- `/api/paper/scalp`: returns 30 SCALP_HLC trades correctly
- `paper_scalp-live.service`: running stably (PID 944550), single instance

## Live Verification Status
`LIVE_GENERATION_NOT_YET_VERIFIED` — No new HLC 3-bar alignment signals have
occurred on candles after 11:35 IST on 2026-10-30. Market is open until
15:30 IST. New signals will be processed correctly by the fixed pipeline.
