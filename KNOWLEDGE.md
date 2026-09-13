# TradingAI.in — Project Knowledge

> Living document. Update it whenever architecture, rules, or roadmap change.
> Last updated: 2026-09-13 (8th pass — today LIVE reset after close / Spot+Live P&L top bar, 640×190 backtest payoff on today, gunicorn 3×2 gthread + nginx 10s api_cache, docker purged, 40 grids unified 240px).

## 1. What this is

**TradingAI.in is an AI-assisted trading system** (not an auto-trader, not a Yahoo clone).
Pipeline: market data → indicators → regime engine → AI outlook → human trader decides.
- **Indexes (NIFTY, BANKNIFTY, FINNIFTY, SENSEX):** option strategies (spreads, condors, intraday).
- **Stocks (all caps):** simple **BUY / HOLD / EXIT** outlook with numeric targets — never option spreads.
- **P&L:** daily index paper trades, entry 9:30 AM IST, exit 3:20 PM IST, direction-aware. **AI-gated:** no trade row is logged unless the AI outlook says `TRADE`; WAIT/AVOID sessions are never written to `history`. Each trade row also stores the intraday outlook active at entry-time (`entry_outlook` column) for future reference.

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
| API | Flask `backend/api_server.py` on `127.0.0.1:8000` as gunicorn `gthread -w 3 --threads 2 --keep-alive 5 --max-requests 1000` systemd `tradingai-api` (`Restart=always`, `ops/systemd/tradingai-api.service`), proxied at `/api/` by nginx with `proxy_cache_path api_cache:10m 10s` + static `1h` + `gzip_vary`; 2-min curl watchdog restarts on hang. Safe concurrency 50-100 active polling / 150-200 casual (was 15-25). |
| Site | https://tradingai.in (real Let's Encrypt cert since 2026-09-10, auto-renew via certbot timer; HTTP 301 → HTTPS; earlier self-signed cert caused browser warnings) |
| Market hours | 9:30–15:30 IST, Mon–Fri. Cron uses `9-15` hour field as approximation |
| Cleanup | Removed ollama, docker (`docker-ce docker-ce-cli buildx compose containerd.io` + `/var/lib/docker` ~153 MB + 68 MB), snapd/snap, multipathd/iscsid, pip (ipython/jupyter/matplotlib/scipy/scikit/pandas/numpy). RAM: 602→173→198MB used, free: 65→306→612 MB (2026-09-13), disk: 29→25GB → 45G 14G 30%. |
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
| `expiry.py` | Historical expiry 2016-2026: NIFTY/BANKNIFTY Thu→Tue 2025-09-01, FINNIFTY Tue from 2021-01-11, SENSEX Fri→Thu (Holidays shift to prev trading day) — `HISTORICAL_WEEKDAY`, `get_historical_weekly_expiry()` for backtest |
| `lot_sizes.py` | Historical lots 2016-2026: NIFTY 75→50→75→65, BANKNIFTY 40→20→25→15→30→35, FINNIFTY 40→65→60, SENSEX 10→20 (`HISTORICAL_LOTS`, `get_historical_lot()`), used by `backtest.py lot/rupees` |
| `pnl_tracker.py` | `lock` (9:30) / `close` (15:20) / `backfill [date]` / `archive [days]` |
| `bhavcopy.py` | NSE official EOD (`ind_close_all`, incl. index P/E) into `price_1d` — `backfill [days]` / `daily` (18:35 cron) / `holidays` (weekly → `nse_holidays`, auto-used by expiry engine) |
| `monitor.py` / `alert.py` | Health checks / alerts via cron |
| `generate_data.py` / `generate_json.py` | LEGACY JSON pipeline (deprecated; weekly archive inside it disabled) |
| `history_logger.py`, `options.py` | Legacy/helpers |
| `backtest.py` | Full 10y backtest: `BacktestEngine` — `Fixed Short Strangle (o-c)` vs `AI Dynamic` (BULL `c-o`, BEAR `o-c`, NEUTRAL `Short Strangle 50pt` credit spreads `short 50pts ATM` `long 50% prem` `28/35 pts` with theta small-loss→profit), `HISTORICAL_WEEKDAY`+`HISTORICAL_LOTS` (`lot`/`rupees` per trade), `2466` trading days `2016-09-12→2026-09-11`, strikes `short/long/atm` + `strike_desc`, payoff via `expiry.get_historical_weekly_expiry`, `NEUTRAL Credit Spread (Flat)`→`Short Strangle`, clickable `↳ strategy` filters `DAY-BY-DAY` + `Export CSV` |

