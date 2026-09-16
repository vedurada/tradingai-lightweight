# TradingAI — Time-Aware Daily Market Cycle (Locked Product Requirement)

Created: 16 September 2026
Baseline: 3e8f0e2
Status: LOCKED REQUIREMENT — Implementation: Phase 33+ (after runtime/API verification)
Companion: docs/TRADINGAI_STRATEGIC_DIRECTION.md

---

## Core Requirement

TradingAI must be a time-aware daily market intelligence system:

PRE-MARKET → OPEN → LIVE INTRADAY → MARKET CLOSE → POST-MARKET

with timestamped AI outlook snapshots preserved historically for each trading session.

---

## Market State Machine

```
PRE_MARKET
    │ market opens
    ▼
OPEN
    │
    ▼
LIVE
    │ market closes
    ▼
CLOSED
    │ next trading day
    ▼
PRE_MARKET
```

Separate from market state, data has its own state: LIVE / UPDATED / STALE / UNAVAILABLE / ERROR.
Both concepts are independent — LIVE MARKET + STALE DATA is possible and should be shown.

---

## Daily Lifecycle Detail

### 1. Pre-Market (before 09:15 IST)

Generate dated pre-market outlook using verified available data:
- Previous close
- Overnight/global inputs where available
- GIFT NIFTY if reliable source available
- India VIX
- Previous-day levels
- CPR
- Important support/resistance
- Options positioning (PCR/OI)
- Expected move
- Volatility context
- Scheduled market events where data available

Output: "Pre-Market Outlook — 16 Sep 2026" with regime, expected opening context, key levels, options positioning, potential scenarios, invalidation, risk.

Must NOT pretend live market data exists before market opens.

### 2. Market-Open Transition (09:15 IST)

Automatic transition: PRE-MARKET → OPEN → LIVE as fresh data arrives.

Display should show:
```
● LIVE MARKET
16 Sep 2026 · 10:42 IST
Data updated 10:41 IST
```

NOT just generic "Market Status: LIVE" all day.

### 3. Live Intraday AI Outlook

Generate time-stamped outlook snapshots, not one static paragraph:
- 09:20 AI Outlook
- 09:45 AI Outlook
- 10:15 AI Outlook
- 11:00 AI Outlook
- 12:00 AI Outlook
- 13:00 AI Outlook
- 14:00 AI Outlook
- 15:15 AI Outlook

Each snapshot records: date, time, market state, index, regime, directional bias, confidence, support/resistance, PCR, OI context, expected move, technical conditions, AI reasoning, invalidation, risk state, data timestamp.

### 4. Historical Preservation (CRITICAL)

DO NOT overwrite previous outlook. Preserve ALL snapshots per session:

```
AI OUTLOOK HISTORY — 16-Sep-2026
09:20  → Outlook A (Range/neutral)
09:45  → Outlook B
10:30  → Outlook C
11:15  → Outlook D (Momentum developing)
13:30  → Outlook E (Trend weakening)
```

Current page shows latest snapshot; historical data remains available.

### 5. Market Close (15:30 IST)

Transition to MARKET CLOSED → generate post-market summary:
- Market Summary (Open → High → Low → Close)
- Trend/Regime, Volatility, Breadth
- Options positioning, PCR/OI changes
- Key levels
- AI Session Summary (what happened, which scenario, which levels mattered, how conditions changed)
- Next Session Preparation (key levels, options context)

Dated and archived.

### 6. Next Day

Next morning: PRE-MARKET — 17 Sep 2026

---

## Architecture

```
MARKET DATA → INDICATORS → MARKET REGIME → OPTIONS INTELLIGENCE → AI OUTLOOK ENGINE
    ↓
Timestamped AI Snapshot:
  Date, Time, Market State, Regime, Direction, Confidence, Evidence,
  Key Levels, Options Context, Invalidation
    ↓
SQLite / historical archive
```

Same HTML renders different state based on current JSON data. Backend updates data; frontend renders state.

---

## Existing Assets

Likely supported by:
- `history` table — timestamps, regime, indicators, strategy, outcome
- `history_archive` table — historical patterns
- `ai_outlook` table — existing outlook generation pipeline
- `market_outlooks` table — daily outlook records
- Regime/scenarios/strategies tables — existing data

Phase 30/30B/30C must verify this BEFORE implementing new APIs.

---

## Implementation Sequence

1. Phase 30 — VM inventory (read-only)
2. Phase 30B — Dependency mapping
3. Phase 30C — Verify 4 runtime risks
4. Phase 31 — Confirm classifications
5. Phase 32 — API contract repair
6. Phase 33 — Runtime browser audit
7. **Phase 34+ — Time-aware lifecycle implementation** (after above complete)

Do NOT implement time-aware APIs before Phase 32.
First inspect existing Flask/database/history implementation.

---

## User Experience Test

- 8:45 AM → PRE-MARKET OUTLOOK
- 9:40 AM → LIVE — 9:40 AM (updated based on market behavior)
- 11:30 AM → LIVE — 11:30 AM (regime changed)
- 2:45 PM → LIVE — 2:45 PM (current conditions)
- 3:35 PM → MARKET CLOSED (session summary)
- Next morning → PRE-MARKET — 17 Sep 2026

This is the daily-repeat-visit loop.
