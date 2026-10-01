# TRENDING_MARKET_PRE_IMPLEMENTATION_AUDIT.md

**Status: AUDIT ONLY — NO IMPLEMENTATION AUTHORIZED. No code, database, API, cron, SEO, or deployment changes were made to produce this file.**
**Date (IST): 2026-09-30. Scope: read-only inspection of `/opt/tradingai` (branch `production-2026-09-26`, HEAD `28b121a`).**

---

## 1. Executive Summary

- TradingAI.in is a deterministic, education-first market-analytics site: Flask API (`app/api/app.py`, gunicorn `127.0.0.1:8000`) + static HTML frontend served by nginx. The authoritative signal path is **market data → scenarios → StrategyEngine → risk → qualification → decision API → JS label mapping (display only)**.
- **Critical naming mismatches vs the feature specs:** there is **no `/api/market-outlook`**, **no `/api/outlook/<symbol>`**, **no `/api/options-intelligence/<symbol>`**, **no `RegimeEngine`**, and **no `build_outlook`** anywhere in the repo (verified by grep). The real equivalents are `GET /api/decision/<instrument>`, `GET /api/<symbol>/summary`, `GET /api/options/<instrument>`, `StrategyEngine` (`app/strategies/engine.py`), `OptionsStrategyEngine` (`app/options/engine.py`), and the master gate `app/core/qualification.py`. Any implementation plan referencing the spec names must be remapped before authorization.
- **No news, global-market, event, or search-trend infrastructure exists.** The only market-data provider is yfinance (`^NSEI`, `^NSEBANK`, `^INDIAVIX`); the NSE option-chain fetcher is dormant (datacenter 403); options provider is `null` (NO_TRADE when options data is required). Every contextual source in the proposal is a brand-new external dependency.
- The clean separation the specs demand (**context explains, never influences**) is architecturally feasible: engines consume only candles/snapshots/scenario/strategy/risk state; the LLM integration is a **dormant stub** (instantiated once, `.explain()` never called, no network, no DB writes); frontend JS only maps labels and never posts back into decisions.
- Working tree is **dirty** (uncommitted modifications predate and include this session, e.g. a display-only closed-market badge fix on 3 pages plus log churn). Nothing was reset, committed, or pushed during this audit.
- **Recommendation: DO NOT authorize implementation until Q1–Q18 (§25) are decided, especially route choice, cache-vs-tables, and the approved source list.** Then proceed only via the additive, read-only, fail-open shape in §18/§27 under the unlock → verify → relock rule.

---

## 2. Current Production Architecture

```
yfinance (^NSEI/^NSEBANK/^INDIAVIX)
  → app/market/provider.py (read-through SQLite cache, TTL quote 45s / candles 90s)
  → app/market/collector.py → market_candles_5m (INSERT OR IGNORE)
  → snapshots/indicators/levels → app/scenarios/engine.py → app/strategies/engine.py
  → app/risk/engine.py → app/core/qualification.py (daily lock, options gate)
  → app/decision/view.py → app/api/app.py (Flask, envelope {state,timestamp,data})
  → gunicorn 127.0.0.1:8000 (2 workers × 2 threads, timeout 90s)
  → nginx: static root frontend/, /api/ proxied (per DEPLOYMENT.md; live nginx config not visible from app host)
  → static HTML + fetch("/api/decision/<INST>") → user
```

- Entry: `start_api.sh` (guarded gunicorn start). Config: `config/{data_sources,instruments,settings,strategies}.json`. Timezone `Asia/Kolkata` everywhere user-facing; hours 09:15–15:30; 2026 NSE holidays encoded (`app/market/nse_calendar.py`, circular CMTR71775).
- Outbound alerts are a separate, already-authorized path: `scripts/tg_alerts.py` (watch */5 9–15 Mon–Fri, eod 15:35) + `data/tg_alerts_archive.jsonl` + `scripts/build_alerts_page.py` → `frontend/alerts.html`. Cron-managed outputs (`frontend/paper.html`, `frontend/backtest.html`, research CSV/JSON) are the only writable pipeline outputs.
- Single-flight fetch guard (`app/market/flight.py`), NSE calendar fail-safe (unknown years → no holiday name; missing feed → NO_DATA/MARKET_CLOSED, never a trade).

### Git verification (read-only; nothing reset/checked-out/committed/pushed)

