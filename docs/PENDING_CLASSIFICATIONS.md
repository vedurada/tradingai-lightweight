# PENDING Page Classifications

Date: 16 September 2026
Baseline: v2b5583a-baseline

Classification key:
- KEEP — Product page, currently functional or useful
- ARCHIVE — Move outside production webroot (retain for recovery)
- DELETE — Remove after dependency verification (VM only)
- REDIRECT — Preserve URL mapping (VM only)
- PENDING-NEEDS-DECISION — Requires further analysis

---

## Decisions

| Page | Classification | Rationale |
|------|----------------|-----------|
| **index.html** | **KEEP — REDIRECT to /** | Duplicate of / with same canonical. Server should 301 /index.html → /. No content changes needed. |
| **trade.html** | **KEEP (AUXILIARY)** | Phase 4 intraday trade setup with full lifecycle (DETECTED→COMPLETE). Working API integration. Not in approved hierarchy but implements core trade setup workflow. Keep as AUXILIARY. |
| **evidence/historical.html** | **KEEP (TOOL)** | Phase 8 Historical Evidence engine. Deterministic matching. Working UI with loading/error/results states. Part of product architecture. |
| **history/replay.html** | **KEEP (TOOL)** | Phase 8 Historical AI Replay. Working UI. Part of product architecture. |
| **history.html** | **KEEP (TOOL)** | Trade P&L History. Related to journal/replay ecosystem. |
| **tools/intelligence.html** | **KEEP (TOOL)** | Phase 9C personal trading intelligence. Working UI with SUFFICIENT_DATA/INSUFFICIENT_DATA. |
| **tools/journal.html** | **KEEP (TOOL)** | Phase 9A immutable trade journal. Core Phase 9 feature. |
| **tools/walkforward.html** | **KEEP (TOOL)** | Phase 8 walk-forward validation. Core Phase 8 feature. |
| **alerts.html** | **ARCHIVE** | Market Alerts (PCR & OI Signals). Not in approved scope. No corresponding plan page. |
| **options-mobile.html** | **ARCHIVE** | Mobile-first options variant. Responsive design in main pages handles this. |
| **etfs/holdings.html** | **ARCHIVE** | ETFS section not in approved scope. Secondary SEO value doesn't justify separate product page. |
| **etfs/top-etfs.html** | **ARCHIVE** | Same rationale as etfs/holdings.html. |
| **global/markets.html** | **ARCHIVE** | Global markets, not Indian index focus. Contradicts primary audience. |
| **market/outlook-nifty-2026-09-13.html** | **ARCHIVE** | Single dated snapshot page. Dynamic / handles this. |
| **news/index.html** | **ARCHIVE** | News section not in approved scope. |
| **portfolio.html** | **ARCHIVE** | Portfolio tracker not in approved scope. Overlaps with journal. |
| **queries/index.html** | **ARCHIVE** | Query library not in approved scope. |
| **sectors/top.html** | **ARCHIVE** | Sector data not in approved scope. Overlaps with market data. |
| **stock.html** | **ARCHIVE** | Single stock outlook. Overlaps with scanner functionality. |
| **stocks/52-week.html** | **ARCHIVE** | Stock data, overlaps scanner. Not in approved scope (secondary). |
| **stocks/reliance.html** | **ARCHIVE** | Single stock page. Not in approved scope. |
| **stocks/top-large-cap.html** | **ARCHIVE** | Stock data, overlaps scanner. Not in approved scope. |
| **stocks/top-mid-small.html** | **ARCHIVE** | Stock data, overlaps scanner. Not in approved scope. |
| **stocks/top-performers.html** | **ARCHIVE** | Stock data, overlaps scanner. Not in approved scope. |
| **stocks/undervalued.html** | **ARCHIVE** | Stock data, overlaps scanner. Not in approved scope. |

---

## Summary Counts

| Action | Count |
|--------|-------|
| KEEP | 9 |
| ARCHIVE | 16 |
| DELETE | 0 (pending VM dependency check) |
| REDIRECT | 1 (index.html → /) |

## Notes

- **index.html** has canonical `https://tradingai.in/` pointing to /. Server should 301. Verify on VM.
- **trade.html** references `/api/trade-setup/` endpoint which is a backend dependency. Do not delete.
- All ARCHIVE candidates should be moved to `archive/YYYY-MM-DD/` outside webroot, not deleted, until VM verification.
- **tools/journal.html** and **tools/intelligence.html** are Phase 9 tools that depend on journal database. Do not delete.
- **history/replay.html** and **evidence/historical.html** are Phase 8 tools that depend on replay/evidence APIs. Do not delete.
- **tools/walkforward.html** is Phase 8 tool. Do not delete.
- All stock/* and stocks/* pages overlap with scanner and are not in the intraday-index-options primary scope.
