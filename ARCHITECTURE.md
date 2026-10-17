# TradingAI Architecture (live 2026-10-14)

Source of truth: /opt/tradingai on OCI VM. Deterministic CPR-trigger system, not LLM trading.

## Pipeline (live)

LiveEngine.evaluate(dry_run) in app/live/engine.py:
NSE-calendar session gate (MARKET_CLOSED/PREMARKET/WEEKEND/HOLIDAY) to
completed-candle freshness gate (STALE never tradable) to market state
(trend vs mean, VWAP side, 3-bar momentum, ATR band) to
QualificationEngine.qualify (app/core/qualification.py) to
decision view (app/decision/view.py: CPR from previous session only, gap, evidence codes).

QUALIFIED_TRADE requires ALL: session LIVE, fresh completed 5m candle,
scenario CONFIRMED = trend + VWAP side + momentum ALL aligned
(app/scenarios/engine.py; momentum alone never confirms),
credit-only strategy found, live price present, risk <=2pct AND RR >=1.5
(app/risk/engine.py), options valid, one trade per instrument per day (UNIQUE lock).

## Trigger book (shared by live, backtest page, paper logger)

File: app/research/cpr_trigger_engine.py. BEAR/BULL mirror:
- BEAR = bearish trend + below VWAP + negative momentum + first touch R2/R1/prev-high
  or close below BC, bearish gap => Bear Call Spread, SL entry x1.005, target x0.98.
- BULL = bullish trend + above VWAP + positive momentum + first touch S2/S1/prev-low
  or close above TC, bullish gap => Bull Put Spread, SL x0.995, target x1.02.
Bear checked first; within side first listed level wins.
Direction gate (2026-10-17): SHORT_ONLY=True suppresses ALL BULL signals, so only
BEAR is emitted (long side measured negative in-sample AND out-of-sample on both
instruments; see the SHORT_ONLY comment in cpr_trigger_engine.py). bull_trigger()
level math is unchanged for diagnostics/tests.
Weekday gate (2026-10-17, ENFORCED): SKIP_FRIDAY=True drops a BEAR signal whose
session is a Friday (first trigger wins, so the whole session is skipped;
bucket skip_friday). BULL is unaffected. Basis (BEAR book n=199): Fridays
40/47.5%/-0.359R/-14.3R vs non-Friday 159/73.6%/+0.359R/+57.1R, drag recent.
Promoted from the former SHADOW_SKIP_FRIDAY annotation, which is still emitted
as shadow=['SKIP_FRIDAY'] (today_state + live trade dict) for the record.
Fail-open on unknown dates. Monitored by scripts/shadow_friday.py (read-only;
exit 2 = persistent+recent drag). Revert: SKIP_FRIDAY and SHADOW_SKIP_FRIDAY False.
Entries next-open [09:20,15:10), opens-only exits, 15:10 EOD flat, weekly gate >=3 sessions
for aligned, decay NIFTY<30/BN<60/VIX 0.02, min-10-candle days.

## Components

- app/api/app.py — Flask, 30 routes (see API.md). Dry-run composer for decisions (zero writes).
  Only live-trade writer: POST /api/symbol/decision/claim. Removed 2026-09-28:
  POST /api/backtest/run (0 callers; use cpr-triggers). Intraday endpoint added Oct 2026:
  GET /api/symbol/intraday.
- app/live/engine.py — intrabar entry + plain variant (Oct 2026, uncommitted pre-push).
- app/decision/view.py — display fallback + intrabar wording (Oct 2026).
- app/market/ — provider.py (yfinance, 12s bounded fetch + 1 retry, 429 RATE_LIMITED),
  collector.py (today completed candles, UNIQUE dedupe), nse_calendar.py, cache.py,
  events_calendar.py (hand-encoded non-recurring events + rule-generated NSE
  monthly/weekly F&O expiry (Tuesday per NSE/FAOP/68747) and US payrolls, with
  an advisory event_risk overlay).
- app/decision/view.py — event-risk overlay (advisory 2026-10-17): event_risk /
  event_risk_level / event_confirmation_required / upcoming_events + EVENT_RISK_*
  reason codes. Never rewrites bias or the decision; never a gate.
- scripts/events_coverage_check.py — monthly cron guard that warns before the
  hand-encoded table (HAND_ENCODED_END) or recurring window (RECURRING_END)
  runs out; logs to logs/events_coverage.log.
- app/options/ — contract/cache/db/economics/engine/provider/strategy. NSE chain 403-blocked;
  spreads structure-only, CREDIT_ONLY gate on debit dispatch.
- app/paper_trade/, scripts/paper_confluence.py --topup — appends day outcome to paper_align,
  structure rows to paper_spreads. No live premiums so credit null.
- scripts/tg_alerts.py --watch — Telegram entry/exit only, once-per-trade dedupe, IST.
- scripts/build_alerts_page.py, build_replay.py, weekly_review.py, veto_score.py,
  veto_paper_book.py, mistake_guard.py.
- app/observability/, app/ai/explanation.py — downstream non-authoritative AI text only.

## Frontend (nginx root /opt/tradingai/frontend, .html no-store)

- / index: 3 cards (decision+quote+candles), decision/candles 300s, quote 60s.
- /indices/nifty.html, banknifty.html: bias pill, CPR strip, 5m chart + last-12 table.
- /backtest.html: POST cpr-triggers (plain|aligned) + paper merge newer-than-end.
- /paper.html, /alerts.html, /methodology.html, /signal-flow.html, /tools.html, /learn.html.
- /events.html — upcoming market events (RBI, Fed, CPI, Budget, expiry) + event risk;
  homepage card + nav link; reads GET /api/market/events.
- Fixed-loss page is static Strategy Builder (fixed-loss-calc.js/css removed 2026-10-07);
  /api/economics/calculate still exists but has no frontend consumer.

## Database (SQLite WAL, timeout=10, schema_version=2)

34 tables. Core: market_candles_5m (NIFTY/BANKNIFTY ~4462 each + VIX ~3185),
provider_cache (45s/90s TTL), instruments (3), trading_sessions, market_snapshots/levels,
volatility_snapshots, scenario_definitions/candidates/matches, trade_candidates,
qualified_trades + daily_trade_locks (UNIQUE), paper_align/paper_trigger/paper_pivot/
paper_spreads/paper_trades(+events), backtest_runs/decisions/trades/outcomes,
options_provider_cache, system_health, pipeline_runs, data_quality_events.

## Determinism / safety

AI cannot override entry/SL/target/risk/lock. Unknown symbols 404 UNKNOWN_INSTRUMENT.
STALE quote always data_status=STALE, never LIVE. Replay validated + LIMIT 500.
141 except-Exception sites (46 bare pass) — known silent-failure risk, see audit.
No auth on API (nginx rate-limit + Cloudflare only); bind localhost.
