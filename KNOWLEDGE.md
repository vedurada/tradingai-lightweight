# TradingAI.in — Project Knowledge

> Living document. Update it whenever architecture, rules, or roadmap change.
> Last updated: 2026-09-11 (2nd pass).

## 1. What this is

**TradingAI.in is an AI-assisted trading system** (not an auto-trader, not a Yahoo clone).
Pipeline: market data → indicators → regime engine → AI outlook → human trader decides.
- **Indexes (NIFTY, BANKNIFTY, FINNIFTY, SENSEX):** option strategies (spreads, condors, intraday).
- **Stocks (all caps):** simple **BUY / HOLD / EXIT** outlook with numeric targets — never option spreads.
- **P&L:** daily index paper trades, entry 9:30 AM IST, exit 3:20 PM IST, direction-aware.

## 2. Environment

| Item | Value |
|---|---|
| VM | 129.159.224.81, Ubuntu 22.04, 1 CPU / 956MB RAM + 2GB swap, TZ Asia/Kolkata |
| SSH | `ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81` |
| Repo | https://github.com/vedurada/tradingai-lightweight |
| Local dir | `/Users/satya/remove_workspace/tradingai-lightweight` |
| VM app dir | `/opt/tradingai` (repo rsync target) |
| VM web root | `/var/www/tradingai.in/html` (nginx serves this, NOT /opt) |
| DB | `/opt/tradingai/database/tradingai.db` (SQLite, WAL off, single writer) |
| API | Flask `backend/api_server.py` on `127.0.0.1:8000` as systemd unit `tradingai-api` (`Restart=always`, unit in `ops/systemd/`), proxied at `/api/` by nginx; 2-min curl watchdog restarts on hang |
| Site | https://tradingai.in (real Let's Encrypt cert since 2026-09-10, auto-renew via certbot timer; HTTP 301 → HTTPS; earlier self-signed cert caused browser warnings) |
| Market hours | 9:30–15:30 IST, Mon–Fri. Cron uses `9-15` hour field as approximation |
| Cleanup | Removed ollama, docker, containerd, snapd, snap packages, multipathd/iscsid, unnecessary pip (ipython/jupyter/matplotlib/scipy/scikit/pandas/numpy). RAM: 602→173MB used, free: 65→306MB, disk: 29→25GB. |
| LLM | Free cloud chain (gemini→groq→deepseek→openrouter→rule-based). Ollama on VM too slow (60s+ timeouts, 956MB RAM) — removed from chain. No API keys on VM; providers skip fast, rule-based used. Add key via `export GEMINI_API_KEY=...` on VM to enable. |

## 3. Architecture (database-first, layered)

```
yfinance (only external source today)
   ↓  every minute, tiered
Raw Market Database (SQLite: price_1m/5m/15m/1d, vix_data, option_chain, fundamentals, news, corporate_actions)
   ↓
Indicators (computed locally: EMA/SMA/VWAP/RSI/MACD/ADX/ATR/Bollinger/Pivot/CPR/S-R) + Regime + Scenarios
   ↓
Strategy layer (index option spreads | stock BUY/HOLD/EXIT) + AI outlook (LLM free-chain or rule-based fallback)
   ↓
Flask API :8000 → nginx /api/ → static HTML + vanilla JS (20s silent refresh, scroll-preserved, no market-hours gate)
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
| `nse_source.py` | NSE primary quotes (`allIndices`) + market state; `live_quotes` table preferred by API when fresh (<25 min), yfinance fallback, synth candles prevent chart gaps |
| `indicators.py` | Local indicator math (fixed S/R swap bug Sep 2026) |
| `regime.py` | TRENDING_BULLISH/BEARISH, RANGE_BOUND, HIGH_VOLATILITY scoring |
| `scenarios.py` | Returns **dict** `{bullish, bearish, range, breakout, reversal}` (not a list) |
| `strategies.py` | `INDEX_SYMBOLS={NIFTY,BANKNIFTY,SENSEX,FINNIFTY}` → option spreads; everything else → `select_stock_outlook()` BUY/HOLD/EXIT with numeric T1/T2/stop from S/R+ATR |
## AI / LLM Outlook

`backend/ai_outlook.py` — `AIOutlookEngine` generates `ai_outlook` JSON per symbol.

**Providers (tried in order, first success wins):**
| Provider | Model | Key env var | Endpoint | Status |
|---|---|---|---|---|
| Gemini | gemini-2.0-flash | `GEMINI_API_KEY` | Google generative API | Ready |
| Groq | llama-3.3-70b-versatile | `GROQ_API_KEY` | OpenAI-compatible | Ready |
| DeepSeek | deepseek-chat | `DEEPSEEK_API_KEY` | OpenAI-compatible | Ready |
| OpenRouter | google/gemini-flash-1.5 | `OPENROUTER_API_KEY` | OpenAI-compatible | Ready |
| Ollama | qwen2.5:0.5b (local) | none | `http://localhost:11434` | On VM but too slow (60s+), removed from chain |

