# Phase 9 — Live Market Data Pipeline & Production Decision Readiness Audit

## 1. Deployment Architecture

| Component | Finding |
|---|---|
| Active `server_name` | `tradingai.in`, `www.tradingai.in` (443 + 80→443 redirect) |
| Active `root` | `/var/www/tradingai.in/html` — **EMPTY** (no index.html; all non-API routes 404/301) |
| API proxy | `location /api/` → `http://127.0.0.1:8000` (10s cache for 200s) |
| Upstream | `tradingai-api.service`: gunicorn `-w 2 --threads 2`, `WorkingDirectory=/opt/tradingai_new`, app `app.api.app:app` — serves the NEW project code |
| Gunicorn state | running, but unit is **disabled** (will not survive reboot); no `gunicorn.service` unit |
| nginx state | **inactive (dead) since Sat 2026-09-19 19:21 IST** — public site unreachable; left untouched per audit-only mandate |
| `/var/www/tradingai/html/` | does not exist — legacy, inactive, nothing to clean |
| `/opt/tradingai_new/` served? | NO — nginx root points at the empty webroot; new frontend in `/opt/tradingai_new/frontend/` is not deployed |
| Live project API | reachable only on localhost:8000 (verified `/api/health` 200, DB = `/opt/tradingai_new/database/tradingai.db`) |
| Cron | only `*/2 *` health-curl + restart guard; **no data-collector cron** — live data is fetched on demand by the API |
| Logs | `logs/` 256K, no runaway growth; `tradingai-logrotate` present |

Recommendations (not applied): enable `tradingai-api.service`, restart nginx,
deploy `/opt/tradingai_new/frontend/` to the webroot (backup first).

## 2. Data Source

yfinance (`^NSEI`, `^NSEBANK`), free, unchanged provider. Verified live in the
dry-run: Friday-close quotes returned with honest quote timestamps + ages
(NIFTY 23346.40, BANKNIFTY 56358.70 @ 2026-09-18T15:25+05:30, age ~41.8h on
Sunday morning). Hardened contract: quote `timestamp` is the quote time (was
wall-clock), `age_seconds` exposed, non-positive prices → UNAVAILABLE (never
0), `get_5m_candles` flags only fully-closed candles `is_complete` (was all
True) with IST +05:30 normalization. No paid provider introduced. No
collector daemon exists — documented limitation: quotes/candles are fetched
per API call (subject to yfinance rate limits); a persistent collector is
future work, not added here.

## 3. Candle Contract

Timestamp == candle OPEN (09:15 … 15:25 IST, 75/day — matches DB convention).
`completed(T) = floor_5m(T − 5min)`; no completed candle exists before 09:20.
The forming candle is never decision-eligible (`is_complete=False` from the
provider; LiveEngine derives completion from wall time independently).
Decisions use the completed candle's close — identical to the research
`entry = signal close × 0.995` convention, so economics match replay exactly.

## 4. Timestamp Contract

`Asia/Kolkata` everywhere: engine (`completed_candle_ts`, `session_state`),
provider normalization, DB rows (`+05:30`), API `now_ist`, frontend display
(`toLocaleTimeString en-IN/Asia/Kolkata`). Naive datetimes are interpreted as
IST, never server-local (tested). Qualification on the live path passes
explicit `trade_date` (completed-candle date) and `as_of` (completed
timestamp) — no `datetime.now().date()` lock keying, no global-latest lookup.

## 5. Freshness

