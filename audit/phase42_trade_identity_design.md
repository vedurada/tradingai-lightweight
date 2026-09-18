# Phase 42 — Trade Identity Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Define what a "distinct setup" should mean

---

## Problem

1,184 trades were generated from 1,950 candles over 26 days. 87.2% of re-entries occurred within 5 minutes. The trade count may be inflated by:
- Repeated signals on the same setup
- Candle-by-candle qualification (each candle re-qualifies independently)
- Lack of setup persistence (no cooldown after exit)
- Re-entry behavior
- Direction changes within same setup

## Proposed Setup Definitions

### Definition A: Instrument + Date + Direction

```
Setup = instrument + date + direction (BULLISH/BEARISH)
```
- Simple to compute
- May group multiple entries under one setup
- Does not capture regime or evidence state

### Definition B: Instrument + Date + Direction + Strategy

```
Setup = instrument + date + direction + strategy
```
- More granular
- Same instrument/date/direction with different strategies = different setups
- Strategy is None in replay (bug), so this needs fixing first

### Definition C: Instrument + Date + Direction + Regime + Evidence State

```
Setup = instrument + date + direction + regime + evidence_state_summary
```
- Captures market context
- More robust against regime changes mid-setup
- Complex to compute

### Definition D: Entry Timestamp Window

```
Setup = instrument + (entry_timestamp rounded to N minutes) + direction
```
- Simple time-based grouping
- N = 5 minutes (one candle) may be too granular
- N = 30 minutes may be too coarse

## Signal Persistence

**Question**: How many consecutive 5m candles represent the same setup?

Options:
1. Each candle = new potential setup (current behavior)
2. Each setup persists until exit (no re-qualification)
3. Each setup persists for N candles after qualification
4. Setup persists while market state doesn't change

## Re-entry Classification

When should a new trade count as:

| Category | Definition | Research Implication |
|----------|-----------|---------------------|
| Same setup | Continuation of existing position | Should not count as independent |
| Continuation | Adding to position | May need position sizing analysis |
| New setup | Distinct setup after exit | Counts as independent |
| Exit/re-entry | Exit and re-enter same direction | May be legitimate or duplicate |

## Cooldown Research

Should a later Phase 42 experiment test a cooldown?

**Documented for future research**:
- Cooldown duration options: 5min, 15min, 30min, 1hr, until next signal
- Cooldown applies after: exit, NO_TRADE, strategy change
- Cooldown research is NOT implementation — only documentation

## Recommendation for Phase 42

1. Define "independent setup" using Definition A + E (instrument + date + direction + regime)
2. Measure: trade count vs independent setup count
3. Determine: what percentage of 1,184 trades are genuinely independent
4. Document: whether 1,184 or a much smaller number is the correct sample size
