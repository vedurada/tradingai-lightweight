# LIVE WEB CRAWL AUDIT

Created: 16 September 2026
Baseline: 3e8f0e2 → v2b5583a-baseline-16-g3e8f0e2
Companion: docs/H30_HTML_INVENTORY.md (workspace structural audit)

Purpose: Establish what is publicly discoverable/crawlable on tradingai.in vs what the approved hierarchy says should exist.

IMPORTANT: This audit establishes PUBLIC DISCOVERABILITY. It does NOT replace the workspace inventory (H30) or VM inventory (Phase 30). Both datasets are needed.

---

## Audit Categories

| Category | Meaning | Action |
|----------|---------|--------|
| A | Approved page, correct layout | KEEP |
| B | Approved page, incomplete layout | RESTRUCTURE |
| C | Publicly discoverable but NOT in approved hierarchy | REDIRECT/ARCHIVE |
| D | In approved hierarchy but not publicly discoverable | INVESTIGATE on VM |

---

## CATEGORY C — Legacy Pages Publicly Discoverable (P0)

These pages are publicly crawlable/indexable but NOT in the approved 52-file hierarchy.

### /home.html (🔴 CRITICAL)
- **Status**: Legacy portal architecture
- **Exposes**: 52-Week, Stock News, Global Markets, Stock Options, Query Library, Portfolio, Alerts, ETF Holdings, Stock Research
- **Issue**: Search engines can discover this. Users see old architecture. Competes with / for authority.
- **Action**: Immediate 301 to / on production nginx. Remove from sitemap. Re-submit sitemap to Search Console.

### /index.html (🔴 CRITICAL)
- **Status**: Separate URL from /, different structure
- **Exposes**: Market Grid, Scanner, Backtest, Today LIVE cards + 1-month backtest block
- **Issue**: Creates duplicate content with /. Different layout from master spec home.
- **Action**: 301 to / OR canonicalize. Ensure /index.html serves same content as / or redirects.

### /today/index.html (🟠 CRITICAL)
- **Status**: Live terminal accessible, but has unrelated cards
- **Exposes**: Market Grid / Scanner / Backtest / Today LIVE card block underneath terminal
- **Issue**: Master spec says Today should ONLY have terminal sections. Dashboard cards violate spec.
- **Action**: Remove Market Grid, Scanner, Backtest, Today LIVE cards from Today page.

### /home.html legacy variants (🟠 P0)
- /index-option-risk-management.html — legacy research guide, not in hierarchy
- /etf-index-fund-investor-guide.html — legacy research guide, not in hierarchy
- /faq.html — publicly indexed, NOT in 52-file hierarchy at all
- **Action**: 301 each to appropriate approved destination.

---

## CATEGORY B — Approved but Incomplete/Incorrect Layout (P0-P1)

### / (Homepage) — 🟠 RESTRUCTURE NEEDED
- **Crawl result**: Dashboard structure (correct sections present)
- **Runtime**: NIFTY/BANKNIFTY/SENSEX/FINNIFTY rendered as —, last refreshed —, breadth Loading…
- **Master spec match**: Partially — sections exist but runtime data missing
- **Issues**: 
  - Master spec requires Home/Market/Today/Options/Strategies/Tools/Learn nav
  - Current nav: Market, Scanner, Today, Backtest (WRONG per spec)
  - Per H30: needs restructuring per master spec

### /today/index.html — 🟠 RESTRUCTURE NEEDED
- **Crawl result**: Still exposes "Loading today's session…" to crawler
- **Runtime**: Loading state persists
- **Master spec match**: Structure is correct per H30 (most complete core page)
- **Issues**:
  - Has unrelated Market Grid/Scanner/Backtest/Today LIVE cards (per live crawl)
  - Needs these removed per master spec
  - 3 missing API endpoints + 1 structure mismatch (per PHASE 29)

### /indices/banknifty.html, /indices/finnifty.html, /indices/sensex.html — 🔴 RESTRUCTURE NEEDED
- **Workspace finding** (H30): No H2 sections, only H3 Market Grid/Scanner/Backtest cards
- **Live finding**: Presumably similar to workspace
- **Master spec**: Should match NIFTY deep-dive template
- **Action**: Apply NIFTY template as base (H31 batch 2)

### /mutual-funds/ — 🟠 RESTRUCTURE NEEDED
- **Crawl result**: "Loading mutual funds…", "Anualised" typo
- **Master spec match**: Sections are correct
- **Issues**: Typo, loading state, secondary page should not load main JS bundles unnecessarily

---

## CATEGORY A — Approved and Broadly Aligned (KEEP)

### /learn/ — 🟢 ALIGNED
- Crawl confirms: Option Chain, PCR, VWAP, CPR, Greeks
- Education → live tool workflow present
- Master spec match: Good

### /strategy-builder.html — 🟢 ALIGNED
- Crawl confirms: index-options builder structure
- Master spec match: Good

### /about.html — 🟢 ALIGNED
- Crawl confirms: About/data-source/limitations content
- No dashboard cards (per PHASE 11 cleanup)
- Master spec match: Good

### /market.html — 🟠 PARTIAL
- Master spec sections present: Market Overview, Index Grid, Breadth, Sector/Condition, Technical Snapshot, Regime, Deep-Dive Links
- Runtime: Loading market pulse in index grid (expected)
- Master spec match: Good

