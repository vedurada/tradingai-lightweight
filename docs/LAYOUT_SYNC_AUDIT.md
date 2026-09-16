# TradingAI — Layout Synchronization Audit

Created: 16 September 2026
Baseline: v2b5583a-baseline (commit 35decaf)

## Milestone Progress

| Phase | Status |
|-------|--------|
| Baseline tagged | ✅ v2b5583a-baseline (commit 35decaf) |
| Page manifest | ✅ 52 HTML files catalogued |
| Pending page classification | ✅ 25 pages classified (9 KEEP, 16 ARCHIVE) |
| Duplicate nav removal | ✅ 5 legal/info pages cleaned |
| NIFTY deep-dive redesign | ✅ 7 sections as explicit HTML |
| Today terminal redesign | ✅ 10 sections with loading states |
| Market page redesign | ✅ 7 sections as explicit HTML |
| Data-state standard | ✅ LIVE/UPDATED/STALE/UNAVAILABLE/ERROR |
| Tests | ✅ 75 passing |
| Browser/API verification | ⏳ Deferred until VM runtime |
| Deployment | ⏳ Deferred until VM verification |

## PHASE 29 — Production Page Functional Audit (COMPLETE)

| Phase | Status |
|-------|--------|
| PHASE 29 audit | ✅ Complete |
| Today API contracts | 🔴 3 endpoints absent, 1 structure mismatch |
| /home.html redirect | 🟠 Config exists, VM verification needed |
| / vs /index.html canonical | 🟠 Unverified |
| Legacy URLs (/home.html etc.) | 🟠 Public access still possible |
| Mutual funds | 🟠 Typo + Loading state |

Documents:
- `docs/PHASE29_FUNCTIONAL_AUDIT.md` — 24-page status matrix + today terminal chain analysis
- `docs/PHASE29_API_MAP.md` — 90 backend routes mapped + VM verification checklist

## PHASE 30 — Next Phase (Pending VM Access)

Production VM Read-Only Inventory & Runtime Dependency Audit

- 30A: VM inventory (read-only)
- 30B: Dependency mapping (HTML → JS → API → Flask → Python → SQLite → external source)
- 30C: Verify 4 highest-risk issues (Today contracts, /home.html, canonical, market pipeline)
- 31: Confirm classification + dependency map
- 32: Repair API/data contracts
- 33: Runtime browser audit
- 34: Data freshness/integrity
- 35: Cross-page workflow testing
- 36: Legacy cleanup
- 37: SEO/Search Console
- 38: Performance/mobile/security regression
- Production release



For every retained core page: compare approved layout plan vs current HTML.

Status options:
- ✅ ALIGNED — Page matches planned layout
- 🟠 PARTIAL — Some required sections present, some missing
- 🔴 MISMATCH — Page significantly deviates from plan, needs restructure

---

## Core Pages

### / (Homepage)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Header with market tickers | NIFTY/BANKNIFTY/FINNIFTY/SENSEX/VIX | Live market ticker present | ✅ |
| AI Market Outlook | Direction, evidence, reasoning | AI OUTLOOK section present | ✅ |
| Market Regime | Bullish/Bearish/Range | Present | ✅ |
| Key Levels | Support/Resistance/VWAP | KEY LEVELS present | ✅ |
| Options Intelligence | PCR/OI/Max Pain/Expected Move | Present | ✅ |
| Today's Trade Conditions | Bullish/Bearish/No-trade | Present | ✅ |
| AI Strategy | Strategy candidates | STRATEGIES section present | ✅ |
| Risk/Position Size | Risk calculation | POSITION SIZE present | ✅ |
| Related Tools | Links to tools | RELATED TOOLS present | ✅ |
| Live market data | All values populated | Several Loading… states | 🟠 |
| Freshness indicators | Timestamps on data | Some present, some missing | 🟠 |

**Overall: 🟠 PARTIAL** — Right structure, but data-driven sections show Loading… instead of values.

---

