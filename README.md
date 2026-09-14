# TradingAI.in — Lightweight Production Tree

AI market intelligence site (NSE/BSE indices, stocks, options) served at
https://tradingai.in from a single VM (Gunicorn + Flask + SQLite + nginx).

## Layout

- `backend/` — API (`api_server.py`), model layer (`regime.py`, `strategies.py`,
  `outlook.py`, `scenarios.py`, `options.py`, `ai_outlook.py`, `backtest.py`,
  `indicators.py`), fetchers, ops helpers
- `tests/` — 483-test suite (`test_phase6b_*.py`, `test_phase7_track_a.py`)
- `ops/` — systemd unit, nginx config + security snippet, self-heal watchdog,
  backup/restore, crontab, logrotate, runbooks (`DEPLOYMENT.md`, `RESTORE.md`, `KEY_MANAGEMENT.md`)
- `config/` — instruments, settings, alert thresholds (`alerting.json`)
- `static/`, `*.html`, `stocks/`, `indices/`, `learn/` … — served web content
- `deploy-vm.sh` — canonical deploy path (rsync + migrate + restart + health gate)
- `scripts/` — benchmarks; `verify_*.py` — gate checkers
- `PHASE*.md` — full audit/spec/review/freeze trail (authoritative governance record)

## Development

Requirements: Python 3.9+ (prod runs 3.10), pip packages: `yfinance`, `flask>=3.0`,
`flask-cors`, `flask-limiter`, `gunicorn==23.0.0`, `pytest`.

```bash
python3 -m pytest tests/ -q          # full suite (must stay 483 green)
python3 backend/db_schema.py          # init/migrate local DB
cd backend && python3 api_server.py   # dev server (or gunicorn api_server:app)
./deploy-vm.sh                        # deploy to live VM (runs health gate)
```

## Governance (read before changing anything)

Frozen lineage: `45f90fc` (analytical baseline) → `d4990e4` (B.4) → `4b7260f` (B.5) →
`8c9faff` (B.6) → Phase 7 tracks (A authorized/implemented, B/C pending).

Hard boundaries:

- **0/8 model files ever modified** (`regime`, `strategies`, `outlook`, `scenarios`,
  `options`, `ai_outlook`, `backtest`, `indicators`) — verify with
  `git diff <freeze>..HEAD --name-only -- backend/<those files>` (must be empty)
- No engine / confidence / threshold / backtest-methodology changes
- LIVE / STALE / PARTIAL / DATA UNAVAILABLE / SYSTEM DEGRADED semantics preserved
- Workflow per phase: Scope Review → Approval → Specification → Authorization →
  Implementation → Acceptance → Independent Review → Freeze → STOP

Current state: Phase 7 Track A implemented (security hardening, pending independent
review); Tracks B/C not started. See `PHASE7_AUTHORIZATION.md` and
`PHASE7_TRACK_A_SPECIFICATION.md`.
