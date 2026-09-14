# PHASE 6B-3 B.5 — Specification

**Status**: IN PROGRESS — Awaiting Authorization

**Baseline**: `d4990e4` (B.4 frozen)
**Analytical baseline**: `45f90fc` (immutable)
**Model files**: 0/8 modified (preserved)
**Regression baseline**: 421/421 (must remain green)

---

## Specification Boundaries

### Mandatory Preservations

| Boundary | Protection |
|---|---|
| Model files | 0/8 modified — RegimeEngine, StrategyEngine, OptionsEngine, confidence, thresholds, backtest methodology — ALL frozen |
| Analytical outputs | No changes to any analytical computation, output format, or data quality semantics |
| Regression | 421/421 must remain green after B.5 implementation |
| Data quality semantics | DATA UNAVAILABLE, STALE, PARTIAL, SYSTEM DEGRADED semantics NOT weakened |
| Observational only | Monitoring/recovery changes must not influence trading decisions |
| B.4 freeze | d4990e4 remains starting baseline |

### Explicit Exclusions

| Item | Reason |
|---|---|
| Auth expansion | Separate scope required |
| Secrets management | VM-level, not code |
| Distributed tracing | Architecture review required |
| Centralized error tracking | Vendor selection required |
| Staging environment | Infrastructure |
| _symbol_data refactor | Separate design required |
| CSRF protection | Depends on auth design |

---

## B.5 Part 1: Deep Health Checks (Finding 3.5)

### Current State

The `/api/health` endpoint (api_server.py:416-450) currently returns:
- `status`: "ok" or "degraded"
- `timestamp`: ISO-8601 UTC
- `warnings`: array of warning strings
- `data_freshness`: `{source}_minutes_ago` per source
- `sources`: per-source status objects (ok/stale/unavailable + age_minutes)
- `overall`: "ok" or "degraded"
- `pool`: connection pool status

Current checks: source freshness (3 sources), connection pool exhaustion.

### Required Additions

| Check | Description | Method |
|---|---|---|
| Database row counts | Per key table: verify row counts are above minimum thresholds | Query `SELECT COUNT(*)` on key tables |
| Date range coverage | Verify key tables have data within expected date ranges | Query `MIN(created_at)`, `MAX(created_at)` per table |
| Value sanity | Verify key numeric values are within reasonable bounds | Query min/max of key columns |

### Key Tables to Monitor

| Table | Min Rows | Expected Date Range | Value Sanity |
|---|---|---|---|
| `price_1m` | 0 (may be empty in test) | Within 30 days of now | price > 0 |
| `price_1d` | 100 | Within 365 days of now | price > 0 |
| `vix_data` | 10 | Within 90 days of now | vix >= 0 |
| `market_outlooks` | 1 | Within 30 days of now | confidence in [0, 1] |

### Response Schema Addition

Add `deep_health` field to `/api/health` response:

```json
{
  "deep_health": {
    "database": {
      "tables_checked": 4,
      "all_healthy": true,
      "details": {
        "price_1d": {
          "row_count": 248,
          "min_date": "2025-09-11",
          "max_date": "2026-09-11",
          "status": "ok"
        }
      }
    },
    "overall": "ok"
  }
}
```

### Constraints

- Health checks must use a dedicated database connection (not pooled) with short timeout (5s)
- Health checks must NOT modify any data
- Health checks must be rate-limit exempt (`@limiter.exempt`)
- Health checks must complete within 2 seconds (per ENDPOINT_TIMEOUTS)
- If any deep check fails, `deep_health.overall` = "degraded" but `/api/health` still returns 200 (health is informational, not gating)
- Must work with sparse test databases (0 rows in some tables)

### Tests Required

| Test | Verifies |
|---|---|
| `test_health_deep_db_row_counts` | Deep health includes row counts for key tables |
| `test_health_deep_date_ranges` | Deep health includes date range info |
| `test_health_deep_value_sanity` | Deep health includes value sanity checks |
| `test_health_deep_does_not_modify_db` | Health check doesn't modify any data |
| `test_health_deep_under_timeout` | Deep health completes within 2s |