### /indices/nifty.html (NIFTY Deep Dive)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| NIFTY 50 price info | Spot/Change/VIX/Regime/Confidence | Present but thin | 🟠 |
| AI Market Outlook | Direction/Evidence/Drivers | Present | ✅ |
| Technical Structure | VWAP/EMA/RSI/MACD/ADX/CPR | 8-factor grid mentioned but not fully visible | 🟠 |
| Key Levels | Support/Resistance/Opening Range/Zones | Mentioned, may not be fully populated | 🟠 |
| Options Intelligence | PCR/OI/Call Wall/Put Wall/Max Pain/Expected Move | Mentioned but data may not render | 🟠 |
| Intraday Conditions | Bullish/Bearish/No-trade | Present | ✅ |
| AI Options Strategy | Structure/Entry/Risk/Target/Invalidation | Present | ✅ |
| Tools links | Strategy Builder/PCR/Backtest/Position Size/Today | Present | ✅ |

**Overall: 🔴 MISMATCH** — Page describes deep analysis but is mostly navigation + explanation. Core data components (technical indicators, options data) not rendered in fetched HTML. Needs major work per user audit.

---

### /indices/banknifty.html

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Same template as NIFTY | All NIFTY sections for BANKNIFTY | Structure exists | 🟠 |
| Data rendering | Live values | Not verified (crawler failed for some) | ⚠️ |

**Overall: 🟠 PARTIAL** — Assumed similar to NIFTY audit; needs browser verification.

---

### /indices/finnifty.html

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Same template as NIFTY | All NIFTY sections for FINNIFTY | Structure exists | 🟠 |
| Data rendering | Live values | Not verified | ⚠️ |

**Overall: 🟠 PARTIAL** — Needs verification.

---

### /indices/sensex.html

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Same template as NIFTY | All NIFTY sections for SENSEX | Structure exists | 🟠 |
| Data rendering | Live values | Not verified | ⚠️ |

**Overall: 🟠 PARTIAL** — Needs verification.

---

### /today/index.html (Today's Trading Terminal)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Date/Session | Highly visible date | Present | ✅ |
| Market Status | Status/Last update | Present | ✅ |
| Market Snapshot | NIFTY/BANKNIFTY/VIX | Present | ✅ |
| AI Outlook | Regime/Direction/Confidence/Explanation | "Loading today's session…" | 🔴 |
| Key Levels | Support/Resistance/Opening Range | Mentioned, data may not render | 🟠 |
| Options Intelligence | PCR/OI/Max Pain/Expected Move | Mentioned | 🟠 |
| Market Breadth | Breadth data | Not visible in fetched HTML | 🔴 |
| Intraday Conditions | Bullish/Bearish/No Trade | Present as concept | 🟠 |
| AI Strategy Candidates | Strategy suggestions | Not visible | 🔴 |
| Risk Management | Risk warning | Present | ✅ |
| Session Timeline | Timeline/phases | Not visible in fetched HTML | 🔴 |

**Overall: 🔴 MISMATCH** — Described as much richer than current implementation. Multiple Loading… states. Needs major work.

---

### /market.html (Market Overview)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Market Overview | Header/description | Present | ✅ |
| Index Grid | All tracked indices | "Loading market pulse…" | 🔴 |
| Market Breadth | Breadth data | Not visible | 🔴 |
| Sector/Condition | Sector performance | Not visible | 🔴 |
| Technical Snapshot | Technical data | Not visible | 🔴 |
| Market Regime | Regime classification | Present | ✅ |
| Links to Index Deep Dives | NIFTY/BANKNIFTY/etc links | Present | ✅ |

**Overall: 🔴 MISMATCH** — Market grid not rendered. Repeated navigation cards (already removed from some pages).

---

### /options/pcr.html (Options Intelligence)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Options Intelligence header | Header | Present | ✅ |
| Index Selector | NIFTY/BANKNIFTY/FINNIFTY/SENSEX | Present | ✅ |
| PCR | Current PCR/Trend/Interpretation | Mentioned | 🟠 |
| Open Interest | Call OI/Put OI/Change/Concentration | Mentioned | 🟠 |
| Max Pain | Max Pain data | Mentioned | 🟠 |
| Call Wall | Call wall data | Not verified (crawler failed) | ⚠️ |
| Put Wall | Put wall data | Not verified | ⚠️ |
| Expected Move | Expected move | Mentioned | 🟠 |
| AI Interpretation | AI analysis | Mentioned | 🟠 |
| Related links | Today/Strategies/Builder | Present | ✅ |

