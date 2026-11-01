# Phase 5.8 — Feature Flag Design

## Flag Specification

| Property | Value |
|----------|-------|
| Name | `HLC_ONLY_MODE` |
| Default | `false` (CPR-driven behavior) |
| Type | Boolean string ("true"/"false") |
| Source of truth | Environment variable `HLC_ONLY_MODE` (primary) or `config/settings.json` key `hlc_only_mode` (fallback) |
| Missing → | `false` |
| Invalid → | `false` |
| Unreadable → | `false` |

## Fail-Safe Behavior

```python
def _hlc_only_mode():
    # 1. Try environment variable
    val = os.environ.get('HLC_ONLY_MODE', '').strip().lower()
    if val in ('true', '1', 'yes'):
        return True
    if val in ('false', '0', 'no', ''):
        return False
    # 2. Try config file
    try:
        with open('config/settings.json') as f:
            cfg = json.load(f)
        val = str(cfg.get('hlc_only_mode', '')).strip().lower()
        if val in ('true', '1', 'yes'):
            return True
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    # 3. Default to false
    return False
```

## Mode Behavior

### Mode A: HLC_ONLY_MODE = false (Current Default)

| Aspect | Behavior |
|--------|----------|
| Signal detection | CPR trigger engine (`_cpr_book_signal`) |
| HLC engine | Retained as overlay (display only) |
| New trade initiation | CPR path only |
| Existing trades | Managed via monitor() (scalp + CPR branches) |

### Mode B: HLC_ONLY_MODE = true (Future Deployment)

| Aspect | Behavior |
|--------|----------|
| Signal detection | HLC 3-bar scalp engine (`_hlc_book_signal`) |
| CPR engine | Retained for rollback (not used for new decisions) |
| New trade initiation | HLC path only |
| Existing trades | Managed via monitor() (scalp + CPR branches) |

## Exactly One Path Initiates New Trades

### Mode A
```
app/live/engine.py: decision() → _cpr_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

### Mode B
```
app/live/engine.py: decision() → _hlc_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

No other path initiates new trades. `tg_alerts.py` only alerts for existing trades.

## Existing Open Trades Remain Manageable

- All open trades remain in `paper_trades` table
- `monitor()` handles both scalp and CPR branches based on `scenario` field
- Exit logic determined by `scenario`, not by feature flag
- No trade is abandoned or orphaned during mode switch

## Historical Trade Records Preserved

- No migration or deletion of trade records
- `paper_trades` table retains all historical trades
- Feature flag only affects NEW trade decisions
- Historical analysis remains available

## Code Paths Requiring Changes (Future Deployment)

| File | Function | Change |
|------|----------|--------|
| app/live/engine.py | decision() | Read flag, call appropriate signal function |
| app/live/engine.py | __init__() | Conditionally initialize CPR or HLC components |
| app/api/app.py | decision endpoint | Display HLC as primary when flag=true |
| scripts/paper_scalp_live.py | run_once() | Add daily trade limit check |

## Dashboard/API and Alerting Consistency

- All modes use same `paper_trades` table
- API endpoints read from same DB regardless of mode
- Telegram alerts tied to persisted trades (DB check before alert)
- No mode-specific output changes needed
