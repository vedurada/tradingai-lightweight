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
