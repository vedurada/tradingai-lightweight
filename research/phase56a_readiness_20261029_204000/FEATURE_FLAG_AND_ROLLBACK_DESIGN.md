# Phase 5.6A — Feature Flag and Rollback Design

## Feature Flag: `HLC_ONLY_MODE`

### Specification

| Property | Value |
|----------|-------|
| Flag name | `HLC_ONLY_MODE` |
| Default | `false` (CPR-driven decision behavior) |
| Type | Boolean |
| Location | Environment variable or `config/settings.json` |
| Missing → | Default (`false`) |
| Invalid → | Default (`false`) |
| Unreadable → | Default (`false`) |

### Fail-Safe Behavior

- If the flag is missing, invalid, or unreadable, the system MUST default to `false` (CPR-driven).
- No error should be raised; the system should log a warning and continue with CPR behavior.
- The flag must be read at startup and on each decision cycle (not cached indefinitely).

## Mode Behavior

### Mode A: `HLC_ONLY_MODE = false` (Current Default)

| Aspect | Behavior |
|--------|----------|
| Signal detection | CPR trigger engine (`_cpr_book_signal`) |
| HLC engine | Not used for decisions (retained as overlay) |
| New trade initiation | CPR path only |
| Existing trades | Managed via monitor() (scalp + CPR branches) |

### Mode B: `HLC_ONLY_MODE = true` (Future Deployment)

| Aspect | Behavior |
|--------|----------|
| Signal detection | HLC 3-bar scalp engine (`_hlc_book_signal`) |
| CPR engine | Not used for new decisions (retained for rollback) |
| New trade initiation | HLC path only |
| Existing trades | Managed via monitor() (scalp + CPR branches) |

## Exactly One Path May Initiate a New Trade

### In Mode A (false)

```
live/engine.py: decision() → _cpr_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

### In Mode B (true)

```
live/engine.py: decision() → _hlc_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

No other path may initiate new trades. `tg_alerts.py` only alerts for existing trades.

## Existing Open Trades Remain Manageable

When the mode changes:
- All existing open trades (from either strategy) remain in `paper_trades`
- `monitor()` handles both scalp and CPR branches:
  - Scalp: 1.5% stop / 3% target (from `scalp_engine.py`)
  - CPR: 0.5% stop / 2% target (from `paper_trade/engine.py`)
- Exit logic is determined by `scenario` field, not by the feature flag
- No trade is abandoned or orphaned

## HLC Entry Freshness and Price Validation

In both modes, when HLC signals are used:
- Signal uses 3 completed candles (no lookahead)
- Entry price from live provider at decision time
- Stale data rejected (>20 min)
- Entry-time guard rejects expired signals

## Duplicate Trade Prevention

- Deterministic `trade_id` (SHA-1 of link_key) ensures idempotency
- `trade_id` is PRIMARY KEY in `paper_trades`
- `scalp_signals` has UNIQUE constraint on `(instrument_id, source_candle_ts, direction)`
- `tg_alerts.py` checks DB before alerting (dedup via `fired` key)

## API/Dashboard and Telegram Output

- All modes use the same `paper_trades` table
- API endpoints (`/api/paper/scalp`, `/api/decision`, `/api/strategy/scalp`) read from same DB
- Telegram alerts tied to persisted trades (DB check before alert)
- No mode-specific output changes needed

## Rollback Procedure

### From Mode B to Mode A

1. Set `HLC_ONLY_MODE=false` (or remove from environment)
2. Restart gunicorn: `systemctl restart tradingai-gunicorn` (or manual restart)
3. CPR engine resumes as default decision path
4. Existing HLC trades remain manageable (monitor() handles both branches)
5. No trade history deleted
6. No open trades abandoned

### Verification After Rollback

1. API responds: `curl http://127.0.0.1:8000/api/decision`
2. Check decision source: should show CPR, not HLC
3. Open trades still monitored: `curl http://127.0.0.1:8000/api/paper/scalp`
4. Telegram alerts continue (cron unchanged)

## Code Paths Requiring Changes (Future Deployment)

| File | Change | Mode |
|------|--------|------|
| `app/live/engine.py` | Read `HLC_ONLY_MODE` flag; call `_hlc_book_signal()` or `_cpr_book_signal()` | Both |
| `app/api/app.py` | Display HLC as primary (not overlay) when flag=true | Mode B |
| `scripts/paper_scalp_live.py` | Add daily trade limit check | Mode B |
| `config/settings.json` | Add `HLC_ONLY_MODE`, `MAX_TRADES_PER_INSTRUMENT_PER_DAY` | Both |

## Configuration to NOT Change

- `app/research/cpr_trigger_engine.py` — retain for rollback
- `app/research/cpr_strategy_engine.py` — retain for rollback
- `app/core/qualification.py` — retain for rollback
- `app/strategies/engine.py` — retain for rollback
- `app/scenarios/engine.py` — retain for rollback
- All CPR cron jobs — retain for rollback
- All CPR API endpoints — retain for rollback