## 6. Database tables (SQLite)

Prices: `symbols`, `price_1m`, `price_5m`, `price_15m`, `price_1d`, `vix_data`, `etf_data`.
Derivatives: `option_expiries`, `option_chain` (usually empty — Yahoo has no NSE options).
Computed: `indicators` (+`support_resistance` JSON col), `market_regime`, `scenarios`, `strategies` (primary flattened; full list JSON inside `legs`), `ai_outlooks` (LLM or rule-based, full JSON in `outlook`), `signals`, `market_breadth`, `sector_data`, `market_snapshots`.
Company: `fundamentals` (merged info + analyst views + statements JSON), `news`, `corporate_actions` (DIVIDEND/SPLIT), `earnings` via fundamentals.
P&L: `history` (+`entry_time`/`exit_time`/`direction`/`entry_outlook`), `history_archive` (same cols incl. `entry_outlook`), `portfolio` (schema only, unused).
Ops: `data_status`, `alerts`.

## 7. Fetcher tiers (`data_fetcher_db.py::fetch_all`, cron `* 9-15 * * 1-5`)

- **Every run:** indices 1m + screens, India VIX 1m, ETF prices, LARGE-cap 1m + screens.
- **Every 5th minute:** MID-cap 1m + screens, NIFTY/BANKNIFTY option chains, breadth.
- **Every 15th minute:** SMALL-cap 1m + screens, info + news/actions/analyst merged into fundamentals (indices+LARGE).
- **Weekly (Mon 9:xx):** MID/SMALL extras + LARGE financial statements.
- Daily candles cached in `price_1d` (DB-first, not re-fetched per symbol).
- Retention cleanup per run: price_1m 2d, options 3d, fundamentals 7d, news 30d.
- **STORED-TIME CONVENTION (2026-09-12):** `price_1m` timestamps are naive **UTC wall-clock** — yfinance's IST-aware index is converted to UTC on write, and the NSE synthetic fallback writes `datetime.now(timezone.utc)`. All other intraday tables (`vix_data`, `indicators`, `live_quotes`, `data_status`) store UTC ISO. `_to_ist_iso` (api_server) tags naive `YYYY-MM-DD HH:MM:SS` as `+00:00` (UTC); only `price_1d` keeps `+05:30`. Do NOT tag naive 1m stamps as IST — that produces a stale-looking "Data as of ~5.5h behind". Frontends locale-convert (`Intl`/`toLocaleString('en-IN', Asia/Kolkata)` / browser-local `.getHours()`).

## 8. Strategy doctrine

- **Indexes only:** Bull/Bear spreads, Iron Condor, defined-risk premium selling, ND intraday straddle/strangle (NIFTY + BANKNIFTY, VIX-gated, 9:30 entry / 3:20 exit).
- **Stocks/ETFs:** BUY/HOLD/EXIT via `select_stock_outlook()` — regime first, VWAP+RSI fallback. Numeric levels from `_stock_levels()`: T1 = nearest resistance (else +8%/2×ATR), T2 (+12%/3×ATR), stop = support (else −5%/1.5×ATR), with upside/risk/RR percentages embedded in text fields.
- `strategies.legs` holds `{"legs": [...], "all_strategies": [...]}`; API rebuilds legacy `{strategies: [...]}`.

## 8b. Stock investment views (`backend/investment.py`, table `investment_views`)