### Files Modified

- `backend/api_server.py` — `/api/health` endpoint addition

### Files Created

- Tests added to `tests/test_phase6b_b5.py` (or existing test file)

---

## B.5 Part 2: Deeper Freshness Validation (Finding 3.6)

### Current State

Freshness checks exist in `_check_source_freshness()` (api_server.py:281-330):
- Per-source timestamp comparison (e.g., "nifty_price" data older than 30 minutes → stale)
- `/api/data_status` returns raw `data_status` table rows
- `_record_fetch_result()` tracks success/error counts

Current gap: Only checks if last fetch timestamp is recent. Does NOT verify:
- Row count expectations (is data actually populated?)
- Date range coverage (does data span expected periods?)
- Value sanity (are values within reasonable bounds?)

### Required Additions

| Validation | Description | Trigger |
|---|---|---|
| Row count check | Verify data_status table has expected row count per source | On each data fetch |
| Date range check | Verify data spans expected date range per source | On each data fetch |
| Value range check | Verify key numeric values within bounds per source | On each data fetch |

### Implementation

Add a `_validate_data_depth()` function in `data_fetcher_db.py` that:
1. Takes a source name (e.g., "price_1m", "vix_data")
2. Queries the table for row count, min/max dates, min/max values
3. Compares against expected thresholds
4. Returns a validation result dict

```python
def _validate_data_depth(source_name):
    """Validate data depth for a source.
    
    Returns: {
        "source": source_name,
        "row_count": int,
        "min_date": str,
        "max_date": str,
        "value_range": {"min": float, "max": float},
        "status": "ok" | "degraded" | "unavailable",
        "issues": [str]
    }
    """
```

### Integration Points

- Called from `_check_source_freshness()` as an additional validation layer
- Results stored in `data_status` table (new columns or existing `error_count` increment on validation failure)
- Referenced by deep health check (Part 1)

### Constraints

- Must NOT modify any model files
- Must NOT change existing data quality semantics (LIVE/STALE/UNAVAILABLE)
- Validation failures should mark source as "degraded" in health, not "unavailable" (data exists but depth is questionable)
- Must work with sparse test databases

### Tests Required

| Test | Verifies |
|---|---|
| `test_data_depth_row_counts` | Row count validation returns correct counts |
| `test_data_depth_date_ranges` | Date range validation returns correct ranges |
| `test_data_depth_value_ranges` | Value range validation returns correct bounds |
| `test_data_depth_marks_degraded` | Validation failures mark source as degraded, not unavailable |
| `test_data_depth_preserves_data_quality` | Data quality labels not weakened |

### Files Modified

- `backend/data_fetcher_db.py` — `_validate_data_depth()` function
- `backend/api_server.py` — `_check_source_freshness()` integration

### Files Created

- Tests in `tests/test_phase6b_b5.py`

---

## B.5 Part 3: Process Supervisor Enhancements (Finding 11.2)

### Current State

Gunicorn runs via systemd unit (`ops/systemd/tradingai-api.service`):
- 3 workers, 2 threads, gthread class
- `--timeout 90 --max-requests 1000 --max-requests-jitter 100`
- `--access-logfile /opt/tradingai/logs/gunicorn-access.log`
- `--error-logfile /opt/tradingai/logs/gunicorn-error.log`
- OOMScoreAdjust=-200, Restart=always, RestartSec=10

No dedicated gunicorn config file. No memory limits. No logrotate for gunicorn logs.

### Required Enhancements

| Enhancement | Specification |
|---|---|
| Memory limit | Add `--max-memory 512m` per worker (512MB x 3 workers = 1.5GB max). Add `MemoryMax=2G` to systemd unit. |
| Logrotate | Create `/etc/logrotate.d/tradingai-gunicorn` with daily rotation, 7-day retention, compress, missingok, notifempty |
| Memory restart threshold | Add systemd `MemoryHigh=1.5G` (trigger memory cgroup pressure), `MemoryMax=2G` (hard limit, OOM kill) |

### Implementation

