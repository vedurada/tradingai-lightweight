# TradingAI.in — Compliance Presentation Audit (presentation-only, 2026-09-28)

Source of truth: production filesystem on VM (`/opt/tradingai`), live files only
(frozen `*.frozen-*` / `*.pre-*` / `*.backup*` copies were NOT edited and are excluded from serving via robots `Disallow`).

Objective restated: present TradingAI.in consistently as an **automated, standardized,
non-personalised market-research/model-signal platform for Indian index-options traders**,
without changing the trading engine.

## 1. Pages audited

| URL/path | File | Purpose | Risk before | Change | Presentation-only |
|---|---|---|---|---|---|
| `/` | `frontend/index.html` | A. Live model hub (NIFTY/BANKNIFTY/VIX cards) | HIGH — "Recommended Strategy", "Market Direction", "Market Insights \| Smart Setups \| Better Trades", "Follow the recommended strategy", no non-personalised notice near output | Standardized title/meta/h1/tagline; Model Strategy; Model Direction; model-notice + CTA strip (View Live Signals / Join Telegram Alerts / View Historical Performance); detail rows renamed | Yes |
| `/indices/nifty.html` | `frontend/indices/nifty.html` | A. NIFTY live model page | HIGH — "NIFTY 50 Decision", "CURRENT DECISION", "RECOMMENDED STRATEGY", "TRADE SETUP", "WHY THIS DECISION?", no explicit non-personalised block | "NIFTY — Current Model Output"; CURRENT MODEL OUTPUT; MODEL STRATEGY STRUCTURE / NO MODEL SETUP; MODEL SETUP; WHY THIS MODEL OUTPUT?; full + compact non-personalised notices; setup/strategy row labels → Model labels | Yes |
| `/indices/banknifty.html` | `frontend/indices/banknifty.html` | A. BANKNIFTY live model page | HIGH — same as NIFTY | Same framework as NIFTY | Yes |
| `/backtest.html` | `frontend/backtest.html` | B. Research/backtest runner | MEDIUM — "Win rate" bare, "CPR Trigger Backtest/Result", no hypothetical banner near stats | "Historical CPR Trigger Backtest — Hypothetical Model Results"; hypothetical + underlying/index-based banner; "Historical winning-trade percentage"; "Historical Model Trades" + decay note | Yes |
| `/paper.html` | `frontend/paper.html` | B. Paper/hypothetical ledger + live spreads | MEDIUM-HIGH — "Paper Trades", "Live Paper Spreads", "Win rate" bare | "Live Model Spread Structures (Hypothetical Model Trades)"; "Live Model Spread Structures" + hypothetical/research-only banner; "Historical winning-trade percentage"; "CPR Align Hypothetical Model Trades" | Yes |
| `/methodology.html` | `frontend/methodology.html` | B+C. Methodology + education (also serves as strategy guide; no separate builder/guide pages exist) | MEDIUM — "Recommended Strategy", "How a trader benefits", "Live Paper Spreads", entries/stops as trader instructions | Standardized positioning block (standardized/same-rules/no-user-data/no-portfolio/no-funds/no-execution); "Model Strategy Structure"; "How the model output is interpreted"; "Live Model Spread Structures"; "predefined model rules for hypothetical/research evaluation"; illustrative-example labels | Yes |
| `/disclaimer.html` | `frontend/disclaimer.html` | D. Legal disclaimer | LOW (already good: no-advice, SEBI/NSE non-registration) — strengthened | Added Phase-14 structure paragraph (automated/rules-based, standardized non-personalised, no advice/portfolio/execution/funds, no guarantees, hypothetical, options risk, user responsibility, no self-certification of compliance). Date 28 Sep 2026 | Yes |
| `/terms.html` | `frontend/terms.html` | D. Terms of use | LOW — strengthened | Added research/model-output statement + does-not list (advice/money/execution/returns/accuracy/brokerage). "Win rates" → "Historical winning-trade percentages". Date 28 Sep 2026 | Yes |
| `/contact.html` | `frontend/contact.html` | D. About/contact | LOW (already: no brokerage/money/personalised advice) | About → "independent, automated, rules-based market research and model-signal platform for Indian index-options traders"; meta description aligned | Yes |
| `/privacy.html` | `frontend/privacy.html` | D. Privacy | LOW — no advisory claims | No content change (footer inherits nothing; verified) | N/A |
| `/404.html` | `frontend/404.html` | E. Error page | LOW | No change | N/A |
| `/sitemap.xml`, `/robots.txt` | `frontend/sitemap.xml`, `robots.txt` | E. SEO/crawl | LOW | sitemap lastmod 2026-09-26 → 2026-09-28 | Yes |
| Telegram templates | `scripts/tg_alerts.py` | A. Telegram alert UI/copy | HIGH — bare "Entry \| Stop / Strategy" alerts, no standardized non-personalised footer | Standardized TRADINGAI MODEL ALERT / MODEL UPDATE / MODEL LEVELS / MODEL EOD with Model Direction/Strategy Structure/Trigger/Invalidation/Target Reference/Status + required footers (text/template only) | Yes |
| API text | `app/api/app.py`, `app/decision/view.py` | Engine/contract | — | NOT changed (response contracts preserved) | N/A |