Stocks are investments, not intraday signals: SHORT horizon (weeks: SMA20/50 + RSI + 20d return → BUY/HOLD/EXIT with swing target/stop) and LONG horizon (months: SMA200 + 52w position + P/E + analyst upside + dividend → ACCUMULATE/HOLD/AVOID + fair value). Computed from `price_1d` + stored fundamentals (zero extra Yahoo calls), stored per (symbol, date, horizon). API: `/api/investment/<sym>` + `investment` block in symbol payloads; scanner shows long-term badge.

## 9. P&L tracker (`pnl_tracker.py`)

- `lock` 9:30 IST (cron `30 9 * * 1-5`): 09:30-candle entry + strategy/regime/bias snapshot. Direction from bias: BEARISH→SHORT else LONG.
- `close` 15:20 IST (cron `20 15 * * 1-5`): strict 15:20-candle exit (fallback: last candle). **SHORT: points = entry − exit**; LONG: exit − entry. WIN/LOSS/FLAT.
- **AI gate (2026-09-12):** `evaluate`/`lock`/`backfill` write a row ONLY when the gating outlook verdict is `TRADE`. NO row is written for WAIT/AVOID/NO_TRADE sessions (`_upsert_no_trade` removed). `close()` still guards legacy `no_trade_conditions` rows defensively. This keeps `history` = real trades only (currently NO_TRADE rows = 0).
- **`entry_outlook` column (2026-09-12):** every entry (`_upsert_entry`, `backfill`, `close` fallback) captures the latest stored `market_outlooks` payload (date ≤ trade date) as a compact JSON snapshot — verdict/regime/bias/confidence/expected_range/strategies — via `_entry_outlook_snapshot()`. Exposed through `outlook.py _trades()` as `trades[].entry_outlook`; the AI-GATED TRADE RECORD renders it under the strategy cell (e.g. `09-11 · AI: TRADE · Range-Bound · 72%`). Also added to `history_archive` + all archive INSERTs so it survives archiving.
- `backfill [date]`: rebuild any day from stored 1m candles.
- `archive [days]` (default 365): monthly cron `0 2 1 * *` moves settled rows older than a year to `history_archive`.
- Retention: 1 year live. `/api/history` merges both tables, default 365 days, grouped `{SYM: [...]}`.
- History page columns: Date | Symbol | Outlook(BUY/SELL) | Direction(LONG/SHORT) | Entry Time/Price | Exit Time/Price | Points(±, green/red) | Result | Strategy + summary bar + symbol filters.

**Live floating P&L (2026-09-12, history.html):** `/api/history` attaches `live_price`/`live_points` to any `result=OPEN` row using the **cached** `/api/market` snapshot only (never triggers the ~20s rebuild — helper `_mark_open_trades` returns early when cache is empty). Points are direction-aware (SHORT sign flips). history.html renders an OPEN trade showing `●LIVE` amber badge, live price in the Exit column, floating points, result `OPEN · LIVE`, and a `Live(OPEN): +N pts` segment in the P&L summary. Refreshes via existing `startDataRefresh` (20s during market hours); settles to the final result at the 15:20 close.

- Live NSE data (verified 2026-09-10): `option-chain-contract-info` gives authoritative expiry dates per symbol, stored in `option_expiries` by the 9 AM daily refresh; API prefers these over weekday math (payload `source: NSE`).
- Live NSE lot sizes from `fo_mktlots.csv` into `symbols.lot_size` (NIFTY 65 / BANKNIFTY 30 / FINNIFTY 60, source=NSE; SENSEX 20 source=config until a BSE file is found). Refresh writes only on change; Builder reads live lots from the API.

## 10. Expiry rules (`expiry.py`)

