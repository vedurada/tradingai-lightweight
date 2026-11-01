# Changes and Backups

## Backup Location
`/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913/`

## Backup Contents
| File | SHA256 (pre-change) |
|---|---|
| app/api/app.py | 51b08639ebe64c075db41822d6a17d4d19b0ea28d2dd3e7a88aae9719f05d234 |
| app/live/engine.py | 119685d33fb0bc28483ae90250e0d8d78529dd49576ee933eb4ce6ccb9b98bf7 |
| app/research/scalp_engine.py | 127c09d6dfcf4ac930d116d311d56b21005fff84acf40eab8aca01ba7aaf7e23 |
| app/strategies/scalp.py | 7711ad0683ebca88080e1ebbb5efcc3e8e61ba8a994f47282eb380de12f50c82 |
| app/paper_trade/engine.py | da8109c6f764865617c72fc30d87ca6d8d909bc83ba57af060d047d72017c0f7 |
| scripts/paper_scalp_live.py | e3c61da1534b8ebc92fc7caf703d8273e2edeb239f91b35148429784becc97d6 |
| app/market/collector.py | 4ad20bf7f6d690243faeacc2c0032ce98c28b02c82cfb9f9e65e0799548954bf |
| config/settings.json | 8aff897ec2973b6d936c789ba7f10d26f8c6078924dcee2ba245b51e6ac9c543 |
| frontend/scalp.html | 5a3c75646987fda645014746012141704f8bc966f9a9a1995de695929670dce4 |
| frontend/backtest.html | 9a108f447fecb7a0721a82cd6d302c12c09f47282eb380de12f50c82 |
| tradingai.db (SQLite backup) | n/a |

## Pre-Change Verification
- SQLite integrity check: `ok`
- Tables verified: market_candles_5m, paper_trades, scalp_signals, paper_trade_events, trade_journal, daily_trade_locks, qualified_trades
- Row counts: market_candles_5m=17074, paper_trades=94, scalp_signals=36, paper_trade_events=33, trade_journal=246, daily_trade_locks=21, qualified_trades=20
- Latest candles: NIFTY/BANKNIFTY/INDIA_VIX all at 2026-10-30T13:00:00+05:30
- HLC_ONLY_MODE: unset (defaults to CPR mode per `app/live/engine.py:_hlc_only_mode()`)

## Changes Applied to Production

### 1. `/opt/tradingai/scripts/paper_scalp_live.py`
**Change A**: Removed `is_stale()` check at line 287
```python
# REMOVED:
if is_stale(st.get("entry_time") or signal_ts):
    continue
```
Reason: `_entry_time_guard()` already handles signal expiration with the correct
5-minute entry window. The 20-minute `is_stale()` threshold was prematurely
skipping valid signals.

**Change B**: Fixed yfinance symbol mapping in `_get_entry_price_from_provider()`
```python
# BEFORE:
candles_data = provider.get_5m_candles(inst)
# AFTER:
yf_symbol = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(inst, inst)
candles_data = provider.get_5m_candles(yf_symbol)
```
Reason: yfinance rejects "NIFTY"/"BANKNIFTY" with HTTP 404. Correct symbols:
^NSEI / ^NSEBANK. Verified: ^NSEI returns state=LIVE, 100 candles.

### 2. `/opt/tradingai/app/research/scalp_engine.py`
**Change**: Added bounds check in `_trade_for()`
```python
# BEFORE:
def _trade_for(candles, idx, direction):
    c = candles[idx]
    nc = candles[idx + 1]
# AFTER:
def _trade_for(candles, idx, direction):
    c = candles[idx]
    if idx + 1 >= len(candles):
        return None
    nc = candles[idx + 1]
```
Reason: `_scan_signals()` can return a signal at the last candle (live signal
detection). `_trade_for()` accessed `candles[idx + 1]` without bounds check,
causing IndexError in `run_opens_range()`.

### 3. `/opt/tradingai/app/strategies/scalp.py`
**Change**: Fixed `first_trigger` import source
```python
# BEFORE:
from app.research.scalp_engine import first_trigger, today_state, run_opens_range
# AFTER:
from app.research.cpr_trigger_engine import first_trigger
from app.research.scalp_engine import today_state, run_opens_range
```
Reason: `first_trigger` is defined in `cpr_trigger_engine.py:337`, not in
`scalp_engine.py`. The broken import would cause ImportError when the module
is loaded.

## Post-Change Checksums
| File | SHA256 (post-change) |
|---|---|
| scripts/paper_scalp_live.py | fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51 |
| app/research/scalp_engine.py | de07d65a77e1e1c092fa18a45a2f486eba0bbb43f3ee7ae1b528212acb2f6590 |
| app/strategies/scalp.py | dba6ae960038ed2a8a96972657d9197be233ff9e9b357eb7daeddf83126b1b42 |

## Database
- SQLite backup: `/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913/tradingai.db`
- No schema changes
- No data modifications
- All historical records preserved

## Service Restart
`tradingai-paper-scalp-live.service` restarted at 2026-10-30 13:26:15 IST to
pick up code changes. Previously running instance (PID 806158) holding stale
flock was killed. Service now running stably (PID 944550), single instance.