Notes:
- No separate `strategy builder`, `strategy guide`, `FAQ`, `README/help` public pages exist in `frontend/` — methodology covers education; strategy-builder statement (Phase 13) has no page to attach to. Flagged in §7.
- `VIX` card on homepage is volatility-regime only by design (no strategy) — preserved.
- Static marketing/social content: only meta/OG/Twitter + footer + CTA copy found; no separate social image copy. Banners/CTAs standardized.

## 2. Files changed

- `frontend/index.html`
- `frontend/indices/nifty.html`
- `frontend/indices/banknifty.html`
- `frontend/backtest.html`
- `frontend/paper.html`
- `frontend/methodology.html`
- `frontend/disclaimer.html`
- `frontend/terms.html`
- `frontend/contact.html`
- `frontend/sitemap.xml`
- `scripts/tg_alerts.py`
- Backups in `/tmp/*.bak_compliance` (index, nifty, banknifty, backtest, paper, methodology, disclaimer, terms, contact, sitemap, tg_alerts).

## 3. Files intentionally NOT changed

- Live/trading engine + math: `app/live/*`, `app/research/cpr_trigger_engine.py`, `app/research/cpr_strategy_engine.py`, `app/research/backtest.py`, `app/research/live_sim.py`, `app/research/replay.py`, `app/market/*`, `app/options/*`, `app/paper_trade/*`, `app/strategies/*`, `app/scenarios/*`, `app/risk/*`, `app/decision/view.py`, `app/api/app.py`, `app/core/*`, `app/observability/*`
- Market-data provider, live engine, database schema + records (`database/tradingai.db*`, `database/schema.sql`), API response contracts, signal timing, Telegram trigger logic/timing, strike/200pt-spread logic, cron/systemd (`tradingai-api.service`), gunicorn, nginx (`/etc/nginx/sites-enabled/*`).
- Frozen/pre backups (`*.frozen-*`, `*.pre-*`, `*.backup*`, `*.removed-*`), generated/static binaries, `.tg_env`, `data/tg_state.json`.
- `frontend/privacy.html`, `frontend/404.html`, `frontend/robots.txt`, configs (`config/*.json`).

## 4. Wording changes (Before → After)

