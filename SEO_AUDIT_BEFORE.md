# SEO_AUDIT_BEFORE.md — TradingAI.in (baseline 2026-09-29, pre-change)

Branch: `production-2026-09-26` @ `28b121a`. Audit of live served HTML (fetched 2026-09-29).
No code, content, or trading logic changed to produce this file.

## 1. Homepage URL
- `https://tradingai.in/` (also serves `https://tradingai.in/index.html` → 200, duplicate representation)

## 2. Current titles
| Page | Title (len) |
|---|---|
| `/` | `TradingAI.in — Live CPR-Based NIFTY & BANKNIFTY Model Signals for Indian Index-Options Traders` (94) — long, will truncate |
| `/indices/nifty.html` | `NIFTY — Current Model Output \| TradingAI.in` (43) — weak, no today/outlook/analysis/levels |
| `/indices/banknifty.html` | `BANKNIFTY — Current Model Output \| TradingAI.in` (43) — same weakness |
| `/backtest.html` | `Historical Backtest — Hypothetical Model Results \| TradingAI.in` — OK |
| `/methodology.html` | `Methodology — TradingAI.in` (24) — weak, no strategy/options keywords |
| `/paper.html` | `TradingAI - Paper Trades` (24) — weak, hyphen inconsistent with site `—` style, no instrument keywords |
| Guides (8) | Descriptive, unique, 60–90 chars — GOOD |

## 3. Current meta descriptions
- `/`: 166 chars — slightly long, may truncate.
- `/indices/nifty.html`: 208 chars — TOO LONG, will truncate in SERP.
- `/indices/banknifty.html`: same 208-char template with instrument swapped (thin/near-duplicate).
- `/paper.html`: 105 chars — short, no instrument/outlook terms.
- Guides: 140–160, unique — GOOD.

## 4. Current H1s (exactly one per page — GOOD)
- `/`: `TradingAI.in — Live NIFTY & BANKNIFTY model signals for Indian index-options traders` — descriptive, keep.
- `/indices/nifty.html`: `NIFTY current model output` — weak (no Today/outlook/levels).
- `/indices/banknifty.html`: `BANKNIFTY current model output` — weak.
- `/backtest.html`: `CPR trigger backtest` — lowercase, weak.
- `/methodology.html`: `How TradingAI works — automated model rules (research guide)` — GOOD.
- `/paper.html`: `Paper Trades EXPERIMENTAL` — weak.
- Guides: descriptive unique H1s — GOOD.

## 5. Current canonicals — GOOD
Every indexable page has an absolute canonical to its preferred URL
(`https://tradingai.in/...`). `/index.html` serves 200 as a duplicate of `/`;
canonical on `index.html` correctly points to `https://tradingai.in/`.

## 6. Robots directives
- `frontend/robots.txt`: `Allow: /`, `Disallow: /*frozen*`, `/*pre-*`, `/*backup*`, `/*removed-*`, sitemap declared — GOOD.
- `404.html`: `noindex` — GOOD. No other page sets robots meta (all indexable) — intended.

## 7. Open Graph / Twitter — mostly GOOD, gaps noted
- All pages: `og:type`, `og:site_name` (most), `og:url`, `og:title`, `og:description`, `twitter:card=summary` + title/description — present.
- Gaps: no `og:image` anywhere (link previews render text-only); no `theme-color`.

## 8. JSON-LD — MISSING EVERYWHERE
Zero pages contain `application/ld+json`. No WebSite / WebPage / Article /
BreadcrumbList / FAQPage markup on any page.

## 9. Existing indexable pages (all 200, all in sitemap unless noted)
`/`, `/indices/nifty.html`, `/indices/banknifty.html`, `/backtest.html`,
`/methodology.html`, `/paper.html`, `/cpr-guide.html`, `/credit-spreads.html`,
`/narrow-wide-cpr.html`, `/how-to-use-cpr-intraday.html`,
`/nifty-support-resistance.html`, `/bull-put-spread.html`,
`/bear-call-spread.html`, `/free-backtesting-tool.html`,
`/contact.html`, `/privacy.html`, `/terms.html`, `/disclaimer.html`

## 10. Existing market pages
`/indices/nifty.html`, `/indices/banknifty.html` (model output + levels via
existing API/JS). Hompage `/` shows NIFTY/BANKNIFTY/INDIA VIX cards.

## 11. Existing options pages — GAP
**No dedicated options page exists.** `/api/options/<instrument>` exists but no
HTML page exposes option-chain / PCR / OI / Max Pain / Expected Move concepts.
Instrument pages contain ZERO occurrences of: PCR, Max Pain, expected move,
open interest, option chain, put-call ratio, implied volatility.

