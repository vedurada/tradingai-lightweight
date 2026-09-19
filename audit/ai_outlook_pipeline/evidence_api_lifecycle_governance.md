# Evidence API, AI Outlook Lifecycle & Security/Governance

Date: 2026-09-18

## Evidence API for AI Outlooks (Section 22)

### Current Evidence-Related Endpoints

| Endpoint | Purpose | Status |
|----------|---------|--------|
| /api/outlook/5m/latest/<symbol> | Change detection results (regime, rsi, adx, vix) | WORKING (computed on fly) |
| /api/outlook/5m/changes/<symbol> | Material change detection | WORKING |
| /api/outlook/5m/snapshot/<symbol> | 5m market snapshot | BROKEN (market_snapshots_5m empty) |
| /api/outlook/5m/timeline/<symbol> | Historical 5m outlooks | BROKEN (ai_outlooks_5m empty) |
| /api/outlook/5m/scheduler | Diagnostic only (dry_run=True) | WORKING (diagnostic) |

### Missing Evidence APIs

- No endpoint to retrieve structured evidence breakdown (trend, momentum, structure, volatility separately)
- No endpoint to get evidence confidence scores over time
- No endpoint to compare evidence across symbols
- No endpoint for evidence freshness/staleness per category

## AI Outlook Lifecycle (Section 23)

### Full Lifecycle

```
1. TRIGGER (cron / scheduler)
   ├─ outlook.py (9AM/7PM) → ai_outlooks [WORKING]
   └─ outlook_scheduler.py → ai_outlooks_5m [NEVER TRIGGERED]

2. GENERATE
   ├─ AIOutlookEngine.generate(symbol, data, use_llm=True) [WORKING for legacy]
   └─ AIOutlookGenerator5m.generate(symbol, market_state, ...) [BROKEN]

3. VALIDATE
   ├─ AIOutlookEngine._normalize_llm_outlook() [WORKING]
   └─ AIOutlookGenerator5m._validate() [NEVER CALLED]

4. STORE
   ├─ INSERT OR REPLACE INTO ai_outlooks [WORKING for legacy]
   └─ INSERT OR REPLACE INTO ai_outlooks_5m [NEVER REACHED]

5. EVALUATE
   ├─ outlook_change_detector.evaluate() [WORKING - uses legacy data]
   └─ ai_outcome_predictions [EMPTY - never evaluated]

6. LINK OUTCOME
   └─ research_outcome_tracking [WORKING - for paper trades, NOT AI outlooks]

7. RETIRE
   └─ No explicit retirement — old outlooks stay in db indefinitely
```

### Lifecycle Gaps

| Stage | Legacy | 5m |
|-------|--------|----|
| Trigger | Cron (2x/day) | None |
| Generate | LLM + template | Bug (hardcoded NIFTY) |
| Validate | normalize_llm_outlook | _validate (never called) |
| Store | INSERT OR REPLACE | N/A |
| Evaluate | evaluate() works | N/A |
| Outcome | Not tracked | Not tracked |
| Retire | Not implemented | N/A |

## Security & Governance (Section 24)

### API Security

| Concern | Status |
|---------|--------|
| CORS | Production origins only (https://tradingai.in, https://www.tradingai.in) |
| Debug mode | Must be False in production (verified) |
| Rate limiting | 30/min on AI outlook endpoints |
| API key exposure | No keys in frontend code |
| Error schema | All errors use error_response() with code, message, timestamp |

### Data Security

| Concern | Status |
|---------|--------|
| GROQ API key | /etc/tradingai/groq.env (mode 600) |
| Database | SQLite at /opt/tradingai/database/tradingai.db |
| WAL mode | Yes |
| Backup | Daily at 18:00 via vm-backup.sh |
| No sensitive data in logs | Verified |

### Financial Data Integrity

| Concern | Status |
|---------|--------|
| AI outlook not used for direct trading | Correct — AI outlook is intelligence, not signal |
| No bare except | Should check — pre-commit hook enforces |
| No print in non-test code | Should check — pre-commit hook enforces |
| CORS production only | Verified |

## Model Governance (Section 25)

### Frozen Model Files

Per AGENTS.md, these files are FROZEN and must NOT be modified:
- backend/regime.py
- backend/strategies.py
- backend/indicators.py
- backend/options.py
- backend/outlook.py
- backend/scenarios.py
- backend/ai_outlook.py
- backend/backtest.py

**Critical**: `backend/outlook.py` is FROZEN. Any changes to it require a new Phase decision.
**Note**: `backend/ai_outlook_5m.py` is NOT listed as frozen — it CAN be modified.
**Note**: `backend/outlook_scheduler.py` is NOT listed as frozen — it CAN be modified.

### What This Means for Fixes

1. **ai_outlook_5m.py _call_llm bug**: CAN be fixed (not frozen)
2. **outlook_scheduler.py trigger**: CAN be added (not frozen)
3. **outlook.py changes**: FROZEN — must not be modified without Phase decision
4. **ai_outlook.py changes**: FROZEN — must not be modified without Phase decision

### Pre-Commit Hooks

- Checks for frozen model file modifications
- Checks for bare except
- Checks for print statements in non-test code
- Checks for other quality issues
