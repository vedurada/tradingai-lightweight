# TradingAI.in — Educational Indian Market Analytics (NIFTY / BANKNIFTY / VIX)

Live site: https://tradingai.in — Educational market analytics. Not investment advice.

TradingAI.in publishes daily rule-based market context for NIFTY, BANKNIFTY and INDIA_VIX:
price vs VWAP, prior-session Central Pivot Range (CPR), opening gap, regime, plus
Telegram entry/exit alerts, paper journal and historical CPR-trigger backtests.

## What it does (live)

1. Market context — completed 5-min candles only (NSE 09:15-15:30 IST), VWAP side,
   trend vs mean, 3-bar momentum, ATR band, gap direction.
2. CPR-trigger classification — BEAR = below VWAP + bearish trend + negative momentum
   + first touch of R2/R1/prev-high or close below BC; BULL = mirror with S2/S1/prev-low
   or close above TC. Bear checked first. Entries next-open [09:20,15:10), EOD flat 15:10.
3. Credit-only spreads — BEAR means Bear Call Spread (SL entry x1.005, target x0.98);
   BULL means Bull Put Spread (SL x0.995, target x1.02). Risk <=2pct AND RR >=1.5,
   one trade per instrument per day (UNIQUE lock).
4. Paper + alerts — scripts/paper_confluence.py topup (15:45 IST), Telegram bot to
   channel entry/exit only, archive frontend/alerts.html.
5. Learning — payoff / risk calculators, journal (browser-local), guides in frontend.

Deterministic engine makes decisions. No LLM generates trades. All outputs hypothetical,
for study. See methodology.html on site, ARCHITECTURE.md, API.md.

## Quick start (live code)

Install deps, run API with same flags as systemd, check health, fetch decisions,
run tests with pytest. See DEPLOYMENT.md for systemd/nginx/cron.

- pip install -r requirements.txt
- gunicorn -w 2 --threads 4 --worker-class gthread --bind 127.0.0.1:8000 --timeout 90 app.api.app:app
- curl http://127.0.0.1:8000/api/health
- curl http://127.0.0.1:8000/api/decision/NIFTY
- curl http://127.0.0.1:8000/api/quote/BANKNIFTY
- python3 -m pytest tests/ -q

## Architecture

yfinance 5m to completed-candle gate to market state to QualificationEngine
to CPR trigger book (app/research/cpr_trigger_engine.py) to risk (<=2pct, RR>=1.5)
to daily lock to decision view to Telegram / paper / frontend.

See ARCHITECTURE.md. Removed 2026-09-28: POST /api/backtest/run (use POST /api/backtest/cpr-triggers).

## Project structure (/opt/tradingai)

- app/api/ — Flask (app.py + e2_economics blueprint, 30 routes)
- app/live/engine.py — session gate, freshness, market state
- app/core/qualification.py, app/decision/view.py — qualify + display contracts
- app/scenarios/, app/strategies/, app/risk/ — CONFIRMED rule, credit-only, risk caps
- app/research/cpr_trigger_engine.py, backtest.py — live book + research approximation
- app/market/ — provider (12s fetch, 1 retry), collector, nse_calendar
- scripts/ — paper_confluence.py, tg_alerts.py, build_alerts_page.py, weekly_review.py
- frontend/ — static HTML (index, indices/nifty.html, banknifty.html, backtest.html,
  paper.html, alerts.html, methodology.html, learn guides), nginx root
- config/ — instruments.json, settings.json, strategies.json, data_sources.json
- tests/ — 32 files, pytest (see DEPLOYMENT.md for slow/stale notes 2026-10-13)
- database/tradingai.db — SQLite WAL (market_candles_5m, paper tables, backtest, locks)

## Pages

- Home (3 outlook cards): /index.html
- NIFTY / BANKNIFTY dashboards: /indices/nifty.html, /indices/banknifty.html
- Intraday dashboards: /nifty-intraday-dashboard.html, /banknifty-intraday-dashboard.html
- Backtest (CPR triggers): /backtest.html
- Paper journal: /paper.html
- Alerts archive: /alerts.html
- Methodology / Signal flow: /methodology.html, /signal-flow.html
- Tools / Learn: /tools.html, /learn.html

## Data

- Market: yfinance NIFTY/BANKNIFTY/INDIA_VIX, 5m completed only, quote TTL 45s, candles 90s.
- Options: NSE chain blocked (403) — spreads structure-only, credit null, CREDIT_ONLY gate.
- Time: Asia/Kolkata IST for display; NSE calendar gates LIVE/PREMARKET/CLOSED.
- Costs: 0.10R/trade estimate as net_R in API payload only, never displayed.

## Operations

- systemd: tradingai-api.service (gunicorn 2x4 gthread), tradingai-market-data.timer (5m),
  tradingai-watchdog.timer (2m). nginx to 127.0.0.1:8000, 60r/m limit, Cloudflare only.
- Cron: paper topup weekdays 15:45 IST; tg_alerts watch every 5m 09-15 Mon-Fri;
  weekly_review Sun 08:30.
- Backups: /home/ubuntu/backups/ + /opt/tradingai_backups/, freeze tarballs + sha.

## Limitations / disclosure

Educational only. No live premiums, single VM (SPOF), JS-rendered pages, September samples
small/regime-specific, paper approx 60pct win is structure/spot-R not realizable P&L.
Past/hypothetical does not predict future. See disclaimer.html, docs/audit-2026-10-13.md.
