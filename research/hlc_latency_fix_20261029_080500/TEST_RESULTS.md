# TradingAI Phase 3.5 — TEST_RESULTS.md

**Audit directory:** /opt/tradingai/research/hlc_latency_fix_20261029_080500/
**Test date:** 2026-10-29  
**Host:** webserver (Oracle VM)

## Test Environment

- Python 3.x on Ubuntu (Oracle VM)
- Application root: /opt/tradingai
- Database: /opt/tradingai/database/tradingai.db (read-only for tests)

## Syntax Checks

| File | Command | Result |
|------|---------|--------|
| `app/research/scalp_engine.py` | `python3 -m py_compile` | PASS |
| `scripts/paper_scalp_live.py` | `python3 -m py_compile` | PASS |

## Import Checks

| Module | Command | Result |
|--------|---------|--------|
| `app.research.scalp_engine` | `import _scan_signals, _live_signal, today_state, today_signals` | PASS |
| `scripts.paper_scalp_live` | `import _entry_time_guard, _get_entry_price_from_provider, run_once, scalp_trade_id, scalp_link` | PASS |

## Functional Tests

### Test 1: `_scan_signals()` with 7 candles (entry candle in data)

**Setup:** 7 candles with HLC uptrend pattern at the end.

**Expected:** 1 signal at index 5 (6th candle), entry candle at index 6 (7th candle).

**Result:** PASS — 1 signal found at index 5, candle ts=2026-10-28T09:25:00+05:30

### Test 2: `_scan_signals()` with 5 candles (entry candle NOT in data)

**Setup:** 5 candles with HLC uptrend pattern at the end (last 3 candles form pattern).

**Expected:** 1 signal at index 4 (last candle), entry=None (entry candle not in data).

**Result:** PASS — 1 signal found at index 4, candle ts=2026-10-28T09:20:00+05:30
- `_live_signal()` returned: entry=None, entry_time=2026-10-28T09:25:00+05:30, stop=22034.0

### Test 3: `_entry_time_guard()` boundary conditions

| entry_time | now | Expected | Result |
|------------|-----|----------|--------|
| 14:50:00 | 14:49:59 | ok | PASS |
| 14:50:00 | 14:50:00 | ok | PASS |
| 14:50:00 | 14:52:30 | ok | PASS |
| 14:50:00 | 14:55:00 | ok | PASS (boundary) |
| 14:50:00 | 14:55:01 | expired | PASS |
| 14:50:00 | 15:00:00 | expired | PASS |

## Import Error Tests

No import errors when loading `app.research.scalp_engine` or `scripts.paper_scalp_live` with `sys.path.insert(0, '/opt/tradingai')`.

## Live Process Restart Test

| Check | Result |
|-------|--------|
| Old process (PID 752009) terminated | PASS |
| New process (PID 778264) running | PASS |
| New process running updated code | PASS (files scp'd before restart) |
| Process acquires file lock successfully | PASS |
| Process enters main loop | PASS (no crash on startup) |

## Known Limitations

- Full end-to-end latency measurement requires waiting for a live market session to produce a qualifying HLC signal. This cannot be forced without creating artificial market data.
- The paper_scalp_live.py process was restarted during market hours; no signal had fired at the time of this test, so end-to-end latency could not be measured.
- Telegram alert delivery timing cannot be tested without a live signal.
