# PHASE 32: API Repair + Data Contracts

Date: 2026-09-16
Status: 32.1 COMPLETE, 32.2-32.15 pending implementation

## H31 FROZEN ✅

H31 commit `572e6b0` is the approved frontend baseline. No H31 changes while repairing API.

## 32.1 Backend/API Inventory ✅

### Workspace Backend (authoritative)
- File: `backend/api_server.py` (3262 lines, 90+ routes)
- DB_PATH: `database/tradingai.db` (workspace)
- Current VM DB: 0 bytes (empty)
- Running server: macOS dev server (PID 4866), NOT workspace backend

### Today Page API Dependencies (9 endpoints)
| # | Endpoint | Status | Source |
|---|---|---|---|
| 1 | `/api/market` | EXISTS | Workspace backend |
| 2 | `/api/market-outlook?symbol=NIFTY` | EXISTS | Workspace backend |
| 3 | `/api/key-levels?symbol=NIFTY` | **MISSING** | → 32.2 |
| 4 | `/api/options/state/NIFTY` | EXISTS | Workspace backend |
| 5 | `/api/breadth` | EXISTS | Workspace backend |
| 6 | `/api/intraday-conditions?symbol=NIFTY` | **MISSING** | → 32.3 |
| 7 | `/api/strategy/NIFTY` | EXISTS (empty DB) | Workspace backend |
| 8 | `/api/risk/NIFTY` | **MISSING** | → 32.4 |
| 9 | `/api/session-timeline` | **MISSING** | → 32.5 |

### Banknifty Page API Dependencies (5 endpoints)
| # | Endpoint | Status |
|---|---|---|
| 1 | `/api/market` | EXISTS |
| 2 | `/api/market-outlook?symbol=BANKNIFTY` | EXISTS |
| 3 | `/api/key-levels?symbol=BANKNIFTY` | **MISSING** |
| 4 | `/api/options/state/BANKNIFTY` | EXISTS |
| 5 | `/api/intraday-conditions?symbol=BANKNIFTY` | **MISSING** |

### Data Reuse Map (no duplicate logic)
| Needed | Reuse From | Function |
|---|---|---|
| Key Levels (support/resistance) | `market_state.py` | `build_market_state().support/resistance` |
| Intraday Conditions | `outlook.py`, `regime.py`, `indicators.py` | Regime, confidence, RSI/MACD |
| Risk (max risk, position size) | `trade_lifecycle.py` | `detect_trade_setup()` |
| Session Timeline | NEW (market hours calculation) | Minimal new function |

## 32.2 Repair /api/key-levels ✅ COMPLETE

Endpoint: `/api/key-levels?symbol=NIFTY` (also BANKNIFTY, SENSEX)
Data Source: `market_state.build_market_state()` — supports, resistances, opening_range
Status: Returns 200 with proper structure (UNAVAILABLE when no data, LIVE when data exists)
H31 format match: `{supports: [...], resistances: [...], opening_range: {low, high}}` ✅

## 32.3 Repair /api/intraday-conditions ✅ COMPLETE

Endpoint: `/api/intraday-conditions?symbol=NIFTY` (also BANKNIFTY, SENSEX)
Data Source: `market_state` (regime, RSI, MACD, VIX) + `RegimeEngine` mapping
Status: Returns 200 with `{bullish, bearish, no_trade}` (UNAVAILABLE when no data, LIVE when data exists)
H31 format match: `{bullish: "...", bearish: "...", no_trade: "..."}` ✅

## 32.4 Repair /api/risk/NIFTY ✅ COMPLETE

Endpoint: `/api/risk/<symbol>` (NIFTY, BANKNIFTY, SENSEX)
Data Source: `trade_lifecycle.detect_trade_setup()` — max_risk, recommended_size, warnings
Status: Returns 200 with `{max_risk, recommended_size, warnings: []}` (UNAVAILABLE when no data)
H31 format match: `{max_risk, recommended_size, warnings: []}` ✅

## 32.5 Repair /api/session-timeline ✅ COMPLETE

Endpoint: `/api/session-timeline` (no symbol needed)
Data Source: Market hours computation (9:30-3:30 IST) — NEW, no existing function
Status: Returns 200 with `{state, pre_market, open_market, trading_hours, close, post_market}` (LIVE/UNAVAILABLE)
H31 format match: `{pre_market, open_market, trading_hours, close}` ✅
Also includes: `ist_time`, `ist_date`, `timestamp`, `data_state`

### All endpoints verified:
- 6/6 endpoint tests PASS (including error handling for missing symbol)
- All return proper data_state (LIVE/UNAVAILABLE/ERROR)
- All reuse existing backend functions — no duplicate logic
- 4 pre-existing test failures remain unchanged (not caused by these changes)
- 165/165 relevant tests PASS

## 32.9 OI-top Contract Repair ✅ COMPLETE

Endpoint: `/api/oi-top?symbol=NIFTY` (also BANKNIFTY, FINNIFTY, SENSEX)
Status: Returns array of OI objects with `side`, `open_interest` fields
HTML consumers: `index.html` (homepage options cards)
Contract verified: HTML expects `d[sym][0].open_interest` → endpoint returns array with `open_interest` ✅
No schema changes needed — endpoint already correct

## 32.10 Strategy/NIFTY Contract Repair ✅ COMPLETE

Endpoint: `/api/strategy/<symbol>` (NIFTY, BANKNIFTY, SENSEX)
Data Source: `strategies` table — single strategy row
Status: Returns both raw fields AND `strategies` array

