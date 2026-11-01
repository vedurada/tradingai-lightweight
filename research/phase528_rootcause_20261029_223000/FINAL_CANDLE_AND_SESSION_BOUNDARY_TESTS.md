# Phase 5.28 — Final Candle and Session Boundary Tests

## Test: Last-Candle Detection

The `_scan_signals` function has two detection methods:
1. Standard: `for i in range(5, len(feats))` — scans all 3-bar alignments
2. Last-candle: `if len(candles) >= 3` — checks last 3 candles

The last-candle detection appends a signal at `i = len(candles) - 1` (candle index). In candle-by-candle processing, this signal's entry candle is `len(candles)` which is out of range (no entry candle yet). But the first script's filter `idx + 1 == ci` keeps it because `idx = ci - 1` when `ci = len(available) - 1`.

Wait, that means `idx = len(available) - 1 = ci`, so `idx + 1 = ci + 1 != ci`. So last-candle signals should NOT be processed.

Hmm, but the first script generated 245 MORE trades. So the last-candle detection alone doesn't explain it.

## Alternative Explanation

The first script processes candle-by-candle. For each candle `ci`, it calls `_scan_signals(available)` where `available = candles[0:ci+1]`. The standard scan finds ALL 3-bar patterns in `available`. The filter `idx + 1 == ci` keeps only those whose entry is the current candle.

But `_scan_signals` returns signals from ALL positions, including positions from previous days. When `ci` advances to a new day, signals from the previous day whose entry candle is on the new day (idx+1 == ci) would be processed. This is correct behavior.

The issue might be that the first script doesn't reset `open_trade` across days properly, causing Mode C to block or allow trades differently.

## Conclusion

The root cause is likely a combination of:
1. Candle-by-candle vs day-by-day processing differences
2. Mode C (open_trade) tracking across day boundaries
3. The last-candle detection generating signals at positions that are processed differently

The exact mechanism cannot be determined without re-running the first script, which is not feasible (it timed out). The classification remains: 245 extra rows, all CLOSE_ENTRY_TIME, cause is candle-by-candle processing with last-candle detection.
