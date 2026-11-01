# Phase 5 — Preflight Verification (Read-Only)

Date: **2026-10-31 15:33 IST**
Script: `/opt/tradingai/scripts/phase5_audit.py`
Scope: read-only inspection and isolated `/tmp` tests. No November 2–6 data was created; no final report was generated.

## Script hash

| item | value |
|---|---|
| expected SHA-256 | `5f0f5f4136fea2d4fd48ee3137924b7e1be07213b510edddbbaa898a68dac62a` |
| actual SHA-256 | `5f0f5f4136fea2d4fd48ee3137924b7e1be07213b510edddbbaa898a68dac62a` |
| result | **PASS** — matches; hash unchanged before and after tests |

## Check results

| # | check | result |
|---|---|---|
| 1 | Script SHA-256 matches expected | **PASS** |
| 2 | All database connections use SQLite read-only mode | **PASS** |
| 3 | Daily pre/post snapshots are date-specific and cannot overwrite each other | **PASS** |
| 4 | Missing pre/post snapshots reported as incomplete, not zero activity | **PASS** (with presentation weakness) |
| 5 | Zero signals distinguishable from missing/failed collection | **FAIL** |
| 6 | Duplicate execution is safe and does not silently replace evidence | **FAIL** |
| 7 | Daily reports identify dry-run versus live evidence | **PASS** |
| 8 | Final-report date guard blocks before 2026-11-07 | **PASS** |
| 9 | Final report refuses when required daily live JSON is missing | **PASS** |
| 10 | LATE_PROPOSAL is not counted as LIVE_CAPTURE | **PASS** |
| 11 | Timestamps interpreted consistently in IST | **PASS** |
| 12 | Script does not start/stop/restart/reconfigure services | **PASS** |

## Evidence by check

### 1. Hash — PASS
`sha256sum` returned the expected value both before and after the tests. The backup copy at `/opt/tradingai/backups/phase5-audit-20261031-1529/hash.txt` also records the same value. The script was not modified.

### 2. Read-only database access — PASS
All four `sqlite3.connect` calls use `file:{DB_PATH}?mode=ro`:

```text
75:  c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
99:  c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
114: c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
126: c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
```

No `INSERT/UPDATE/DELETE/DROP/REPLACE` executes in the tool. The only write SQL string in the file is inside the static read-only auditor’s allowlist (`UPDATE ... WHERE 0`), not an executed query.

### 3. Date-specific snapshots — PASS
Commands with `--date 2026-11-02 --snapshot pre|post` produced distinct files:

```text
phase5_counts_20261102_pre.json
phase5_counts_20261102_post.json
```

The date and label are both in the filename, so a pre snapshot and post snapshot for the same date cannot overwrite each other. Same-label rerun behavior is a separate failure under check 6.

### 4. Missing snapshots — PASS, with weakness
A daily run with no snapshots printed:

```text
- Pre-session snapshot: `null`
- Post-session snapshot: `null`
```

Missing snapshots are represented as `null`, not as zero counts. Weakness: there is no explicit `COMPLETE`/`INCOMPLETE` field, and a zero-eligible day prints `LIVE_CAPTURE: 0 (None%)`.

### 5. Zero signals vs missing/failed collection — FAIL
Missing collection is silently treated as empty collection:

- `read_jsonl()` returns `[]` when the events or probe file is absent.
- `cmd_day()` does not validate that the events/probe sources exist, are readable, or cover the session.
- The report has no `source_status`, `events_present`, `probe_present`, or `collection_complete` field.

Test: running 2026-10-30 with deliberately absent events and probe paths produced:

```text
signals 20, eligible 20, live_capture 0, late_proposals 0, traded 10, expired 10
has_source_status False
```

A genuine zero-signal date (2026-11-01) produced `signals 0` with the same absence of source-status metadata. A reader cannot distinguish “no signals” from “shadow/probe evidence missing”.

### 6. Duplicate execution — FAIL
Partial protection exists, but evidence can still be silently replaced:

- Daily report with an existing `.md` was refused: `exit=3`, message `REFUSED: ... exists; use --force to overwrite`.
- Snapshot rerun silently overwrote the same file: hash changed `93b88dfe…` → `d7dce08a…`, mtime changed 15:32:44 → 15:32:46, despite unchanged counts (the `captured_at` field changed).
- If the `.md` is absent but the `.json` exists, the live daily run silently overwrote the JSON: hash `34a076f6…` → `b1cfd9a3…`, `exit=0`.
- Dry-run outputs (`*_DRYRUN.md/.json`) are overwritten without a guard.

