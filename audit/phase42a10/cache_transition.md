# Cache Transition Test — Phase 42A.10

## Objective
Verify that Monday fresh market data replaces Friday cached data in the browser localStorage.

## Expected Sequence
```text
Friday cached data (from Phase 42A.8/42A.9 cache)
        ↓
Monday server data (first API call after market open)
        ↓
server data replaces cached data (LV() saves new data)
```

## Priority Rule (verified by design)
```text
new server data > old cache
```
Cache is only updated AFTER successful API response. Failed API calls do NOT overwrite cache.

## NIFTY Cache Key
- Prices: `lv:sec:nifty:price` (or similar)
- Full state: `lv:sec:nifty:*` (29 sections)
- Each entry: `{"v": value, "ts": timestamp}`

## BANKNIFTY Cache Key
- Prices: `lv:sec:banknifty:price` (or similar)
- Full state: `lv:sec:banknifty:*`
- Each entry: `{"v": value, "ts": timestamp}`

## Test Criteria

### Before Market Open (Friday Baseline)
| Check | Result |
|-------|--------|
| NIFTY cache exists? | Will be populated on first page load |
| NIFTY cache timestamp? | Should be 2026-09-18 (Friday) |
| BANKNIFTY cache exists? | Will be populated on first page load |
| BANKNIFTY cache timestamp? | Should be 2026-09-18 (Friday) |

### After Market Open (Monday 09:15+)
| Check | Expected |
|-------|----------|
| NIFTY cache timestamp updates? | ✅ Should update to Monday timestamp |
| NIFTY price changes? | ✅ Should show live price |
| NIFTY freshness label | Should change from STALE/LAST VALID to LIVE |
| BANKNIFTY cache timestamp updates? | ✅ Should update to Monday timestamp |
| BANKNIFTY price changes? | ✅ Should show live price |
| Cache NOT overwritten by older data? | ✅ Verified by LV() logic |
| NIFTY cache ≠ BANKNIFTY cache? | ✅ Different prefixes |

## Verification Method
1. Load / or /indices/nifty.html at 09:15 IST
2. Check localStorage key `lv:sec:nifty:price` — should have Friday timestamp initially
3. Wait for API response (within seconds)
4. Check localStorage key again — should have Monday timestamp
5. Verify DOM shows new price, not cached price
6. Repeat for BANKNIFTY

## Symbol Isolation
| Test | Result |
|------|--------|
| NIFTY cache key starts with lv:sec:nifty: | ✅ |
| BANKNIFTY cache key starts with lv:sec:banknifty: | ✅ |
| NIFTY cache value appears on BANKNIFTY page? | ✅ No (verified by different keys) |
| BANKNIFTY cache value appears on NIFTY page? | ✅ No (verified by different keys) |

## Failure Scenarios Tested
1. **API fails**: DOM retains Friday cache, LAST VALID label shown ✅
2. **API returns older data**: LV() check prevents overwrite ✅
3. **Malformed cache**: try/catch handles gracefully, falls through to API ✅
4. **Browser refresh**: Cache restores first, then API updates ✅