- "Market Insights | Smart Setups | Better Trades" → "Live CPR-Based Model Signals for Indian Index-Options Traders" (title/tagline/h1/meta, index)
- "Decision-first intraday dashboard: … recommended strategy and Trade/Wait/No Trade from the TradingAI engine." → "Live NIFTY & BANKNIFTY model signals … CPR-based automated market analysis with Bull Put and Bear Call credit-spread model structures…" (meta/OG/Twitter)
- "🎯 Today's Focus / Follow the recommended strategy…" → "Live NIFTY & BANKNIFTY Model Signals / CPR-based automated market analysis…" + CTA strip: View Live Signals / Join Telegram Alerts / View Historical Performance
- "Recommended Strategy" → "Model Strategy" (home cards + methodology reference)
- "Decision detail (engine values)" → "Model detail (model values)"
- "Market Direction" → "Model Direction" (labels + JS `Model Direction ↗/↘/→`)
- "Why: … Engine qualified … Entry X, stop Y, target Z" → "Model output: … Model qualified … Model trigger X, model invalidation Y, model target reference Z"
- Detail rows "Trigger/Entry/Invalidation/Target" → "Model Trigger / Model Entry Reference / Model Invalidation / Model Target Reference"
- "NIFTY 50 Decision / BANKNIFTY Decision" → "NIFTY/BANKNIFTY — Current Model Output"; "CURRENT DECISION" → "CURRENT MODEL OUTPUT"; "RECOMMENDED STRATEGY" → "MODEL STRATEGY STRUCTURE"; "TRADE SETUP" → "MODEL SETUP"; "WHY THIS DECISION?" → "WHY THIS MODEL OUTPUT?"
- Setup/strategy rows → "Model Strategy Structure / Model Direction / Model Setup / Model Trigger / Model Entry Reference / Model Invalidation / Model Target Reference / Model Risk/Reward"
- Added near-output notices: full "Automated model output based on predefined market rules. It is not personalised to your financial circumstances, objectives, portfolio or risk tolerance." + compact "Automated, non-personalised model output — not personalised investment advice."
- "CPR Trigger Backtest / CPR Trigger Result / Win rate" → "Historical CPR Trigger Backtest — Hypothetical Model Results / Historical Model Results / Historical winning-trade percentage" + hypothetical + underlying/index-based banners
- "Paper Trades / Live Paper Spreads / Win rate / CPR Align Paper" → "Live Model Spread Structures (Hypothetical Model Trades) / Live Model Spread Structures (+ hypothetical/research-only banner) / Historical winning-trade percentage / CPR Align Hypothetical Model Trades"
- Methodology: added standardized positioning block; "Recommended Strategy" → "Model Strategy Structure"; "How a trader benefits" → "How the model output is interpreted"; "Benefit: … entries, stops…" → "Model interpretation: predefined model rules … model trigger/invalidation/target references…"; "Live Paper Spreads" → "Live Model Spread Structures"; "Worked/Payoff example" → "Worked/Payoff illustrative example"
- Footer "Smarter Analysis. Disciplined Trading." → "Live CPR-based model signals for Indian index-options traders…" (+ non-personalised note on instrument pages)
- Link cards: "NIFTY/BANKNIFTY Analysis (OI, PCR, setup)" → "NIFTY/BANKNIFTY Model Output (Model levels, CPR, model setup)"; "Backtest / Check past performance" → "Historical Performance / See complete historical signal performance — historical results do not guarantee future performance"; "Our strategy & approach" → "Model rules & approach"
- Disclaimer/Terms/Contact per §§14–16 (see file diffs); sitemap lastmod bump.

## 5. Telegram changes (Before → After; logic/timing/strikes untouched)

- Test: "🔧 TradingAI alerts online. Morning levels, intraday TRADE signals and EOD recaps…" → "🔧 TradingAI model alerts online. Morning model levels, intraday model signals and EOD model recaps… Automated, standardized model output. Not personalised investment advice…"
- Morning: "📊 CPR LEVELS" → "📊 TRADINGAI MODEL LEVELS"; "Live decisions from 09:15" → "Live model signals from 09:15" + standardized footer.
- Signal (was `"{emoji} {INST} ({DIR})\nEntry X | Stop Y\nStrategy: …"`): now
  `TRADINGAI MODEL ALERT / {INST} / Model Direction / Model Strategy Structure / Model Trigger / Model Invalidation / Model Target Reference / Model Status: ACTIVE / footer: Automated, standardized model output. Not personalised investment advice. Verify current market conditions and option prices independently…`
  (Target added from existing `trade.target` field for display only; no calc change. No BUY/SELL/ENTER imperatives.)
- Exit (was `"{em} {INST} ({DIR}) CLOSED — {reason}\nEntry X\nStrategy: …"`): now
  `TRADINGAI MODEL UPDATE / Instrument / Model Status: CLOSED — {reason} / Model Outcome / Model Strategy Structure / footer: Hypothetical/model output for research purposes. Not personalised investment advice.`
- EOD: "🔔 EOD … Full ledger … Posted win or lose. Educational research only" → "🔔 TRADINGAI MODEL EOD … Full hypothetical ledger … Hypothetical/model output for research purposes. Not personalised investment advice."
- `spread_name()`, `resolve_reason()`, polling/dedup/state keys, NAV buttons unchanged.

