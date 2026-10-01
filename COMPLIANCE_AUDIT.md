# TradingAI.in — Compliance Audit Report (Task 1)

Scope: all live (non-frozen) frontend pages, routes, nav/footer links, buttons,
cards, JS user-facing strings, titles, meta/OG/Twitter copy, JSON-LD.
Backend/API/DB inspected read-only only to classify exposure (no changes).
Date: 2026-09-29. Baseline commit: `28b121a` (branch `production-2026-09-26`).

Mandatory notice (reused below, exact text from owner brief):
> “TradingAI.in provides general educational market information based on
> predefined rules and public data. This content does not consider your
> financial circumstances, objectives, or risk profile. It is not investment
> advice, a research recommendation, or an instruction to buy, sell, or hold
> any security or derivative.”

Risk levels: Keep / Rewrite / Remove / Manual review.

## A. Site-wide elements (all pages)

| # | Location | Existing wording/functionality | Risk | Reason | Replacement / implementation |
|---|---|---|---|---|---|
| A1 | Main nav, all pages: `Join Telegram` button (`tg-join`, blinking) | CTA to t.me/tradingai_cpr trade-alert channel | Remove | Alert channel delivers entry/exit trade instructions (forbidden channel) | Delete link from every nav; no replacement CTA |
| A2 | Footer legal trio (Privacy/Contact/Terms) + Disclaimer on some | Incomplete legal set | Rewrite | Missing Risk Disclosure prominence, Refund, Affiliate, About, Learn, Methodology links | Standard footer: About, Methodology, Learn, Tools, Risk Disclosure, Terms, Privacy, Refund Policy, Affiliate Disclosure, Contact |
| A3 | Blinking bull/bear animations (`bullBlink`, `tgBlink`, dir pills) | Flashing BUY/SELL-style direction badges | Remove | Actionable direction emphasis; flashing trade cues | Neutral static outlook labels with text (green/red/grey/amber + words) |
| A4 | Titles/metas/OG/Twitter with “Model Signals”, “Paper Trades”, “Current Model Output” | Signal/call marketing language in SEO | Rewrite | Implies trading instructions; contradicts education positioning | Outlook/education titles (see Task 8 list) |
| A5 | JSON-LD WebPage/Article names with “Model Signals” | Same as A4 in structured data | Rewrite | Same | Mirror new titles |
| A6 | `api-offline.json`, gtag analytics | Analytics only, no trade function | Keep | No advice/notifications; analytics explicitly preservable | Keep unchanged |
| A7 | Telegram alert crons (`tg_alerts.py --watch` every 5 min, `--eod`) | Push entry/exit trade alerts to Telegram | Remove (disable) | Core forbidden notification flow | Comment out both cron lines; keep script file unscheduled; document |
| A8 | `scripts/tg_alerts.py` (289 lines, Telegram Bot API sender) | Sends position instructions | Manual review | File retained but dead after A7; owner to decide delete vs keep-for-audit | Leave file, remove from cron; report |

## B. Homepage (`/`, `index.html`)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| B1 | H1 “Live NIFTY & BANKNIFTY model signals…”, H2 “Live NIFTY & BANKNIFTY Model Signals” | Rewrite | “Signals” implies trade calls | H1 per brief: “Understand Indian Market Conditions. Learn Before You Decide.” + positioning subheadline |
| B2 | Live direction pills (Model Direction BULLISH/BEARISH), strategy names, “View Details →” | Rewrite | Buy/sell direction + actionable strategy | Outlook cards: outlook label + confidence + observed inputs + why-may-change + how-to-read + mandatory notice |
| B3 | NIFTY/BANKNIFTY/VIX cards only (no FINNIFTY/SENSEX) | Rewrite | Required 5-instrument grid | Add FINNIFTY + SENSEX cards as “Insufficient Data — coverage planned” (honest, no fabricated data) |
| B4 | About paragraph: “model signals… Bull Put/Bear Call… entry… Telegram” | Rewrite | Signals/entries/alerts language | Education positioning paragraph + deterministic-boundary sentence |
| B5 | Link cards “NIFTY Today — Intraday Outlook”, “Historical Performance” with win-rate framing | Rewrite | Outlook okay; performance marketing not | “Market Outlook”, “Historical Scenario Analysis” (results ≠ future), Methodology, Tools, Learn cards |
| B6 | “Hypothetical paper ledger”, backtest stats | Rewrite | P&L-as-marketing | Point to Historical Scenario Analysis + Model Observations journal with hypothetical labeling |

