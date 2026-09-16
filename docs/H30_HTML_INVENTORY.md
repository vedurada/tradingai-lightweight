# H30 — HTML Structural Inventory

Created: 16 September 2026
Baseline: 3e8f0e2 → v2b5583a-baseline-16-g3e8f0e2

Method: Extract all H1/H2/H3 headers from 52 HTML files, compare against TRADINGAI_MASTER_SPEC.md required sections.

---

## Legend

| Check | Action |
|-------|--------|
| ✅ | Matches master spec |
| 🔴 | Critical deviation (wrong structure, obsolete modules) |
| 🟠 | Partial deviation (missing sections, needs restructuring) |
| 🟡 | Minor (typo, formatting, polish) |
| ⚪ | Not in approved scope (legacy/archive) |

---

## CORE PAGES (Highest priority)

### /index.html — HOME

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: Market Status | ⚠️ Check — found H3 LIVE MARKET TICKER, MARKET SNAPSHOT, NIFTY 50 (H2s may exist but not captured in header scan) |
| AI Market Outlook | ⚠️ Per PHASE 29: shows "Loading AI Market Outlook…" |
| Market Snapshot | 🔴 NIFTY/BANKNIFTY/SENSEX/FINNIFTY all show "—" |
| Options Intelligence | 🟠 PCR/Max Pain show "—"/"Data unavailable" |
| Key Levels | 🟠 Loading |
| AI Strategy Context | 🟠 Loading |
| Quick Actions | ⚠️ Verify |
| Unrelated modules | 🔴 Per PHASE 29: remove MF grid, scanner results, old modules |
| Master spec compliance | 🟠 RESTRUCTURE needed |

---

### /today/index.html — TODAY

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: TODAY'S NIFTY TERMINAL | ✅ |
| H2: Market Snapshot (NIFTY/BANKNIFTY/SENSEX/FINNIFTY/VIX) | ✅ Present |
| H2: Today's AI Market Outlook | ✅ Present |
| H2: Today's Key Levels | ✅ Present |
| H2: Options Intelligence (PCR/OI/Max Pain/Expected Move) | ✅ Present |
| H2: Market Breadth | ✅ Present |
| H2: Intraday Conditions (Bullish/Bearish/No Trade) | ✅ Present |
| H2: AI Strategy Candidates | ✅ Present |
| H2: Risk Conditions | ✅ Present |
| H2: Session Timeline | ✅ Present |
| Runtime | 🔴 Per PHASE 29: 3 missing endpoints + structure mismatch |
| Master spec compliance | ✅ STRUCTURAL — needs API repair (Phase 32) |

**Note**: Most important finding — the HTML structure is CORRECT. The runtime issues are API contract problems documented in PHASE29_FUNCTIONAL_AUDIT.md.

---

### /market.html — MARKET

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: Market Overview | ✅ |
| H2: Index Grid (NIFTY/BANKNIFTY/FINNIFTY/SENSEX/VIX) | ✅ Present (Loading market pulse…) |
| H2: Market Breadth | ✅ Present |
| H2: Sector & Market Condition | ✅ Present |
| H2: Technical Snapshot (VWAP/RSI/ADX/MACD) | ✅ Present (Loading) |
| H2: Market Regime | ✅ Present (Loading) |
| H2: Index Deep-Dive Links | ✅ Present |
| Master spec compliance | ✅ STRUCTURAL — runtime verification needed |

---

### /indices/nifty.html — NIFTY DEEP DIVE

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: NIFTY 50 (Spot/Change/VIX) | ✅ Present |
| H2: AI Market Outlook | ✅ Present |
| H2: Technical Structure (VWAP/EMA/RSI/MACD/ADX/CPR) | ✅ Present |
| H2: Key Levels (Support/Resistance/Opening Range) | ✅ Present |
| H2: Options Intelligence (PCR/OI/Call Wall/Put Wall/Max Pain/Expected Move) | ✅ Present |
| H2: Intraday Conditions | ✅ Present |
| H2: AI Options Strategy Analysis | ⚠️ Verify — per PHASE 29 audit was restructured |
| H2: Build Strategy / Position Size / Backtest links | ⚠️ Verify |
| Master spec compliance | ✅ STRUCTURAL — runtime verification needed |

**Note**: Most complete core page in workspace. Template to replicate for BANKNIFTY/FINNIFTY/SENSEX.

---

### /indices/banknifty.html, /indices/finnifty.html, /indices/sensex.html — INDEX DEEP DIVES

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2 sections | 🔴 MISSING — only has H3 cards (Market Grid, Scanner, Backtest) |
| Index header (spot, change, VIX, regime) | 🔴 MISSING |
| AI Market Outlook | 🔴 MISSING |
| Technical Structure | 🔴 MISSING |
| Key Levels | 🔴 MISSING |
| Options Intelligence | 🔴 MISSING |
| Intraday Conditions | 🔴 MISSING |
| AI Strategy | 🔴 MISSING |
| Master spec compliance | 🔴 RESTRUCTURE — need full deep-dive template |

