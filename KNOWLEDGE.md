# TradingAI.in — Project Knowledge

> Living document. Update it whenever architecture, rules, or roadmap change.
> Last updated: 2026-09-10.

## 1. What this is

**TradingAI.in is an AI-assisted trading system** (not an auto-trader, not a Yahoo clone).
Pipeline: market data → indicators → regime engine → AI outlook → human trader decides.
- **Indexes (NIFTY, BANKNIFTY, FINNIFTY, SENSEX):** option strategies (spreads, condors, intraday).
- **Stocks (all caps):** simple **BUY / HOLD / EXIT** outlook with numeric targets — never option spreads.
- **P&L:** daily index paper trades, entry 9:30 AM IST, exit 3:20 PM IST, direction-aware.

## 2. Environment

| Item | Value |
|---|---|
| VM | 129.159.224.81, Ubuntu 22.04, 1 CPU / 1 GB RAM, TZ Asia/Kolkata |
| SSH | `ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81` |
| Repo | https://github.com/vedurada/tradingai-lightweight |
| Local dir | `/Users/satya/remove_workspace/tradingai-lightweight` |
| VM app dir | `/opt/tradingai` (repo rsync target) |
| VM web root | `/var/www/tradingai.in/html` (nginx serves this, NOT /opt) |
| DB | `/opt/tradingai/database/tradingai.db` (SQLite, WAL off, single writer) |
| API | Flask `backend/api_server.py` on `127.0.0.1:8000` as systemd unit `tradingai-api` (`Restart=always`, unit in `ops/systemd/`), proxied at `/api/` by nginx; 2-min curl watchdog restarts on hang |
| Site | https://tradingai.in (real Let's Encrypt cert since 2026-09-10, auto-renew via certbot timer; HTTP 301 → HTTPS; earlier self-signed cert caused browser warnings) |
| Market hours | 9:30–15:30 IST, Mon–Fri. Cron uses `9-15` hour field as approximation |

## 3. Architecture (database-first, layered)

```
yfinance (only external source today)
   ↓  every minute, tiered
Raw Market Database (SQLite: price_1m/5m/15m/1d, vix_data, option_chain, fundamentals, news, corporate_actions)
   ↓
Indicators (computed locally: EMA/SMA/VWAP/RSI/MACD/ADX/ATR/Bollinger/Pivot/CPR/S-R) + Regime + Scenarios
   ↓
Strategy layer (index option spreads | stock BUY/HOLD/EXIT) + AI outlook (rule-based)
   ↓
Flask API :8000 → nginx /api/ → static HTML + vanilla JS (30s auto-refresh, no market-hours gate)
```

Legacy JSON pipeline (`generate_data.py`, `generate_json.py` → `data/*.json`) is **deprecated but still deployed**; no cron calls it. Frontend reads **only** `/api/*`.

## 4. Instrument universe (all verified against yfinance)

- **Indexes:** NIFTY (`^NSEI`), BANKNIFTY (`^NSEBANK`), FINNIFTY (`^CNXFIN`), SENSEX (`^BSESN`)
- **Volatility:** India VIX (`^INDIAVIX` — was wrongly `^VIX`/US VIX before Sep 2026 fix)
- **ETFs:** NIFTYBEES.NS, BANKBEES.NS, JUNIORBEES.NS (price-only, no screens)
- **Stocks (39):** 24 LARGE + 10 MID + 5 SMALL, each with `cap` + `sector` in `config/instruments.json`
  - LARGE: RELIANCE, HDFCBANK, ICICIBANK, SBIN, INFY, TCS, LT, AXISBANK, ADANIENT, BHARTIARTL, WIPRO, HCLTECH, TECHM, MARUTI, ITC, KOTAKBANK, BAJFINANCE, SUNPHARMA, TITAN, ULTRACEMCO, POWERGRID, NTPC, ONGC, COALINDIA
  - MID: PERSISTENT, COFORGE, MPHASIS, DIXON, CUMMINSIND, MAXHEALTH, LUPIN, VOLTAS, GODREJPROP, ASTRAL
  - SMALL: KPITTECH, TANLA, KPRMILL, RADICO, CCL
- Config-driven: fetcher derives all lists from `config/instruments.json` (no hardcoded symbol lists).

## 5. Backend modules (`backend/`)