- NSE=Tuesday, BSE=Thursday (SEBI 1-Sep-2025; NSE circular FAOP/68747). **Historical 2016-2026:** `HISTORICAL_WEEKDAY` — NIFTY/BANKNIFTY Thu until 2025-08-31 → Tue from 2025-09-01, FINNIFTY Tue from 2021-01-11, SENSEX Fri (2016) → Tue (2024-11) → Thu (2025-09). `get_historical_weekly_expiry(symbol, date)` used by backtest for correct `expiry (DTE)` per year.
- NIFTY: weekly every Tue (current) + monthly last Tue. SENSEX: weekly every Thu + monthly last Thu.
- BANKNIFTY/FINNIFTY: **monthly-only** post 2025, last Tuesday (weeklies discontinued Nov 2024) — but historical weeklies existed Thu before.
- Post-15:30 IST on expiry day rolls to next; holidays in `HOLIDAYS_IST` + `nse_holidays` table shift to previous trading day (extend every January from NSE/BSE circulars).
- API `_symbol_data[].expiry` = `{..., tenor, weekly:{...}|None, monthly:{...}}`; index pages show both.
- Backtest `10y 2466 trading days 2016-09-12→2026-09-11` matches `price_1d DISTINCT 2467` ( `0.04%` diff, 1 holiday).
- Lots `lot_sizes.py:HISTORICAL_LOTS` — NIFTY 75→50 (2021-07)→75 (2025-01)→65 (2025-12-30), BANKNIFTY 40→20→25→15→30→35, FINNIFTY 40→65→60, SENSEX 10→20 — `get_historical_lot()` gives `lot`/`rupees` per backtest trade (not `pts*75`).

## 10b. Backtest engine (`backend/backtest.py` + `tools/backtest.html`)

- `Fixed Short Strangle (o-c)` baseline vs `AI Dynamic` market-condition adaptive: `BULLISH` (`Long Call/Bull Call` → `c-o`, `Bull Put Spread` → BS `short PUT ATM-50 long where prem≈50% short` net `BS prem_s-prem_l` `≈28`), `BEARISH` (`Bear Call` `ATM+50` similarly, else `o-c`), `NEUTRAL` `Short Strangle` `BS call ATM+50 + put ATM-50` `BS net` `≈35` (`move<50` win else `35-(move-50)*0.9` `-80`). **Black-Scholes proxy** `backend/backtest.py:26 _bs_price(S,K,T,VIX/100,r6%,DTE)` for realistic premiums (not fixed 28/35), with fallback to `28/35` breakeven when `|pts|<5`.
- Credit spreads `short 50 pts from ATM, long at premium 50% of short` (search `+50/+100/+150/+200` via BS) as requested.
- Features: `outlook.py` VIX `cover_prob` (`GAP DOWN v<14 & |gap|<1%→75% else 25%`), past `3d/5d` trend + `call/put OI buildup` confirmation (`feature_engine.past_confirmation`), `ADX/RSI/EMA` etc. — hierarchical `prev_day → market_open → regime→direction→probs`.
- `10y 2466` rows every trading day `AI TRADE 2305 (93.5%)` + `FLAT 161 WAIT`, `1 month ≈21-23` trading days (calendar `*0.72`), last trading day `2026-09-11` always included via `DESC LIMIT` not `date('now','-days')`. NSE `2467 DISTINCT` `2016-09-12→2026-09-11` matches within 1.
- `tools/backtest.html` — default `1 month` `30cal→22 trading` `ceil(days*5/7)` auto-load `22 (AI)` (`10y 2461` still via dropdown), `FIXED vs AI` table, `AI DIRECTION` `BULL/BEAR/NEUTRAL` + `Market Condition/Year/Month/Week/WIN RATE/PF/AI EDGE` all `clickable-row` → filters `DAY-BY-DAY`, `8 cols` `Date·Expiry(DTE)·Verdict·Strategy·Strikes·Result·Points·Payoff view` single-click `view` delegated `data-date` → `drawPayoffFor`. **Payoff chart** `640×190` per trade `drawPayoffFor` — `between-strikes green #86efac (profit) / beyond red #fca5a5 (loss)` vertical zones, `ATM #eab308` `Short #0ea5e9` `Long #38bdf8` `BE #8b5cf6` (Strangle dual `24365/24535` width `100`) `current spot dot`, header `Max Profit ₹`/`Max Loss ₹` (`pts×lot` historical `50→65`), `Breakeven`, `Spot Now`, X `Spot expiry` Y `P&L pts`, legend. Aggregated strategy payoff also shown on filter. Grid `std_single auto-fit 240px` inside `</main>`.
- `₹` uses historical lot `NIFTY 75→50→75→65` etc. (`total_rupees`), not `pts*75`.
- `today/index.html` — **LIVE reset after close**: `showLiveStrat = mode==='live' && verdict==='TRADE' && prim`; `LIVE 9:15-15:30 + TRADE` → green `AI VERDICT — TRADE` top bar `Spot now | Live P&L (+pts · ₹, color #15803d/#dc2626) | ● LIVE` `background #f8fafc` above `<h3>`, then `Regime/Bias/ATM/Short/Long/Credit/Lot/Expiry` + same `640×190` `drawPayoffFor` backtest payoff `60s poll` `live spot dot`; otherwise dashed `AI VERDICT — WAIT · No live strategy (modeLabel)` `Live strategy resets after 15:30 — next at 9:15 IST when AI outlook generates TRADE.` — payoff cleared. Spot/Live P&L always **top of strategy name**.

