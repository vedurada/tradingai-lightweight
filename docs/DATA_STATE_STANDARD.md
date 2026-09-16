# TradingAI — Data-State Standard

Created: 16 September 2026
Baseline: v2b5583a-baseline

Every dynamic component on every production page must display exactly one of these five states:

## The Five States

### LIVE
When data is current and fresh.
```
LIVE
NIFTY 23,118.60
Updated 09:31:24 IST
```
- Value is populated
- Timestamp shows when data was last updated
- Color indicates freshness (green/default)

### UPDATED
When data was recently refreshed but may not be current.
```
UPDATED 09:28:00 IST
NIFTY 23,115.20
```
- Value is from a recent refresh
- Timestamp visible
- Amber/yellow indicator

### STALE
When data is too old to be reliable.
```
STALE — data > 15 minutes old
NIFTY 23,100.00
Last successful update: 09:15:00 IST
```
- Value is from last successful update
- Timestamp shows last update time
- Red indicator
- Warning message

### UNAVAILABLE
When no data is available (market closed, no feed).
```
UNAVAILABLE
Market data not active
Last update: Yesterday 15:30 IST
```
- No current value shown
- Explicit "unavailable" message
- Last update timestamp

### ERROR
When data fetch failed.
```
ERROR — Market data temporarily unavailable.
Last successful update: 09:30:42 IST
[Retry]
```
- Error message visible
- Last successful update timestamp
- Retry mechanism

## NEVER Show

- Permanent "Loading…" without transition to one of the above states
- Old data displayed as current
- Silent failures where the page appears to work but shows nothing

## Implementation

Every dynamic component should:
1. Start in LOADING state on page load
2. Transition to LIVE/UPDATED when data arrives
3. Transition to STALE after 15 minutes without refresh
4. Transition to UNAVAILABLE when market is closed
5. Transition to ERROR on fetch failure
6. Show timestamp in all non-LOADING states
7. Auto-refresh on interval (30-60 seconds during market hours)

## State Transitions

```
LOADING ──success──→ LIVE ──15min──→ STALE
  │                        │
  │──error──→ ERROR ──retry──→ LOADING
  │
  │──market closed──→ UNAVAILABLE
```

## Timestamp Format

All timestamps: IST (Indian Standard Time)
Format: "Data as of DD Mon YYYY, HH:MM:SS IST"
Example: "Data as of 16 Sep 2026, 09:31:24 IST"
