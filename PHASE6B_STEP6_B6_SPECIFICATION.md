# PHASE 6B-3 B.6 — Specification ("Reliability Core")

**Status**: 🟡 SPECIFICATION — no implementation authorized.

**Baseline**: `4b7260f` 🔒. Scope: approved B.6 review (`PHASE6B_STEP6_B6_SCOPE_REVIEW.md`), items B6.1–B6.9 only.

**Global constraints**: 0/8 model files · no engine/confidence/threshold/backtest changes ·
LIVE/STALE/PARTIAL/DATA UNAVAILABLE/SYSTEM DEGRADED semantics preserved · ops/observational only.

---

## B6.1 Thread-safe production timeouts (2.5, 10.7)

**Current state**: `ENDPOINT_TIMEOUTS` (`api_server.py:67-93`) + SIGALRM arming
(`106-114`) is skipped in gthread worker threads (B.5 `8a7a625`), so enforcement is
dead in prod; only gunicorn `--timeout 90` bounds a hung request. Blemishes: `signal.alarm(0)`
in `after_request` (`:121`) runs in worker threads (harmless no-op, but unguarded), and a
dead duplicate metrics block sits after `return` (`:147-164`); `duration_ms` at `:129` is
negated (`start - now`).

**Change**:
1. `ops/systemd/tradingai-api.service`: `worker-class gthread -w 3 --threads 2` →
   `--worker-class sync -w 3` (drop `--threads`). Rationale: SIGALRM (the only true
   in-Python interruption) works only on the main thread; sync workers each serve on
   their main thread, making `ENDPOINT_TIMEOUTS` реально enforced. Concurrency tradeoff
   is explicit and re-verified (acceptance below).
2. `api_server.py`: guard `signal.alarm(0)` with the same main-thread check; delete the
   dead block `:147-164`; fix sign at `:129` to `(now - start)`.
3. Defense in depth: pass explicit timeouts to upstream fetch calls on request-served
   paths (yfinance calls made while serving API requests), so the hang source is bounded
   even before the alarm fires. Values: ≤ `ENDPOINT_TIMEOUTS` entry for the calling endpoint.
4. Keep the `TimeoutError → 504` handler (`:167-170`) unchanged (envelope preserved).

**Files**: `ops/systemd/tradingai-api.service`, `backend/api_server.py`
(+ fetch call sites for upstream timeouts; list in implementation).

**Tests** (3): unit main-thread arming still works; slow endpoint forced past its timeout
returns 504 envelope; gunicorn unit asserts `sync` workers (config test).

**Acceptance**: B.4 G7 concurrency test re-run green; benchmark delta vs B.4 recorded
(any regression documented, not hidden); 504 envelope byte-shape unchanged.

## B6.2 Circuit-breaker wiring (6.1, 6.3)

**Current state**: `CircuitBreaker` (`circuit_breaker.py`, threshold 5 / recovery 60s,
`CircuitOpenError`, thread-safe) has zero production call sites; `monitor.record_external_failure`
/ `record_circuit_breaker_state` are called only by tests.

**Change**:
1. Module-level breakers in `data_fetcher_db.py`: `YF_BREAKER = CircuitBreaker("yfinance", 5, 60)`,
   `NSE_BREAKER = CircuitBreaker("nse_live", 5, 60)` (values from B6.8 config at runtime,
   constructor defaults as fallback).
2. Wrap inside `fetch_yf_ohlcv` (outside the existing retry, so one logical call = one
   breaker sample) and the NSE live-quote fetch path.
3. On `CircuitOpenError`, call sites fall through to the **existing** fallback chain
   (live→1m→1d, STALE/DATA UNAVAILABLE flags). **Caution (mandatory)**: an open breaker
   must never manufacture market data or analytical outputs; it transitions into the
   existing degradation states only. No new labels, no synthesized values.
