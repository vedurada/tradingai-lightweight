# TradingAI — Adaptive AI Outlook & Market Decision Engine

## Implementation Date
2026-09-16

## Overview

TradingAI's AI Outlook Engine has been upgraded from a simple Bullish/Bearish/Wait classification to a full condition-driven market decision engine. The system now identifies market structure, directional bias, tradeability, trade type, and entry conditions before recommending any strategy.

**Core principle**: The engine is condition-driven, not direction-driven. It never forces a trade when conditions don't support one.

---

## Architecture

```
LIVE MARKET DATA
    ↓
DATA VALIDATION (LIVE/DELAYED/STALE/CLOSED/UNAVAILABLE/ERROR)
    ↓
INDICATOR ENGINE (EMA, VWAP, RSI, MACD, ADX, ATR, CPR, Pivot/S1-S3/R1-R3)
    ↓
ADAPTIVE CLASSIFICATION ENGINE (adaptive_engine.py)
    ↓
  market_structure (8 states)
  directional_bias (6 states)
  trade_class (4 types)
  trade_status (6 states)
  entry_trigger, confirmation, invalidation, target
    ↓
LLM LAYER (optional — explanation only, never overrides decisions)
    ↓
TRADINGAI UI (homepage, today terminal, index pages, strategies)
```

---

## Current AI Provider/Model Configuration

