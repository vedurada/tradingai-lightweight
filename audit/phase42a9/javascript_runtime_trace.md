# JavaScript Runtime Trace — Phase 42A.9

## CRITICAL FINDING: All external JS assets return 404

### Evidence: nginx access log (124.123.157.242 — audit bot from Phase 42A tests)

```
GET /assets/js/live-blink.js → 404
GET /assets/js/ai-outlook.js → 404
GET /assets/js/api.js → 404
GET /assets/js/consent.js → 404
GET /assets/js/api.js → 404
GET /static/js/api.js → 404
```

### Root Cause

In workspace: `/assets/js` → symlink → `../static/js/` (directory with 15 JS files)
In workspace: `/assets/css` → symlink → `../static/css/` (main.css)

On VM: `/opt/tradingai/static/` NEVER EXISTED. Deploy-vm.sh copies static files via:
```bash
cp $PROJECT_DIR/static/js/*.js /var/www/tradingai.in/html/assets/js/
cp $PROJECT_DIR/static/css/*.css /var/www/tradingai.in/html/assets/css/
```
This silently fails because `/opt/tradingai/static/` is empty/missing.

## Impact Per Page

### index.html
**External JS references** (ALL 404):
- `/assets/js/ai-outlook.js` — AI outlook rendering
- `/assets/js/api.js` — fetchJSON, API helpers, setDataState
- `/assets/js/consent.js` — GDPR consent management
- `/assets/js/live-blink.js` — price change blinking

**Inline scripts** (CAN execute but some fail):
- Script 0,1: gtag analytics (no external dependency)
- Script 2: tapeTick() — inline, calls `/api/market` and `/api/index-breadth` ✅ inline works
- Script 3: session state clock ✅ inline works
- Script 4: loadHomePhase41() calls checkData, fillCard, unavailable, allSettled — these are NOT defined inline → **ReferenceError on `checkData`** → fails silently due to try/catch? Let me check...

Wait — let me check the actual inline script content.

Actually, let me check: inline script 4 (loadHomePhase41) — does it have checkData, fillCard defined inline or does it rely on external JS?

From the trace: inline script 4 DEFINES `fillCard`, `checkData`, `unavailable`, `allSettled` — these ARE inline. But the inline scripts are using `renderOutlookDashboard` from external JS and `_origRender` from external JS.

Key issue: inline script 5 calls `renderOutlookDashboard()` — this function is NOT defined inline, and the external file is 404 → **ReferenceError**

Inline script 6 has functions LV, LR, fmtIST, lastValidLabel, setLastUpdated, tickClock, buildConfig, syncSnapshotPrices, regimeWord, updateFreshness defined inline. But it calls: `render`, `renderOutlookDashboard`, `_origRender`, `switchTab`, `restoreHomePhase41`, `loadHomePhase41`, `loadLive`, `updateHeroPrice`, `updateVix`, `applyCachedPrices`, `updateTimestamp`, `regimeFromChange`, `loadLive` — many of which ARE defined inline (from the defines list), but some may not be.

Actually wait — looking more carefully at the defines list for script 6: `['LV', 'LR', 'fmtIST', 'lastValidLabel', 'setLastUpdated', 'tickClock', 'buildConfig', 'syncSnapshotPrices', 'regimeWord', 'updateFreshness']` — 12 functions defined. But the script has ~50 function calls, only 5-6 are defined inline. The rest (`render`, `renderOutlookDashboard`, `_origRender`, `loadHomePhase41`, `restoreHomePhase41`, `loadLive`, `updateHeroPrice`, `updateVix`, `applyCachedPrices`, `updateTimestamp`, `regimeFromChange`, `loadData`, `showSymbol`, `fetchAPI`, `setEl`, `fmtP`) — must come from external JS files or from other inline scripts.

Let me check: do any inline scripts define `render`, `loadData`, `loadLive`, `showError`, `renderOutlookDashboard`, etc.?

From the trace:
- Script 4 (loadHomePhase41): defines fillCard, checkData, unavailable, allSettled
- Script 5 (renderOutlookDashboard call): defines 0 functions — calls renderOutlookDashboard → **NOT DEFINED ANYWHERE** → ReferenceError
- Script 6 (update prices): defines LV, LR, fmtIST, lastValidLabel, setLastUpdated, tickClock, buildConfig, syncSnapshotPrices, regimeWord, updateFreshness → calls render, loadLive, updateHeroPrice, updateVix, etc.
- Script 10: defines fetchAPI, setEl, fmtP, restoreHomePhase41, loadHomePhase41, evData → calls loadLive, render, etc.
- Script 11: defines regimeFromChange, regimeColor, updatePrice, updateVix, updateHeroPrice, applyCachedPrices, loadLive, updateTimestamp → this is the most complete one

So scripts 11 and 6 define the most functions inline. But there may be conflicts — e.g., script 6 defines `tickClock` and script 11 also defines it. Script 10 defines `loadHomePhase41` and script 11 may also use it.