**11.2a: Memory Limits**
- Update `ops/systemd/tradingai-api.service`:
  - Add `MemoryMax=2G` (hard limit)
  - Add `MemoryHigh=1.5G` (soft limit, triggers cgroup pressure)
  - Add `MemorySwapMax=0` (prevent swap usage)

**11.2b: Logrotate**
- Create `ops/logrotate/tradingai-gunicorn`:
  ```
  /opt/tradingai/logs/gunicorn-*.log {
      daily
      rotate 7
      compress
      missingok
      notifempty
      copytruncate
  }
  ```
- Create `ops/logrotate/tradingai-api.log`:
  ```
  /opt/tradingai/logs/*.log {
      daily
      rotate 7
      compress
      missingok
      notifempty
      copytruncate
  }
  ```

**11.2c: Self-heal integration**
- Add to `ops/self-heal.sh`: check if gunicorn memory usage exceeds threshold, restart if needed

### Constraints

- Must NOT affect API behavior or response times
- Memory limits are for operational safety, not performance
- Logrotate configs must use `copytruncate` (no gunicorn restart needed)
- Self-heal memory check should be best-effort (not fail if memory info unavailable)

### Tests Required

| Test | Verifies |
|---|---|
| `test_systemd_has_memory_limits` | systemd unit has MemoryMax and MemoryHigh |
| `test_logrotate_config_exists` | Logrotate configs exist for gunicorn logs |
| `test_logrotate_config_valid` | Logrotate configs have required directives |
| `test_self_heal_memory_check` | Self-heal includes memory threshold check |

### Files Modified

- `ops/systemd/tradingai-api.service` — Add memory limits
- `ops/self-heal.sh` — Add memory check

### Files Created

- `ops/logrotate/tradingai-gunicorn` — Logrotate config for gunicorn logs
- `ops/logrotate/tradingai-api` — Logrotate config for API logs
- Tests in `tests/test_phase6b_b5.py`

---

## B.5 Part 4: Structured Deployment Logging (Finding 11.3)

### Current State

`deploy-vm.sh` currently logs:
- Start banner (`=== Deploying TradingAI Lightweight ===`)
- File copy status
- Health check result (DEPLOY SUCCESS/FAILED)
- End banner (`=== Deployment complete ===`)
- Nginx re-assertion log

Logging is plain text with no structure, no timestamps, no stage tracking.

### Required Enhancement

Convert deploy logging to structured format with:
- Timestamp for each log entry (ISO-8601)
- Stage names for each deployment step
- Duration for each stage
- Structured output (JSON or key-value format) for machine parsing

### Implementation Specification

Create a logging function in `deploy-vm.sh`:
```bash
deploy_log() {
    local stage="$1"
    local status="$2"
    local message="$3"
    local duration_ms="$4"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "{\"timestamp\":\"$timestamp\",\"stage\":\"$stage\",\"status\":\"$status\",\"message\":\"$message\",\"duration_ms\":$duration_ms}"
}
```

Each deployment stage logs:
- START: stage begins
- STEP: individual step within stage
- COMPLETE: stage ends with duration
- FAILURE: stage fails with error details

### Deployment Stages

| Stage | Steps |
|---|---|
| PRE_DEPLOY | File integrity check, DB backup |
| DEPLOY | File copy, dependency install |
| POST_DEPLOY | DB schema, data fetch, service restart |
| VERIFY | Health check, nginx config |
| CLEANUP | Log rotation check, cleanup temp files |

### Constraints

- Must NOT change deployment behavior — only add structured logging
- Must remain compatible with existing deploy workflow
- Must NOT touch model files or analytical code
- Plain text logs still work; structured fields are additional

### Tests Required

| Test | Verifies |
|---|---|
| `test_deploy_logs_structured` | Deploy log entries include timestamp, stage, status, duration |
| `test_deploy_all_stages_logged` | All 5 deployment stages produce log entries |
| `test_deploy_unchanged_behavior` | Deploy still succeeds/fails for same reasons |

### Files Modified

- `deploy-vm.sh` — Add structured logging function and stage tracking

### Tests Created