## 11. API (`/api/*`, Flask :8000)

**Single genuine price source (2026-09-13):** every live price is `quote {price,change,change_pct,previous_close,timestamp,source}` built by `backend/api_server.py:_build_quote` → `live_quotes (NSE allIndices, <25 min fresh, source NSE)` → fallback `price_1m latest close (yfinance/synth, source yfinance)` → fallback `price_1d EOD` (weekend). `previous_close` is NSE `previous_close` when live, else `price_1d` EOD prev close (never 1m-prev). All three live endpoints return the **same** quote: `GET /api/price/<SYM>` + `GET /api/<SYM> {quote}` + `GET /api/market {instruments.<SYM>.quote}` are byte-identical (`diff price==quote.price` verified). Frontend single source is `quote.price` — never `price_1m.close` or hard-coded. History candles `GET /api/prices/<SYM>?interval=1m|1d` remain OHLC history only.

Health, symbols, price[s], vix(+history), indicators, regime(s), strategy/strategies, scenarios, outlook(s), options(+expiries), breadth(+history), snapshot(s), fundamentals, company (analyst views/financial flags), news(+per-symbol), actions (dividends/splits), market (legacy `{instruments:{...}}`), history (grouped, 365d), etf, data_status. Generic `/api/<symbol>` (case-insensitive) serves any symbol page incl. scanner stocks.

## 12. Frontend (static HTML + inline JS, 20s silent refresh, no time gate)

Every page shares: **AI-Assisted Market Intelligence Platform** header (single-color pill nav `#f0fdf4`, live IST clock top-right in header brand-row, favicon `favicon.svg` + `apple-touch-icon.svg` + header brand mark `header h1 img` 22×22 rounded), scrolling ticker tape (60s loop, price + NSE A/D, pause on hover, on **every** page), and centered `Data as of ... IST` bar (true IST via `Intl`, data-time from quote candle, red "Update failed" on fetch error). All cards/rows site-wide are `cursor:pointer` → `detailHref(symbol)` (market grid, scanner rows, stock-options rows, history rows, strategy cards, index hero tiles).