### 7. Dry-run versus live — PASS
Daily filenames use a `_DRYRUN` suffix for dry runs. Markdown headers state either:

```text
**DRY RUN — historical/backfill only; NOT live evidence.**
**LIVE SESSION EVIDENCE.**
```

JSON includes `"mode": "DRY_RUN"` or `"mode": "LIVE"`.

### 8. Final date guard — PASS
On 2026-10-31:

```text
REFUSED: final report may only be generated after the 2026-11-06 session
exit=2
```

No final file was created.

### 9. Missing daily JSON — PASS
With the clock isolated to 2026-11-07 and an empty output directory:

```text
REFUSED: missing live daily JSON for 2026-11-02, 2026-11-03, 2026-11-04, 2026-11-05, 2026-11-06
rc 2
```

### 10. LATE_PROPOSAL handling — PASS
Using the 2026-10-30 sandbox replay events only as calculation input:

```text
live_capture 0, live_capture_pct 0.0, late_proposals 10
classification_counts {"LATE_PROPOSAL": 10, "TRADED": 10}
```

`live_capture` is set only when `classification == "LIVE_CAPTURE"`. Historical replay was not treated as live evidence.

### 11. IST consistency — PASS
```text
2026-11-02T10:00:00          -> 2026-11-02T10:00:00+05:30 (offset 5:30:00)
2026-11-02T10:00:00+00:00    -> 2026-11-02T10:00:00+00:00 (offset 0:00:00)
2026-11-02T10:00:00+05:30    -> 2026-11-02T10:00:00+05:30 (offset 5:30:00)
```
Naive timestamps are assigned IST; explicit offsets are preserved. Minor weakness: event ordering uses lexical ISO strings, which assumes a uniform `+05:30` offset.

### 12. No service operations — PASS
`subprocess.run` is used only for `systemctl show` and `journalctl`. There are no `start`, `stop`, `restart`, `enable`, or `disable` calls. Service PIDs and restart counts were unchanged by every test.

## Weaknesses requiring correction (not fixed)

1. **Missing/failed collection is silent (check 5).** Add explicit source existence/readability checks and a `collection_complete` status. Live reports should refuse or mark gates `NOT_EVALUATED` when events/probe sources are missing for the session.
2. **Silent evidence replacement (check 6).** Guard the daily `.json` as well as the `.md`, require `--force` for any live rerun, and protect snapshots from same-label overwrite. Consider run-ID or immutable snapshot names.
3. **No explicit snapshot completeness label (check 4).** `null` is used, but reports do not print `INCOMPLETE`; zero-eligible days also print `None%`.
4. **Read-only gate freshness.** The gate trusts `/opt/tradingai/logs/data_probe/selftest.json` without checking its age or binding it to the current script hash.
5. **Lexical event ordering.** Safe while all producers use IST ISO strings; would misorder mixed-offset timestamps.
6. **Production execution-attempt timestamp** is not signal-linked in logs, so the report uses the shadow attempt and labels it as such.
7. **Manual snapshots.** Pre/post snapshots and daily reports are manual; no timer was added.

## Production unchanged

- Script hash unchanged: `5f0f5f41…ac62a`.
- Database: 49 signals / 104 trades / 17,161 5m candles; integrity `ok`.
- Services unchanged and running:
  - `tradingai-paper-scalp-live` PID 1085625, `NRestarts=0`
  - `tradingai-entry-shadow` PID 1086807, `NRestarts=0`
  - `tradingai-data-probe` PID 1086258, `NRestarts=0`
- Production Phase 5 pre-session snapshot unchanged: `phase5_counts_20261102_pre.json` hash `d216f2a4…a5e57`.
- No production services, timers, database schema, trading logic, Nginx, or existing reports were modified.
- All test files were written under `/tmp/pf_test` and removed. No test rows were written to the production database.

## Preflight conclusion

**Not ready for unattended Phase 5 gate reporting** until checks 5 and 6 are corrected. Data collection by the existing probe and entry shadow can continue unchanged. No fallback was enabled and no production behavior was changed.
