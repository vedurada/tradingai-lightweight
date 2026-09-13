# PHASE 6A — User-Facing Safety Hardening Specification

**Status**: SPECIFICATION — READY FOR IMPLEMENTATION
**Frozen Baseline**: `45f90fc` (184/184 passing)
**Scope**: UI/UX safety hardening only — NO model logic changes
**Commit Plan**: 45f90fc → PHASE 6A implementation commit → PHASE 6A freeze

---

## 1. Objective

Fix the three critical user-facing safety issues identified in PHASE 6 audit before public deployment. All changes are UI/UX only. No production logic is modified.

---

## 2. Implementation Items

### 2.1 Confidence Explanation (CRITICAL)

**Problem**: Users see "58%" and interpret it as "58% probability of being correct." Per STEP 7 finding, confidence = signal agreement, NOT directional reliability.

**Current behavior**: Payload contains `"confidence": 58`. Frontend displays raw number as "Confidence: 58%".

**Required changes**:

#### A. Rename label from "Confidence" to "Signal Confidence"

Files to modify:
- `backend/api_server.py` — wherever confidence is displayed in API response summary fields
- `market/outlook-nifty-2026-09-13.html` — or the JS that renders the dashboard (`ai-outlook.js`, `live-blink.js`)
- All HTML pages that display confidence to users

Change:
```
Before: Confidence: 58%
After:  Signal Confidence: 58%
```

#### B. Add tooltip explanation

Add an info icon (ⓘ) next to the Signal Confidence label with the following text:

```
Measures agreement among market signals.
It is not a probability of being correct.
Higher = signals align more strongly on this classification.
```

Implementation: HTML `title` attribute or JavaScript tooltip on hover/click.

#### C. Meta tag description update

Update `market/outlook-nifty-2026-09-13.html` meta description:

```
Before: ...confidence 58%, tradeability LOW...
After: ...signal confidence 58%, tradeability LOW...
```

#### D. About page mention

Add to `about.html` under "How the analysis is produced" section:

```
Signal Confidence reflects how strongly our indicators agree on the
current market classification. It does not represent the probability
of the market moving in any particular direction.
```

### 2.2 WAIT / NO TRADE Messaging (CRITICAL)

**Problem**: Users may interpret WAIT as "AI is uncertain" rather than "intentional risk-management decision."

**Required changes**:

#### A. WAIT explanation in dashboard

Add explicit text wherever WAIT/NO TRADE is displayed:

```
WAIT / NO TRADE
Current conditions do not provide sufficient edge for the available strategies.
Staying out is the recommended risk-control action.
```

#### B. "How to read this outlook" update

In `market/outlook-nifty-2026-09-13.html`, add to the content card:

```
<p>When the AI says WAIT or NO TRADE, it is choosing not to trade because
the available strategies do not have sufficient edge under current conditions.
This is an intentional risk-management decision, not uncertainty about the market.</p>
```

#### C. Avoid these words in all user-facing text:

| Avoid | Use Instead |
|-------|-------------|
| "AI is uncertain" | "Insufficient edge for available strategies" |
| "AI is unsure" | "Selective — no trade currently recommended" |
| "Cannot determine" | "Conditions do not meet strategy criteria" |
| "Waiting for signal" | "No trade recommended — risk control active" |

#### D. Decision verdict display

Update the decision.verdict field display in `market/outlook-nifty-2026-09-13.html`:

```
Before: AI Verdict: WAIT
After:  AI Verdict: WAIT — No trade recommended (risk control)
```

### 2.3 Basic Data-Freshness / Health Monitoring (CRITICAL)

**Principle**: "A stale intelligence system must fail visibly rather than silently produce yesterday's analysis."

**Required changes**:

#### A. API health enhancement

Enhance `backend/api_server.py` `/api/health` endpoint:

```python
@app.route("/api/health")
def health():
    conn = get_db()
    # Check data freshness
    latest_price = conn.execute("SELECT MAX(timestamp) as ts FROM price_1m WHERE symbol='NIFTY'").fetchone()
    latest_vix = conn.execute("SELECT MAX(timestamp) as ts FROM vix_data").fetchone()
    latest_outlook = conn.execute("SELECT MAX(date) as ds FROM market_outlooks WHERE symbol='NIFTY'").fetchone()
    now = datetime.now(timezone.utc)
    
    status = "ok"
    warnings = []
    
    if latest_price["ts"]:
        price_age = (now - datetime.fromisoformat(latest_price["ts"])).total_seconds() / 60
        if price_age > 30:
            status = "degraded"
            warnings.append(f"NIFTY price data {price_age:.0f}m stale")
    
    if latest_vix["ts"]:
        vix_age = (now - datetime.fromisoformat(latest_vix["ts"])).total_seconds() / 60
        if vix_age > 60:
            status = "degraded"
            warnings.append(f"VIX data {vix_age:.0f}m stale")
    
    if latest_outlook["ds"]:
        outlook_age = (now.date() - datetime.strptime(latest_outlook["ds"], "%Y-%m-%d").date()).days
        if outlook_age > 1:
            warnings.append(f"Outlook {outlook_age}d old")
    
    conn.close()
    return jsonify({
        "status": status,
        "timestamp": now.isoformat(),
        "warnings": warnings,
        "data_freshness": {
            "nifty_price_minutes_ago": price_age if latest_price["ts"] else None,
            "vix_minutes_ago": vix_age if latest_vix["ts"] else None,
            "outlook_days_old": outlook_age if latest_outlook["ds"] else None,
        }
    })
```

#### B. Frontend freshness indicator

In `market/outlook-nifty-2026-09-13.html` or the shared `assets/js/live-blink.js`, add a data freshness bar:

```
Last updated: 14:32 IST | Price data: 2m old | VIX data: 5m old | Outlook: today
```

If any data is stale:
```
Last updated: 14:32 IST | ⚠️ Price data: 45m stale | ⚠️ VIX data: 70m stale | Outlook: today
```

#### C. Monitoring checklist (manual, automated in Phase 6B)

Create a monitoring script (temporary, or in tools/ directory):

```python
#!/usr/bin/env python3
"""Basic health check — run every 5 minutes via cron."""
import requests, sys, json

BASE = "http://localhost:8000"
checks = [
    ("/api/health", "Health endpoint"),
    ("/api/market-outlook", "Market outlook"),
    ("/api/vix", "VIX data"),
    ("/api/indicators/NIFTY", "Indicators"),
    ("/api/options/expiries/NIFTY", "Options expiries"),
]

all_ok = True
for path, name in checks:
    try:
        r = requests.get(BASE + path, timeout=10)
        if r.status_code == 200:
            print(f"✅ {name}: OK")
        else:
            print(f"⚠️ {name}: HTTP {r.status_code}")
            all_ok = False
    except Exception as e:
        print(f"🔴 {name}: FAILED ({e})")
        all_ok = False

if not all_ok:
    # Log to file for alerting
    with open("/tmp/tradingai_health.log", "a") as f:
        f.write(f"{datetime.now()} - HEALTH CHECK FAILED\n")
    sys.exit(1)
sys.exit(0)
```

---

## 3. What Must NOT Change (Mandatory)

| Component | Prohibition |
|-----------|-------------|
| RegimeEngine | No threshold changes, no formula changes |
| StrategyEngine | No strategy selection logic changes |
| Confidence mathematics | No changes to `_confidence()` in regime.py |
| Options calculations | No changes to OptionsEngine |
| LLM boundary | No changes to merge_llm_into_payload() |
| Transaction costs | No changes to cost assumptions |
| Backtest methodology | No changes to backtest.py |
| Position sizing | No changes to _position_size() |
| Regime → Strategy mapping | No changes to the BULLISH/BEARISH/etc. mappings |

**All changes in PHASE 6A must be UI/UX/monitoring only.**

---

## 4. Acceptance Criteria

### 4.1 Confidence Explanation

| Criteria | Pass |
|----------|------|
| Label changed from "Confidence" to "Signal Confidence" | ✅ All user-facing displays updated |
| Tooltip visible on hover/click | ✅ Info icon (ⓘ) present next to label |
| Tooltip text: "Measures agreement among market signals..." | ✅ Exact wording or equivalent |
| Meta description updated | ✅ "Signal confidence" in meta |
| About page mentions confidence nature | ✅ Added to "How the analysis is produced" |
| Model outputs unchanged | ✅ /api/health returns same confidence value |

### 4.2 WAIT/NO TRADE Messaging

| Criteria | Pass |
|----------|------|
| WAIT explanation added to dashboard | ✅ Visible when verdict = WAIT |
| "Intentional risk-management decision" language | ✅ Not "uncertain" or "unsure" |
| Avoid words list documented | ✅ No forbidden words in user-facing text |
| Decision verdict updated | ✅ "WAIT — No trade recommended (risk control)" |
| Model outputs unchanged | ✅ /api/health returns same verdict |

### 4.3 Data-Freshness Monitoring