**Action**: Apply nifty.html template as base. This is the biggest structural gap.

---

### /options/pcr.html — OPTIONS INTELLIGENCE

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: OPTIONS PCR & MAX PAIN | ✅ |
| H3: NIFTY/BANKNIFTY/FINNIFTY (index selector) | ✅ |
| Full spec sections (OI, Max Pain, Call Wall, Put Wall, Expected Move, Option Chain, AI Interpretation, Strategy Connection) | ⚠️ Need verification — per PHASE 29 was restructured |
| Master spec compliance | 🟠 PARTIAL — verify remaining sections |

---

### /strategies.html — STRATEGIES

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: OPTIONS STRATEGY ENGINE | ✅ |
| H3: Strategy Intelligence, STRATEGY CARDS, STRATEGY COMPARISON | ✅ |
| Today's market context | ✅ Present |
| AI strategy candidates | 🔴 Per PHASE 29: STRATEGY ANALYSIS = Loading…, STRATEGY PERFORMANCE = Loading… |
| Master spec compliance | 🟠 STRUCTURAL PARTIAL — runtime issues documented |

---

### /strategy-builder.html — STRATEGY BUILDER

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: Strategy Builder | ✅ |
| Interactive payoff/leg builder | ✅ Present |
| Results (max profit/loss, breakeven, capital, margin, risk) | ✅ Present |
| Master spec compliance | 🟢 ALIGNED — interactive |

---

### /tools/position-size.html — POSITION SIZE

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: FREE TRADING TOOLS | ⚠️ Master spec says: Position Size Calculator |
| H3: Position Size Calculator | ✅ |
| H3: Expected Move (from live ATR) | ⚠️ Extra module |
| Master spec compliance | 🟠 Minor restructure needed |

---

### /tools/backtest.html — BACKTEST

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: Settings/Run/Results sections | 🔴 MISSING — only has H1 + "How to read this page" |
| Master spec compliance | 🟠 RESTRUCTURE — needs all sections |

---

### /tools/intelligence.html — PERSONAL INTELLIGENCE

| Finding | Status |
|---------|--------|
| H1: Trading Intelligence | ✅ |
| H2: By Instrument, By Strategy, By Regime, Behavior, Mistakes, Setup Adherence | ✅ All present |
| Master spec compliance | ✅ ALIGNED (per PHASE 9C) |

---

### /tools/journal.html — TRADE JOURNAL

| Finding | Status |
|---------|--------|
| H1: Trade Journal | ✅ |
| H2: Did you take this setup?, Actual Trade, Why Skipped?, Notes, Personal Statistics, Recent Entries | ✅ All present |
| Master spec compliance | ✅ ALIGNED (per Phase 9A) |

---

## SECONDARY PAGES

### /scanner.html — STOCK SCANNER

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: Market Scanner | ✅ |
| Filters (Market, Trend, RSI, VWAP, EMA, MACD, Volume) | ⚠️ Need verification |
| Results table | 🔴 Per PHASE 29: Loading… |
| Extra modules | 🔴 Has Market Grid + Scanner duplicate |
| Master spec compliance | 🟠 RESTRUCTURE — remove duplicate cards, fix results |

---

### /mutual-funds/index.html — MUTUAL FUNDS

| Finding | Status |
|---------|--------|
| H1: TradingAI | ✅ |
| H2: BEST MUTUAL FUNDS IN INDIA | ✅ |
| Typo | 🟡 "Anualised" → "Annualised" (confirmed) |
| Extra modules | 🔴 Has Market Grid + Scanner |
| Runtime | 🔴 Per PHASE 29: "Loading mutual funds…" |
| Master spec compliance | 🟠 RESTRUCTURE — remove cards, fix typo |

---

### /learn/* — EDUCATION

| Page | H1 | H2 Master Spec | Status |
|------|-----|---------------|--------|
| /learn/index.html | TradingAI | LEARN OPTIONS TRADING | ✅ |
| /learn/option-chain.html | TradingAI | How to Read an Option Chain | ✅ |
| /learn/pcr.html | TradingAI | PCR Explained: Put-Call Ratio | ✅ |
| /learn/vwap.html | TradingAI | VWAP Explained for Intraday Trading | ✅ |
| /learn/option-greeks.html | TradingAI | Option Greeks in Plain English | ✅ |
| /learn/cpr.html | TradingAI | CPR Strategy: Pivot Range Trading | ✅ |

All learn pages: Master spec compliance ✅ ALIGNED — education + live tool links

---

### TRUST PAGES

| Page | H1 | H2 | Master Spec | Status |
|------|-----|-----|-------------|--------|
| /about.html | TradingAI | About TradingAI, What we do, etc. | ✅ Clean | ✅ ALIGNED |
| /contact.html | TradingAI | Contact, Email, What to include | ✅ Clean | ✅ ALIGNED |
| /privacy.html | TradingAI | Privacy Policy, all sections | ✅ Clean | ✅ ALIGNED |
| /terms.html | TradingAI | Terms of Service, all sections | ✅ Clean | ✅ ALIGNED |
| /disclaimer.html | TradingAI | Disclaimer, all sections | ✅ Clean | ✅ ALIGNED |
| /404.html | TradingAI | Page not found (404) | ✅ Simple | ✅ ALIGNED |

