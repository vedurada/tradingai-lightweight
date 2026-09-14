# PHASE 7 — End-to-End Integration Audit (read-only, uncommitted)

**Scope**: source → fetch → DB → processing → API → JS → HTML for the frozen
artifact (`6befcad`). No writes, no fixes, no commits. Backend frozen — findings
that need engine changes stop at documentation.

## 1. Data lineage — golden paths (verified live, snapshots 10:29–10:50 UTC)

| Datum | Source/log | DB | API | UI mapping | Verdict |
|---|---|---|---|---|---|
| NIFTY spot 23398.1 | NSE log 15:59 IST | live_quotes fresh | `/api/market` quote.price identical | `fp()` en-IN | 🟢 PASS, same snapshot |
| BANKNIFTY 56606.55 / FINNIFTY 25545.4 | same fetch | same | same | same | 🟢 PASS |
| VIX 12.27 | vix_data intraday fresh | fresh | API + `vixRegime()` | thresholds documented | 🟢 PASS |
| PCR 0.64 / MaxPain 25750 | pcr_history **dated 09-10** | 1 trading-day stale (Fri 09-11 missing) | expiries[0] passthrough | `toFixed`, no rescaling | 🟡 P4 freshness note, values intact |
| Confidence 64 / exp_range | market_outlooks | full | present | bars/levels | 🟢 PASS |
| FINNIFTY outlook | market_outlooks FULL today (~5KB) | ok | `ai_outlooks` = `"{}"` | S3 no-data branch | 🟡 Presentation handled; pipeline split (see §5) |

Endpoint discipline: the render path uses `/api/market-outlook?symbol=` (deterministic
payload, all consumed keys present). `/api/outlook/<sym>` (AI-summary layer, sparse
keys) is NOT consumed by the main UI — recorded to prevent future confusion.

## 2. Database integrity (read-only queries)

- `price_1d`: 44 symbols, 17,372 rows, max 09-11 (Friday; weekend gap normal).
- **FINNIFTY: 7 rows vs ~250** — skew originates at FETCH/backfill coverage, upstream
  of the generator. Root-cause location identified (frozen).
- `vix_data` intraday fresh; daily VIX series thin (6 rows) — non-blocking.
- `oi_top_strikes`: 8,248 rows, fresh 09-11, broad symbols. 🟢
- `ai_outlooks`: FINNIFTY `"{}"` ×1012 + COALINDIA ×1 — persistent summarizer
  emptiness for FINNIFTY (frozen). No other symbol affected.
- **`fetch_health`: EMPTY — `_record_fetch_result()` has zero callers.** B6.7
  shipped write-never. P4 (questions B6 acceptance; needs scoped follow-up, not E2E fix).
- `live_quotes`: 4 rows, fresh. `monitor.log`: FAIL lines reference legacy
  `nifty.json` + cron check — stale monitor expectations post-cleanup (P4).

## 3. Fetch pipeline

26-line crontab correct; `data.log` shows healthy intraday NSE fetches through
15:59 IST; backfill Sundays; backup/cleanup/self-heal wired. No failed-fetch
evidence today. Scheduler gap: none observed. FINNIFTY thinness = coverage config,
not runtime failure.

## 4. API contracts (consumed paths only)

`/api/market` (instruments/quote/regime) · `market-outlook?symbol=` (full outlook
schema — all UI-read keys present) · `vix` · `breadth` · `maxpain`/`pcr` ·
per-symbol feeds. Field names/types/units match JS readers; nullability handled
(`!= null` guards); timestamps present (`last_updated`, `computed_at`).

## 5. HTML→JS component map

Snapshot ids ← `dashboard.js` + S2 prerender ← `/api/market` · outlook sections ←
`ai-outlook.js` ← market-outlook/vix/breadth · PCR/MaxPain rows ← `options.js` ←
pcr/maxpain endpoints · strategies ← `strategies.js` · scanner/backtest/historical
paths unchanged. No orphaned components found; no UI field without a provider
(except known FINNIFTY-outlook → guarded).

## 6. Formatter boundaries (executed, 12/12)

`0→0.00`, `-0.01`, `1,00,000.00`, `null→—`, `NaN→NaN` (honest, no crash),
`Infinity→∞`, sign handling, `%`, `""`/`"{}"`→empty-state. Missing ≠ zero upheld.

## 7. Cross-instrument matrix

NIFTY/BANKNIFTY/SENSEX full-path green. FINNIFTY: price path green, outlook path
honestly empty (guarded). VIX green. No hard-coded single-symbol assumptions found.

## 8. Data→layout interaction (limits)

State branches (loading/valid/empty/error-stale) verified in code + prerender
SKIP path executed (exit 3, values preserved). Visual shift/overflow needs
rendering — joins existing device deferrals; pathological-data layout cases
(long labels, huge OI) unrendered here.

## Findings (classified)

- P0/P1/P2: **NONE**.
- P4: PCR 1-day staleness · `fetch_health` write-never · monitor legacy checks ·
  FINNIFTY fetch skew + summarizer emptiness (boundary) · sitemap gaps (prior).
- All P4s are documented future/boundary scope, none block the frozen artifact.

## Overall E2E verdict

**🟢 E2E PASS** — every traceable datum is consistent across layers at matching
snapshots; empty states are honest; no silent transforms; no cross-boundary fix
required. Push gate: no E2E blocker found (push itself still needs explicit auth).