## C. Instrument pages (`/indices/nifty.html`, `/indices/banknifty.html`)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| C1 | H1/title “NIFTY Today — Intraday Market Outlook” (keep intent), live bias pills, MODEL STRATEGY STRUCTURE w/ spread legs, MODEL SETUP (trigger/invalidation/target), strike notes | Rewrite | Current strike/direction/entry/target/stop exposure | “NIFTY Market Outlook”: outlook card (label, confidence, observed inputs, why-may-change, how-to-read, notice); keep price/CPR chart/levels/timeline as data viz; DELETE strategy-structure, setup, trigger, invalidation, target, live-spread sections |
| C2 | “ABOUT THIS…” + levels/options-intel paragraphs | Rewrite | Contains “model signals”, spread-trade framing | Education framing + links to Learn guides; keep factual level descriptions |
| C3 | WHAT TO WATCH / WHY lists fed by reason codes incl. trigger/invalidation text | Rewrite | May render trade instructions from `explanation`/`trigger` fields | Render ONLY safe fields: bias→outlook label, regime, vwap_relation, CPR position/type, gap, volatility, breadth (if present), timestamps, prices; never `decision/entry/invalidation/strategy/target/trade/trigger` |
| C4 | Canonical `/indices/nifty.html` etc. | Keep | Correct | Keep |

## D. Methodology (`methodology.html`)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| D1 | §3 “How a strategy enters — the exact rules” (entry at next open, stop/target) | Rewrite | Entry/stop/target instructions | “How rule-based classifications are computed” — observational inputs + classification table; no entry/stop/target framing |
| D2 | §8/§10 payoff examples with “Max profit +₹3,900… Winners ride… edge” | Rewrite | Profit marketing + edge claims | Educational illustrations: structure, theoretical payoff shape, break-even concept, maximum theoretical loss, risk factors; “illustrative premiums, not live, not a recommendation” |
| D3 | §11 Telegram alerts (entry/exit alerts post here) | Remove | Forbidden notification flow | Delete section; replace with “No alerts” transparency note: TradingAI.in does not send trade alerts by any channel |
| D4 | Title/H1 “Methodology/How TradingAI works” | Rewrite | Add outlook-label definitions, sources, refresh, timezone, missing-data, limitations, version history, no-prediction statement (Task 6.2) | Expanded methodology per spec |
| D5 | “Bull Put vs Bear Call… when each model structure is used” | Rewrite | Implies current-use instruction | “Structures researchers often study; general conditions studied historically; not a suggestion to use today” |

## E. Backtest (`backtest.html`)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| E1 | Title/H1 “Historical Backtest — Hypothetical Model Results” | Rewrite | Rename per 5C | “Historical Scenario Analysis — Hypothetical Backtest Explorer” |
| E2 | Win/Loss columns, win-rate cards, “Wins/riding” framing, R multiples as performance marketing | Rewrite | Win-rate/P&L marketing; implies future results | Neutral outcome columns (“reference outcome: above/below”), methodology + cost/slippage/liquidity assumptions + drawdown + limitations; “historical ≠ future” notice |
| E3 | “Run CPR trigger backtest” form (user picks instrument/variant/dates) | Keep (rewrite labels) | User-controlled historical analysis is allowed | Keep; relabel “Explore historical scenarios”; keep hypothetical labeling |
| E4 | Related-research card | Keep | Fine | Keep; update anchors if renamed |