`index.html` — gradient **TODAY'S NIFTY** hero + **🎯 Strategy card** + tiles + breadth bar + CTA grid `Market Grid / Scanner / 📈 Backtest (→ tools/backtest.html, AI-gated vs Fixed) / Today LIVE` `std_single auto-fit 240px` `cta cta-single` (Paper P&L card removed) + live `Backtest — 1 month (NIFTY)` preview `fetch api/backtest?days=30` `WR/PF/Net/DD` grid + `stock.html?symbol=` detail pages. All 40 html grids unified `minmax(240px,1fr) margin-top:1.5rem` inside `<main>` (rsync `/var/www/tradingai.in/html`).
`market.html` — **MARKET PULSE** gradient hero with 4 clickable tiles (NIFTY/BANKNIFTY/SENSEX/VIX — VIX now shows change as pill, grid-aligned) + grid of brand-tinted `brandBtn` cards (favicon + color per symbol, whole card clickable). Hero tiles use `border:1px solid transparent` (not `border:none`) so hover green border is visible on dark background.
`indices/nifty.html` `banknifty.html` `finnifty.html` `sensex.html` — hero price strip (`card hero`, all four enabled) + 🧠 AI MARKET OUTLOOK (green left border), 📍 KEY LEVELS (amber), 📈 Chart + OPTIONS INTELLIGENCE side-by-side, **NIFTY vs INDIA VIX — Intraday** dual-% chart (`nifty-vix-chart`), ⚡ AI INTRADAY STRATEGY (blue, 9:30 `daily_strategy` lock), MARKET INTERNALS, WHAT CHANGED timeline, HISTORICAL PERFORMANCE. All four share the card-accent system. Hero right-side "India VIX" heading uses `.hero h3 { color:#fff; background:transparent }` (was `#d1fae5` on `#f1f5f9` — invisible). All `.card` and `.tile` elements have hover lift + shadow + green border.
`scanner.html` / `stock-options.html` / `history.html` — full-width tables (`.pnl-full` / `.scan-table` fixed layout, no horizontal scroll bleed). Scanner: hero + sortable table (Symbol/Cap/Price/Chg%/Regime/Signal/**Invest**/Target/Stop/S-R, rows clickable). Stock-options: **navy `hero-stock` + amber `stock-card`** **positional table** (no scroll, header Lot simplified) — visually distinct from index green hero, Exit column is dynamic positional (from live strategy, not 15:20).
`strategies.html` — strategy engine header now `hero`; strategy template cards → Builder with `?index=&template=`; `strategies-guide.html` / `strategy-builder.html` / `learn/*` / `tools/position-size.html` follow the same header/ticker/clock shell.
Expiry readout is uniform everywhere: `Expiry: 15 Sep 2026 (5 DTE, WEEKLY)` (index pages, strategies cards, builder header; live NSE `source: NSE` preferred).
Table CSS: `.history-table{min-width:980px}` + nowrap + right-aligned numbers; gains green `#15803d` (light `#86efac` on dark heroes) / losses red `#dc2626` (`#fca5a5` on dark) site-wide, with high-contrast pill badges on dark heroes for `+6.18%` etc.

**LIVE badge (2026-09-12):** the AI MARKET OUTLOOK header badge is now market-timing-aware (`ai-outlook.js marketStatusBadge()`): green dot + **LIVE** Mon–Fri 09:15–15:30 IST, amber dot + **CLOSED** otherwise (weekends/nights). Computed client-side via `Intl.DateTimeFormat` with `Asia/Kolkata`. Purely informational — it does not reflect data freshness.
**Data as of bar (2026-09-12):** `#last-updated-bar` de-dupes the date — when `as_of_ist` begins with `outlook.date`, only the time portion is shown (e.g. `Data as of 2026-09-11 · 23:15 IST` instead of repeating the date).

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
30 9 * * 1-5        outlook.py --symbol ×4     (pre-market intraday outlook refresh: merges prior-day data + live open, gates TOMORROW's session — overrides today's market_outlooks row)
20 15 * * 1-5       pnl_tracker.py close      (3:20 exits)
0 19 * * 1-5        outlook.py --symbol ×4 + sitemap_gen.py (final daily outlook + sitemap)
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

**Crontab dedupe (2026-09-12):** when rewriting crontab, deploy filters existing lines with `grep -v` for the entries it manages (`outlook.py|sitemap_gen.py|bhavcopy.py|backfill_yearly.py|fo_fetcher.py|daily_page.py|monitor.py|alert.py|pnl_tracker.py|data_fetcher_db.py|nse_live_chain.py|mf_fetcher.py|etf_fetcher.py|aggregate.py`) so repeated deploys never accumulate duplicate cron lines.

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
- Adding a column to `history` must also be mirrored in: `db_schema.py` CREATE + ALTER migration, `database.py` CREATE + `_migrate()` additions, `pnl_tracker.py` INSERTs (entry/close/backfill/archive), `history_archive` in both schema files, and any `INSERT INTO history_archive` SELECT list (3 of them in `database.py`). (entry_outlook is the blueprint for this — 2026-09-12.)

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

