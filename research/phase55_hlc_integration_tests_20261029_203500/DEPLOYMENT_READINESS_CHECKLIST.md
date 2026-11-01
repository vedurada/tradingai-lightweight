# Phase 5.5 — Deployment Readiness Checklist

## 1. Safe Handling of Dirty Working Tree

| Item | Status | Notes |
|------|--------|-------|
| Modified tracked files | 98 | Must commit or stash before consolidation |
| Untracked files | 214 | Must be committed or added to .gitignore |
| Total dirty files | 312 | Requires cleanup before any deployment |

**Recommendation:** Commit or stash all changes before proceeding with any migration.

## 2. SQLite Backup/Restore Validation

| Item | Status | Notes |
|------|--------|-------|
| Database integrity | OK | `PRAGMA integrity_check` → OK |
| WAL mode | Active | `PRAGMA journal_mode=WAL` |
| Backup method | SQLite `.backup` API | Recommended for consistency |
| Restore tested | NOT TESTED | No isolated test DB created |

## 3. Feature-Flag Design

| Item | Status | Notes |
|------|--------|-------|
| Feature flag designed | HLC_ONLY_MODE | Default: false (current behavior) |
| Location | Environment variable or config/settings.json | To be implemented |
| Effect when true | `_hlc_book_signal()` becomes default | `_cpr_book_signal()` disabled |
| Effect when false | Current behavior (CPR default) | Unchanged |
| Rollback | Set `HLC_ONLY_MODE=false` → restart gunicorn | Documented |

## 4. Single Authoritative Source for New Paper-Trade Decisions

| Item | Status | Notes |
|------|--------|-------|
| Sole creator | paper_scalp_live.py | Confirmed by code inspection |
| tg_alerts.py creates trades | No | Only alerts for existing trades |
| Duplicate prevention | Deterministic trade_id PK | Confirmed |

## 5. HLC Entry Validation and Stale-Data Rejection

| Item | Status | Notes |
|------|--------|-------|
| Signal uses 3 completed candles | VERIFIED (code review) | `_scan_signals()` iterates completed triples |
| Entry candle not required for signal detection | VERIFIED (code review) | Phase 3.5 added last-candle detection |
| Entry price from live provider | VERIFIED (code review) | `_get_entry_price_from_provider()` queries yfinance |
| Stale data rejected | VERIFIED (code review) | `validate_candle()` rejects stale (>20 min) candles |
| Entry-time guard | VERIFIED (code review) | `_entry_time_guard()` rejects expired signals |

## 6. Configurable Daily and Concurrent-Position Limits

| Item | Status | Notes |
|------|--------|-------|
| Concurrent-position limit | IMPLEMENTED | Mode C: one open position per instrument |
| Daily trade limit | NOT IMPLEMENTED | Needs `daily_trade_locks` integration |
| Configurable via settings | DESIGNED | `MAX_TRADES_PER_DAY` in settings.json |

## 7. Existing Open Trades Monitored During Mode Switch

| Item | Status | Notes |
|------|--------|-------|
| Monitor handles scalp branch | VERIFIED (code review) | `PaperTradeEngine.monitor()` handles scalp exits |
| Restart recovery | VERIFIED (code review) | `recover_open_positions()` checks DB |
| CPR trades remain monitored | VERIFIED (code review) | Monitor handles both scalp and CPR branches |

## 8. Idempotent Trade Creation and Restart Recovery

| Item | Status | Notes |
|------|--------|-------|
| Deterministic trade_id | VERIFIED (code review) | SHA-1 of link_key |
| trade_id is PRIMARY KEY | VERIFIED | schema.sql:81 |
| Restart recovery | VERIFIED (code review) | `recover_open_positions()` + `recover_new_signals()` |
| Signal UNIQUE constraint | VERIFIED | `scalp_signal_store.py:13` |

## 9. API/Dashboard Compatibility

| Item | Status | Notes |
|------|--------|-------|
| Gunicorn running | VERIFIED (runtime) | 3 workers |
| `/api/strategy/scalp` returns data | VERIFIED (runtime) | Returns HLC signal state |
| `/api/decision` returns data | VERIFIED (runtime) | Returns CPR decision with HLC overlay |
| `/api/paper/scalp` returns data | VERIFIED (runtime) | Returns HLC paper trades |

## 10. Telegram Notification Behavior

| Item | Status | Notes |
|------|--------|-------|
| tg_alerts scheduled | VERIFIED (cron) | `* 9-15 * * 1-5` runs `--watch` |
| tg_alerts creates trades | NO | Only alerts for existing trades |
| Dedup via fired key | VERIFIED (code review) | `tg_alerts.py:399` |
| Alerts tied to persisted trades | VERIFIED (runtime) | 141 alerts in archive, all delivered |

## 11. Systemd Service Design for HLC Paper-Trade Process

| Item | Status | Notes |
|------|--------|-------|
| systemd unit exists | NO | No unit for paper_scalp_live.py |
| Process runs as background | YES | PID 806096, started manually |
| Restart on failure | NO | No Restart=always configured |
| Log files | YES | paper_scalp_live.out, paper_scalp_live.log |

**Recommendation:** Create a systemd unit similar to `tradingai-paper-scalp-live.service` (already exists in /etc/systemd/system/ but not enabled).

## 12. Rollback Rehearsal Using Isolated Config/Test Data

| Item | Status | Notes |
|------|--------|-------|
| Rollback procedure documented | YES | MIGRATION_AND_ROLLBACK_PLAN.md |
| Rollback tested | NOT PERFORMED | No isolated test environment created |
| Backup verified | NOT VERIFIED | No backup created during this phase |

## 13. Separation Between Deploying HLC Decisions and Retiring CPR

| Item | Status | Notes |
|------|--------|-------|
| HLC deploy vs CPR retire separated | DOCUMENTED | Migration plan separates these concerns |
| CPR retained for rollback | YES | `_cpr_book_signal()` retained in live/engine.py |
| CPR API endpoints retained | YES | `/api/backtest/cpr-triggers`, `/api/strategy/cpr` |
| CPR cron jobs retained | YES | paper_confluence.py, signal_articles.py, veto_paper_book.py |
