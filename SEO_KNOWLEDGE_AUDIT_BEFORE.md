# SEO_KNOWLEDGE_AUDIT_BEFORE.md — TradingAI.in (2026-09-29, pre-change)

Branch: `production-2026-09-26` @ `28b121a` (prior SEO pass uncommitted in tree).
Backend inspected READ-ONLY to ground knowledge copy in actual implementation.

## Backend truth (what the product actually does — copy must not exceed this)
- CPR: previous-session HLC → TC/BC/Pivot + S1/S2/R1/R2, gap classification,
  first trigger per session, next-open entries 09:20–15:20, 0.5% stop / 2% target,
  15:20 flat, weekly-CPR gate (aligned variant). Deterministic rule codes
  (`CPR_NARROW`, `GAP_BULLISH`, `PRICE_ABOVE_TC`, `VIRGIN_CPR`, …).
- Options: `option_snapshots` stores `expected_move`, `pcr`, `total_oi`, `atm_iv`
  WHEN the NSE feed is reachable. Currently unreachable from the host —
  provider returns `OPTIONS_UNAVAILABLE`, engine qualifies `NO_TRADE` with
  `OPTIONS_DATA_UNAVAILABLE`. **Max Pain is NOT computed anywhere in backend.**
- NO frontend page calls `/api/options/*` — no instrument/options UI renders
  PCR, Max Pain, OI or Expected Move today.
- NO LLM anywhere in `app/` (grep clean). All explanations are deterministic
  rule-code evaluations. Copy must describe “AI-assisted” as automated rules
  and must NOT claim LLM-generated explanations.
- INDIA_VIX tracked as 5m-candle instrument (`^INDIAVIX`), shown as homepage
  volatility card + regime context.
- Backtest: validated 5m data, no-lookahead, hypothetical results only.
- No AdSense/consent/cookie implementation on site.

## Knowledge inventory per topic (before)
| Topic | Existing knowledge location | Verdict |
|---|---|---|
| NIFTY today/outlook/analysis | `/indices/nifty.html` (live model output, levels, gap, timeline, why-codes) + short SEO sections (levels, options-intel) | Live data GOOD; interpretation/limitations THIN |
| BANKNIFTY today/outlook | `/indices/banknifty.html` (mirror) | Same as NIFTY |
| CPR (TC/BC/Pivot, width, narrow/wide, virgin, gaps, weekly) | `/cpr-guide.html`, `/narrow-wide-cpr.html`, `/how-to-use-cpr-intraday.html`, methodology §§2–3 | GOOD (preserve) |
| Support/resistance | `/nifty-support-resistance.html` (CPR levels, PDL/PDH) | GOOD but no OI-based S/R (not computed — correctly absent) |
| PCR | 2-sentence mention on instrument pages only | GAP: no definition, calc, interpretation, limitations |
| Max Pain | 1-phrase mention only; NOT computed by backend | GAP: educational page needed, must not imply live computation |
| Expected Move | 1-phrase mention; backend stores it when feed reachable | GAP: concept + limitations + availability states |
| Option chain / OI / change-in-OI | passing mentions only | GAP: what OI means, concentration, limits |
| India VIX | homepage card + regime pill; methodology mention | GAP: what VIX is, high/low context, limits |
| Bull/Bear spreads, credit spreads | `/bull-put-spread.html`, `/bear-call-spread.html`, `/credit-spreads.html`, methodology §8 | GOOD (preserve) |
| Backtesting | `/backtest.html` (rules, disclaimer) + `/free-backtesting-tool.html` | GOOD (preserve) |
| Model signals (inputs, invalidation, limits) | methodology §§1–4,9; instrument “why” codes | GOOD, scattered — link, don’t duplicate |
| AI/market intelligence boundary | weak: “AI” barely defined; no deterministic-vs-AI statement | GAP |

## Structural audit (before)
- Pages: `/`, `/indices/{nifty,banknifty}.html`, `/backtest.html`,
  `/methodology.html`, `/paper.html`, 8 guides, legal pages. No `/today/`,
  `/market.html`, `/options.html`, `/strategies.html`, `/learn/`, `/home.html`
  (all 404, none linked — do not create).
- Canonical: absolute + correct everywhere. Robots: allows `/`, blocks
  frozen/pre/backup/removed snapshots, declares sitemap. Sitemap: all 18
  indexable URLs, lastmod 2026-09-29.
- Schema: WebSite (home), WebPage (5 hubs), BreadcrumbList (instrument pages),
  Article (8 guides). No FAQPage (no visible FAQs — correctly absent).
- Nav: Methodology in every main nav (prior pass). Guides linked from home,
  methodology §12, backtest, paper, instrument about-sections.
- `display:none` occurrences are CSS rules (`.statusbar`) — no hidden
  keyword content anywhere (verified by scan).
- Live-data states preserved site-wide (`—`, `Connecting…`, `unavailable`
  wording); no fabricated values in static copy.
- Baseline counts: duplicate titles 0 · missing canonical 0 · missing H1 0 ·
  invalid JSON-LD 0 · broken internal links 0.