- Tests in `tests/test_phase6b_b5.py`

---

## B.5 Part 5: Crontab Auto-Install (Finding 11.4)

### Current State

- `ops/crontab.txt` defines crontab entries (self-heal, backup, etc.)
- `deploy-vm.sh` installs crontab from `ops/crontab.txt` on deploy
- `ops/self-heal.sh` runs via cron but does NOT manage crontab entries
- If crontab is accidentally cleared, self-heal stops running with no automatic recovery

### Required Enhancement

Add to `ops/self-heal.sh` a crontab verification step:
1. Check if crontab contains expected entries from `ops/crontab.txt`
2. If any expected entries are missing, reinstall from `ops/crontab.txt`
3. Log the action (crontab was repaired)

### Implementation Specification

Add to `ops/self-heal.sh`:

```bash
# Crontab verification and repair
EXPECTED_CRONTAB="ops/crontab.txt"
if [ -f "$EXPECTED_CRONTAB" ]; then
    MISSING_ENTRIES=0
    while IFS= read -r line; do
        [ -z "$line" ] || [ "${line:0:1}" = "#" ] && continue
        if ! crontab -l 2>/dev/null | grep -qF "$line"; then
            MISSING_ENTRIES=$((MISSING_ENTRIES + 1))
        fi
    done < "$EXPECTED_CRONTAB"
    
    if [ "$MISSING_ENTRIES" -gt 0 ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) REPAIR crontab: $MISSING_ENTRIES missing entries, reinstalling" >> /opt/tradingai/logs/self-heal.log
        crontab "$EXPECTED_CRONTAB"
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) REPAIR crontab: reinstalled $MISSING_ENTRIES entries" >> /opt/tradingai/logs/self-heal.log
    fi
fi
```

### Constraints

- Crontab repair is best-effort (must not fail self-heal if crontab command unavailable)
- Must NOT modify crontab if all entries present (no spurious changes)
- Must NOT touch analytical code, model files, or trading decisions
- Repair log must NOT be mistaken for trading signal

### Tests Required

| Test | Verifies |
|---|---|
| `test_self_heal_crontab_verify` | Self-heal checks crontab for expected entries |
| `test_self_heal_crontab_repair` | Self-heal reinstalls missing crontab entries |
| `test_self_heal_no_spurious_crontab_change` | No changes when crontab already complete |

### Files Modified

- `ops/self-heal.sh` — Add crontab verification and repair

### Tests Created

- Tests in `tests/test_phase6b_b5.py`

---

## B.5 Part 6: Database Backup Verification (Finding 11.5)

### Current State

- `ops/vm-backup.sh`: daily backup with integrity check + row count verification
- Backups stored on GitHub vm-backup branch
- `ops/self-heal.sh`: has emergency DB restore from `/opt/tradingai-backup/database/tradingai.db` (lines 54-57)
- Backup age NOT verified in self-heal — stale backup may go undetected

### Required Enhancement

Add to `ops/self-heal.sh` a backup verification step:
1. Check if backup file exists
2. Check if backup is within acceptable age (e.g., 7 days)
3. Verify backup integrity (can open with sqlite3)
4. If backup is stale or corrupt, log alert but DO NOT attempt restore (restore only on explicit failure)

### Implementation Specification

```bash
# Backup verification
BACKUP_FILE="/opt/tradingai-backup/database/tradingai.db"
MAX_BACKUP_AGE_DAYS=7

if [ -f "$BACKUP_FILE" ]; then
    # Check backup age
    BACKUP_AGE_DAYS=$(( ( $(date +%s) - $(stat -c %Y "$BACKUP_FILE") ) / 86400 ))
    if [ "$BACKUP_AGE_DAYS" -gt "$MAX_BACKUP_AGE_DAYS" ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALERT backup_stale: backup is ${BACKUP_AGE_DAYS} days old (max ${MAX_BACKUP_AGE_DAYS})" >> /opt/tradingai/logs/self-heal.log
    else
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK backup_age: ${BACKUP_AGE_DAYS} days old" >> /opt/tradingai/logs/self-heal.log
    fi
    
    # Check backup integrity
    if ! sqlite3 "$BACKUP_FILE" "SELECT 1 FROM symbols LIMIT 1" >/dev/null 2>&1; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALERT backup_corrupt: cannot read backup" >> /opt/tradingai/logs/self-heal.log
    else
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OK backup_integrity: verified" >> /opt/tradingai/logs/self-heal.log
    fi
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALERT backup_missing: no backup file found" >> /opt/tradingai/logs/self-heal.log
fi
```