**Overall: 🟠 PARTIAL** — Conceptually aligned but data rendering unverified. Crawler couldn't access.

---

### /strategies.html (Strategy Engine)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Today's Market Context | Market data | Present | ✅ |
| Market Regime | Regime classification | Present | ✅ |
| Options Intelligence | PCR/OI/Max Pain | Present | ✅ |
| AI Strategy Analysis | Strategy analysis | "AI STRATEGY ANALYSIS = Loading…" | 🔴 |
| Strategy Candidates | Candidate strategies | Present | ✅ |
| Risk/Reward | Risk analysis | Present | ✅ |
| Strategy Comparison | Comparison table | Present (Buy CE, Bull Call Spread, etc.) | ✅ |
| Strategy Performance | Performance metrics | "STRATEGY PERFORMANCE = Loading…" | 🔴 |
| Build This Strategy | Link to builder | Present | ✅ |

**Overall: 🟠 PARTIAL** — Framework good, but two key data sections are Loading…

---

### /strategy-builder.html (Strategy Builder)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Instrument selection | Index selection | Present | ✅ |
| Template | Template selection | Present | ✅ |
| Lots/Lot size | Position sizing | Present | ✅ |
| Generate | Generate payoff | Present | ✅ |
| Payoff | Payoff diagram | Present | ✅ |
| Max Profit/Loss | Profit/Loss calc | Present | ✅ |
| Breakeven | Breakeven calc | Present | ✅ |
| Margin/Capital | Capital requirement | Present | ✅ |
| Risk | Risk metrics | Present | ✅ |
| "Build This Strategy" integration | Link from strategies page | Needs verification | 🟠 |

**Overall: 🟢 ALIGNED** — Structurally good. Integration workflow needs testing.

---

### /tools/backtest.html (Backtest)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Instrument | Selection | Present | ✅ |
| Strategy | Selection | Present | ✅ |
| Period/Lookback | Time range | Present | ✅ |
| Capital | Capital input | Present | ✅ |
| Risk/Trade | Risk parameters | Present | ✅ |
| Brokerage/Slippage | Cost model | Present | ✅ |
| Run | Execute backtest | Present | ✅ |
| Results | Trades/Win Rate/P&L/Profit Factor/Max Drawdown/Avg R | Empty until run (expected) | ✅ |
| Equity Curve | Chart | Empty until run (expected) | ✅ |
| Drawdown | Chart | Empty until run (expected) | ✅ |
| Trade Ledger | Table | Empty until run (expected) | ✅ |
| Deterministic disclaimer | AI excluded | Present | ✅ |

**Overall: 🟢 ALIGNED** — Good architecture. Empty results before run is expected behavior.

---

### /tools/position-size.html (Position Size)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Capital | Capital input | Present | ✅ |
| Risk % | Risk percentage | Present | ✅ |
| Risk Amount | Calculated risk | Present | ✅ |
| Entry | Entry price | Present | ✅ |
| Stop | Stop loss | Present | ✅ |
| Lot Size | Calculated | Present | ✅ |
| Number of Lots | Quantity | Present | ✅ |
| Position Size | Total size | Present | ✅ |
| Maximum Loss | Max loss | Present | ✅ |
| Link from strategy | Natural link from strategies | Needs verification | 🟠 |

**Overall: 🟢 ALIGNED** — Structurally good. Link integration needs testing.

---

### /scanner.html (Scanner)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Stock Scanner | Header | Present | ✅ |
| Filters | Bullish/Bearish/Range/Breakout/Breakdown/Buy/Hold/Exit/RSI/DMA/MACD | Present | ✅ |
| Market Regime | Regime indicator | Present | ✅ |
| Technical Signals | Signal display | Present | ✅ |
| Stock Results | Stock list | "Loading…" | 🔴 |
| Stock Detail | Individual stock detail | Not applicable without results | 🔴 |
| Secondary positioning | Visually secondary to index workflow | Needs verification | 🟠 |

