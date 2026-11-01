# Phase 5.20 — Feature Flag Implementation

## File Modified

`app/live/engine.py` (only file changed)

## Changes

1. Added `import os` to imports
2. Added `_hlc_only_mode()` function after `LIVE_VARIANT`
3. Modified `evaluate()` to select between `_hlc_book_signal` and `_cpr_book_signal` based on flag

## Function: `_hlc_only_mode()`

```python
def _hlc_only_mode():
    val = os.environ.get('HLC_ONLY_MODE', '').strip().lower()
    if val in ('true', '1', 'yes'):
        return True
    if val in ('false', '0', 'no'):
        return False
    try:
        import json as _json
        _base = os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
        with open(os.path.join(_base, 'config', 'settings.json')) as _f:
            _cfg = _json.load(_f)
        val = str(_cfg.get('HLC_ONLY_MODE', '')).strip().lower()
        if val in ('true', '1', 'yes'):
            return True
        if val in ('false', '0', 'no'):
            return False
    except Exception:
        pass
    # Default: preserve current production behavior (HLC)
    return True
```

## Default Behavior

- No config/env → True (HLC, current behavior preserved)
- HLC_ONLY_MODE=false → CPR (rollback)
- HLC_ONLY_MODE=true → HLC (explicit)
- Invalid/missing → True (HLC, fail safe)

## Production State

- HLC_ONLY_MODE not set → defaults to True (HLC, current behavior)
- No production behavior change
- CPR retained for rollback