- `git status --short`: dirty. Modified includes `app/api/app.py`, `app/live/engine.py`, `app/research/cpr_trigger_engine.py`, `frontend/{404,backtest,contact,disclaimer,index,methodology,paper,privacy,terms}.html`, `frontend/indices/{banknifty,nifty}.html`, `frontend/sitemap.xml`, plus `logs/gunicorn-*` churn. (Includes this session's authorized display-only badge change on the 3 outlook pages.)
- `git branch --show-current`: `production-2026-09-26`
- `git log --oneline -20` (tail): `28b121a Sep-28 1406 freeze …` ← HEAD, then `c48e8a8 Sep-28 fix-all + display freeze`, `0502c26 Weekly learning review`, `788b795 Unify live firing onto CPR book`, `9f8d2c8 Methodology…`, `b69e4ea/b69e4ea… Nav Telegram buttons`, `cdfa784/5fcc00d/d98070f Telegram alerts automation`, … down to `8ae523e production snapshot 2026-09-26`.

---

## 3. Current Website/Page Map

- **Live pages: 29** = 27 root + 2 indices (`nifty.html`, `banknifty.html`). Root: `404, affiliate-disclosure, alerts, backtest, bear-call-spread, bull-put-spread, contact, cpr-guide, credit-spreads, disclaimer, expected-move-guide, free-backtesting-tool, how-to-use-cpr-intraday, index, india-vix-guide, learn, max-pain-guide, methodology, narrow-wide-cpr, nifty-support-resistance, option-chain-guide, paper, pcr-guide, privacy, refund-policy, terms, tools`.
- **No FINNIFTY and no SENSEX pages exist** (only `india-vix-guide.html`). Any "FINNIFTY UI work / SENSEX page" referenced in older planning docs is not present as a live page.
- Outlook surface today: `/` (NIFTY + BANKNIFTY cards), `/indices/nifty.html`, `/indices/banknifty.html`. Canonicals: `https://tradingai.in/`, `…/indices/nifty.html`, `…/indices/banknifty.html`. H1s: home "Understand Indian Market Conditions. Learn Before You Decide."; indices pages use visually-hidden H1s ("NIFTY/BANKNIFTY Market Outlook — Conditions and Learning Context").
- `alerts.html` is cron-generated from the Telegram archive (title "Model Alerts Archive — Daily Records, Exits & Outcomes"). `paper.html` / `backtest.html` are cron-regenerated (`paper_confluence --topup` 15:45 Mon–Fri). `tools.html` calculators are local (no API fetch found); `paper.html`/`backtest.html` fetch only `POST /api/backtest/cpr-triggers` client-side.
- Common nav/footer across pages; every page carries the mandatory no-advice notice and footer legal links; subscribe block (`aria-label="Model alert channel"`) exists on exactly the 3 outlook pages (owner-authorized 2026-09-29).

---

## 4. Current Data Sources

| Feed | Provider / symbols | Refresh / TTL | Reliability notes |
|---|---|---|---|
| NIFTY / BANKNIFTY / INDIA_VIX quotes + 5m candles | yfinance `^NSEI`, `^NSEBANK`, `^INDIAVIX`; timeout 10s, retry 3 | Provider cache quote 45s / candles 90s; config cache 5 min; fresh ≤30 min, stale ≤60 min; candle STALE after 900s without a fresh 5m close | 15–60 min delays possible on Indian indices; quote `age_seconds` recomputed at serve time from original ts so cache can never masquerade as fresh |
| Option chain / OI | none (`options.provider: null`); `nse_chain.py` dormant (NSE 403s datacenter IPs) | n/a | System returns NO_TRADE when options data is required; OI/PCR/Max-Pain-from-chain unavailable |
| S&P 500 / Nasdaq / Dow / futures / Asia / GIFT Nifty / crude / USD-INR / US 10Y / gold / macro events / RBI-Fed calendar / news / search trends | **NONE — no code, no config, no cron** | n/a | Every item is a new dependency: needs provider selection, licensing review, rate-limit, hours/timezone, and failure handling |

---

## 5. Current Database/Data Model

- SQLite `database/tradingai.db` (+ `-shm`/`-wal`), schema `database/schema.sql`. Tables: `instruments`, `trading_sessions`, `market_candles_5m`, `market_snapshots`, `market_levels`, `market_indicators` (per DATABASE.md; verify against schema before migration), `volatility_snapshots`, `historical_sessions`, `scenario_definitions`, `scenario_candidates`, `scenario_matches`, (`scenario_confirmations` per docs), `option_contracts`, `option_snapshots`, `trade_candidates`, `qualified_trades`, `daily_trade_locks`, `paper_trades`, `paper_trade_events`, `backtest_runs`, `backtest_decisions`, `backtest_trades`, `backtest_outcomes`, `ai_explanations` (no writers found — dormant), `data_quality_events`, `pipeline_runs`, `system_health`, `research_daily_decisions`, plus runtime-created `provider_cache`, `options_provider_cache`, `live_observations`.
- **No `market_news`, `daily_market_context`/`market_context`, `market_events`, or `market_trending_topics` tables exist.** Flat-file precedent exists instead: `data/tg_alerts_archive.jsonl`, `data/tg_state.json`, `data/generated/india_vix_*.json`.
- States: market data LIVE/STALE/LAST_VALID/PARTIAL/UNAVAILABLE/INSUFFICIENT_DATA/API_ERROR/WAITING (+ quote STALE); trading NOT_ACTIVE/WATCH/PARTIALLY_MATCHED/CONFIRMED/INVALIDATED/EXPIRED/QUALIFIED/NO_TRADE/ACTIVE/CLOSED.

---

## 6. Current API Map

Live routes in `app/api/app.py` (verified; 23 total). Authoritative signal/data routes: `GET /api/health`, `GET /api/<symbol>/summary`, `GET /api/<symbol>/decision`, `GET /api/quote/<instrument>`, `GET /api/decision/<instrument>`, `POST /api/<symbol>/decision/claim`, `GET /api/<symbol>/candles`, `GET /api/<symbol>/paper-trade`, `GET /api/paper/spreads`, `GET /api/paper/spread/today`, `POST /api/backtest/cpr-triggers`, `GET /api/backtest/<run_id>`, `GET /api/backtest/validation/<run_id>`, `GET /api/research/scenarios|/scenarios/<instrument>|/performance|/baseline/<instrument>|/trade/<instrument>/<date>|/replay/<i>/<d>/<t>`, `GET /api/options/<instrument>`, `GET /api/options/strategy/<instrument>`, `GET /api/performance/live|/live/<instrument>`, `GET /api/strategy/cpr-triggers`, `GET /api/strategy/cpr`.
- Response envelope `{state, timestamp, data}`; unavailable data is expressed as explicit states (NO_TRADE / STALE / UNAVAILABLE with reason codes such as `NO_COMPLETED_CANDLE_YET`, `PREMARKET_NO_LIVE_SETUP`), not HTTP 500s.
- **Absent (do not reference as existing):** `/api/market-outlook`, `/api/outlook/<symbol>`, `/api/options-intelligence/<symbol>`, any `/api/market-context`, any news/event/trend endpoint.
- Frontend consumers verified: exactly 3 `fetch("/api/decision/…")` calls (home NIFTY/BANKNIFTY cards, nifty page, banknifty page). No other page calls decision APIs.

---

## 7. Existing Signal Dependency Graph

```
5m candles + quotes (yfinance, IST)
 → validation/normalize/dedupe → market_candles_5m → snapshots/indicators/levels
 → scenario candidates/matching (WATCH/PARTIALLY_MATCHED/CONFIRMED/INVALIDATED)
 → StrategyEngine (scenario+direction+volatility → credit-spread selection)
 → risk engine (entry/stop/target, ≥1.5 R:R, ≤2% risk, ≤4h hold)
 → qualification.py (daily-lock → scenario → strategy → price → risk → options gate)
 → QUALIFIED_TRADE (uuid) or NO_TRADE + reason codes
 → decision/view.py → API → frontend outlookOf/statusOf/badge (DISPLAY ONLY)
```

Inputs that can change regime/bias/confidence/tradeability/range/levels/strategy/scenario: candle OHLCV/timestamps, quote freshness, scenario match state, strategy selection inputs, risk parameters, daily lock, options-data availability gate. Nothing else.
Influence audit (verified, not assumed): **LLM cannot affect outputs** — `AIExplanation` is instantiated once (`app.py:56`) but `.explain()` is never called; it performs no network I/O (stub builds a template string) and writes no DB rows (no `ai_explanations` writers found); `decision/view.py` builds its own deterministic explanation dict. **News/manual/frontend-JS cannot affect outputs** — no news code exists; no POST path from UI into engines except `decision/claim` (lock-claiming, not signal-shaping); frontend only maps `market_bias/regime/volatility_state` → labels and session/status → badges.

---

## 8. Protected/Frozen Components

- `FROZEN` (2026-09-26): entire repo read-only (`444` files / `555` dirs; verified on `.`, `scripts`, `frontend`). Rule: no update without explicit owner authorization per change; unlock → change → verify → relock. Cron-output exceptions only: `frontend/paper.html`, `frontend/backtest.html`, research CSV/JSON (pipeline churn, not code change). Freeze snapshots: `FREEZE_2026-09-26*.md`, `FREEZE_2026-09-28-*.md`, `FREEZE_FULL_2026-09-26-1339.md`, plus `*.frozen-*` / `*.pre-*` baselines in tree.
- Must-not-touch for this feature: all engine/qualification/decision/market/live/scenario/paper-trade/research code; existing API route semantics; DB schema; cron lines; `tg_alerts.py` + archive chain; existing compliance/SEO/test assertions; frozen baselines; secrets (`.tg_env`, 600, gitignored).

---

## 9. Current News/Global-Context Capabilities

> **No existing production news pipeline was found** (no news/RSS/Reuters/feed/parser/summarizer/headline-store code). **No global-market context capability exists** (no US/Asia/GIFT/commodity/FX/yield/event source in code or config). Only India VIX exists as a regular instrument via yfinance. The "trending topics" concept has zero backing store and zero fetcher. All of §12/§13/§14's "current capabilities" answer is therefore: **absent**.

---

## 10. Current SEO Architecture

- `frontend/sitemap.xml`: 28 URLs with lastmod/changefreq/priority (home daily 1.0; indices daily 0.9; paper/alerts daily; guides monthly; legal yearly). `frontend/robots.txt`: `Allow: /`, disallow `*frozen*/*pre-*/*backup*/*removed*`, sitemap pointer (served at `/sitemap.xml` via nginx root mapping).
- Sampled pages carry canonical + OG (`og:type/site_name/url/title/description`) + Twitter card + JSON-LD (`WebSite` on home, `WebPage`+`isPartOf` on nifty). `tests/test_seo.py` enforces the contract; SEO audit/map docs exist (`SEO_AUDIT_BEFORE.md`, `SEO_IMPLEMENTATION_REPORT.md`, `SEO_KEYWORD_URL_MAP.md`, etc.).
- Risk anchor: any new daily NIFTY/BANKNIFTY page must have unique daily content + canonical + structured data + internal links, or it reads as a doorway/duplicate of `/indices/*`.

---

## 11. Current AdSense/Trust Architecture

- Every sampled page contains consent/ads-disclosure wording (sitewide grep hit) and the mandatory no-advice notice; legal pages (disclaimer/terms/privacy/refund/affiliate) exist, are footer-linked, and carry professional-review flags (compliance-enforced).
- **No ad units are deployed** (no `adsbygoogle`/`data-ad` in `index.html`). A future context layer must keep Market Data / Classification / News / Context / Education / Advertisement visually and textually distinct, and must not place ads where they read as signals. (Track B/C freezes, trust headers, nginx ghost guard, and prerender work are cited in planning docs; live nginx/headers were not visible from the app host and are marked unverified.)

---

## 12. Current UI/Layout Architecture

- Card/grid static pages; outlook cards (H3 instrument + meta status line + label pill + Confidence + Observed-inputs + Why-it-may-change + How-to-read + notice); reference-level blocks; footer nav; visually-hidden H1s on indices pages; mobile single-row nav (per history).
- Compliance bans animated trade-ish badges (`tgBlink`/`bullBlink`/etc. — absent, enforced). No trending/context/global sections exist anywhere. Insertion risk: outlook visibility, CLS, card overlap on 375–430px widths, and ad-collision (when ads eventually deploy).

---

## 13. Data Freshness Model

- Hours 09:15–15:30 IST; pre-market → PREMARKET + STALE + `NO_COMPLETED_CANDLE_YET` (badge now "Market Closed" after today's authorized display fix); intraday → LIVE/Delayed by quote age; post-close/weekend/holiday → prior close as latest input, STALE/End-of-day/MARKET_CLOSED or NO_DATA; holidays never produce trades.
- TTLs: quote 45s, candles 90s (cache); config fresh 30 min / stale 60 min; candle STALE after 900s. Cached payloads keep original timestamps; quote age recomputed at serve time.
- **Future context layer needs its own freshness model**: news/events/trends must carry `published_at`/`fetched_at`/TTL and render "Updated X ago"; overnight/weekend context MAY keep operating (unlike the signal engine) provided every item is timestamped and expired items are demoted — decision required (§25 Q9/Q10).

---

## 14. Failure Isolation Analysis

- **A (news down):** no news consumer exists → signal trivially unaffected. Future: context section must render `DATA TEMPORARILY UNAVAILABLE`, signal path untouched. Requirement, not current behavior.
- **B (global provider down):** same as A; no global code exists today.
- **C (LLM down):** already guaranteed — the LLM stub cannot fail the request path (no I/O; deterministic fallback strings in view).
- **D (market-data down):** current rules apply — STALE/UNAVAILABLE/API_ERROR states, NO_TRADE with reason codes, HTTP 200 envelopes; yfinance single-provider is the residual risk (no fallback provider configured).
- **E (context store down):** must degrade to cached-or-absent context with signal live — to be built, not present.
- **F (all context fails):** site must serve existing deterministic functionality — holds today (nothing depends on context); must be preserved by making every context fetch non-blocking with timeouts and never gating signal rendering or `/api/decision/*` on context health.

---

## 15. Data → DB → API → UI → Layout Matrix

| Data | Source | Fetch | Validation | DB | API | Formatter | UI | Layout |
|---|---|---|---|---|---|---|---|---|
| NIFTY price/candles | yfinance ^NSEI | PASS (10s×3, single-flight) | PASS (OHLC/dedupe/session checks) | PASS (`market_candles_5m`) | PASS (`/api/decision/NIFTY`) | PASS (view envelope) | PASS (cards+pages) | PASS |
| BANKNIFTY price/candles | yfinance ^NSEBANK | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| India VIX | yfinance ^INDIAVIX | PASS | PASS | PASS | PASS | PASS | PASS (guide+refs) | PASS |
| PCR | OptionsEngine (chain-gated) | **RISK** (provider null → gate) | PASS (gate→NO_TRADE) | GAP (no chain snapshots) | PASS (explicit unavailable) | PASS | PASS (guides state limits) | PASS |
| Max Pain | OptionsEngine aggregate-intrinsic | **RISK** (same gate) | PASS | GAP | PASS | PASS | PASS | PASS |
| Expected Move | OptionsEngine | **RISK** | PASS | GAP | PASS | PASS | PASS | PASS |
| Regime/bias/confidence | engines+qualification | PASS | PASS | PASS | PASS | PASS | PASS (display map only) | PASS |
| Global cues | — | **GAP** | **GAP** | **GAP** | **GAP** | **GAP** | **GAP** | UNKNOWN |
| News/events | — | **GAP** | **GAP** | **GAP** | **GAP** | **GAP** | **GAP** | UNKNOWN |
| Search trends | — | **GAP** (+ no legitimate source identified) | **GAP** | **GAP** | **GAP** | **GAP** | **GAP** | UNKNOWN |

---

## 16. Duplication Risks

Homepage snapshot vs indices outlook vs proposed daily outlook vs guides vs alerts-archive all overlap on levels/bias/narrative. Verdict: **one canonical context data layer reused by every page** (fetch once, render per template); never per-page fetchers or per-page copies of levels/bias text. New daily pages must add net-new value (dated global cues + events + sourced news + dated summary) or they duplicate `/indices/*` + `/alerts.html`.

---

## 17. Source-of-Truth Risks

NIFTY/BANKNIFTY/VIX price → yfinance pipeline. PCR / Max Pain / Expected Move / strategies → OptionsEngine+chain gate (unavailable when gated — context layer must echo the state, never recompute). Regime/bias/confidence/tradeability/levels → engines+qualification. Signal → decision API. Explanations → deterministic view dicts (+dormant stub). News/global/events/trends → future approved sources only. **Rule: if an authoritative engine owns a value, the context layer displays the engine's value-or-state and computes nothing.**

---

## 18. Proposed Context-Layer Boundary (design only, not built)

```
Market Data ──► EXISTING SIGNAL ENGINE ──► TradingAI Signal ──► UI (unchanged)
                     (engines/qualification/decision APIs — read-only from here)

External context ──► Market Context Layer (NEW, isolated: own fetcher/cache/API/pages)
(Global/news/events/commodities/FX — NEW sources only)      │
                                                            ▼
                                              Context UI (new sections/pages only)
```

Boundary rules: one-way reads of signal state for display; no shared tables for computed values; no shared code paths with engines; separate TTLs/cron; context failure ⇒ `DATA TEMPORARILY UNAVAILABLE` with signal untouched; banned-phrase and no-advice-notice compliance on every new string; LLM (if ever used) = summarization/presentation only, missing data ⇒ explicit unavailable states, never synthesized values.

---

## 19. Proposed API Design (proposal only, not created)

`GET /api/market-context?symbol=NIFTY|BANKNIFTY` → `{symbol, date, updated_at, data_quality: LIVE|STALE|UNAVAILABLE|ERROR, global_context:{status,ssummary,drivers[]}, trending_topics[], news[]({headline,source_name,source_url,published_at,fetched_at,category,relevance}) , events[], summary}`. Non-blocking cached reads; per-item `published_at`/`fetched_at`; invalid symbol → 4xx JSON; partial failures → per-section statuses, never a 500, never fake defaults. Rate-limit and cache headers TBD on approval.

---

## 20. Proposed Data Model (only if flat-file cache is rejected)

Preference: extend the existing flat-file pattern (`data/generated/market_context_YYYY-MM-DD.json` + archive), avoiding migration. If tables are mandated: `market_news(id, source, source_url, headline, summary, category, symbols, published_at, fetched_at, relevance, status; unique(source_url,published_at); retain 30d)`, `market_events(id, title, source, source_url, event_at, fetched_at, category, relevance, status; unique(source,title,event_at); retain 90d)`, `market_context_daily(symbol, date PK, payload_json, data_quality, generated_at)`, `market_trending_topics(id, topic, category, source, source_url, trend_at, relevance, status; unique(topic,source,trend_at); retain 14d)`. Every row needs source+timestamps+status for freshness/expiry/idempotent upserts.

---

## 21. Proposed Daily Outlook Page Structure (structure only, not built)

NIFTY/BANKNIFTY page: H1 + date + updated-ago + data status → Market Snapshot (engine values, read-only) → What moved overnight → Global cues → India events → Sourced news (links out) → TradingAI classification (unchanged block) → Key levels → Options intelligence (states as-is) → Context-vs-signal (careful "may/could" language, no combined scores) → Methodology + disclaimer + internal links. Compatible with education-first positioning only if every section is sourced, dated, and non-directive.

---

## 22. SEO Opportunity Assessment

Supportable with genuine content: "Nifty outlook today / global cues / support resistance", "Bank Nifty outlook / global cues / support resistance", plus news-today variants — **only** as the dated, sourced pages in §21 with canonical/OG/JSON-LD/sitemap/internal-links. Avoid: keyword stuffing, thin auto-generated dailies with no real inputs, and near-duplicate targeting of `/indices/*` (canonical strategy required: either the new pages canonicalize the indices pages for overlapping queries or they must be materially distinct dated briefings).

---

## 23. AdSense/UX Risks

No ad units today, but density/CLS/confusion risks on approval: keep ads out of the signal/context reading flow, never adjacent to buttons in misleading ways, never labeled as information; reserve fixed slots to avoid layout shift from variable-length news lists; long headlines/source names need clamping; missing-data states must hold layout height.

---

## 24. Testing Strategy (+ verification actually performed)

- Gate: full existing suite must pass before/after any future change (433 tests collected via `pytest tests/ --collect-only`).
- **Run during this audit (read-only, no state writes): `tests/test_compliance.py` + `tests/test_seo.py` → 28 passed** (pytest-cache warning only; cache dir not writable — cosmetic).
- **Not run:** the remaining ~405 tests — several exercise live network/yfinance paths and long replays; running them now would be slow and could touch the live DB. A full baseline run must precede any implementation authorization.
- Future validation: §19/§23 matrices (data staleness/duplicates/bad URLs/holidays/timezones; API symbol/partial-failure cases; A–F isolation proofs with signal byte-identical; desktop 1920/1440/1280, tablet 1024/768, mobile 430/390/375 for overlap/overflow/scroll/ads/timestamps/attribution).

---

## 25. Open Questions — Q1–Q18 answered explicitly

- **Q1 Where should Trending Market Information live?** Undecided pending approval; candidates: (a) new homepage section below snapshot cards, (b) new blocks inside `/indices/*`, (c) new dated pages. (a)+(c) preferred; (b) risks outlook crowding.
- **Q2 Reuse market-data infra?** Yes for NIFTY/BANKNIFTY/VIX levels/prices (read-only); no for everything else — no reusable fetcher exists for global/news/trends.
- **Q3 New sources required?** All of them: global indices/futures, GIFT Nifty, crude, USD-INR, yields, gold, macro calendar, news wires, and (if ever) a legitimate trends source. Each needs licensing, rate-limit, hours/timezone, and reliability vetting.
- **Q4 New tables?** Not proven necessary; recommend flat-file cache first. Tables only if retention/query needs demand it (§20).
- **Q5 One template for both dailies?** Yes — one template, symbol-parameterized, like the current indices pages (which share JS structure).
- **Q6 Canonical URLs?** Undecided; do NOT assume `/nifty-outlook/` — must be chosen against existing `/indices/nifty.html` + `/indices/banknifty.html` with a duplicate-content plan.
- **Q7 Display without affecting signal?** Yes via §18: separate fetcher/cache/API/UI, read-only signal display, no shared compute or tables.
- **Q8 News failures isolated?** Achievable (fail-open sections, timeouts, no gating) but must be proven by A–F tests pre-release.
- **Q9 Operate outside 09:15–15:30?** Technically yes for context (dated global/news content), signal engine keeps its own hours; policy decision required.
- **Q10 Freshness model?** Per-item `published_at`/`fetched_at`/TTL + "Updated X ago"; expired items demoted, never presented as current.
- **Q11 Define "trending"?** No search-volume source exists: label must be "Trending market topics / current market themes" (coverage-based, sourced, timestamped) — never claim Google rank/volume.
- **Q12 SEO without doorway risk?** Only via materially distinct dated briefings (§21/§22); otherwise do not create the pages.
- **Q13 UI changes?** New sections/pages only; no restyling of signal blocks; 2–3 placement options with consequences in §10/§12.
- **Q14 Data-validation tests?** Sources on/off, stale, duplicates, bad URLs, holidays, timezones, market-closed states.
- **Q15 Layout tests?** §24 breakpoint/state matrix incl. missing-data and ad-collision states.
- **Q16 Accidental duplication?** Snapshot/outlook/daily/guides/archive (§16) — mitigated by one canonical context layer.
- **Q17 Untouched components?** §8 list (engines, qualification, decision, market, live, scenarios, paper-trade, research, existing API semantics, schema, cron, tg/archive chain, compliance/SEO/tests, baselines, secrets).
- **Q18 Smallest safe architecture?** One fetcher + one cache + one read API + one template + one cron, all additive, all fail-open (§27 phase 1–2 only).

---

## 26. Implementation Risks

Spec/repo name mismatches (§1) causing wrong integration targets; compliance failures from news/outlook wording; SEO doorway/duplicate penalties; frozen-repo process violations; new-source reliability/licensing/copyright; LLM boundary leakage; cron overlap with the 09–15 watch window; secret handling; scope creep into signal logic; dirty-tree baseline confusion (uncommitted changes predate this audit).

---

## 27. Recommended Implementation Sequence (gated; not started)

1. Freeze exception + full test baseline (433) + decisions on Q1–Q18. 2. Read-only context fetcher + flat-file cache (no API/UI). 3. Additive `/api/market-context` + A–F isolation proofs. 4. One template + homepage section behind existing compliance/SEO gates. 5. Idempotent daily cron + freshness/expiry. 6. Full regression + layout matrix + docs (`IMPLEMENTATION/TEST_REPORT/DATA_SOURCES`). Each phase requires re-authorization; any signal-logic touch aborts the track.

---

## 28. Explicit "NO CODE CHANGES MADE" confirmation

**Code changes: NONE. Database changes: NONE (no reads beyond audit greps and the pre-existing live API; no writes). API changes: NONE. Signal logic changes: NONE. Cron changes: NONE. SEO changes: NONE. Deployment: NONE (no restarts, no deploys, no config edits). Tests modified: NONE (two read-only suites executed: 28 passed; collection-only run: 433). Git: no reset/checkout/commit/push (tree left exactly as found, dirty). The sole filesystem addition after this section is this audit file itself, created under explicit authorization.**