| File | Role |
|---|---|
| `data_fetcher_db.py` | Tiered every-minute fetcher; writes everything to DB |
| `api_server.py` | Flask API, legacy-compatible shapes for the pages |
| `db_schema.py` | Full SCHEMA + `init_database()` with ALTER migrations (never DROP) |
| `database.py` | Legacy `Database` class (history CRUD, archive, portfolio) |
| `fetch_market.py` | `MarketFetcher`: quote/OHLCV/VIX/options with TTL cache |
| `indicators.py` | Local indicator math (fixed S/R swap bug Sep 2026) |
| `regime.py` | TRENDING_BULLISH/BEARISH, RANGE_BOUND, HIGH_VOLATILITY scoring |
| `scenarios.py` | Returns **dict** `{bullish, bearish, range, breakout, reversal}` (not a list) |
| `strategies.py` | `INDEX_SYMBOLS={NIFTY,BANKNIFTY,SENSEX,FINNIFTY}` → option spreads; everything else → `select_stock_outlook()` BUY/HOLD/EXIT with numeric T1/T2/stop from S/R+ATR |
| `ai_outlook.py` | Rule-based outlook (LLM providers removed after 401s); full JSON stored in `ai_outlooks.outlook` |
| `expiry.py` | Per-index expiry rules (NSE=Tuesday, BSE=Thursday; weeklies only NIFTY/SENSEX) |
| `pnl_tracker.py` | `lock` (9:30) / `close` (15:20) / `backfill [date]` / `archive [days]` |
| `bhavcopy.py` | NSE official EOD (`ind_close_all`, incl. index P/E) into `price_1d` — `backfill [days]` / `daily` (18:35 cron) / `holidays` (weekly → `nse_holidays`, auto-used by expiry engine) |
| `monitor.py` / `alert.py` | Health checks / alerts via cron |
| `generate_data.py` / `generate_json.py` | LEGACY JSON pipeline (deprecated; weekly archive inside it disabled) |
| `history_logger.py`, `backtest.py`, `options.py` | Legacy/helpers; backtest not wired to UI |

## 6. Database tables (SQLite)

Prices: `symbols`, `price_1m`, `price_5m`, `price_15m`, `price_1d`, `vix_data`, `etf_data`.
Derivatives: `option_expiries`, `option_chain` (usually empty — Yahoo has no NSE options).
Computed: `indicators` (+`support_resistance` JSON col), `market_regime`, `scenarios`, `strategies` (primary flattened; full list JSON inside `legs`), `ai_outlooks` (full JSON in `outlook`), `signals`, `market_breadth`, `sector_data`, `market_snapshots`.
Company: `fundamentals` (merged info + analyst views + statements JSON), `news`, `corporate_actions` (DIVIDEND/SPLIT), `earnings` via fundamentals.
P&L: `history` (+`entry_time`/`exit_time`/`direction`), `history_archive`, `portfolio` (schema only, unused).
Ops: `data_status`, `alerts`.

## 7. Fetcher tiers (`data_fetcher_db.py::fetch_all`, cron `* 9-15 * * 1-5`)

- **Every run:** indices 1m + screens, India VIX 1m, ETF prices, LARGE-cap 1m + screens.
- **Every 5th minute:** MID-cap 1m + screens, NIFTY/BANKNIFTY option chains, breadth.
- **Every 15th minute:** SMALL-cap 1m + screens, info + news/actions/analyst merged into fundamentals (indices+LARGE).
- **Weekly (Mon 9:xx):** MID/SMALL extras + LARGE financial statements.
- Daily candles cached in `price_1d` (DB-first, not re-fetched per symbol).
- Retention cleanup per run: price_1m 2d, options 3d, fundamentals 7d, news 30d.

## 8. Strategy doctrine

- **Indexes only:** Bull/Bear spreads, Iron Condor, defined-risk premium selling, ND intraday straddle/strangle (NIFTY + BANKNIFTY, VIX-gated, 9:30 entry / 3:20 exit).
- **Stocks/ETFs:** BUY/HOLD/EXIT via `select_stock_outlook()` — regime first, VWAP+RSI fallback. Numeric levels from `_stock_levels()`: T1 = nearest resistance (else +8%/2×ATR), T2 (+12%/3×ATR), stop = support (else −5%/1.5×ATR), with upside/risk/RR percentages embedded in text fields.
- `strategies.legs` holds `{"legs": [...], "all_strategies": [...]}`; API rebuilds legacy `{strategies: [...]}`.

## 8b. Stock investment views (`backend/investment.py`, table `investment_views`)

Stocks are investments, not intraday signals: SHORT horizon (weeks: SMA20/50 + RSI + 20d return → BUY/HOLD/EXIT with swing target/stop) and LONG horizon (months: SMA200 + 52w position + P/E + analyst upside + dividend → ACCUMULATE/HOLD/AVOID + fair value). Computed from `price_1d` + stored fundamentals (zero extra Yahoo calls), stored per (symbol, date, horizon). API: `/api/investment/<sym>` + `investment` block in symbol payloads; scanner shows long-term badge.

