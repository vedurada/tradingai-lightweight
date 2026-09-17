# Phase 40 — Evidence Replay Document

## 1. Replay Architecture

The deterministic evidence engine can be replayed over historical NIFTY 5-minute data.
This is a STRUCTURAL REPLAY of the evidence engine, NOT historical AI performance.

> The deterministic evidence engine is historically replayable.
> This does NOT constitute historical AI performance unless actual historical AI outputs were stored and evaluated.

## 2. Replay Procedure

```text
Historical 5m candle 1 → evidence_engine.evaluate() → evidence record
Historical 5m candle 2 → evidence_engine.evaluate() → evidence record
...
Historical 5m candle N → evidence_engine.evaluate() → evidence record
```

Each evaluation is deterministic — same input always produces same output.

## 3. Data Source

Primary: `price_5m` table (NIFTY 5-minute candles from VM DB)
Supporting: `indicators`, `market_regime`, `option_chain`, `vix_data`

## 4. Signal Distribution (Expected)

When replayed over 30 days of NIFTY 5-minute data, expected distributions:

| Signal | Expected Proportion |
|--------|-------------------|
| BULLISH | ~25-35% |
| BEARISH | ~20-30% |
| RANGE | ~15-25% |
| MIXED | ~10-20% |
| INSUFFICIENT_DATA | ~5-15% |

Note: Actual numbers depend on market conditions during the replay period.

## 5. Evidence Funnel

```text
Total 5-minute candles (N)
        ↓
Candles with valid snapshot (≥ 95% of N)
        ↓
Candles with all 6 evidence groups available (~60-80% of N)
        ↓
Candles with directional evidence (BULLISH/BEARISH/RANGE) (~40-60% of N)
        ↓
Candles with overall signal (always ≤ directional count)
        ↓
AI outlook generated (only on material change triggers)
        ↓
Strategy condition evaluated (separate engine)
        ↓
Trade condition satisfied (rare, by design)
```

## 6. Conflict Frequency

Expected: ~5-15% of candles have conflicting evidence (different groups disagreeing).

High conflict indicates market uncertainty — aligns with "WAIT" trade state.

## 7. Data Availability

| Data Source | Availability | Notes |
|------------|-------------|-------|
| Price (5m) | HIGH | Core input |
| Indicators (EMA, RSI, MACD, ADX) | HIGH | Calculated from price |
| VWAP | HIGH | Calculated from price |
| VIX | MEDIUM | May have gaps |
| Options (PCR, OI) | LOW | EOD or delayed |
| Market breadth | MEDIUM | May have gaps |
| Support/Resistance | HIGH | From indicators table |

## 8. Replay Output Files

- `audit/phase40_evidence_distribution.csv` — Signal distribution per candle
- `audit/phase40_signal_funnel.csv` — Funnel from candle → evidence → AI → trade

## 9. What Replay Does NOT Prove

- Historical AI accuracy (no AI outputs were stored for historical candles)
- Strategy profitability (strategy engine is separate)
- Win rate (not calculated, would require actual AI outputs)

## 10. Replay Use Cases

1. **Structure validation**: Verify evidence engine produces sensible signals across market conditions
2. **Threshold calibration**: Understand default threshold behavior (NOT optimization)
3. **Missing data analysis**: Identify which data gaps affect evidence quality
4. **Conflict analysis**: Understand how often evidence groups disagree