## 20. Intraday Market Outlook Framework (2026-09-11) — MUST follow for any market outlook

**Role:** Expert Indian derivatives analyst (NIFTY/BANKNIFTY/SENSEX intraday options). Generate a **data-driven** outlook. NEVER invent data/prices/news/OI/probabilities. Goal is to determine the ENVIRONMENT (regime, bias, volatility, suitable strategies, and TRADE / WAIT / AVOID) — NOT to force a trade.

**Inputs considered:** MARKET (spot, prev close, day change %, high/low, gap %, VWAP, SMA20/50, EMA, RSI, ATR, momentum, volume, breadth, sectors) · INDIA VIX (value, prev, change %, intraday H/L, percentile, trend) · OPTIONS (call/put OI, OI change, volume, PCR, strike OI + OI-change, ATM IV, call/put IV, IV percentile, greeks, expected move) · FUTURES (price, premium/discount, OI, OI change) · GLOBAL/MACRO (GIFT NIFTY, Asia/US/EU, USDINR, crude, gold, economic events) · NEWS (India/global/sector, RBI/Fed, elections/geopolitical, earnings) · TIME (IST, day of week, time to close, expiry).

**Process (13 steps):**
1. **Data quality check** — flag missing/contradictory/stale data; lower confidence; do NOT guess. If critical data missing → state "Insufficient data for high-confidence outlook."
2. **Market regime** — ONE of: STRONG BULLISH TREND / BULLISH / BULLISH RANGE / NEUTRAL / RANGE / VOLATILE RANGE / BEARISH RANGE / BEARISH / STRONG BEARISH TREND / EVENT·ABNORMAL VOLATILITY. Never from a single indicator (use price vs VWAP, vs SMA20, SMA slope, momentum, ATR, breadth, OI, PCR, VIX, futures, expected move, time of day, news risk).
3. **Directional bias** — Bullish / Mildly Bullish / Neutral / Mildly Bearish / Bearish, with Bullish/Neutral/Bearish percentages **totalling exactly 100%** (analytical, not guaranteed). Confidence reflects data quality + agreement.
4. **Volatility regime** — VERY LOW / LOW / NORMAL / ELEVATED / HIGH / EXTREME, from India VIX, VIX change, IV, IV percentile, ATR, expected move, actual intraday movement. State whether it favours buying / premium selling / defined-risk / waiting. Never recommend naked selling merely because IV is high.
5. **Options positioning** — call OI concentration, put OI concentration, OI add/unwind, PCR, ATM/OTM IV, IV skew, futures OI → identify support zones, resistance zones, probable breakout zone, probable breakdown zone. High OI alone ≠ absolute S/R; combine with price action.
6. **Expected move** — expected range from expected move/IV/ATR; compare vs actual intraday move (if much already consumed, reduce attractiveness of fresh trades). Upside/downside level, expected range, invalidation level.
7. **Time of day** — opening price discovery is volatile; midday rangey/low momentum; afternoon trend/ reversal; expiry sessions differ; late-day gamma rises fast. Never use one strategy for the whole day.
8. **Event risk** — LOW/MODERATE/HIGH/EXTREME. If HIGH/EXTREME → prioritise capital protection + defined-risk.
9. **Tradeability score 0–100** — 0–20 AVOID · 21–40 VERY LOW · 41–55 LOW · 56–70 MODERATE · 71–85 GOOD · 86–100 VERY GOOD. Reflects directional clarity, trend quality, vol suitability, OI clarity, liquidity, expected move, event risk, time of day, signal agreement. High score ≠ prediction.
10. **Strategy selection** — score each of {Long Call, Long Put, Bull Call Spread, Bear Put Spread, Bull Put Spread, Bear Call Spread, Iron Condor, Short Strangle, Short Straddle, Calendar Spread, No Trade} 0–100 considering regime/bias/VIX/IV/expected move/OI/time remaining/event risk/RR. Pick BEST, SECOND-BEST, STRATEGY TO AVOID. If no edge → BEST = NO TRADE.
11. **Entry conditions** — conditional, never unconditional: entry trigger + confirmation + invalidation + stop + profit-target + time-based exit.
12. **Risk** — LOW/MODERATE/HIGH/EXTREME; name primary risk (directional/gamma/IV-expansion/gap/event/liquidity/time-decay/whipsaw). High risk reduces attractiveness.
13. **No-trade engine** — explicitly decide NO TRADE if insufficient edge, conflicting signals, abnormal vol, poor RR, or significant event risk; explain why. NO TRADE is a valid, preferred outcome.