**Note**: Per PHASE 11, duplicate navigation cards were already removed from these pages.

---

## LEGACY / NON-MANIFEST PAGES

These pages are NOT in the approved page hierarchy but exist in the workspace:

| Page | Classification | Issue |
|------|---------------|-------|
| /alerts.html | ARCHIVE per PENDING_CLASSIFICATIONS | Has Market Grid + Scanner + Backtest cards |
| /portfolio.html | ARCHIVE | Has Market Grid + Scanner + Backtest cards |
| /stock.html | ARCHIVE | Has Market Grid + Scanner + Backtest cards |
| /queries/index.html | ARCHIVE | Has related modules |
| /news/index.html | ARCHIVE (per PAGE_MANIFEST) | Has Market Grid + Scanner cards |
| /global/markets.html | ARCHIVE | Has Market Grid + Scanner cards |
| /sectors/top.html | ARCHIVE | Has Market Grid + Scanner cards |
| /history.html | ARCHIVE | Has Market Grid + Scanner + Backtest cards |
| /history/replay.html | ARCHIVE (Phase 5) | Has "How this works" |
| /market/outlook-nifty-2026-09-13.html | ARCHIVE | Generated outlook page |
| /trade.html | KEEP per PAGE_MANIFEST | Per manifest, approved |
| /options-mobile.html | ARCHIVE per PENDING_CLASSIFICATIONS | Has Market Bias + Key Levels |
| /tools/walkforward.html | KEEP per PAGE_MANIFEST | Approved tool page |
| /tools/journal.html | KEEP per PAGE_MANIFEST | Approved tool page |
| /tools/intelligence.html | KEEP per PAGE_MANIFEST | Approved tool page |

**All archive pages**: Share common pattern of Market Grid / Scanner / Backtest cards → REMOVE in H39

---

## STOCKS / ETFS / STOCKS PAGES

Per PAGE_MANIFEST, these are classified ARCHIVE:

| Page | Status | Common Issue |
|------|--------|-------------|
| /stocks/52-week.html | ARCHIVE | Market Grid + Scanner + Backtest cards |
| /stocks/reliance.html | ARCHIVE | Same cards |
| /stocks/top-large-cap.html | ARCHIVE | Same cards |
| /stocks/top-mid-small.html | ARCHIVE | Same cards |
| /stocks/top-performers.html | ARCHIVE | Same cards |
| /stocks/undervalued.html | ARCHIVE | Same cards |
| /etfs/holdings.html | ARCHIVE | Same cards |
| /etfs/top-etfs.html | ARCHIVE | Same cards |

**All share identical Market Grid / Scanner / Backtest card pattern** → Bulk REMOVE in H39

---

## H30 Summary — Critical Findings

### Biggest structural gap

**BANKNIFTY / FINNIFTY / SENSEX index pages** — All 3 have NO H2 sections. Only H3 Market Grid / Scanner / Backtest cards. Need full deep-dive template (NIFTY template available as base).

### Most common problem

**Market Grid + Scanner + Backtest cards** appearing on 20+ pages that don't need them. This is the "four giant cards repeated everywhere" problem the user identified.

### Pages structurally ready

| Page | Status |
|------|--------|
| /today/index.html | ✅ Structure correct (API repair = Phase 32) |
| /market.html | ✅ Structure correct (runtime = Phase 33) |
| /indices/nifty.html | ✅ Structure correct (runtime = Phase 33) |
| /strategy-builder.html | ✅ Structure correct |
| /tools/intelligence.html | ✅ Structure correct |
| /tools/journal.html | ✅ Structure correct |
| All /learn/* | ✅ Structure correct |
| All trust pages | ✅ Structure correct |
| /options/pcr.html | 🟠 Mostly correct, verify remaining |
| /strategies.html | 🟠 Structure present, analysis loading |
| /index.html | 🟠 Needs restructuring per spec |
| /indices/banknifty|finnifty|sensex | 🔴 Need full restructure |
| /tools/backtest | 🟠 Needs section restructure |
| /tools/position-size | 🟠 Minor |
| /scanner | 🟠 Needs cleanup |
| /mutual-funds | 🟠 Needs cleanup |

### Legacy/archive pages requiring cleanup

20+ pages share identical obsolete card pattern → H39 bulk removal

---

## H31 Readiness

With H30 complete, the next steps are clear:

**H31**: Global shell first (header with Home/Market/Today/Options/Strategies/Tools/Learn + breadcrumb + related tools + data status + footer), then restructure core pages per user's batch order:
1. Home → Today → Market → NIFTY → BANKNIFTY → FINNIFTY → SENSEX → Options → Strategies → Tools → Scanner → MF → Learn → Trust

Ready for H31 when authorized.
