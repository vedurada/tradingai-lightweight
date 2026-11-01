# Phase 5.41 Stage 2 — HLC_ONLY_MODE Discrepancy Audit

## Finding
- Source comment (app/live/engine.py ~line 73-76): "Default preserves current production behavior (HLC). Set HLC_ONLY_MODE=false ... to roll back to CPR. Missing/invalid config fails safe to current behavior (HLC)."
- Source implementation fallback (app/live/engine.py ~line 95-100): "# Default: fail safe to CPR (approved design)"; `return False`.
- Phase 5.22 record: "Missing or invalid HLC_ONLY_MODE defaults to CPR. Explicit HLC_ONLY_MODE=true enables HLC."
- Phase 5.41 inventory: "HLC_ONLY_MODE default = HLC."

## Resolution
- Actual source behaviour with HLC_ONLY_MODE unset in env and absent from config/settings.json: returns False → CPR.
- Explicit HLC_ONLY_MODE=true → True → HLC.
- Explicit false → False → CPR.
- Empty/invalid → falls through to config (absent) → returns False → CPR.
- Production runtime: systemd unit `/etc/systemd/system/tradingai-api.service` line 12: `Environment=HLC_ONLY_MODE=true` → effective runtime = HLC.

## Root Cause
- Stale comment in source contradicts implemented fallback.
- Phase 5.41 inventory relied on comment rather than code.
- Behaviour (missing/invalid → CPR) is consistent with Phase 5.22 records and code.

## Discrepancy Summary
- Documented discrepancy: comment vs implementation fallback.
- Resolved: actual source behaviour for missing/invalid = CPR; effective production = HLC (systemd true).
