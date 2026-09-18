# Phase 42A.5D — Frontend Rendering Failure Diagnosis Report

## Date
2026-09-18 (Market hours: 09:30–15:30 IST)

## Summary

4 public index pages (NIFTY, BANKNIFTY, SENSEX, FINNIFTY) and the homepage were stuck in perpetual **Loading** state. All backend APIs returned HTTP 200 with valid data. The root cause was a frontend data-model mismatch: inline JavaScript passed a dictionary object to rendering functions that expected a string, causing a TypeError that was silently caught, halting all DOM updates.

## Affected Pages (4 pages + homepage)

1. `/indices/nifty.html` (28,200 bytes) — 11+ Loading elements
2. `/indices/banknifty.html` (26,025 bytes) — 11+ Loading elements
3. `/indices/sensex.html` (19,518 bytes) — 11+ Loading elements
4. `/indices/finnifty.html` (22,158 bytes) — 11+ Loading elements
5. `/index.html` (36,518 bytes) — Trend display shows "N/A" (milder)

## Root Cause

**TypeError in `regimeText()` function**

The `/api/market` endpoint returns `instruments.{SYMBOL}.regime` as a structured dictionary:

```json
{
  "regime": "BEARISH",
  "trend": "BEARISH",
  "momentum": "BEARISH",
  "breadth": "NEUTRAL",
  "confidence": 70.0,
  "vix_regime": "LOW",
  "volatility": "LOW"
}
```

The frontend inline script at line 208/209 of each index page passes this dict directly to `regimeText()`:

```javascript
regimeText(inst.regime)  // inst.regime is a dict, not a string
```

The `regimeText()` function (line 188) calls `r.toUpperCase()` on the dict, which throws:

```
TypeError: r.toUpperCase is not a function
```

The error is caught by the empty `catch(e){}` block, halting all subsequent DOM updates in the function.

## Fix Location

| File | Line | Change |
|------|------|--------|
| indices/banknifty.html | 208 | `regimeText(inst.regime)` → `regimeText(inst.regime?.regime||'')` |
| indices/nifty.html | 209 | `regimeText(inst.regime)` → `regimeText(inst.regime?.regime||'')` |
| indices/sensex.html | 190 | `regimeText(inst.regime)` → `regimeText(inst.regime?.regime||'')` |
| indices/finnifty.html | 190 | `regimeText(inst.regime)` → `regimeText(inst.regime?.regime||'')` |
| index.html | 254 | `regimeWord(inst.regime)` → `regimeWord(inst.regime.regime||'')` |

## APIs Verified (5+, all 200)

- `/api/market` → 200, all instruments with data
- `/api/market-outlook?symbol=NIFTY` → 200, outlook data present
- `/api/market-outlook?symbol=BANKNIFTY` → 200, outlook data present
- `/api/options/state/NIFTY` → 200, options data present
- `/api/options/state/BANKNIFTY` → 200, options data present
- `/api/key-levels?symbol=NIFTY` → 200, key levels present
- `/api/key-levels?symbol=BANKNIFTY` → 200, key levels present
- `/api/strategy/NIFTY` → 200, strategy data present
- `/api/strategy/BANKNIFTY` → 200, strategy data present
- `/api/market-evidence/NIFTY` → 200, evidence data present
- `/api/market-evidence/BANKNIFTY` → 200, evidence data present

## Test Results

Created `tests/test_phase42a5d.py` with **12 tests** across 4 test classes:

- TestRegimeDictStringMismatch: 8 tests
- TestIndexPageRegimeFix: 2 tests
- TestAllPagesConsistency: 2 tests

**Result: 12/12 PASSED ✅**

## Deployment

All 5 fixed HTML files deployed to `/var/www/tradingai.in/html/` via scp. Verified on production VM: fix pattern present in all files, no remaining buggy patterns.

## Key Insight

The `market.html` page already correctly used `inst.regime?.regime` (line 133). This was the reference pattern that should have been applied to all index pages. The fix follows the same extraction approach.
