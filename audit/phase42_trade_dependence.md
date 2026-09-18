# Phase 42 — Trade Dependence Analysis Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Determine how many of 1,184 trades are genuinely independent

---

## Problem

1,184 trades over 26 days from 1,950 candles. Many trades may come from the same market move, same setup, or same directional sequence. Treating all 1,184 as independent observations overstates confidence.

## Types of Trade Dependence

### Type 1: Consecutive Trades from Same Market Move

A single market move (e.g., NIFTY rally from 23000 to 23100) may trigger:
- Initial entry
- Re-entry after exit
- Multiple qualifications on the same move

**Test**: For each trade, identify if it occurred within 5/10/15 minutes of previous same-direction trade.

### Type 2: Repeated Entries (Same Setup)

The same setup may generate multiple trades:
- Re-entry after stop-out
- Multiple signals on same setup before exit

**Test**: For each trade, check if same instrument + same direction + same regime existed in previous N candles.

### Type 3: Overlapping Exposure

Was there ever more than one position open at the same time?
- Check: were there any overlapping timestamps?
- If yes, PnL attribution is ambiguous

**Test**: For each pair of trades, check if their time ranges overlap.

### Type 4: Same-Direction Sequences

Consecutive BULLISH trades (or consecutive BEARISH trades) may be driven by:
- One extended move (multiple signals)
- Multiple independent moves

**Test**: Compute run-length of same-direction sequences.

### Type 5: Same Evidence State

Trades generated from identical or very similar evidence states are not independent.

**Test**: Compare evidence group scores between consecutive trades.

## Measurement Design

### Independence Score (Per Trade)

For each trade T, compute:
- Minutes since previous same-instrument trade
- Same direction as previous trade? (Y/N)
- Same regime as previous trade? (Y/N)
- Overlaps with any open position? (Y/N)
- Evidence score distance from previous trade (0-100%)

### Clustering

Group trades into clusters where:
- Same instrument AND
- Same direction AND
- Gap < 15 minutes AND
- Same regime

Number of clusters = estimate of independent setups (minimum).

### Expected Results

Based on Phase 41 data:
- 1,184 trades, 26 days, 45.54 trades/day
- If each trading day has ~3-5 independent setups (intraday): ~78-130 independent setups per instrument
- Expected independent setup range: 50-200 (unknown, needs calculation)
- Trade-to-setup ratio: potentially 6:1 to 24:1

## Not-Independent Trade Impact

If 1,184 trades represent 150 independent decisions:
- Standard error of WR: sqrt(0.3843*0.6157/150) = 0.040 = ±4.0% at 95% CI
- vs if truly 1,184 independent: ±1.8%
- 2.2x wider confidence interval
- Drawdown calculations similarly affected

## Methodology for Phase 42

1. Apply independence scoring to all Phase 41 trades
2. Count independent setups (using multiple methods)
3. Compare: raw trade count vs independent count
4. Report: "1,184 trades represent approximately X independent setups"
5. Use X (not 1,184) for all statistical analysis going forward

## Production Data Collection Requirement

For production trades, log:
- Trade entry timestamp
- Previous trade exit timestamp (for same instrument)
- Setup ID (if applicable)
- Position state (OPEN/CLOSED) at entry time
- This enables automatic independence tracking going forward