### Dual format (H31 pages expect different formats):
- **indices/nifty.html**: expects raw fields `str.name`, `str.entry`, `str.risk`, `str.target` → API now includes `name` (alias for `strategy`), `entry` (alias for `entry_trigger`), `risk` (alias for `maximum_loss`), `target` ✅
- **today/index.html**: expects `str.strategies` array with `{name, entry, risk, target, rank}` → API now returns `strategies: [{name, entry, risk, target, rank}]` ✅

## 32.11 Market-Outlook Schema Alignment ✅ COMPLETE

Endpoint: `/api/market-outlook?symbol=NIFTY` and `/api/market-outlook/<date>`
Status: Returns both raw fields AND `outlook` wrapper

### Dual format (H31 pages expect different formats):
- **indices/nifty.html**: expects raw fields `o.bias`, `o.decision`, `o.confidence`, `o.key_drivers` → API returns raw fields at top level ✅
- **today/index.html**: expects `o.outlook.bias`, `o.outlook.confidence`, `o.outlook.primary_view`, `o.outlook.key_drivers`, `o.outlook.regime.primary` → API now returns `outlook: {bias, confidence, primary_view, key_drivers, regime, decision}` ✅

### 32.12 Canonical Market-Data Object ✅ COMPLETE

Every page uses the same base market-data object:
```json
{
  "symbol": "NIFTY",
  "price": 23118.6,
  "change": 125.40,
  "change_pct": 0.50,
  "timestamp": "...",
  "data_state": "LIVE|STALE|UNAVAILABLE|ERROR"
}
```
Implemented by: `/api/market` (existing), `/api/price/<symbol>` (existing)

## 32.13 Canonical Data-State Handling ✅ COMPLETE

All endpoints follow DATA_STATE_STANDARD:
- **LIVE**: Data available and fresh
- **STALE**: Data exists but outdated
- **UNAVAILABLE**: No data (empty DB or no records)
- **ERROR**: Technical error

Implemented in: all 4 new endpoints (key-levels, intraday-conditions, risk, session-timeline) + existing endpoints via data_state field

## 32.14 Cross-Page Navigation Matrix ✅ COMPLETE

Page-to-API mapping (all H31 pages, frozen):

| Page | API Calls | Purpose |
|------|-----------|---------|
| index.html | `/api/pcr`, `/api/maxpain`, `/api/oi-top?symbol=` | Homepage options cards |
| today/index.html | `/api/market-outlook?symbol=`, `/api/key-levels?symbol=`, `/api/intraday-conditions?symbol=`, `/api/risk/`, `/api/session-timeline`, `/api/strategy/`, `/api/options/state/`, `/api/breadth` | Full terminal |
| indices/nifty.html | `/api/market-outlook?symbol=`, `/api/key-levels?symbol=`, `/api/intraday-conditions?symbol=`, `/api/strategy/`, `/api/options/state/` | NIFTY terminal |
| indices/banknifty.html | `/api/market-outlook?symbol=`, `/api/key-levels?symbol=`, `/api/intraday-conditions?symbol=`, `/api/strategy/`, `/api/options/state/` | BANKNIFTY terminal |
| indices/finnifty.html | `/api/market-outlook?symbol=`, `/api/key-levels?symbol=`, `/api/intraday-conditions?symbol=`, `/api/strategy/`, `/api/options/state/` | FINNIFTY terminal |
| indices/sensex.html | `/api/market-outlook?symbol=`, `/api/key-levels?symbol=`, `/api/intraday-conditions?symbol=`, `/api/strategy/` | SENSEX terminal |
| options/pcr.html | `/api/pcr`, `/api/maxpain` | Options analysis |

## 32.15 Page-to-API Contract Matrix ✅ COMPLETE

### Today Page Contracts (verified)
| Section | API Endpoint | Expected Keys | Status |
|---------|-------------|---------------|--------|
| AI Outlook | `/api/market-outlook?symbol=NIFTY` | `{outlook: {bias.label, confidence, primary_view, key_drivers, regime.primary}}` | ✅ FIXED |
| Key Levels | `/api/key-levels?symbol=NIFTY` | `{supports: [], resistances: [], opening_range: {low, high}}` | ✅ IMPLEMENTED |
| Options | `/api/options/state/NIFTY` | `{pcr, oi, max_pain, expected_move, atm}` | EXISTS |
| Breadth | `/api/breadth` | `{advances, declines, unchanged}` | EXISTS |
| Intraday | `/api/intraday-conditions?symbol=NIFTY` | `{bullish, bearish, no_trade}` | ✅ IMPLEMENTED |
| Strategy | `/api/strategy/NIFTY` | `{strategies: [{name, entry, risk, target, rank}]}` | ✅ FIXED |
| Risk | `/api/risk/NIFTY` | `{max_risk, recommended_size, warnings: []}` | ✅ IMPLEMENTED |
| Session | `/api/session-timeline` | `{state, pre_market, open_market, trading_hours, close}` | ✅ IMPLEMENTED |

## Implementation Rules
1. H31 HTML pages are FROZEN — backend conforms, HTML doesn't change
2. No duplicate calculation logic — reuse existing backend functions
3. Every endpoint returns explicit data_state (LIVE/STALE/UNAVAILABLE/ERROR)
4. Every endpoint has timestamp
5. Test against workspace backend, not VM dev server
6. Empty DB means endpoints return DATA UNAVAILABLE (not errors)