`STALE_AFTER_MIN = 15`: during session, a completed candle older than 15 min,
or a dead feed (today's newest row older than 15 min → `FEED_STALE`), yields
`DATA STALE` with no trade object. Missing/empty feed → `NO DATA`. Stale is
never coerced to 0/neutral/bearish. API exposes `completed_candle`,
`completed_age_minutes`, `feed_newest`, `feed_gap_minutes`, `session`,
`reasons` so the frontend can explain the state.

## 6. Market Session

PREMARKET (< 09:15) → no decisions; LIVE (09:15–15:30, data present) →
gated evaluation; MARKET_CLOSED (after 15:30, weekends, no-data days) →
never trades. Verified by dry-run (Sunday → MARKET_CLOSED, zero writes) and
unit tests for each boundary.

## 7. Live Scenario Timing

Live path uses the Phase 8 `get_scenario_for_timestamp` + `qualify(...,
as_of=completed_ts)` exclusively — no divergent implementation, no
`latest_scenario` on any decision path (`get_active_scenario` retained only
for as-of-now research display). Proven by `test_live_scenario_lookup_scoped`
(scenario must pre-exist the decision ts) and the FULL-day live==replay loop.

## 8. Live/Replay Parity

`test_live_matches_replay_full_day`: 2026-09-16 NIFTY, every candle —
LiveEngine (dry-run) qualification == replay trace qualification, and the
selected trade (14:15, BREAKOUT, entry/stop/target) matches exactly.
`phase9_live_replay_parity.json` records per-candle MATCH rows.

## 9. Daily Lock

`MAX_QUALIFIED_TRADES_PER_DAY = 1`, keyed `(instrument, trade_date)`.
Live mode persists to `daily_trade_locks` (UNIQUE) so the lock is shared
across the 2 gunicorn workers; a new `sqlite3.IntegrityError` guard converts
a lost cross-worker race into `DAILY_TRADE_LIMIT_REACHED` instead of a 500.
NIFTY and BANKNIFTY locks verified independent. First signal wins; later
signals rejected with explicit reason.

## 10. Research Isolation

Dry-run + backtest + replay leave `(qualified_trades, paper_trades,
daily_trade_locks) == (0, 0, 0)`; mutation residue 0. Live writes occur only
through the gated live decision path.

## 11. Frontend/API

API: `/api/{NIFTY,BANKNIFTY}/{summary,decision}` return distinct states
(QUALIFIED / NO_TRADE / STALE / NO_DATA / PREMARKET / MARKET_CLOSED) with
reasons, session, freshness; unknown symbols keep quote passthrough.
Frontend (static HTML/CSS/vanilla JS, zero trading logic — display only):
status badge honors backend state, shows decision-as-of candle + age,
NO_TRADE reasons, entry/stop/target when qualified; split refresh (price
30s, decision 120s) so the 5m decision display stays stable. Design note:
each `/decision` view can consume the server daily lock (pre-existing
semantic, now documented) — a POST-to-qualify separation is recommended
future work, not changed here. Options panel stays "Options data
unavailable" — nothing fabricated; backtest documented as index-price
research, not executable options strategy.

## 12. VM Resource Usage

956 MB RAM (281 used, 521 avail), disk 41%, DB 10.5 MB, logs 256K.
Gunicorn 2 workers × 2 threads (~100 MB each RSS). No duplicate collectors,
no runaway processes. Stack unchanged (Python/SQLite/nginx/gunicorn/static).

## 13. Public Deployment

Direct verification: nginx down → `https://tradingai.in/` unreachable
(connection refused); webroot empty → even with nginx up there is no
frontend. **The public website is NOT serving `/opt/tradingai_new/`** (neither
frontend nor API). Localhost API serves the new code correctly. `index.html`,
`indices/*`, `backtest.html`, `methodology.html` exist only in
`/opt/tradingai_new/frontend/` (source of truth, not deployed).

## 14. Limitations

* No real options data (strikes/premiums/IV/OI/PCR/expiry/fills) — qualification
  is index-price based; backtest is not an executable options strategy.
* No transaction-cost model; live fills unvalidated.
* 39-session historical sample; non-Q3 regimes insufficiently validated.
* Live data is on-demand yfinance (rate-limit sensitive); no collector daemon.
* `tradingai-api.service` disabled; nginx down; webroot empty — ops issues
  documented, not modified in this audit.
* No live-profitability or future-win-probability claims. PIT research
  baseline stands: NIFTY 34 trades (31/2/1, total R 16.21), BANKNIFTY
  31 trades (28/2/1, total R 16.63).