4. Record every trip/sample via `monitor.record_circuit_breaker_state` /
   `record_external_failure` (already surfaced in `/api/metrics`).

**Files**: `backend/data_fetcher_db.py`, NSE fetch module, `backend/api_server.py` (fallthrough only — no new branches beyond try/except).

**Tests** (3): breaker opens after threshold and HALF_OPEN recovers; open breaker yields
STALE (not synthesized) response; `/api/metrics` shows breaker state.

**Acceptance**: forced-outage simulation → degradation labels unchanged in shape; recovery without restart.

## B6.3 Scheduled cleanup + DB size signal (7.3)

**Current state**: `ops/cleanup.sh` (retention from `config/instruments.json`) is unscheduled
(absent from `ops/crontab.txt` and the deploy cron block); no size signal in health.

**Change**:
1. `ops/crontab.txt` += `0 3 * * * /opt/tradingai/ops/cleanup.sh >> /opt/tradingai/logs/cleanup.log 2>&1`
   (self-heal crontab verify picks it up automatically). Mirror in `deploy-vm.sh` cron block.
2. `/api/health` += `db_size_mb` (from `PRAGMA page_count × page_size`, single cheap query)
   plus `db_size_note` when over 80% of a 4 GB advisory threshold. Advisory only — never blocks.

**Files**: `ops/crontab.txt`, `deploy-vm.sh`, `backend/api_server.py`.

**Tests** (2): crontab contains the cleanup line; health carries numeric `db_size_mb`.

## B6.4 Connection-close hardening (1.3 remainder)

**Current state**: hot paths use try/finally; regime/strategy builders still use raw
`conn.close()` with no try/finally — an exception before `close()` leaks a pool slot.

**Change**: inventory every `conn.close()` in `backend/` via grep; convert remaining raw
sites to try/finally (or pooled context). No query or logic changes.

**Files**: `backend/api_server.py` (+ any other backend file the inventory finds; model
files excluded — if a leak site lives in a model file, document and defer instead of touching it).

**Tests** (2): error-injection test proves no pool-slot leak on exception path; pool-exhaustion test still green.

## B6.5 sql_guard coverage (1.7, 8.7)

**Current state**: `assert_table_name` enforced at 2 sites; dynamic table names elsewhere
(`api_server.py:298,311,358,568`, `database.py:293`, `data_fetcher_db.py:1009-1015` plus the
B.5 `date_col` interpolation) unguarded. `ALLOWED_TABLES` lacks `market_outlooks`,
`market_snapshots` (tables the code legitimately queries).

**Change**: extend `ALLOWED_TABLES` with the legitimately queried tables only; call
`assert_table_name` (and a literal allow-map for `date_col`) at every dynamic-table site.
No query-semantics change; disallowed input raises before SQL is built.

**Files**: `backend/sql_guard.py`, call sites above.

**Tests** (2): disallowed table raises; all allow-listed tables pass (incl. `market_outlooks`).

## B6.6 Backup 24h + restore verification (11.5, 9.4)

**Current state**: self-heal checks `.db` then `.db.gz` (gzip integrity, 7-day threshold);
vm-backup runs daily 18:30; DB-restore path (`self-heal.sh:51-58`) is log-only.

**Change**:
1. `MAX_BACKUP_AGE_DAYS` 7 → 1 (backup is daily; >24h means a missed run).
2. Live-vs-backup row compare: `symbols` + `price_1d` counts on live DB vs uncompressed
   backup copy (stream to temp, never overwrite live); mismatch beyond 5% → `ALERT backup_diverged`.
3. Restore path: count key tables before/after restore, log both; restart API only if
   post-restore integrity passes.

**Files**: `ops/self-heal.sh` (threshold + compare + verify; restore stays opt-in as today).

**Tests** (3): 24h threshold present; diverged-row alert logic (content/behavior test);
restore verify ordering (integrity before restart).

## B6.7 Unified fetch health (3.10)