## F. Paper (`paper.html` + generator `scripts/paper_confluence.py` template)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| F1 | Live spread cards (current Bear Call/Bull Put legs, strikes, expiries) + auto-refresh | Remove | Real-time actionable strategy instruction w/ current strikes | Delete live-spread section from template |
| F2 | Align ledger: Direction BEAR/BULL, entry/exit prices, WIN/LOSS colored, strategy names | Rewrite | Direction + prices + win/loss read as trade calls/P&L marketing | “Historical Model Observations”: date, instrument, observed-state reference, session context; hypothetical + notice; no colored WIN/LOSS badges (neutral text) |
| F3 | “Paper Trades — … Model Signals” title/H1/meta | Rewrite | Signals language | “Historical Model Observations (Hypothetical) |
| F4 | DB/API fields (`signal, entry, target, stop_loss…`) | Manual review | Must not surface in public UI/notifications/SEO | UI already being scrubbed; cron logging (historical record) continues — allowed as historical analytics; Telegram exposure removed via A7 |

## G. Spread/strategy guides (`bull-put-spread`, `bear-call-spread`, `credit-spreads`)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| G1 | “how bullish/bearish model signals use it”, payoff “Max profit +₹…” | Rewrite | Current-use instruction + profit framing | Pure learning: structure, payoff mechanics, theoretical max loss, break-even concept, risk factors, “often studied when…” (no today-direction) |
| G2 | Payoff numbers (illustrative premiums) | Keep (relabeled) | Allowed as educational illustration | Keep numbers, label “Educational illustration with assumed premiums — not live prices, not a recommendation” |

## H. Knowledge guides (CPR/VIX/PCR/MaxPain/EM/chain/S-R/intraday/narrow-wide/tool)

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| H1 | “entry”, “trigger”, “first trigger wins”, “how TradingAI turns CPR into signals” | Rewrite | Entry/signal instruction language | Observational equivalents (“first classified observation”, “how the model classifies context”); keep all educational substance |
| H2 | “guarantee” occurrences (all in “no guarantee” disclaimers) | Keep | Compliant usage | Keep |
| H3 | Honesty constraints (Max Pain not computed; snapshots when reachable) | Keep | Required transparency | Keep |

## I. Legal/company pages

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| I1 | `disclaimer.html` (risk disclaimer) | Rewrite | Upgrade to full Risk Disclosure (Task 6.1: worthless-expiry, leverage, delays, responsibility) | Expanded page, keep URL (add canonical stability), H1 “Risk Disclosure” |
| I2 | `terms.html`, `privacy.html` | Rewrite | Add educational-purpose/no-advice/no-solicitation, liability, placeholders; privacy: payments/data-rights sections | Expanded per Task 6.3/6.4 |
| I3 | `contact.html` (“About TradingAI.in”, signal positioning) | Rewrite | About positioning + signal language | About content: education positioning, no-advice statement, contact placeholder |
| I4 | Missing: Refund Policy, Affiliate Disclosure, Learn hub, Tools page | Remove (n/a) / Create | Required by Tasks 4/6/7 | Create `refund-policy.html`, `affiliate-disclosure.html`, `learn.html`, `tools.html` |

## J. JS strings / dynamic text

| # | Existing | Risk | Reason | Replacement |
|---|---|---|---|---|
| J1 | `dir-pill` BULLISH/BEARISH rendering, “Model Direction”, “Model Strategy”, strike notes, “Connecting…” | Rewrite | Direction/strategy directives | Outlook-label renderer w/ enum (Bullish…Insufficient Data) + confidence + observed-inputs list; unavailable-state fallbacks |
| J2 | Paper live-spread fetcher (`/api/paper/spread/today`) | Remove | Feeds actionable UI (F1) | Delete fetcher + section |
| J3 | Backtest runner JS (form → `/api/backtest/cpr-triggers`) | Keep | User-controlled historical analysis | Keep; relabel UI strings only |

## K. SEO metadata (all pages)

Rewrite all titles/descriptions/OG/Twitter/JSON-LD per Task 8 examples
(signals/calls/profit language → outlook/education language). Sitemap labels
updated for new pages. No new parameterized URLs.

## Manual-review queue
- A8 `tg_alerts.py` file fate (leave unscheduled vs delete).
- Paper ledger presentation depth (F2): full column list to finalize in implementation.
- Corporate Actions Calendar: no data source exists — recommend documenting as planned coverage, NOT building hollow page.
- FINNIFTY/SENSEX: no instruments/feeds — “Insufficient Data” cards (no fabricated values).
- Payoff/risk calculators + journal (Tools): client-side, user-controlled — allowed; build on Tools page.