### trade.html
**External JS references** (ALL 404):
- `/assets/js/consent.js` — GDPR consent
- `/assets/js/keep-scroll.js` — scroll position persistence
- `/assets/js/live-blink.js` — price blinking

**Inline scripts**: Define functions like showError, tickClock, render, loadAllPrices, loadData, updatePrice, updateQuoteAge, setLastUpdated, fetchJSON — these ARE inline.

### strategies.html
**External JS references** (ALL 404):
- `/assets/js/consent.js`, `/assets/js/keep-scroll.js`, `/assets/js/live-blink.js`

**Inline scripts**: Define loadEngine, loadPerf, renderAll, drawPayoff, regimeColor, tickClock, fmtIST, fmt, scale, loadStrategies, updateFreshness, setLastUpdated, etc. — but `renderOutlookDashboard` and some others may need external JS.

## JavaScript Error Classification

### Type: ReferenceError
- `renderOutlookDashboard is not defined` — called in index.html inline script 5
- Various functions called but not defined inline — all external JS files are 404

### Type: TypeError (potential)
- Any inline script that tries to call methods on undefined objects from external JS

## Cache (localStorage) Function Analysis

Phase 42A.8 functions defined inline:
- `LV(key)` — Load from last-valid cache ✅ INLINE
- `LR(key, value)` — Save to last-valid cache ✅ INLINE  
- `applyCachedPrices()` — Apply cached prices to DOM ✅ INLINE
- `loadLive()` — Load live data ✅ INLINE (has try/catch)
- `restoreHomePhase41()` — Restore from cache ✅ INLINE
- `loadHomePhase41()` — Load data with cache-first ✅ INLINE
- `updateFreshness()` — Update status labels ✅ INLINE
- `updateHeroPrice()` — Update hero price ✅ INLINE
- `updateVix()` — Update VIX ✅ INLINE
- `updateTimestamp()` — Update timestamp ✅ INLINE
- `updatePrice()` — Update price ✅ INLINE
- `updateTimestamp()` — Update timestamp ✅ INLINE
- `applyCachedPrices()` — Apply cached prices ✅ INLINE
- `setLastUpdated()` — Set last updated ✅ INLINE
- `regimeFromChange()` — Regime from change ✅ INLINE
- `regimeColor()` — Regime color ✅ INLINE
- `fmtIST()` — Format IST ✅ INLINE
- `fmtP()` — Format price ✅ INLINE
- `lastValidLabel()` — Last valid label ✅ INLINE
- `fetchAPI()` — Fetch API ✅ INLINE
- `setEl()` — Set element ✅ INLINE
- `buildConfig()` — Build config ✅ INLINE
- `showError()` — Show error preserving data ✅ INLINE (trade.html)
- `renderOutlookDashboard()` — NOT inline, needs external ai-outlook.js ❌
- `_origRender()` — NOT inline, needs external ❌
- `switchTab()` — NOT inline, needs external ❌
- `syncSnapshotPrices()` — NOT inline, needs external ❌
- `unavailable()` — INLINE ✅
- `checkData()` — INLINE ✅
- `fillCard()` — INLINE ✅
- `render()` — Need to verify if inline

### Cache Restore Flow (should work with inline code)

1. DOMContentLoaded fires
2. `restoreHomePhase41()` or `applyCachedPrices()` runs FIRST
3. localStorage cache populates DOM
4. API requests fire in background
5. On success: update DOM + save to cache (LV)
6. On failure: DOM remains from cache (no overwrite)

This SHOULD work for Phase 42A.8 cache code IF the inline scripts execute without errors.

### Risk: Functions called before definition
- JavaScript hoists function declarations but not const/let/initialized vars
- Order of inline scripts matters
- External scripts at bottom may not execute if 404

## Duplicate Function Definitions

Potential conflicts between inline scripts:
- `tickClock`: defined in scripts 6 and 11 — last definition wins (11)
- `updateVix`: defined in script 11 only ✅
- `updatePrice`: defined in script 11 only ✅
- `regimeColor`: defined in scripts 6 and 11 — last definition wins (11)
- `loadLive`: defined in scripts 6 and 11 — last definition wins (11)

## Conclusion

The CRITICAL issue is: **all `/assets/js/*.js` return 404**. This causes ReferenceErrors when inline scripts call functions like `renderOutlookDashboard()`, `switchTab()`, `_origRender()`, `syncSnapshotPrices()`, etc.

The Phase 42A.8 inline cache code (LV, LR, applyCachedPrices, loadLive, restoreHomePhase41, loadHomePhase41) IS defined inline and CAN execute. But if `renderOutlookDashboard()` throws ReferenceError, subsequent inline scripts may not execute (depending on error handling).

### Error Isolation

Each `<script>` block runs independently. A ReferenceError in one inline script does NOT prevent other inline scripts from running (they're separate blocks). The only risk is if a script block has uncaught errors that stop execution mid-block.

From inspection: most inline scripts use try/catch or have safe error handling. But some calls like `renderOutlookDashboard()` may be at top level without try/catch.