### Constraints

- Backup verification is observational only — does NOT trigger automatic restore
- Must NOT modify the backup file
- Must NOT touch model files or analytical code
- Must handle missing sqlite3 command gracefully (best-effort)
- Alert log entries must NOT be mistaken for trading signals

### Tests Required

| Test | Verifies |
|---|---|
| `test_self_heal_backup_verify` | Self-heal checks backup age |
| `test_self_heal_backup_integrity` | Self-heal verifies backup can be read |
| `test_self_heal_backup_missing_alert` | Self-heal logs alert when backup missing |
| `test_self_heal_backup_no_auto_restore` | Verification does NOT trigger automatic restore |

### Files Modified

- `ops/self-heal.sh` — Add backup verification step

### Tests Created

- Tests in `tests/test_phase6b_b5.py`

---

## Implementation Order

All 6 parts are independent and can be implemented in any order:

```
Part 1 (Deep Health) ←→ Part 2 (Freshness)
Part 3 (Process Supervisor) — independent
Part 4 (Deploy Logging) — independent
Part 5 (Crontab) — independent
Part 6 (Backup Verify) — independent
```

Parts 1 and 2 share the `_validate_data_depth()` function — coordinate implementation to avoid duplication.

---

## Test Summary

All B.5 tests added to `tests/test_phase6b_b5.py`:

| Part | Tests | Count |
|---|---|---|
| Part 1 (Deep Health) | health deep checks, non-modification, timeout | 5 |
| Part 2 (Freshness) | depth validation, data quality preservation | 5 |
| Part 3 (Process Supervisor) | memory limits, logrotate, self-heal | 4 |
| Part 4 (Deploy Logging) | structured logs, stage coverage | 3 |
| Part 5 (Crontab) | verification, repair, no spurious change | 3 |
| Part 6 (Backup Verify) | age, integrity, missing, no auto-restore | 4 |
| **Total** | | **24** |

**Regression**: 421/421 must remain green after all 24 new tests pass.

---

## File Summary

### Files Modified (6)

| File | Parts |
|---|---|
| `backend/api_server.py` | Part 1 (health endpoint) |
| `backend/data_fetcher_db.py` | Part 2 (data depth validation) |
| `ops/systemd/tradingai-api.service` | Part 3 (memory limits) |
| `ops/self-heal.sh` | Parts 3, 5, 6 (memory check, crontab, backup verify) |
| `deploy-vm.sh` | Part 4 (structured logging) |

### Files Created (8)

| File | Purpose |
|---|---|
| `ops/logrotate/tradingai-gunicorn` | Logrotate config for gunicorn |
| `ops/logrotate/tradingai-api` | Logrotate config for API logs |
| `tests/test_phase6b_b5.py` | All B.5 tests (24) |
| PHASE6B_STEP5_B5_SPECIFICATION.md | This document |

### Files NOT Modified (Protected)

All 8 model files, all analytical code, all config files, auth code.

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Health check slows endpoint | Low | Medium | Dedicated connection, 2s timeout, rate-limit exempt |
| Logrotate config breaks | Low | Low | copytruncate, daily rotation, testable |
| Crontab repair causes issues | Low | Low | Best-effort, only when missing |
| Backup verification false alert | Medium | Low | Observational only, no auto-restore |
| Self-heal script syntax error | Low | High | Syntax check in CI, staged deploy |

---

## STOP — Awaiting Authorization

This specification is complete and ready for authorization.

Next step: B.5 Implementation Authorization.

Only after explicit authorization should implementation begin.

🔒 Baseline remains d4990e4.
🛑 STOP after review.