## 6. Marketing changes (Before → After)

- No "best/high accuracy/guaranteed/profit/sure-shot/no loss/100%/make money/easy profits/AI prediction" claims were found in live files — none to remove. Verified via recursive search.
- Reframed remaining promotional-adjacent copy factually: "Check past performance" → historical-performance wording + "historical results do not guarantee future performance"; "Win rate" → "Historical winning-trade percentage"; payoff zones kept as "profit zone/loss zone" only inside explicitly-labelled educational illustrations with "Illustrative premiums, not live".
- Social/SEO: titles/descriptions/OG/Twitter rewritten to audience + structure keywords (Indian index-options traders, NIFTY, BANKNIFTY, CPR, Bull Put/Bear Call, credit spread, live model signals, Telegram alerts, historical model performance) with no accuracy/profit guarantees. Preferred social description applied via meta/OG.
- No genuine historical statistics deleted.

## 7. Remaining compliance-sensitive areas (RED/AMBER)

- AMBER: No dedicated Strategy Builder page exists — Phase-13 calculator disclaimer has nowhere to live. If a builder is added later, include: "This calculator is an educational/planning tool. It does not determine whether a strategy is suitable for any individual user and does not provide personalised investment advice." (No calc change needed now.)
- AMBER: Paper ledger columns still show Entry/Exit Price/Points/Win-Loss on underlying moves — correctly contextualized as hypothetical/underlying-based, but a first-time reader could still skim numbers without the banner. The banner is directly above; no data deleted per instructions.
- AMBER: API JSON field names (`strategy`, `trigger`, `entry_zone`, `target`, `win_rate`) are unchanged by design (contract freeze) — UI relabels them as Model references; raw API consumers still see engine names. Acceptable, but note for review.
- AMBER: `contact.html` email is a personal Outlook address; methodology payoff SVGs show "PROFIT/LOSS" inside explicitly educational illustrations (preserved as legitimate educational context).
- RED (none created): wording changes do NOT constitute legal/regulatory approval. SEBI registration NOT claimed/invented; NSE non-affiliation preserved; no "SEBI compliant/approved / legally compliant / guaranteed safe" statements made.
- Manual review URLs: `/`, `/indices/nifty.html`, `/indices/banknifty.html`, `/backtest.html`, `/paper.html`, `/methodology.html`, `/disclaimer.html`, `/terms.html`, `/contact.html`, Telegram channel `@tradingai_cpr` (send `--test` only if owner approves a public test message).

## 8. Trading-engine regression

Identical before/after (presentation-only confirmed):
- Pre: NIFTY `TRADE BEAR Bear Call Spread TC 23124.2751 BC 23091.8252 trigger=…entry 22949.5 stop 23064.25 target 22490.51`; BANKNIFTY `TRADE BEAR Bear Call Spread TC 55576.2741 BC 55568.0254 entry 54941.4 stop 55216.11 target 53842.57`.
- Post: identical values re-polled (NIFTY + BANKNIFTY TRADE/BEAR, same CPR/trigger/stop/target).
- Backtest NIFTY aligned 2026-07-29→2026-09-25: pre `signals 38 days 42 losses 11` → post `signals 38 days 42 losses 11 wins 27`. No numerical/model change.
- DB untouched (no writes by edits; `tg_alerts.py` logic/state format unchanged).

## 9. Test results

- `node --check` on extracted inline scripts for all 11 HTML files: PASS.
- `python3 -m py_compile scripts/tg_alerts.py`: PASS; `spread_name`/`resolve_reason` pure-function smoke test: PASS.
- HTTP (production nginx): `/`, `/indices/nifty.html`, `/indices/banknifty.html`, `/backtest.html`, `/paper.html`, `/methodology.html`, `/disclaimer.html`, `/terms.html`, `/privacy.html`, `/contact.html`, `/sitemap.xml`, `/robots.txt` → all `200` (desktop + iPhone UA spot-check).
- API: `/api/decision/nifty`, `/api/decision/banknifty` reachable; NIFTY/BANKNIFTY data renders (TRADE/BEAR payloads); CPR values unchanged (§8).
- Backtest API + paper ledger endpoints reachable; ledger row counts/stats unchanged.
- Telegram: generation functions verified; NO live `--test/--morning/--watch/--eod` sends performed (avoid unsolicited channel messages) — content verified by code review + py_compile.
- Links: internal nav (Home/Nifty/BankNifty/Backtest/Paper/Disclaimer/Terms/Privacy/Contact/Methodology) + Telegram `telegram.me/tradingai_cpr` verified present on each page.
- Metadata: titles/descriptions/OG/Twitter/canonical verified per page.
- Final recursive search for prohibited phrases: only legitimate legal/educational contexts remain (`…not personalised investment advice`, `…not a recommendation to buy/sell…`, `…not personalised recommendations`); zero promotional/actionable occurrences.
- Mobile/desktop: viewport + responsive `@media` CSS retained; compact `.model-notice` banner verified non-dominant; layout smoke-tested via HTTP size + markup checks (full visual QA recommended on device).