**Current state (defect)**: `_record_fetch_result` (`api_server.py:331-348`) writes
`success_count`/`consecutive_failures`/`last_error`/`WHERE source = ?` against the
`data_status` schema (`db_schema.py:325`), which has none of those columns — every call
rolls back silently. The fetcher-side `update_data_status` writes per-symbol rows. The
`/api/data_status` endpoint (`:1915-1919`) reads the symbol-grained table. Consecutive
failures are invisible.

**Change**: add migration for a new `fetch_health(source TEXT PK, success_count,
error_count, consecutive_failures, last_error, last_ok_at)` table; point
`_record_fetch_result` at it (same call signature); surface `consecutive_failures` per
source in `/api/data_status` response. `update_data_status` and existing columns untouched.

**Files**: `backend/db_schema.py` (migration), `backend/api_server.py`.

**Tests** (3): failure increments consecutive count; success resets; endpoint exposes it.

## B6.8 Central alert configuration (3.4)

**Current state**: thresholds hardcoded (`monitoring.py:100-101`, `alert.py:154-159` PCR values).

**Change**: new `config/alerting.json` holding current values verbatim (sustained-failures
10/60s, p95 5000ms/300s, freshness 30/60/1440, backup 24h, breaker 5/60s, PCR 0.65/1.30):
load once at startup in `api_server.py`, pass into `check_alerts(alert_rules)` (signature
already supports it); invalid/missing file → built-in defaults + warning log. Tuning
after this requires no code change. PCR values move to the file but are read by `alert.py`
with identical fallback defaults.

**Files**: `config/alerting.json` (new), `backend/api_server.py`, `backend/alert.py` (read-only wiring).

**Tests** (2): custom file overrides defaults; corrupt file falls back safely.

## B6.9 Liveness/readiness split + startup gate (3.5 rem, 9.6)

**Caution (mandatory, from scope approval)**: readiness must distinguish *process ready to
serve* from *market data valid and fresh*. A healthy process must never imply healthy data;
the data-quality protocol (`/api/health` overall/sources/deep_health) stays authoritative.

**Change**:
1. New `GET /api/ready` (limiter-exempt, uncached): returns 200 `{ready: true}` iff DB file
   exists + is readable AND pool not exhausted. It MUST NOT include freshness, overall
   data verdicts, or deep_health. Any data staleness → still 200 (process is ready; data
   health belongs to `/api/health`).
2. Deploy gate (`ops/health_gate.sh`): check `/api/ready` first (fast, 3 tries), then the
   existing `/api/health` gate. Self-heal keeps polling `/api/health` (data-aware).
3. Systemd: `ExecStartPost` calling the ready check with short retries is documented but
   NOT enabled (gunicorn master binds before workers boot; a blocking post-start check
   risks restart loops) — readiness enforced at deploy time instead. This decision is explicit.

**Files**: `backend/api_server.py`, `ops/health_gate.sh`.

**Tests** (3): ready 200 with empty/stale DB while `/api/health` degrades (the caution test);
ready 503 when DB file missing; gate script checks ready before health.

---

## Test & acceptance plan

- New tests: ~22 (counts above). Total target ≈ 468 green locally.
- Full VM deploy + suite on VM green; md5 tree-identity check as in B.5.
- B.4 G7 concurrency + benchmark comparison re-run (B6.1 worker-class change).
- Boundaries verified: `git diff` 0/8 model files vs `45f90fc`, `d4990e4`, `4b7260f`;
  data-quality label tests; backtest-equivalence test.

## Explicit non-goals (reaffirmed)

CSRF · staging VM · Sentry · second provider · request queuing · `_symbol_data` purity ·
B.7 parked items (extended stale-serving, error-schema completion, cache/pagination
remainder, fetcher retries, latency probe, deploy-log path) · any model/analytical change.

---

🛑 **STOP — Specification complete. No implementation authorized. Next: Authorization.**