**Fallback chain:** configured provider → each free provider in order → rule-based `_rule_based_outlook()` (always works, no key needed).

**Config:** `config/settings.json` — `llm_provider` (single) or `llm_providers` (list). Keys read from env vars, never committed.

**Caching:** 300s in-memory per symbol. `data_fetcher_db.py` calls `generate()` during store; results persisted to `ai_outlooks` DB table and `data/<symbol>.json`.

**Free tier limits:** Gemini 15 RPM / 1M tokens/day; Groq 30 RPM; DeepSeek generous; OpenRouter free models limited; Ollama unlimited local.
| `expiry.py` | Per-index expiry rules (NSE=Tuesday, BSE=Thursday; weeklies only NIFTY/SENSEX) |
| `pnl_tracker.py` | `lock` (9:30) / `close` (15:20) / `backfill [date]` / `archive [days]` |
| `bhavcopy.py` | NSE official EOD (`ind_close_all`, incl. index P/E) into `price_1d` — `backfill [days]` / `daily` (18:35 cron) / `holidays` (weekly → `nse_holidays`, auto-used by expiry engine) |
| `monitor.py` / `alert.py` | Health checks / alerts via cron |
| `generate_data.py` / `generate_json.py` | LEGACY JSON pipeline (deprecated; weekly archive inside it disabled) |
| `history_logger.py`, `backtest.py`, `options.py` | Legacy/helpers; backtest not wired to UI |

## 6. Database tables (SQLite)

Prices: `symbols`, `price_1m`, `price_5m`, `price_15m`, `price_1d`, `vix_data`, `etf_data`.
Derivatives: `option_expiries`, `option_chain` (usually empty — Yahoo has no NSE options).
Computed: `indicators` (+`support_resistance` JSON col), `market_regime`, `scenarios`, `strategies` (primary flattened; full list JSON inside `legs`), `ai_outlooks` (LLM or rule-based, full JSON in `outlook`), `signals`, `market_breadth`, `sector_data`, `market_snapshots`.
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

## 12. Frontend (static HTML + inline JS, 20s silent refresh, no time gate)

Every page shares: **AI-Assisted Market Intelligence Platform** header (single-color pill nav `#f0fdf4`, live IST clock top-right in header brand-row, favicon `favicon.svg` + `apple-touch-icon.svg` + header brand mark `header h1 img` 22×22 rounded), scrolling ticker tape (60s loop, price + NSE A/D, pause on hover, on **every** page), and centered `Data as of ... IST` bar (true IST via `Intl`, data-time from quote candle, red "Update failed" on fetch error). All cards/rows site-wide are `cursor:pointer` → `detailHref(symbol)` (market grid, scanner rows, stock-options rows, history rows, strategy cards, index hero tiles).

`index.html` — gradient **TODAY'S NIFTY** hero (price + change as high-contrast pill, regime pill, expected range, S/R, VIX pill + VWAP, market_summary) + **🎯 Strategy card** (VIX-range engine with entry/exit rules + payoff canvas graph) + tiles (NIFTY/BANKNIFTY/FINNIFTY/SENSEX + VIX) + breadth bar + P&L glance + CTA row + `stock.html?symbol=` detail pages.
`market.html` — **MARKET PULSE** gradient hero with 4 clickable tiles (NIFTY/BANKNIFTY/SENSEX/VIX — VIX now shows change as pill, grid-aligned) + grid of brand-tinted `brandBtn` cards (favicon + color per symbol, whole card clickable). Hero tiles use `border:1px solid transparent` (not `border:none`) so hover green border is visible on dark background.
`indices/nifty.html` `banknifty.html` `finnifty.html` `sensex.html` — hero price strip (`card hero`, all four enabled) + 🧠 AI MARKET OUTLOOK (green left border), 📍 KEY LEVELS (amber), 📈 Chart + OPTIONS INTELLIGENCE side-by-side, **NIFTY vs INDIA VIX — Intraday** dual-% chart (`nifty-vix-chart`), ⚡ AI INTRADAY STRATEGY (blue, 9:30 `daily_strategy` lock), MARKET INTERNALS, WHAT CHANGED timeline, HISTORICAL PERFORMANCE. All four share the card-accent system. Hero right-side "India VIX" heading uses `.hero h3 { color:#fff; background:transparent }` (was `#d1fae5` on `#f1f5f9` — invisible). All `.card` and `.tile` elements have hover lift + shadow + green border.
`scanner.html` / `stock-options.html` / `history.html` — full-width tables (`.pnl-full` / `.scan-table` fixed layout, no horizontal scroll bleed). Scanner: hero + sortable table (Symbol/Cap/Price/Chg%/Regime/Signal/**Invest**/Target/Stop/S-R, rows clickable). Stock-options: **navy `hero-stock` + amber `stock-card`** **positional table** (no scroll, header Lot simplified) — visually distinct from index green hero, Exit column is dynamic positional (from live strategy, not 15:20).
`strategies.html` — strategy engine header now `hero`; strategy template cards → Builder with `?index=&template=`; `strategies-guide.html` / `strategy-builder.html` / `learn/*` / `tools/position-size.html` follow the same header/ticker/clock shell.
Expiry readout is uniform everywhere: `Expiry: 15 Sep 2026 (5 DTE, WEEKLY)` (index pages, strategies cards, builder header; live NSE `source: NSE` preferred).
Table CSS: `.history-table{min-width:980px}` + nowrap + right-aligned numbers; gains green `#15803d` (light `#86efac` on dark heroes) / losses red `#dc2626` (`#fca5a5` on dark) site-wide, with high-contrast pill badges on dark heroes for `+6.18%` etc.