**FINAL OUTPUT (exact skeleton):** `## TODAY'S MARKET OUTLOOK` {Market Regime; Directional Bias; Direction Probability (Bullish/Neutral/Bearish = 100%); Confidence X/100; India VIX [value] — [regime]; Tradeability X/100 — [band]; Expected Range [upper]–[lower]; Key Levels: Support 1,2 / Resistance 1,2 / Breakout trigger / Breakdown trigger} → `## OPTIONS MARKET INTELLIGENCE` {PCR + interpretation; Call OI; Put OI; OI Signal (BULLISH/BEARISH/NEUTRAL/MIXED); IV Environment} → `## BEST STRATEGIES` {#1 name, Fit X/100, Why (≥3 reasons), Entry condition, Risk, Exit; #2 name, Fit; Strategy to Avoid + reason} → `## AI DECISION` {# TRADE / WAIT / NO TRADE; Primary view (2–4 sentences); Bullish invalidation level; Bearish invalidation level} → `## IMPORTANT WARNING` (not a guarantee; positional risk).

**Hard rules:** never fabricate data; never guarantee profits; never claim certainty; never force a trade; prefer defined-risk when uncertain; NO TRADE is valid; never rely on PCR/OI/VIX/indicators alone; resolve conflicts explicitly; always explain WHY; always give invalidation levels; probabilities = exactly 100%; distinguish market prediction from strategy suitability; best strategy = most compatible with CURRENT regime (not highest theoretical payoff); lower confidence on poor data; no naked selling just because range-bound; respect gamma (esp. near expiry), time of day, and event risk; always prioritise capital preservation over generating a trade.

**Outlook generation + trade-record wiring (2026-09-12):**
- `outlook.py build_outlook()` sets `trades = _trades(conn, date, symbol) if verdict == "TRADE" else []` — a WAIT/AVOID verdict always yields `trades: []` so the AI-GATED TRADE RECORD section never renders for a session the AI did not confirm (JS returns `''` when empty). A historical trade on that date still exists in `history` for reference but is not shown under a wait/avoid verdict.
- `outlook.py` stores the payload to `market_outlooks` with `ON CONFLICT(date, symbol) DO UPDATE`; the 09:30 intraday run overwrites the same-day row, so the API always serves the newest build. `pnl_tracker._latest_gate` reads `date < date_str` (prior-day outlook gates today), so the 09:30 refresh only affects the NEXT session's gate, never today's.
- `outlook.py` CLI: `--date`, `--symbol`, `--webroot`; adds dated pages `market/outlook-{sym}-{date}.html` (static, render via JS from `/api/market-outlook/{date}`).

---

## AdSense (2026-09-11)
- Pub ID `ca-pub-2262405054444130`, auto-ads injected in `<head>` of all pages (after GA tag; learn pages had no GA → after `<meta charset>`).
- Thin-content fix DONE + deployed: 5 policy pages (`about/contact/privacy/terms/disclaimer.html`) with nav + footer links; unique 250–400-word editorial card ("How to read this page") added before `<footer>` on all 34 content pages via `ops/page_content.py` + `ops/insert_content.py`. All 39 pages ≥200 words. sitemap now 37 URLs (policy pages added to `sitemap_gen.py`).
- `pcr_history` populated on VM via `fo_fetcher.py daily` (40 18 * * 1-5 cron); `/api/pcr-history` verified live.
- TODO: user requests AdSense review; Bing Webmaster verification still blocked on user login.
