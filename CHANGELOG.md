# CHANGELOG

## Unreleased — Phase 1 (In Progress)

### Added
- Database migration framework (`backend/migration.py`)
- Backup system (`scripts/backup.sh`) with timestamp, retention, verification
- Deployment scripts (`scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/health_check.sh`, `scripts/test.sh`)
- Data quality validator (`backend/data_validator.py`)
- AI output validator (`backend/ai_validator.py`)
- Health check endpoint with HEALTHY/DEGRADED/UNHEALTHY status
- Trade event data contract (`docs/trade_event_contract.md`)
- User feedback data contract (`docs/user_feedback_contract.md`)
- Personal learning architecture (`docs/learning_architecture.md`)
- ROADMAP.md
- Log rotation configuration
- .gitignore updates for backups, logs, runtime data

### Fixed
- GROQ API key permissions: 644 → 600
- Log directory missing: created `/opt/tradingai/logs/`
- Market endpoint data_quality: PARTIAL → GOOD mapping
- Database populated via data_fetcher_db.py

### Security
- `/etc/tradingai/groq.env` mode 600 (was 644)
- Secrets excluded from Git via .gitignore
- API error responses do not expose internals

## 0.2.0 — Phase 0 Audit Complete
### Added
- `docs/AUDIT_REPORT.md` — Full production audit with WORKING/PARTIAL/BROKEN/MISSING/UNKNOWN classification
- `AGENTS.md` — Project context for OpenCode agents
- Live price loader (yfinance fallback for all sections)
- AI Outlook dashboard render call
- Market Snapshot cards with live prices and trend words
- Advance/Decline 3-column summary
- LIVE MARKET TICKER section
- All section headings standardized to ALL CAPS

### Fixed
- AI Outlook dashboard was empty (renderOutlookDashboard never called)
- Prices displayed "—" (live loader with yfinance fallback added)
- Layout matched mockup exactly (34/34 structural checks pass)

## 0.1.0 — Initial Release
### Added
- Core market intelligence platform
- NIFTY, BANKNIFTY, FINNIFTY, SENSEX data
- AI Outlook dashboard (11 sections)
- Options intelligence
- Market snapshot, advance/decline
- Educational content and risk disclosure
- API server (Flask + Gunicorn)
- Nginx reverse proxy with security headers
- Systemd service configuration
- Cron-based data pipeline
