# Errors and Repairs Log

## Phase 42A.10B Repairs (Already Deployed)

### Repair 1: api.js SyntaxError
- **File**: static/js/api.js:134-145
- **Issue**: Duplicate `const d` declaration in isMarketHours()
- **Impact**: Entire api.js failed to load in browsers
- **Fix**: Replaced with correct `const now = new Date()` implementation
- **Status**: ✅ Fixed and deployed to VM

### Repair 2: index.html render() Undefined
- **File**: index.html inline Script 6
- **Issue**: `_origRender=render` where render was never defined
- **Impact**: TypeError on DOMContentLoaded → page never rendered dashboard
- **Fix**: Replaced with proper `function render()` definition
- **Status**: ✅ Fixed and deployed to VM

## Phase 42A.10C Known Issues

### Issue: research_ai_call_log Empty
- **Table**: research_ai_call_log
- **Count**: 0 rows
- **Expected**: Will populate during Monday live session via AI scheduler
- **Action**: Monitor during Monday; if no entries by 10:00 IST, diagnose scheduler

### Issue: ai_outlooks_5m Empty
- **Table**: ai_outlooks_5m
- **Count**: 0 rows
- **Expected**: Will populate after AI scheduler runs at 09:30 IST Monday
- **Action**: Monitor during Monday live session

### Issue: pre_market_scenarios Empty
- **Table**: pre_market_scenarios
- **Count**: 0 rows
- **Expected**: May need to be populated before market opens
- **Action**: Check if scenario engine runs before 09:15 IST; if not, may need manual setup

### Issue: market_snapshots_5m Only 2 Rows
- **Table**: market_snapshots_5m
- **Count**: 2 rows (from previous audit)
- **Expected**: Should grow during Monday with every completed 5m candle
- **Action**: Monitor snapshot generation during Monday

### Issue: market_evidence_5m Only 1 Row
- **Table**: market_evidence_5m
- **Count**: 1 row (from previous audit)
- **Expected**: Should grow during Monday with each eligible snapshot
- **Action**: Monitor evidence generation during Monday

## No New Repairs During 42A.10C (Unless Confirmed Defect)
Per spec: "Only repair a confirmed production defect. Do not modify code merely because a potential issue is discovered."
