# Phase 5.25 — Pre-Session Baseline

## Checks Performed (Read-Only)

| Check | Status | Evidence |
|-------|--------|----------|
| Service active | PASS | systemctl is-active → active |
| PID | 863268 | pgrep |
| HLC_ONLY_MODE in env | PASS | HLC_ONLY_MODE=true |
| API health | PASS | {"status":"LIVE","tables":44} |
| DB integrity | PASS | PRAGMA integrity_check → ok |
| paper_trades | 94 | SELECT COUNT |
| scalp_signals | 29 | SELECT COUNT |
| No broker execution | PASS | Code inspection |
| Logs clean | PASS | No errors |
| Market status | CLOSED | 22:17 IST Thursday |

## Target Session

Friday, 30 October 2026, 09:15 IST. Market hours: 09:15-15:30 IST.
