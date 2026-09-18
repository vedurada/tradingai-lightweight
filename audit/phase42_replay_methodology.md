# Phase 42 — Replay Methodology

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Design proper replay methodology for Phase 42 research

---

## Current Replay Limitations

1. **Candle-by-candle qualification**: Each 5m candle independently re-qualifies the full pipeline, potentially creating artificial trades from the same setup
2. **Strategy=None bug**: `_determine_strategy` called before `trade_status` set to TRADE in replay mode — all 1,184 trades have strategy=None
3. **No AI in replay**: AI outlook generation was not called during historical replay
4. **Exit-order ambiguity**: Stop and target may occur in same OHLC candle
5. **Market state persistence**: Market state may not change between adjacent candles
6. **No setup persistence tracking**: No concept of "same setup" across multiple candles

## Proposed Replay Methodology

### Option A: Strict Setup Persistence

1. Generate setup signal from first qualifying candle
2. Hold setup until exit condition OR market state change
3. Count as ONE trade per setup
4. Re-entry after exit counts as new trade only if setup criteria are met again

**Research impact**: Dramatically reduces trade count (1,184 → estimated 200-400 independent setups)

### Option B: Pipeline per Candle (Current)

1. Each 5m candle runs through full pipeline independently
2. Trade created if all qualification checks pass
3. Multiple trades per setup possible
4. Current replay behavior

**Research impact**: Trade count = 1,184 (current)

### Option C: Hybrid

1. Setup created on first qualifying candle
2. Setup persists for N candles or until exit
3. Re-entry within same setup = position management (not new trade)
4. New setup = different direction, different regime, or N candle gap

**Research impact**: Moderate reduction in trade count

## Strict No-Lookahead Requirement

At each timestamp, ONLY data ≤ that timestamp may be used:
- NO future candle close
- NO future VWAP
- NO future RSI
- NO future EMA
- NO future options OI
- NO future AI outlook
- NO future trade outcome
- NO future regime information

### Verification Method

For each trade in replay, verify:
1. All indicators used were computable at trade timestamp
2. No data from later timestamps appears in entry decision
3. Exit decision uses only data available at exit timestamp

## Phase 37 vs Phase 41 Comparability

Phase 37 baseline:
- 12 trades
- 16.67% win rate
- Approximately -₹90,576 P&L

Phase 41 baseline:
- 1,184 trades
- 38.43% win rate
- -₹130,391.72 P&L

**These are NOT comparable because**:
- Different trade counts (12 vs 1,184)
- Different methodologies (Phase 37: simpler; Phase 41: full pipeline)
- Different sample sizes
- Different time periods potentially

**Research requirement**: Any future comparison must use identical methodology on identical data.

## Replay Verification Checklist

For each Phase 42 replay run, verify:
- [ ] All indicators computed only from data ≤ trade timestamp
- [ ] No future data in any entry decision
- [ ] Strategy field correctly populated
- [ ] AI outlook timestamps are before trade timestamps (if AI included)
- [ ] Exit decisions use only data ≤ exit timestamp
- [ ] Trade timestamps match candle timestamps
- [ ] No duplicate trades from same setup
- [ ] All data gaps documented