| Provider | Model | API Key | Status |
|----------|-------|---------|--------|
| **Groq** | `openai/gpt-oss-120b` | `GROQ_API_KEY` (/etc/tradingai/groq.env) | **WORKING** |
| Gemini | `gemini-2.0-flash` | `GEMINI_API_KEY` | Not configured |
| DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` | Not configured |
| OpenRouter | `google/gemini-flash-1.5` | `OPENROUTER_API_KEY` | Not configured |
| Ollama | `qwen2.5:0.5b` (local) | none | Removed (too slow) |

**Provider chain**: gemini → groq → deepseek → openrouter → rule-based fallback

The LLM runs **twice daily** (cron at 09:30/19:00 IST) for core indices only (NIFTY, BANKNIFTY, FINNIFTY, SENSEX). The intraday poller **never** calls the LLM — it reuses cached/stored results.

The LLM provides **EXPLANATION ONLY** — it cannot modify regime, bias, confidence, key levels, verdict, strategy, or any quantitative decision. All authoritative values come from the deterministic engine.

When the LLM fails or is unavailable, the **adaptive_engine.py** (rule-based) continues functioning with full structured output.

---

## Market Structure Definitions

| Structure | Description |
|-----------|-------------|
| **TRENDING_BULLISH** | Strong uptrend confirmed (price > EMA20/50, ADX > 25, momentum positive) |
| **TRENDING_BEARISH** | Strong downtrend confirmed (price < EMA20/50, ADX > 25, momentum negative) |
| **SIDEWAYS** | Range-bound, no trend strength (ADX < 25, price oscillating around VWAP) |
| **SIDEWAYS_TO_BULLISH** | Range-bound but evidence shifting upward (not confirmed) |
| **SIDEWAYS_TO_BEARISH** | Range-bound but evidence shifting downward (not confirmed) |
| **VOLATILE_EXPANSION** | Volatility expanded significantly, direction unclear |
| **TRANSITIONAL** | Market transitioning between two structures |
| **NO_TRADE** | No valid setup exists |

## Directional Bias

| Bias | Description |
|------|-------------|
| **BULLISH** | Strong upward directional tendency |
| **MILD_BULLISH** | Weak upward tendency, not confirmed |
| **NEUTRAL** | No directional edge |
| **MILD_BEARISH** | Weak downward tendency, not confirmed |
| **BEARISH** | Strong downward directional tendency |
| **MIXED** | Conflicting signals, no clear direction |

**Key principle**: Directional bias is independent from market structure. A SIDEWAYS_TO_BULLISH structure can have MILD_BULLISH bias, meaning the market is range-bound but evidence is shifting upward.

## Trade Classifications

| Class | Description |
|-------|-------------|
| **DIRECTIONAL** | Strong trend supports directional entry (spreads, not naked) |
| **MILD_DIRECTIONAL** | Weak directional tendency, conditional entry only |
| **NON_DIRECTIONAL** | Range conditions support non-directional strategy (e.g., Iron Condor) |
| **NO_TRADE** | No valid setup — do not trade |

## Trade Status

| Status | Meaning |
|--------|---------|
| **ACTIVE** | Entry conditions fully met — trade is live |
| **WATCH** | Monitoring for trigger — not yet actionable |
| **WAIT_FOR_CONFIRMATION** | Breakout/breakdown not yet confirmed — wait for trigger |
| **WAIT_FOR_PULLBACK** | Trend confirmed but price extended — wait for pullback |
| **CONDITIONAL** | Entry depends on specific condition being met |
| **NO_TRADE** | Current conditions do not support taking a position |

## Entry Engine

### Entry Triggers (examples)

| Structure | Status | Entry Trigger |
|-----------|--------|---------------|
| TRENDING_BULLISH | ACTIVE | Entry active — price holding above VWAP with positive momentum |
| TRENDING_BULLISH | WAIT_FOR_PULLBACK | Wait for pullback to VWAP or nearest support |
| SIDEWAYS_TO_BULLISH | WAIT_FOR_CONFIRMATION | Wait for 15-min close above resistance with volume confirmation |
| SIDEWAYS_TO_BEARISH | WAIT_FOR_CONFIRMATION | Wait for 15-min close below support with volume confirmation |
| VOLATILE_EXPANSION | NO_TRADE | No valid setup — excessive volatility |
| SIDEWAYS | NO_TRADE | No valid setup — no trend, no confirmation |

### Confirmation Conditions

- Price above/below VWAP
- MACD momentum positive/negative
- ADX confirms trend strength
- RSI supports direction
- Gap unfilled — continuation likely
- Volume confirmation

### Invalidation

| Structure | Invalidation |
|-----------|-------------|
| TRENDING_BULLISH | Close below S1/S2 invalidates bullish view |
| TRENDING_BEARISH | Close above R1/R2 invalidates bearish view |
| SIDEWAYS | Breakout below support or above resistance |
| VOLATILE_EXPANSION | Close beyond ATR range with VIX spike |

## Non-Directional Logic

If market conditions are:
- Low trend strength (ADX < 25)
- Stable range (price oscillating around VWAP/CPR)
- Support and resistance intact
- Expected range is defined
- Volatility is appropriate
- Options data is available and reliable

Then the engine may classify:
- **MARKET STRUCTURE**: SIDEWAYS
- **DIRECTIONAL BIAS**: NEUTRAL
- **TRADE CLASS**: NON_DIRECTIONAL
- **PREFERRED STRATEGY**: IRON_CONDOR (if strategy conditions satisfied)

**If conditions are unsuitable → NO_TRADE**. The engine does NOT force a non-directional strategy simply because the market is sideways.

## No-Trade Logic

NO_TRADE is a legitimate final outcome, not a fallback. Triggers:
- Conflicting signals (≥2 conflicting factors, ≤1 supporting)
- Excessive volatility (VIX HIGH/EXTREME)
- Insufficient data (data_state = UNAVAILABLE/ERROR/STALE)
- Poor market structure (no trend, no bias, no confirmation)
- Critical data missing (zero interpreted as missing, not valid)
- Strategy conditions not satisfied

**Important**: NO_TRADE ≠ NEUTRAL bias. A NO_TRADE decision means conditions don't support a position, regardless of directional bias.

---

## AI/LLM Responsibility Boundary

### LLM CAN do:
- Generate narrative interpretation/explanation
- Provide natural-language reasoning
- Synthesize supporting/conflicting factors
- Offer context for the structured decision

### LLM CANNOT do:
- Invent prices, support/resistance levels
- Fabricate PCR, OI, options data
- Override market structure, bias, or confidence
- Create entry triggers or invalidation levels
- Change trade status or trade class
- Generate confidence numbers (these come from the deterministic engine)

### Deterministic Engine ALWAYS provides:
- market_structure
- directional_bias
- trade_class
- trade_status
- entry_trigger
- confirmation_conditions
- invalidation
- target_zone
- preferred_strategy
- confidence (MODEL_CONFIDENCE)
- supporting_factors
- conflicting_factors

If LLM fails → "AI INTERPRETATION TEMPORARILY UNAVAILABLE" is displayed, but all structured data remains available from the deterministic engine.

---

## Data Quality States

Every input has a data state. Data quality affects confidence:

| State | Meaning | Effect |
|-------|---------|--------|
| **LIVE** | Fresh, real-time data | Full confidence |
| **DELAYED** | Data arrives with delay | Slightly reduced confidence |
| **STALE** | Data is old (FINNIFTY example) | 50% confidence reduction |
| **CLOSED** | Market closed | No trading |
| **UNAVAILABLE** | Data not available | NO_TRADE, reduced confidence |
| **ERROR** | API/connection error | NO_TRADE |

**Critical rule**: Never interpret raw zero as valid market value. Zero = missing data = UNAVAILABLE. This is especially important for FINNIFTY where yfinance returns 0.0 for spot/VWAP.

---

## Examples

### Example A: Sideways + valid range options
- Structure: SIDEWAYS, Bias: NEUTRAL
- Options/range: valid
- Result: NON_DIRECTIONAL, CONDITIONAL → IRON_CONDOR (if conditions satisfied)

### Example B: Sideways to Bullish, not confirmed
- Structure: SIDEWAYS_TO_BULLISH, Bias: MILD_BULLISH
- Breakout not confirmed
- Result: WAIT_FOR_CONFIRMATION (NOT "BUY CALL")

### Example C: Sideways to Bullish, confirmed
- Structure: SIDEWAYS_TO_BULLISH, Bias: MILD_BULLISH
- Breakout confirmed (15-min close above resistance)
- Result: DIRECTIONAL, ACTIVE → BULL CALL SPREAD

### Example D: Sideways to Bearish, not confirmed
- Structure: SIDEWAYS_TO_BEARISH, Bias: MILD_BEARISH
- Breakdown not confirmed
- Result: WAIT_FOR_CONFIRMATION

### Example E: Trending Bullish but extended
- Structure: TRENDING_BULLISH, Bias: BULLISH
- Price extended, poor risk/reward
- Result: WAIT_FOR_PULLBACK (NOT forced entry)

### Example F: Critical data missing
- Structure: ANY, Bias: ANY
- Critical data unavailable
- Result: NO_TRADE or DATA_UNAVAILABLE — never fabricated setup

---

## User Experience Flow

The system answers these questions in order:

1. **WHAT IS THE MARKET DOING?** → Market Structure
2. **WHAT IS THE MARKET STRUCTURE?** → TRENDING/SIDEWAYS/VOLATILE
3. **WHAT IS THE CURRENT BIAS?** → Directional Bias
4. **IS THERE A VALID TRADE NOW?** → Trade Status
5. **IF NOT, WHAT ARE WE WAITING FOR?** → Entry Trigger
6. **WHAT EXACTLY CONFIRMS ENTRY?** → Confirmation Conditions
7. **WHAT INVALIDATES THE VIEW?** → Invalidation
8. **WHAT STRATEGY TYPE FITS?** → Preferred Strategy
9. **WHAT IS THE MAXIMUM RISK?** → Risk/Invalidation
10. **WHAT DATA IS MISSING?** → Data State

---

## Implementation Files

| File | Role |
|------|------|
| `backend/adaptive_engine.py` | Core classification engine (NEW) |
| `backend/ai_outlook.py` | LLM engine + adaptive integration (MODIFIED) |
| `backend/outlook.py` | Framework outlook + adaptive payload fields (MODIFIED) |
| `static/js/ai-outlook.js` | Frontend dashboard renderer (consumes new fields) |
| `config/settings.json` | LLM provider config |

## Test Coverage

- Adaptive engine tests: Market classification, trade classification, entry, data quality, AI consistency
- Existing test suite: 1168/1168 passing (Phase 35 baseline preserved)
- Level invariant tests: S3 < S2 < S1 < Spot < R1 < R2 < R3 (Phase 35 protection)
- FINNIFTY unavailable-data handling preserved
- Options unavailable behavior preserved

---

## Checkpoints

- `phase35-complete` — Phase 35 completion (FROZEN)
- `adaptive-ai-outlook-complete` — This implementation (when tagged)

Do NOT modify or delete `phase35-complete`.