**Overall: 🟠 PARTIAL** — Framework good, results loading.

---

### /mutual-funds/ (Mutual Funds)

| Section | Plan | Current | Status |
|---------|------|---------|--------|
| Best Mutual Funds | AMFI data | Present | ✅ |
| Secondary positioning | Not dominating TradingAI identity | Needs verification | 🟠 |
| Navigation distinction | Clearly separate from trading | Needs verification | 🟠 |

**Overall: 🟠 PARTIAL** — Data currently loading. Positioning needs verification.

---

## Summary

| Page | Status | Priority | Action |
|------|--------|----------|--------|
| / | 🟠 PARTIAL | P1 | Fix Loading… states, add freshness indicators |
| /indices/nifty.html | 🟠 PARTIAL → ✅ REDESIGNED | P1 | Full structural redesign complete — 7 sections as explicit HTML |
| /indices/banknifty.html | 🟠 PARTIAL | P1 | Verify against NIFTY template |
| /indices/finnifty.html | 🟠 PARTIAL | P1 | Verify against NIFTY template |
| /indices/sensex.html | 🟠 PARTIAL | P1 | Verify against NIFTY template |
| /today/index.html | 🟠 PARTIAL → ✅ REDESIGNED | P1 | Full structural redesign complete — 10 sections with loading states |
| /market.html | 🟠 PARTIAL → ✅ REDESIGNED | P1 | Full structural redesign complete — 7 sections as explicit HTML |
| /options/pcr.html | 🟠 PARTIAL | P1 | Verify data rendering |
| /strategies.html | 🟠 PARTIAL | P1 | Fix Loading… states |
| /strategy-builder.html | 🟢 ALIGNED | P2 | Test workflow integration |
| /tools/backtest.html | 🟢 ALIGNED | P2 | Verify (empty results expected) |
| /tools/position-size.html | 🟢 ALIGNED | P2 | Test workflow integration |
| /scanner.html | 🟠 PARTIAL | P2 | Fix Loading…, verify positioning |
| /mutual-funds/ | 🟠 PARTIAL | P3 | Fix Loading…, verify positioning |

---

## Non-Core Pages Requiring Classification

| File | Classification | Reason |
|------|----------------|--------|
| index.html | PENDING | Potential duplicate of / — needs PHASE 9 |
| alerts.html | PENDING | Not in approved manifest |
| etfs/* | ARCHIVE CANDIDATE | ETFS not in approved scope |
| evidence/historical.html | ARCHIVE CANDIDATE | Phase 8 tool, not public product |
| global/markets.html | ARCHIVE CANDIDATE | Global markets, not Indian index focus |
| history.html | ARCHIVE CANDIDATE | May overlap with replay |
| history/replay.html | ARCHIVE CANDIDATE | Phase 8 tool |
| market/outlook-nifty-2026-09-13.html | ARCHIVE | Single dated page |
| news/index.html | ARCHIVE CANDIDATE | News not in approved scope |
| options-mobile.html | ARCHIVE CANDIDATE | Mobile variant |
| portfolio.html | ARCHIVE CANDIDATE | Not in approved scope |
| queries/index.html | ARCHIVE CANDIDATE | Not in approved scope |
| sectors/top.html | ARCHIVE CANDIDATE | Not in approved scope |
| stock.html | ARCHIVE CANDIDATE | Overlaps scanner |
| stocks/* | ARCHIVE CANDIDATE | Stock data, overlaps scanner |
| tools/intelligence.html | KEEP (TOOL) | Phase 9C tool, useful |
| tools/journal.html | KEEP (TOOL) | Phase 9A tool, useful |
| tools/walkforward.html | KEEP (TOOL) | Phase 8 tool, useful |
| trade.html | PENDING | Trade setup, may be CORE |