## 12b. Card heading CSS (2026-09-11)

- `.card h3` → dark green hero gradient (`#052e16 → #15803d`) + light `#d1fae5` text, `border-radius: 8px` (global).
- `.card.stock-card h3` → warm amber `#fef3c7` + dark `#0f172a` text + `#f59e0b` left accent (overrides hero gradient for stock-name cards only).
- `market.html` JS dynamic stock grid cards use `card.className='card stock-card'` to get the amber style.
- **Do NOT touch `index.html`** — frozen, user explicitly said not to modify it.

## 12c. Hover effects (2026-09-11)

- `.card:hover` → `translateY(-2px)` + deeper shadow (`0 8px 24px rgba(15,23,42,0.14)`) + green border `#15803d`.
- `.tile:hover` → same lift + shadow + green border (index page tiles + market.html hero tiles).
- `market.html` tiles changed from `border:none` to `border:1px solid transparent` so hover green border is visible on dark hero background.

## 12d. VIX Strategy Engine (2026-09-11)

- `static/js/index-charts.js` — `vixStrategy(v, vc)` function maps VIX price + change to 5 ranges: LOW (<12), NORMAL (12-15), ELEVATED (15-20), HIGH (20-25), VERY HIGH (>25).
- Each range has: strategy type, risk level, position size %, entry rule, exit rule, payoff color.
- Entry: 9:30 AM, VIX change < 5% positive, short strikes ±100 pts from ATM, hedge ±500 pts from short legs.
- Exit: VIX > 5% from open, ₹2k loss/trade, EOD 3:20 PM.
- `drawPayoff(id, str, atm)` renders visual payoff graph on canvas.
- `loadStrategy()` fetches VIX from hero card, computes strategy, renders card + payoff graph.
- Home page `index.html` has `#strategy-card` in `#today-hero` section; `loadStrategy()` called in DOMContentLoaded.

## 13. Cron (VM, IST)

```
* 9-15 * * 1-5      data_fetcher_db.py        (tiered minute fetch)
*/5 9-15 * * 1-5    monitor.py
0 */2 9-15 * * 1-5  alert.py
30 9 * * 1-5        pnl_tracker.py lock       (9:30 entries)
20 15 * * 1-5       pnl_tracker.py close      (3:20 exits)
35 9 * * 1-5        daily_page.py morning     (→ market/nifty-outlook-YYYY-MM-DD.html)
35 15 * * 1-5       daily_page.py close + sitemap_gen.py (close report + sitemap)
35 18 * * 1-5       bhavcopy.py daily         (NSE EOD backfill)
30 8 * * 1           bhavcopy.py holidays      (weekly holiday sync)
0 2 1 * *           pnl_tracker.py archive 365 (monthly)
*/2 * * * *         API health watchdog (curl /api/health → systemctl restart; catches hangs too)
@reboot              API start
```

## 14. Deploy (`deploy-vm.sh`)

