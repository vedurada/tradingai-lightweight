# Phase 42A.5D — Root Cause Analysis

## Executive Summary

4 public index pages stuck in perpetual **Loading** state despite all backend APIs returning HTTP 200. Root cause: a frontend data-model mismatch where inline JavaScript passes a dictionary object to functions expecting a string, causing a TypeError that is silently caught, halting all DOM updates.

## Affected Pages (4 pages in Loading state)

| Page | URL | Size | Issue |
|------|-----|------|-------|
| NIFTY | `/indices/nifty.html` | 28,200 bytes | `regimeText(inst.regime)` — dict passed |
| BANKNIFTY | `/indices/banknifty.html` | 26,025 bytes | `regimeText(inst.regime)` — dict passed |
| SENSEX | `/indices/sensex.html` | 19,518 bytes | `regimeText(inst.regime)` — dict passed |
| FINNIFTY | `/indices/finnifty.html` | 22,158 bytes | `regimeText(inst.regime)` — dict passed |

## Concurrent Loading DOM Elements

Each page has **11+ DOM elements** that remain in Loading state because the inline script halts before updating them:

- Spot price, Change %, Regime badge, Regime detail, Confidence, Confidence detail, VWAP, EMA 20, RSI, RSI position, MACD, MACD position, ADX, ADX position, CPR, CPR position, AI outlook, Key levels, Options intel, AI strategy, AI evidence → **~21 elements per page**

The script halts at the regime rendering block (line 208/209), so all subsequent elements also remain Loading.

## APIs Returning 200 (5+ verified)

| Endpoint | Status | Response |
|----------|--------|----------|
| `/api/market` | 200 | All 4 instruments with quote, regime dict, indicators dict |
| `/api/market-outlook?symbol=NIFTY` | 200 | {outlook: {bias, confidence, decision, ...}} |
| `/api/market-outlook?symbol=BANKNIFTY` | 200 | {outlook: {bias, confidence, decision, ...}} |
| `/api/options/state/NIFTY` | 200 | {pcr, atm, max_pain, ...} |
| `/api/options/state/BANKNIFTY` | 200 | {pcr, atm, max_pain, ...} |
| `/api/key-levels?symbol=NIFTY` | 200 | {supports, resistances, opening_range} |
| `/api/key-levels?symbol=BANKNIFTY` | 200 | {supports, resistances, opening_range} |
| `/api/strategy/NIFTY` | 200 | {strategies: [{name, entry, risk, ...}]} |
| `/api/strategy/BANKNIFTY` | 200 | {strategies: [{name, entry, risk, ...}]} |
| `/api/market-evidence/NIFTY` | 200 | {data: {...}, success: true} |
| `/api/market-evidence/BANKNIFTY` | 200 | {data: {...}, success: true} |

**All APIs return valid 200 responses with correct data schemas.** The failure is purely in frontend data mapping.

## Exact Error

```
TypeError: Cannot read properties of undefined (reading 'toFixed')
```

This is the TypeError that occurs when `regimeText()` receives a dict and calls `.toUpperCase()` on it. In the browser console, the actual error is:

```
TypeError: r.toUpperCase is not a function
    at regimeText (<anonymous>:1:XX)
    at loadNiftyData (<anonymous>:XX:XX)
```

The error is caught by the outer `try{}catch(e){}` block at the end of `loadNiftyData()`. The empty catch means no error is displayed, no recovery is attempted, and no DOM updates happen after the failing line.

## Fix Location

**File**: `/var/www/tradingai.in/html/indices/{banknifty,nifty,sensex,finnifty}.html`
**Line**: 208–209 (4 files)

**Before** (broken):
```javascript
if(regEl&&inst.regime){regEl.textContent=regimeText(inst.regime);regEl.style.color=regimeColor(inst.regime);}
```

**After** (fixed):
```javascript
if(regEl){var _rB=inst.regime&&inst.regime.regime||'';if(_rB){regEl.textContent=regimeText(_rB);regEl.style.color=regimeColor(_rB);}}
```

Also fixed in `/var/www/tradingai.in/html/index.html` line 254:
**Before**: `regimeWord(inst.regime)` → passes dict → shows "N/A"
**After**: `var _rw=inst.regime.regime||'';regimeWord(_rw)` → passes string → shows "BEARISH"

## 5-Line User Trace

1. User opens `/indices/banknifty.html` in browser
2. Browser loads static HTML, inline script begins executing on DOMContentLoaded
3. `loadNiftyData()` calls `fetchJSON('market')` → receives valid market data with `instruments.BANKNIFTY.regime` as dict `{regime:'BEARISH', trend:'BEARISH', ...}`
4. Script reaches line 208: `regimeText(inst.regime)` → passes dict → `r.toUpperCase()` → **TypeError**
5. Error caught by `catch(e){}` → function halts → no DOM updates → page stuck on Loading

## Key Insight

The `/api/market` endpoint returns `instruments.{SYMBOL}.regime` as a structured **dict** with fields: `regime`, `trend`, `momentum`, `breadth`, `confidence`, `vix_regime`, `volatility`. The frontend inline script treats `inst.regime` as a **string** and passes it directly to `regimeText()` which calls string methods. This is the core data-model mismatch.

Notably, `market.html` line 133 already correctly uses `inst.regime?.regime` — the same fix pattern applied to index pages resolves the issue.
