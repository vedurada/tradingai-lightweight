# Phase 5.21 — Recommended Next Action

## Critical Finding

The Phase 5.20 implementation's default (HLC/True) does not match the approved fail-safe design (CPR/False). The implementation "preserves current behavior" instead of "fails safe to CPR."

## Recommended Action

1. **Fix the default** in `_hlc_only_mode()`: change the final `return True` to `return False` (CPR default)
2. **Update Phase 5.20 report** to reflect the corrected default
3. **Re-run tests** against the approved design
4. **Verify** that production behavior remains unchanged (CPR default = current HLC behavior? No — CPR default would change from HLC to CPR)

Wait, there's a catch: if we change the default to False (CPR), production would switch from HLC to CPR. This changes production behavior.

## Resolution

The fundamental conflict is:
- Approved design: default False (CPR) — but production currently uses HLC
- Current implementation: default True (HLC) — preserves production behavior but violates fail-safe design

The resolution depends on whether the intent is:
A) Restore CPR as default (change production to CPR) — requires user approval
B) Keep HLC as default (update design to match implementation) — requires design change
C) Make the default configurable (production keeps current behavior via explicit config)

**Recommendation:** Option C — add HLC_ONLY_MODE=true to production config/settings.json (making the HLC default explicit), while the code default remains False (CPR). This way:
- Missing config → CPR (fail-safe)
- Production config → HLC (explicit, documented)
- Rollback → remove config or set to false

This satisfies both the fail-safe design and production behavior preservation.