---
Conclusion: **Presentation and messaging have been aligned toward a standardized, automated, non-personalised model-output framework; legal/regulatory classification requires professional review.**

## ADDENDUM 2026-09-28 (15:20 EOD + alert upgrades — owner-approved engine change)

Owner explicitly approved overriding the earlier engine freeze for one item:
intraday flat moved from the **15:10 opening candle to the 15:20 opening candle**.

Engine/code changes (all else frozen):
- `app/research/cpr_trigger_engine.py`: `OPEN_MAX`/`OPEN_EOD` → `15:20`;
  signal scan `< 15:15` → `< 15:25`; entry window `[09:20,15:10)` → `[09:20,15:20)`;
  flat/missing-EOD + stop-at-EOD-open labels → 15:20; `EOD-1510` → `EOD-1520`.
- `app/live/engine.py`, `app/api/app.py`: rule copy → 15:20 (logic inherits constants).
- `scripts/paper_confluence.py`: EOD candle/label/copy → 15:20 (`EOD-1520`,
  display replaces handle both labels for backward compat).
- `scripts/tg_alerts.py`: `resolve_reason` EOD cutoff `15:10` → `15:20`;
  exit alerts now carry `Exit Reference` + signed `Points` (BULL exit−entry,
  BEAR entry−exit); exit sweep persists `closed` records; `do_eod` summarizes
  today's actual outcomes (direction/entry→exit/points/strategy) instead of the
  post-close decision (which wrongly printed NO TRADE on 28 Sep).
- Frontend rule copy (methodology/backtest/paper + generator template) → 15:20.
  Frozen historical ledger rows (actual 15:10 exits) were NOT rewritten.
- Cron (owner-requested EOD alert): added
  `35 15 * * 1-5 … tg_alerts.py --eod` (EOD recap now automatic; `--morning`
  still unscheduled).

Verification:
- `py_compile` on all touched Python files: PASS.
- Targeted pytest (`cpr_triggers`, `unified_book`, `phase5`, `phase45`):
  68 passed, 1 failed — `test_unique_daily_lock_constraint` (expects
  `idx_daily_trade_lock` on `daily_trade_locks`; schema defines it on
  `qualified_trades`). Pre-existing, unrelated to this change.
- Backtest NIFTY aligned 2026-07-29→09-25: was signals 38 W27 L11
  (EOD-1510) → now signals 37 W26 L11 with 33 `EOD-1520` exits. Expected
  shift from the later flat; no other logic touched.
- `tradingai-api` restarted, active; live decision sane (NO TRADE/MARKET_CLOSED
  post-close); homepage/methodology serve 200 with 15:20 copy.
## ADDENDUM SEO 2026-09-28: static crawlable SEO section + noscript on home/nifty/banknifty; new /cpr-guide.html + /credit-spreads.html (visible H1, canonical/OG/Twitter, educational + non-personalised notices); homepage link cards + sitemap entries. No engine/data changes.
## ADDENDUM wording 2026-09-28: owner-approved rule(s)-based -> algorithmic in contact/methodology/disclaimer user copy (AI-based declined as factually unsupported; model-rules phrases kept as accurate).
## ADDENDUM SEO hub 2026-09-28: 6 new compliant guide pages (narrow-wide-cpr, how-to-use-cpr-intraday, nifty-support-resistance, bull-put-spread, bear-call-spread, free-backtesting-tool) + homepage guides links + sitemap 18 URLs. No prediction/AI claims; no engine changes.