rsync repo→/opt (excl. database/data/logs) → pip install → web-root sync (incl. `favicon.svg`/`apple-touch-icon.svg`, `robots.txt`, `sitemap.xml`, `today/`, `learn/`, `tools/`, `market/`, each `indices/*`, `stock-options.html`; missing one from the `cp` list leaves a stale page live) → db_schema → background fetch → install `ops/systemd/tradingai-api.service` + `systemctl restart` → rewrite crontab → `sudo systemctl reload nginx`. Health curl has `|| true` so a slow start can't abort deploy.

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
- Deploy `cp` list is explicit, not wildcard — adding a new top-level page (e.g. `stock-options.html`) without listing it leaves the old version live. Always extend the web-root sync line + `sitemap_gen.py` evergreen list.
- Ticker without `curl_cffi` session warm-up gets 403 from NSE; breadth silently stays stale.

## 16. Data sources & persistence policy

**Every byte fetched externally must land in SQLite** (nothing lives only in memory/JSON):
yfinance per ticker → price_1m/1d (OHLCV), info+targets+recs+earnings→fundamentals, dividends/splits→corporate_actions, news→news, statements→fundamentals (weekly), options→option_chain(+expiries). Computed data (indicators/regime/scenarios/strategies/outlooks/breadth/snapshots) derived locally and stored. API exposes all of it; pages never call Yahoo directly.

## 17. Analytics, SEO & discoverability

- **SEO foundation:** `robots.txt` (allows all but `/api/`, `/data/`), `sitemap.xml` (20 evergreen URLs) + `backend/sitemap_gen.py` (adds dated `market/*.html` pages; run after publishing + weekly). Deploy syncs both + `today/`/`learn/`/`tools/`/`market/` to web root.
- **Meta & brand:** unique OG title/description + canonical + JSON-LD (Organization everywhere; WebSite + BreadcrumbList) on all pages; SVG favicon + apple-touch-icon + header `<h1><img>` brand mark on every page (added 2026-09-11).
- **`/today/` terminal:** pre-open checklist / live mode / close report, session-aware by IST, ticker + clock.
- **GA4:** `G-MJ3X88QYEL` on every page (verified 200 for `gtag/js`); "Data collection isn't active" = zero hits arrived, not a tag bug (ad-blockers kill gtag, Realtime shows visits in ~30s, standard reports lag 24–48h).
- **Google accounts (verified 2026-09-11):** Domain `tradingai.in` bought on GoDaddy with Gmail A; **Search Console is verified with that same Gmail A** (DNS TXT) and sitemap `https://tradingai.in/sitemap.xml` submitted there. AdSense/sitemap Google account is Gmail B — Gmail B added as **Owner** in Search Console (`Settings → Users and permissions → Add user → Owner`) so both see indexing + AdSense linkage. No domain move needed.
- **Pending owner actions:** ~~Bing Webmaster verification, IndexNow on publish~~ **IndexNow DONE 2026-09-11** (key file `42bd61de...bf5b.txt` hosted at web root, pinged 202 Accepted via `ops/indexnow-ping.sh` after deploys). **Bing Webmaster still needs login:** https://www.bing.com/webmasters → Add site `tradingai.in` → DNS TXT or XML-file verify (login `mrsatya84@outlook.com`), then submit `https://tradingai.in/sitemap.xml`.
- **Options PCR / max pain (2026-09-11):** `backend/fo_fetcher.py` pulls NSE FO EOD bhavcopy (`BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`) after 18:35 bhavcopy, populates `option_chain` (~15-16k rows/day), `oi_top_strikes` (top-10 OI/side/expiry), and computes PCR + max pain for NIFTY/BANKNIFTY/FINNIFTY/SENSEX. `daily` + `backfill [d]`; cron 18:40 Mon-Fri → `/opt/tradingai/logs/fo.log`. APIs: `/api/pcr`, `/api/maxpain`, `/api/oi-top`, and `/api/options/<symbol>` now returns real rows. Page: `options/pcr.html` (PCR gauge + max-pain + PE/CE chain). NOTE: data is EOD (not live intraday); PCR reflects close.

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

---

## AdSense (2026-09-11)
- Pub ID `ca-pub-2262405054444130`, auto-ads injected in `<head>` of all pages (after GA tag; learn pages had no GA → after `<meta charset>`).
- Thin-content fix DONE + deployed: 5 policy pages (`about/contact/privacy/terms/disclaimer.html`) with nav + footer links; unique 250–400-word editorial card ("How to read this page") added before `<footer>` on all 34 content pages via `ops/page_content.py` + `ops/insert_content.py`. All 39 pages ≥200 words. sitemap now 37 URLs (policy pages added to `sitemap_gen.py`).
- `pcr_history` populated on VM via `fo_fetcher.py daily` (40 18 * * 1-5 cron); `/api/pcr-history` verified live.
- TODO: user requests AdSense review; Bing Webmaster verification still blocked on user login.