## 9. P&L tracker (`pnl_tracker.py`)

- `lock` 9:30 IST (cron `30 9 * * 1-5`): 09:30-candle entry + strategy/regime/bias snapshot. Direction from bias: BEARISH→SHORT else LONG.
- `close` 15:20 IST (cron `20 15 * * 1-5`): strict 15:20-candle exit (fallback: last candle). **SHORT: points = entry − exit**; LONG: exit − entry. WIN/LOSS/FLAT.
- `backfill [date]`: rebuild any day from stored 1m candles.
- `archive [days]` (default 365): monthly cron `0 2 1 * *` moves settled rows older than a year to `history_archive`.
- Retention: 1 year live. `/api/history` merges both tables, default 365 days, grouped `{SYM: [...]}`.
- History page columns: Date | Symbol | Outlook(BUY/SELL) | Direction(LONG/SHORT) | Entry Time/Price | Exit Time/Price | Points(±, green/red) | Result | Strategy + summary bar + symbol filters.


- Live NSE data (verified 2026-09-10): `option-chain-contract-info` gives authoritative expiry dates per symbol, stored in `option_expiries` by the 9 AM daily refresh; API prefers these over weekday math (payload `source: NSE`).
- Live NSE lot sizes from `fo_mktlots.csv` into `symbols.lot_size` (NIFTY 65 / BANKNIFTY 30 / FINNIFTY 60, source=NSE; SENSEX 20 source=config until a BSE file is found). Refresh writes only on change; Builder reads live lots from the API.

## 10. Expiry rules (`expiry.py`)

- NSE=Tuesday, BSE=Thursday (SEBI 1-Sep-2025; NSE circular FAOP/68747).
- NIFTY: weekly every Tue + monthly last Tue. SENSEX: weekly every Thu + monthly last Thu.
- BANKNIFTY/FINNIFTY: **monthly-only**, last Tuesday (weeklies discontinued Nov 2024).
- Post-15:30 IST on expiry day rolls to next; holidays in `HOLIDAYS_IST` shift to previous trading day (extend every January from NSE/BSE circulars).
- API `_symbol_data[].expiry` = `{..., tenor, weekly:{...}|None, monthly:{...}}`; index pages show both.

## 11. API (`/api/*`, Flask :8000)

Health, symbols, price[s], vix(+history), indicators, regime(s), strategy/strategies, scenarios, outlook(s), options(+expiries), breadth(+history), snapshot(s), fundamentals, company (analyst views/financial flags), news(+per-symbol), actions (dividends/splits), market (legacy `{instruments:{...}}`), history (grouped, 365d), etf, data_status. Generic `/api/<symbol>` (case-insensitive) serves any symbol page incl. scanner stocks.

## 12. Frontend (static HTML + inline JS, 30s refresh, no time gate)

`index.html` (dashboard), `market.html` (grid), `indices/nifty.html`, `indices/banknifty.html`, `scanner.html` (dynamic symbols, cap + Buy/Hold/Exit + regime filters, Target/Stop on stock cards), `strategies.html` (indexes only: nifty/banknifty/finnifty/sensex), `history.html` (P&L table), `stocks/reliance.html` (legacy single-stock page).
Table CSS: `.history-table{min-width:980px}` + nowrap + right-aligned numbers; wrapper scrolls.

## 13. Cron (VM, IST)

```
* 9-15 * * 1-5      data_fetcher_db.py        (tiered minute fetch)
*/5 9-15 * * 1-5    monitor.py
0 */2 9-15 * * 1-5  alert.py
30 9 * * 1-5        pnl_tracker.py lock       (9:30 entries)
20 15 * * 1-5       pnl_tracker.py close      (3:20 exits)
35 18 * * 1-5       bhavcopy.py daily         (NSE EOD backfill)
30 8 * * 1           bhavcopy.py holidays      (weekly holiday sync)
0 2 1 * *           pnl_tracker.py archive 365 (monthly)
*/2 * * * *         API health watchdog (curl /api/health → systemctl restart; catches hangs too)
@reboot              API start
```

## 14. Deploy (`deploy-vm.sh`)

rsync repo→/opt (excl. database/data/logs) → pip install → web-root sync → db_schema → background fetch → install `ops/systemd/tradingai-api.service` + `systemctl restart` → rewrite crontab → `sudo systemctl reload nginx`. Health curl has `|| true` so a slow start can't abort deploy.