### /options/pcr.html — 🟠 PARTIAL
- Master spec sections present: Index selector, PCR, OI, Max Pain areas
- Runtime: Unverified from live crawl
- Master spec match: Good

### /strategies.html — 🟠 PARTIAL
- Master spec sections present: Strategy intelligence, cards, comparison
- Runtime: Strategy Analysis/Performance Loading (per PHASE 29)
- Master spec match: Good

---

## CATEGORY C — Pages on Live Site NOT in Workspace Hierarchy

These pages exist on tradingai.in but are NOT in the workspace 52-file hierarchy:

| Page | Status | Concern |
|------|--------|---------|
| /faq.html | Publicly indexed | Not in 52-file manifest, not in PAGE_MANIFEST |
| Other VM-generated pages | Unknown | May be prerender snapshots or generated content |

**Action for VM inventory**: Identify what /faq.html contains and determine if it should be 301'd or integrated.

---

## Combined Priority Matrix

Finding from workspace H30 + live crawl combined:

| # | Page | H30 Status | Live Status | Combined Priority |
|---|------|-----------|-------------|-------------------|
| 1 | /home.html | Legacy | PUBLICLY DISCOVERABLE | 🔴 P0 — 301 NOW |
| 2 | /index.html | Legacy/duplicate | PUBLICLY DISCOVERABLE | 🔴 P0 — 301/canonical |
| 3 | /today/index.html | Structure correct | Cards + loading | 🟠 P0 — cleanup |
| 4 | /indices/banknifty | Needs restructure | Presumed same | 🔴 P1 — restructure |
| 5 | /indices/finnifty | Needs restructure | Presumed same | 🔴 P1 — restructure |
| 6 | /indices/sensex | Needs restructure | Presumed same | 🔴 P1 — restructure |
| 7 | / | Needs restructure | Loading data | 🟠 P0 — restructure |
| 8 | /market.html | Structure correct | Loading grid | 🟠 P1 — runtime |
| 9 | /options/pcr.html | Partial | Unverified | 🟠 P1 — verify |
| 10 | /strategies.html | Partial | Loading analysis | 🟠 P1 — runtime |
| 11 | /mutual-funds/ | Typo + loading | Typo + loading | 🟠 P2 — fix |
| 12 | /scanner.html | Needs cleanup | Unverified | 🟠 P2 |
| 13 | /strategy-builder | Aligned | Aligned | 🟢 KEEP |
| 14 | /learn/* | Aligned | Aligned | 🟢 KEEP |
| 15 | /about.html | Clean | Clean | 🟢 KEEP |
| 16 | /faq.html | NOT IN WORKSPACE | PUBLICLY INDEXED | 🔴 P0 — investigate |

---

## Critical Discovery: Public Legacy Pages

The workspace audit assumed /home.html had a 301 redirect configured in nginx (`ops/nginx-tradingai.conf:120`). The live crawl proves this redirect is NOT ACTIVE on the production site — /home.html is fully accessible and indexed.

This means either:
1. The nginx config was never deployed to VM
2. The 301 was configured but later removed
3. The nginx config differs between workspace and VM

**This must be verified on VM during Phase 30.**

---

## Critical Discovery: /index.html as Separate URL

Per master spec and Google Search Console, / should be canonical. But /index.html is separately crawlable with DIFFERENT content (Market Grid, Scanner, Backtest cards instead of AI Outlook structure). This creates:
1. Duplicate content issue
2. Different user experience at / vs /index.html
3. Diluted SEO authority

**Action**: Determine canonical relationship on VM. Either 301 /index.html → / or serve identical content.

---

## Critical Discovery: /faq.html

A publicly indexed FAQ page exists on tradingai.in that is NOT in the workspace. This means:
1. The live VM has content the workspace doesn't track
2. There may be other VM-only pages
3. Phase 30 VM inventory MUST include a full file listing

**Action**: During Phase 30, list ALL files on VM and compare against workspace 52-file manifest.

---

## Next Steps

1. **Immediate**: Add /home.html, /index.html, /faq.html to legacy redirect list for H32
2. **H31**: Remove Market Grid/Scanner/Backtest cards from /today/index.html
3. **H31**: Fix navigation on / (Home/Market/Today/Options/Strategies/Tools/Learn)
4. **H31**: Apply NIFTY template to BANKNIFTY/FINNIFTY/SENSEX
5. **Phase 30**: Verify nginx 301 config, all VM files, /faq.html content
6. **Phase 32**: Fix API contracts for homepage and today terminal
7. **Search Console**: Request index removal for /home.html, /index.html legacy variants, /faq.html (pending redirect decision)

---

## Combined Audit Summary

| Source | What it proves |
|--------|---------------|
| H30 (workspace) | What files exist and their structure |
| Live crawl | What is publicly discoverable/crawlable |
| PHASE 29 | What runtime data is actually rendered |
| Phase 30 (VM) | What files exist on production + actual runtime |

All four datasets are needed for complete truth. The live crawl revealed issues that workspace audit alone could not: legacy discoverability, /faq.html existence, /index.html separate content.

---

**Document**: `docs/LIVE_CRAWL_AUDIT.md`
**Updated**: 16 September 2026
**Status**: ACTIVE — first crawl, more pages to audit
