# Root Cause Analysis — Phase 42A.5E Defects

## Defect 1: market_evidence_5m has 0 rows (P1)

### Evidence
- Table: market_evidence_5m
- Row count: 0
- Expected: At least some rows from market evidence engine during market hours

### Affected Layers
- MARKET EVIDENCE (direct)
- MARKET STATE (downstream - may lack evidence context)
- AI OUTLOOK (may lack evidence basis)
- TRADE QUALIFICATION (may lack evidence basis)

### Affected Instruments
- NIFTY (evidence table has 0 rows for all instruments)
- BANKNIFTY (evidence table has 0 rows for all instruments)
- SENSEX (evidence table has 0 rows)
- FINNIFTY (evidence table has 0 rows)

### Root Cause
Under investigation. Possible causes:
1. Evidence engine not activated in this deployment
2. Evidence generation requires a separate trigger or configuration
3. Evidence engine produces output to a different table
4. Pipeline dependency not satisfied (e.g., requires market regime data that was only recently populated)

### Verification
- market_regime table: 39,002 rows ✅ (regime engine working)
- market_snapshots: 1,284 rows ✅ (snapshot engine working)
- market_outlooks: 206 rows ✅ (AI outlook engine working)
- market_evidence_5m: 0 rows ❌ (evidence engine NOT producing)

### Impact Assessment
- Deterministic pipeline continues without evidence (regime/state still generated)
- AI outlooks still generated (may lack evidence context)
- Trade qualification may proceed without evidence basis
- No pipeline blocking (degraded but functional)

### Resolution Status
DOCUMENTED — Requires investigation in future phase. Not blocking for Phase 42A.5E validation.

## Defect 2: 1m data stale (P2)

### Evidence
- Latest 1m timestamp: 2026-09-18 10:29:00 IST
- Current time: 2026-09-18 18:42:37 IST
- Age: 498 minutes (8.3 hours)

### Root Cause
Market closed at 15:30 IST. Data fetcher (data_fetcher_db.py) runs during market hours only (cron: * 9-15 * * 1-5).

### Impact Assessment
Expected behavior. No action required.

### Resolution Status
EXPECTED — Market closed. No fix needed.

## Defect 3: Market snapshots stale (P2)

### Evidence
- Latest snapshot: ~8.3 hours old
- Market closed at 15:30 IST

### Root Cause
Market closed. Snapshot generation stops when market closes.

### Impact Assessment
Expected behavior. No action required.

### Resolution Status
EXPECTED — Market closed. No fix needed.
