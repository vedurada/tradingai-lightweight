# Phase 5.4 — Migration and Rollback Plan

## 1. Feature Flag Design

### Proposed Feature Flag: `HLC_ONLY_MODE`

| Property | Value |
|----------|-------|
| Default | `false` (current behavior preserved) |
| Location | Environment variable or config/settings.json |
| Effect when true | `_hlc_book_signal()` becomes the default; `_cpr_book_signal()` disabled for new decisions |
| Effect when false | Current behavior (CPR is default, HLC is display-only) |
| Rollback | Set `HLC_ONLY_MODE=false` → restart gunicorn |

### Migration Gates

1. **Backup gate:** Verified backup of app/, frontend/, config/, DB schema
2. **Test gate:** All 9 look-ahead tests pass + new integration tests pass
3. **Parity gate:** HLC live output matches HLC backtest output on same data
4. **Risk gate:** Daily trade limit enforced (1 per instrument/day)
5. **Rollback gate:** Restore from backup restores prior behavior

## 2. Migration Steps (Proposed, Not Implemented)

### Step 1: Add daily trade limit to scalp path
- Modify `paper_scalp_live.py` to check `daily_trade_locks` before creating trade
- Default: 1 trade per instrument per day (configurable via settings)

### Step 2: Change live engine default
- Modify `app/live/engine.py:evaluate()` to use `_hlc_book_signal()` instead of `_cpr_book_signal()`
- Keep `_cpr_book_signal()` for rollback

### Step 3: Add entry-candle live protection
- Document backtest/live exit discrepancy (entry candle exclusion)
- Add live protection during entry candle remainder

### Step 4: Wire alert pipeline (optional)
- Integrate `scalp_alert_events.py` into `tg_alerts.py --watch`

### Step 5: Update frontend
- Change HLC from display-only to primary decision display

## 3. Rollback Procedure

1. Set `HLC_ONLY_MODE=false` (or remove feature flag)
2. Restart gunicorn: `sudo systemctl restart tradingai-api.service`
3. Verify CPR path is restored via `/api/decision` endpoint
4. Verify no new HLC trades are created
5. Verify existing HLC trades are still monitored

### Rollback Impact
- Live decision reverts to CPR trigger
- HLC paper trades already created remain in DB (not deleted)
- HLC display overlay reverts to display-only
- No data loss

## 4. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Dirty working tree | HIGH | Commit/stash before migration |
| CPR engine drives live decisions | HIGH | Feature flag defaults to current (CPR) |
| No daily trade limit on scalp | MEDIUM | Add before enabling HLC-only mode |
| Backtest/live exit discrepancy | MEDIUM | Document, don't silently change |
| Two trade stores | LOW | Keep both, unify reporting |
| No systemd unit for paper_scalp_live | MEDIUM | Add unit before migration |

## 5. Approval Requirements

This migration requires explicit owner approval because:
1. It changes the live trade decision engine from CPR to HLC
2. It affects all live paper trades
3. It requires daily trade limit enforcement (new behavior)
4. It requires feature flag infrastructure
5. It affects frontend display

**Do not implement without explicit approval.**
