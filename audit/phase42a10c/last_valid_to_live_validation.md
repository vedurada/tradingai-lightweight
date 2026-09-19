# Last-Valid → Live Transition Validation

## Expected Flow
```text
Friday last-valid data (23346.40, 56358.70, VIX 11.39)
        ↓
Monday 09:15 IST market opens
        ↓
new server data arrives from NSE/yfinance
        ↓
new data replaces cached/stale data
        ↓
fresh Monday timestamp
        ↓
LIVE/current state
```

## Verification Points
- [ ] Server data wins over browser cache (localStorage LV/LR cleared or updated)
- [ ] Friday values disappear from current-data position
- [ ] Monday timestamps displayed (2026-09-21)
- [ ] No stale Friday data labelled LIVE
- [ ] Symbol cache isolation (NIFTY ≠ BANKNIFTY data)
- [ ] API returns fresh timestamps after open

## Current State (Saturday)
```text
NIFTY: STALE, 2026-09-18, 23346.40
BANKNIFTY: STALE, 2026-09-18, 56358.70
VIX: STALE, 2026-09-18, 11.39
```

## Checkpoints
- 09:00 IST: Verify still LAST VALID (no premature LIVE)
- 09:15 IST: Market opens, monitor for transition
- 09:20 IST: Verify LIVE with fresh timestamps
- Verify no "LIVE" label on Friday data at any point