## 12. Existing strategy pages
`/methodology.html` (model rules + strategy entry/invalidation/target rules),
`/credit-spreads.html`, `/bull-put-spread.html`, `/bear-call-spread.html`.
There is NO `/strategies.html` (speculative URL 404s — do not invent; map to
`/methodology.html` + spread guides).

## 13. Existing backtest pages
`/backtest.html` (research ledger) + `/free-backtesting-tool.html` (tool guide).
No `/tools/backtest.html` (404s — map to `/backtest.html`).

## 14. Existing Learn pages
No `/learn/` directory (404s). The 8 evergreen guide pages at root
(`cpr-guide`, `narrow-wide-cpr`, `how-to-use-cpr-intraday`,
`nifty-support-resistance`, `bull/bear spreads`, `credit-spreads`,
`free-backtesting-tool`) serve the Learn intent — do not duplicate.

## 15. Existing internal links
- `/` links to all guides + product pages with mostly descriptive anchors — GOOD.
- `/cpr-guide.html` links to `/credit-spreads.html` — GOOD.
- GAP: `/indices/nifty.html`, `/indices/banknifty.html`, `/methodology.html`,
  `/backtest.html` link to NO guide pages at all.
- GAP: main `<nav>` is inconsistent — `/methodology.html` is missing from the
  nav on `/`, `/indices/*`, `/methodology.html`, `/backtest.html`, guides
  (only `/paper.html` nav includes it).

## 16. Duplicate/overlapping URLs
- `/` vs `/index.html` (both 200; canonical mitigates — keep, monitor).
- `/indices/nifty.html` vs `/indices/banknifty.html` meta descriptions differ
  by one word (thin — acceptable for symmetric product pages, could enrich).
- `*.frozen-*`, `*.pre-*`, `*.backup*`, `*.removed-*` snapshots exist on disk
  but are robots-disallowed — GOOD (not in sitemap — verified).

## 17. Missing SEO keywords (6 core product pages scanned)
MISSING everywhere: `NIFTY today`, `outlook`, `intraday analysis`,
`options analysis`, `option chain`, `PCR`, `Max Pain`, `expected move`,
`open interest`, `put-call`, `implied volatility`, `Central Pivot Range`.
Present only on `/`: `support`, `resistance`. `India VIX` only on `/` + methodology.

## 18. Missing title/H1/meta coverage
- Titles: nifty/banknifty/methodology/paper weak (see §2).
- H1s: nifty/banknifty/backtest/paper weak (see §4).
- Descriptions: nifty/banknifty too long; paper too short (see §3).

## 19. Missing internal linking
Instrument + methodology + backtest pages → guides (see §15). No breadcrumb
markup anywhere. No options-glossary hub links (no options page exists).

## 20. Potential keyword cannibalization
- `/` (NIFTY & BANKNIFTY signals) vs `/indices/nifty.html` vs
  `/nifty-support-resistance.html` all touch "NIFTY levels" — LOW risk today
  because instrument/guide pages lack ranking copy; differentiation will come
  from distinct titles/H1s (Today/outlook vs guide/how-to).
- `/backtest.html` vs `/free-backtesting-tool.html` ("backtest" intent) —
  differentiate: research ledger vs tool guide (titles already distinct — keep).

## 21. Pages exposing stale/empty dynamic content to crawlers
- All product pages are JS-rendered from `/api/*`. A no-JS crawler sees
  placeholders (`—`, `Connecting…`, empty tables). This is pre-existing
  architecture (out of scope to SSR); mitigation = static explanatory SEO copy
  that is accurate with or without live data.
- `/paper.html`: `paper_confluence.py` regenerates the WHOLE file on cron —
  any direct edit to `paper.html` WILL be overwritten; generator template must
  be edited instead.
- `/backtest.html`: `refresh_backtest()` only swaps `<tbody>` blocks — `<head>`
  edits persist. Verified in `scripts/paper_confluence.py`.
- No fabricated values found in static copy (placeholders are `—`/status text) — GOOD.

## 22. Broken SEO/navigation links
- `/today/`, `/market.html`, `/options.html`, `/strategies.html`, `/learn/`,
  `/home.html` → all 404 and **none are linked** from any page — GOOD (do not create).
- All internal hrefs on the 6 core pages resolve to existing files — 0 broken.
- Footer legal trio (privacy/contact/terms) present on all pages — GOOD.

## Baseline counts (for final report)
Duplicate titles: 0 · Missing canonical: 0 · Missing H1: 0 · JSON-LD pages: 0 ·
Pages with guide links: 2 of 14 (index, cpr-guide) · `og:image`: 0 pages.
