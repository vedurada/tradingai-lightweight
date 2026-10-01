# SEO_KEYWORD_KNOWLEDGE_MAP.md — TradingAI.in (2026-09-29)

PASS = genuine useful knowledge on the authoritative page (not mere phrase occurrence).

| Keyword | Intent | Authoritative URL | Knowledge present | Missing knowledge | Live data | Related topics | Status |
|---|---|---|---|---|---|---|---|
| NIFTY today | today's context + outlook | `/indices/nifty.html` | live output, levels, gap, timeline, why-codes; short SEO sections | interpretation + limitations depth | YES (page API/JS) | CPR, S/R, VIX, options, signal | PARTIAL → fix |
| NIFTY outlook / analysis / intraday analysis | analytical framing | `/indices/nifty.html` | model output + regime/gap context | regime/momentum/volatility explainer, expected-range framing | YES | VIX, EM, scenarios | PARTIAL → fix |
| BANKNIFTY today / outlook / analysis / levels / CPR | mirror of NIFTY | `/indices/banknifty.html` | mirror live output | mirror gaps | YES | (mirror) | PARTIAL → fix |
| CPR / Central Pivot Range / TC / BC / narrow / wide / virgin / weekly / gaps | learn + apply CPR | `/cpr-guide.html` (+ narrow-wide, intraday guides) | calculation, width, virgin, gaps, weekly gate | none significant | YES (levels on instrument pages) | S/R, signals | PASS |
| support / resistance | daily levels | `/nifty-support-resistance.html` + instrument pages | CPR levels, PDL/PDH | OI-based S/R (not computed — correctly absent, note as limitation) | YES (levels) | CPR, options | PASS (note limit) |
| PCR | what it is + how to read it | NEW `/pcr-guide.html` (hub); summaries on instrument pages | 2 sentences | definition, calc concept, interpretation, limits, availability | snapshot field when feed reachable; else unavailable state | OI, VIX, regime, CPR | GAP → fix |
| Max Pain | what it represents | NEW `/max-pain-guide.html` (educational; backend does NOT compute it) | 1 phrase | full A–F explainer with honesty constraint | NO live value (state why) | OI, expiry, spot | GAP → fix |
| Expected Move | what it is + IV/time link | NEW `/expected-move-guide.html` | 1 phrase | concept, IV/expiry relation, limits | snapshot field when reachable | IV, VIX, regime | GAP → fix |
| Option chain / OI / change in OI / concentration | read positioning | NEW `/option-chain-guide.html` | mentions | OI meaning, change-in-OI, concentration, limits | contracts layer when reachable | PCR, Max Pain, S/R | GAP → fix |
| India VIX | volatility context | NEW `/india-vix-guide.html` | card + regime pill | what VIX is, high/low, EM link, limits | YES (VIX instrument candles) | EM, regime, options | GAP → fix |
| Bull Put / Bear Call / credit spread / options strategy | strategy education | `/bull-put-spread.html`, `/bear-call-spread.html`, `/credit-spreads.html`, `/methodology.html` | structure, payoff, context, invalidation | none significant | model structures on instrument pages | backtest, paper | PASS |
| backtest / backtesting | historical behavior | `/backtest.html` + `/free-backtesting-tool.html` | rules, data, disclaimer | none significant | YES (engine results) | paper, methodology | PASS |
| paper trades / model track record | hypothetical fills | `/paper.html` | ledger, rules, spreads | none significant | YES (cron ledger) | backtest, signals | PASS |
| model signal (inputs, invalidation, limits) | understand output | `/methodology.html` + instrument why-codes | rules, codes, risks | determinism statement | YES | CPR, gap, backtest | PARTIAL → fix (AI-boundary note) |
| AI market intelligence | what “AI” means here | `/` + `/methodology.html` | “automated/standardized” wording | explicit deterministic-vs-AI boundary (no LLM in product) | n/a (descriptive) | signals, indicators | GAP → fix |

Plan: 5 substantive evergreen guides (PCR, Max Pain, Expected Move, Option Chain/OI,
India VIX) following existing guide template (nav, canonical, OG, Article schema);
instrument-page “How to read this page” knowledge sections linking to them (no
duplication); AI-boundary note on home + methodology; sitemap + index-guides row +
tests extended. No new dynamic features; no JS logic changes.
