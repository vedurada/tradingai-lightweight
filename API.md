# TradingAI API (live 2026-10-14)

Base: http://127.0.0.1:8000/api (nginx /api proxy, 60r/m). Envelope varies by route;
health/quote/decision use state + timestamp + data. Unknown routes UNKNOWN_ROUTE.
Unknown symbols 404 UNKNOWN_INSTRUMENT.

## Health / market

- GET /api/health
- GET /api/quote/<INST> — latest 5m close, day-change vs prev daily close, STALE never as LIVE.
- GET /api/decision/<INST> — dry-run composer, zero writes.
- GET /api/<sym>/summary, GET /api/<sym>/decision (legacy aliases)
- GET /api/<sym>/candles?n<=80 — completed-only, n clamped.
- GET /api/<sym>/intraday — added Oct 2026 (uncommitted pre-push, see git log).
- GET /api/<sym>/paper-trade
- GET /api/market/holidays, GET /api/alerts/status
- GET /api/market/events — scheduled-events calendar (RBI MPC, US FOMC,
  Union Budget, CPI/WPI/GDP, US payrolls/CPI, NSE monthly + weekly F&O expiry)
  + advisory event-risk overlay per instrument. Query: instrument (optional,
  else all), days (default 90, capped 365). Unknown instrument 400
  UNKNOWN_INSTRUMENT. Non-recurring events are hand-encoded; NSE expiry
  (monthly = last Tuesday, weekly Nifty = every Tuesday, previous trading day
  on a holiday — per circular NSE/FAOP/68747) and US payrolls are rule-generated
  (no per-month maintenance). Read-only reference layer: never changes a trade,
  entry/stop/target or a gate. Response coverage block reports hand_encoded_end /
  recurring_end / last_verified.
  Also surfaced inside GET /api/decision/<INST> as event_risk / event_risk_level /
  event_confirmation_required / upcoming_events (+ EVENT_RISK_* reason codes).
  Source app/market/events_calendar.py; guard scripts/events_coverage_check.py
  (monthly cron); page /events.html.

## Trading (writes)

- POST /api/<sym>/decision/claim — ONLY live-trade writer (UNIQUE daily lock;
  loser of race gets daily-limit, never 500).

## Paper

- GET /api/paper/spreads, GET /api/paper/spread/today, GET /api/paper-trade
- Lifecycle scripts/paper_confluence.py --topup. Spreads credit null (NSE 403),
  CREDIT_ONLY gate. Costs 0.10R/trade as net_R API-only, never displayed.

## Backtest (live book)

- POST /api/backtest/cpr-triggers {instrument, variant plain|aligned, dates}
  (+ paper merge newer-than-end, today in missing_eod until 15:10)
- POST /api/backtest/cpr-walkforward
- GET /api/backtest/<run_id>, GET /api/backtest/validation/<run_id>
- Removed 2026-09-28: POST /api/backtest/run (research simulator approximation;
  signal-candle entries, NEUTRAL proxy, forced options_valid — do not mistake for live).

## Research / strategy / performance (kept, mostly unused by pages)

- GET /api/research/scenarios, /api/research/scenarios/<instrument>
- GET /api/research/performance, /api/research/baseline/<instrument>
- GET /api/research/trade/<instrument>/<date>
- GET /api/research/replay/<instrument>/<date>/<timestamp> (validated, LIMIT 500)
- GET /api/strategy/cpr-triggers, /api/strategy/cpr
- GET /api/performance/live, /api/performance/live/<instrument>
- GET /api/options/<instrument>, /api/options/strategy/<instrument> (dormant, NSE 403)

## Economics (orphaned UI)

- GET /api/economics/calculate (blueprint app/api/e2_economics.py) — still exists + tested,
  but frontend/fixed-loss-calc.js/css removed 2026-10-07; fixed-loss-options.html is static
  with no /api calls.

## Rate limits / errors

Per-route limits via flask-limiter + nginx. STALE handling, 400 on bad replay date/ts,
404 on unknown symbol. No auth (localhost bind + nginx/CF only) — do not expose
write endpoints broadly.
