# Phase 42A — Setup Identity Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Constraint**: Setup identity is RESEARCH ONLY. No filtering, no deduplication, no cooldown.

---

## Design Requirements

1. Every completed 5-minute candle with trade qualification attempt must have a setup_id
2. Setup ID must be deterministic (same inputs → same ID)
3. Setup fingerprint must capture all relevant decision context
4. No future information in fingerprint
5. No change to production behavior
6. Research only — no trading decisions affected

## Setup ID Generation

```python
def generate_setup_id(instrument, candle_timestamp, direction):
    raw = f"{instrument}|{candle_timestamp}|{direction}"
    return f"SETUP-{sha256(raw).hexdigest()[:16].upper()}"
```

## Setup Fingerprint Generation

```python
def generate_setup_fingerprint(
    instrument, trading_date, direction, regime, trade_state,
    strategy, evidence_state, ai_outlook_id
):
    raw = "|".join([instrument, trading_date, direction, regime,
                     trade_state, strategy, evidence_state, ai_outlook_id])
    return sha256(raw).hexdigest()[:24].upper()
```

## Setup Identity Fields

| Field | Source | Purpose |
|-------|--------|---------|
| instrument | Trade qualification | Which instrument |
| trading_date | candle_timestamp[:10] | Trading day |
| direction | Trade qualification | BULLISH/BEARISH/NEUTRAL |
| regime | Market regime engine | Market regime at decision |
| trade_state | Trade qualification | TRADE/WAIT/NO_TRADE |
| strategy | Strategy selection | Selected strategy |
| evidence_summary | Market evidence engine | Evidence state at decision |
| ai_outlook_id | AI outlook | Associated AI outlook |

## Setup Type Classification

| Type | Definition | Notes |
|------|-----------|-------|
| NEW | First trade for this setup fingerprint | Baseline |
| CONTINUATION | Same setup, continuing position | To be refined |
| REENTRY | Re-entry after exit | Recorded in re-entry log |

## What Is NOT Changed

- **No cooldown**: Duplicate setups are still allowed
- **No filtering**: Every qualified trade still creates a trade
- **No rejection**: Duplicate setup fingerprint doesn't prevent trade
- **No re-entry logic change**: Re-entry behavior unchanged

## Purpose

The setup fingerprint allows future analysis:
1. How many unique setups exist vs total trades?
2. What percentage are duplicates?
3. How long do setups persist?
4. When do re-entries represent genuinely new opportunities?

## Fingerprint Without Future Info

The fingerprint uses ONLY:
- instrument (known at decision)
- trading_date (known at decision)
- direction (known at decision)
- regime (known at decision)
- trade_state (known at decision)
- strategy (known at decision)
- evidence_state (known at decision)
- ai_outlook_id (known at decision)

NO: outcome, P&L, future candle, exit price, win/loss