## 15. Bug log (recurring traps)

- `display:block` on `<table>` destroys column layout (history looked "shrunk").
- `pgrep -f <pattern>` matches its own cron shell → pgrep watchdogs never fire. Use a `curl /api/health` check instead (also catches hangs, not just dead processes).
- `init_database()` must NEVER DROP tables (once wiped a day of screens).
- `ScenarioEngine.generate()` returns a **dict**, not a list (`scenarios[0]` → KeyError(0)).
- `calculate_all_indicators()["macd"]` is a **dict** `{macd,signal,histogram}` — extract before REAL columns.
- `support_resistance` was returned swapped (support↔resistance) in `indicators.py`.
- `Database.save_history` overwrites the preserved side (close wiped entry with 0) — `pnl_tracker.py` uses raw SQL instead.
- `ticker.info` numeric-only dict is NOT a quote (no `price` key) — always build quotes via `fetch_quote` or 1m candles.
- YF constants were inverted (`YF_ETFS` keys) and VIX was US `^VIX`; correct: `^INDIAVIX`, `^CNXFIN` for FINNIFTY, `*.NS` for ETFs.
- `nohup ... &` without `setsid` dies with the SSH session. API now runs under systemd; never start it by hand with nohup.

## 16. Data sources & persistence policy

**Every byte fetched externally must land in SQLite** (nothing lives only in memory/JSON):
yfinance per ticker → price_1m/1d (OHLCV), info+targets+recs+earnings→fundamentals, dividends/splits→corporate_actions, news→news, statements→fundamentals (weekly), options→option_chain(+expiries). Computed data (indicators/regime/scenarios/strategies/outlooks/breadth/snapshots) derived locally and stored. API exposes all of it; pages never call Yahoo directly.

## 17. Analytics, SEO & discoverability

- **GA4:** measurement ID `G-MJ3X88QYEL` (stream "tradingai" → https://tradingai.in), gtag.js snippet first in `<head>` of all 11 pages (verified served). If GA4 says "data collection isn't active", it means zero hits arrived — check with an adblock-free visit + Realtime report (standard reports lag 24–48h); Tag Assistant confirms firing.
- **SEO foundation:** `robots.txt` (allows all but `/api/`, `/data/`), `sitemap.xml` (10 evergreen URLs) + `backend/sitemap_gen.py` (adds dated `market/*.html` pages; run after publishing + weekly). Deploy syncs both + `today/` to web root (sync once silently skipped them — covered by deploy now).
- **Meta:** unique OG title/description + canonical + JSON-LD (Organization everywhere; WebSite + BreadcrumbList) on all pages.
- **`/today/` terminal:** pre-open checklist / live mode / close report, session-aware by IST.
- **Pending owner actions:** Google Search Console + Bing Webmaster verification, sitemap submit, IndexNow on publish.

## 18. Future implementations (roadmap)

1. **Second live source (critical):** Yahoo has no NSE options chain and 15-min-delayed indices — add NSEindia API or a broker WebSocket (Zerodha/Angel/Dhan) for live options + true tick data; keep Yahoo as fallback/archive.
2. **Intraday aggregation use:** `price_5m`/`price_15m` tables exist but are never populated — aggregate from `price_1m` in-fetcher; base regime screens on 15m, not daily.
3. **FINNIFTY + SENSEX pages:** `indices/finnifty.html`, `indices/sensex.html` (config already lists FINNIFTY page).
4. **Per-stock pages:** generate `stocks/<sym>.html` for all 39 (template + script) or one dynamic `stock.html?symbol=`.
5. **News/Actions UI:** market-page news rail (`/api/news`) + dividend/split badges on stock cards (`/api/actions/<sym>`).
6. **ETF explorer:** NIFTYBEES/BANKNIFTY holdings via yfinance fund APIs (user-requested earlier).
7. **Portfolio tracker:** `portfolio` table exists — wire entry/exit logging + live P&L to a page.
8. **Backtesting:** `backtest.py` exists unwired — backtest regime/strategy rules on `price_1d` history.
9. **Alerts:** `alert.py` + PCR/OI-breakout rules (PCR from option chains when available).
10. **Expiry holidays:** refresh `HOLIDAYS_IST` each January from NSE/BSE circulars.
11. **API hardening:** systemd unit done; remaining: gunicorn workers (Flask dev server is single-threaded) + response caching for `/api/market` (currently ~270 queries/page-load).
12. **Auth/admin:** token-gated `/api/*` write endpoints if journaling/notes are added.
