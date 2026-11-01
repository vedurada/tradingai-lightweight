# Phase 5.21 — HLC Feature-Flag Default and Production-Path Audit

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only, unchanged)
- Phase 5.20: `/opt/tradingai/research/phase520_feature_flag_20261029_223000/`
- Report directory: `/opt/tradingai/research/phase521_flag_audit_20261029_224000/`

## Step 1 — Phase 5.20 Evidence Review

See `PHASE520_EVIDENCE_REVIEW.md`.

Phase 5.20 report claimed PASS with 10/10 tests passing. However, the report's test expectations assumed the default was HLC (current behavior), not CPR (approved design). The Phase 5.20 tests did not test against the approved fail-safe design.

## Step 2 — Source Code Inspection

See `FLAG_BEHAVIOR_MATRIX.csv`.

### `_hlc_only_mode()` Implementation

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

### Behavior Matrix

| Input | Actual | Approved Design | Match |
|-------|--------|----------------|-------|
| Missing (no env, no config) | True (HLC) | False (CPR) | **MISMATCH** |
| false | False (CPR) | False (CPR) | Match |
| true | True (HLC) | True (HLC) | Match |
| empty ('') | True (HLC) | False (CPR) | **MISMATCH** |
| invalid ('garbage') | True (HLC) | False (CPR) | **MISMATCH** |
| 0 | False (CPR) | False (CPR) | Match |
| no | False (CPR) | False (CPR) | Match |

### Key Finding

The implementation defaults to HLC (True) when configuration is missing, empty, or invalid. The approved fail-safe design requires defaulting to CPR (False). This is a **design mismatch** — 3 of 5 primary cases fail the approved policy.

## Step 3 — Production Path Verification

### Running Process

- Gunicorn PIDs: 802784, 824977, 829484 (started before Phase 5.20)
- These processes loaded the OLD code (HLC unconditionally, no flag)
- Source file on disk has the NEW code (with flag)
- **The running process has NOT loaded the Phase 5.20 change**

### Production Environment

- `HLC_ONLY_MODE` not in environment variables
- `HLC_ONLY_MODE` not in config/settings.json
- Gunicorn env does not contain HLC_ONLY_MODE

### Production Behavior

- Running process: HLC unconditionally (old code, no flag)
- Source on disk: HLC by default (new code, flag defaults to True)
- **Production behavior is unchanged (HLC in both cases)**

### Service/Job Bypass

- No service or scheduled job bypasses the flag (flag is in evaluate() only)
- paper_scalp_live.py does not use the flag (uses HLC directly)
- tg_alerts.py does not use the flag

## Step 4 — Fail-Safe Requirement Verification

### Approved Policy vs Implementation

| Requirement | Approved | Implemented | Match |
|-------------|----------|-------------|-------|
| Missing flag → CPR | CPR | HLC | **MISMATCH** |
| false → CPR | CPR | CPR | Match |
| true → HLC | HLC | HLC | Match |
| Empty → CPR | CPR | HLC | **MISMATCH** |
| Invalid → CPR | CPR | HLC | **MISMATCH** |
| CPR available as rollback | Yes | Yes | Match |
| No auto-switch to HLC on missing config | Required | Violated | **MISMATCH** |

### Mismatches

1. **Missing/empty/invalid config defaults to HLC instead of CPR** — violates fail-safe requirement
2. **Default is HLC (True) instead of CPR (False)** — approved policy requires CPR default
3. **The implementation "preserves current behavior" instead of "fails safe to CPR"** — these are different goals

## Step 5 — Regression and Isolation Checks

- Flag behavior tests: 7/10 match approved design (3 mismatches)
- CPR selection functional: YES (_cpr_book_signal unchanged)
- HLC selection under explicit opt-in: YES (flag=true → HLC)
- Expiry guards in selection path: YES (unchanged)
- Duplicate prevention intact: YES (unchanged)
- No broker execution path: YES (code inspection)
- Production DB unchanged: YES (94, 29, 217, 16936 rows)
- Service state unchanged: YES (no restarts)

## Step 6 — Report

See all deliverables in `/opt/tradingai/research/phase521_flag_audit_20261029_224000/`.

## Final Classification

**PARTIAL — NO UNSAFE CHANGES WERE MADE, BUT A CRITICAL PROPERTY REMAINS MISMATCHED**

Reasons:
1. **Design mismatch:** Default is HLC (True) instead of CPR (False) — violates approved fail-safe policy
2. **3 of 5 primary flag cases fail** the approved design (missing, empty, invalid)
3. **Running process has not loaded** the Phase 5.20 change (started before implementation)
4. **Production behavior is unchanged** (HLC in both old and new code) — no safety violation
5. No unsafe changes were made, but the implementation does not match the approved fail-safe design
