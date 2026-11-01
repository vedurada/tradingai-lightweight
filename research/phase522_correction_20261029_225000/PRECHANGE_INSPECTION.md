# Phase 5.22 — Pre-Change Inspection

## Current _hlc_only_mode() Implementation (Before Fix)

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
    return True  # <-- BUG: should be False (CPR)
```

## Authoritative Service Definition

- File: /etc/systemd/system/tradingai-api.service
- Runs: gunicorn -w 2 --threads 4 ... app.api.app:app
- Environment: API_PORT=8000 (no HLC_ONLY_MODE)
- Status: active (running), PIDs 802784, 824977, 829484

## Call Sites

- _hlc_only_mode() called only in LiveEngine.evaluate()
- No other callers
- paper_scalp_live.py uses HLC directly (not via LiveEngine)
- tg_alerts.py does not use the flag

## Current Source Hash

b06dac4f01a0a1e111556f47df0ec2e5034c0d6e04406f2131279a0309167542 (pre-Phase 5.20)
4e4424fc040cb56dbbd327ae06dde13a816bfe48f2ea9ff1624721ff36420417 (post-Phase 5.20, pre-Phase 5.22)