| Criteria | Pass |
|----------|------|
| /api/health returns freshness data | ✅ price/vix/outlook age in response |
| /api/health returns status (ok/degraded) | ✅ Degraded when data stale |
| Frontend shows data age | ✅ "Price data: 2m old" in UI |
| Frontend shows warnings when stale | ✅ ⚠️ indicator for stale data |
| Monitoring script functional | ✅ Checks all critical endpoints |
| 45f90fc model behavior preserved | ✅ Test suite still 184/184 |

---

## 5. Testing Plan

### Pre-implementation baseline
```bash
cd tradingai-lightweight
git status                    # Confirm clean working tree
git diff HEAD --stat          # Confirm zero modifications
python3 run_tests.py          # Confirm 184/184 passing
```

### Post-implementation verification
```bash
# 1. Model behavior preserved
python3 run_tests.py          # Must still be 184/184

# 2. API still returns same data
curl http://localhost:8000/api/market-outlook | python3 -c "import json,sys; d=json.load(sys.stdin); print('confidence:', d['confidence']); print('verdict:', d['decision']['verdict'])"
# Expected: confidence: 58 (unchanged), verdict: WAIT (unchanged)

# 3. Health endpoint enhanced
curl http://localhost:8000/api/health | python3 -m json.tool
# Expected: status, timestamp, warnings, data_freshness fields

# 4. No forbidden word checks
rg -i "uncertain|unsure|cannot determine|waiting for signal" market/ templates/ 2>/dev/null || echo "No forbidden words found"
```

### Commit structure
```bash
# Commit 1: 45f90fc (FROZEN — analytical/model baseline)
git commit -m "PHASE-5-STEP5-IMPLEMENTATION: confidence semantics, strategy authority, scenario normalization, regression tests"

# Commit 2: PHASE 6A implementation (UI/UX/monitoring only)
git commit -m "PHASE-6A-USER-FACING-HARDENING: signal confidence label, WAIT messaging, health monitoring"
```

---

## 6. File Change Summary

### Modified Files (UI/UX only)

| File | Change |
|------|--------|
| `market/outlook-nifty-2026-09-13.html` | Confidence label, WAIT messaging, freshness display |
| `about.html` | Confidence explanation in "How the analysis is produced" |
| `backend/api_server.py` | Enhanced /api/health endpoint |
| `assets/js/live-blink.js` or `ai-outlook.js` | Tooltip rendering, freshness display |
| `PHASE6_PRODUCTIZATION_AUDIT.md` | Mark C1/C2/C3 as addressed |

### New Files

| File | Purpose |
|------|---------|
| `tools/health_check.py` | Basic monitoring script |

### Unchanged Files (mandatory)

| File | Must remain identical to 45f90fc |
|------|----------------------------------|
| `backend/regime.py` | All thresholds, formulas |
| `backend/strategies.py` | All strategy logic |
| `backend/outlook.py` | All outlook construction |
| `backend/ai_outlook.py` | All AI logic |
| `backend/options.py` | All options calculations |
| `backend/backtest.py` | All backtest logic |
| `backend/scenarios.py` | All scenario logic |
| `PHASE5_STEP6_PREDICTIVE_INTEGRITY_AUDIT.md` | Frozen results |
| `PHASE5_STEP7_PREDICTIVE_ARCHITECTURE_REVIEW.md` | Frozen findings |
| All test files | All 184 tests unchanged |

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Model behavior changes | Very Low | High | Tests + diff verification |
| UI broken | Low | Medium | Visual testing before deploy |
| Monitoring script fails | Low | Low | File exists, cron job checks it |
| User confusion persists | Medium | Medium | Add "How to read" section explaining all changes |

---

## 8. Transition to PHASE 6B

PHASE 6A must be frozen (new commit) before PHASE 6B begins.

New frozen checkpoint: `45f90fc-6A` (new commit hash after PHASE 6A implementation)

PHASE 6B will add:
- Standardized API error schema
- Rate limiting
- CI/CD regression execution
- Performance monitoring
- Endpoint health monitoring
- Alerting
- Logging/observability
- Recovery/failure-state testing

All PHASE 6B work occurs on top of the PHASE 6A commit.

---

## 9. Document Control

| Property | Value |
|----------|-------|
| Status | SPECIFICATION — READY FOR IMPLEMENTATION |
| Preceding Audit | PHASE6_PRODUCTIZATION_AUDIT.md (CONDITIONAL PASS) |
| Frozen Baseline | 45f90fc |
| Scope | UI/UX/Monitoring only |
| Model Changes | None — absolutely none |
| Estimated Risk | Very Low — no logic changes |
| Next Action | Implement Phase 6A, test, freeze as new checkpoint |
