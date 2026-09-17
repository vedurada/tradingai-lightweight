# Phase 41 — Trade Attribution & AI Contribution Analysis
Generated: 2026-09-17

## Core Question: What Produces the 38.43% Win Rate?

**Answer**: The deterministic qualification framework, NOT AI prediction.

## Architecture: AI is INPUT ONLY

```
AI Outlook (input) → Evidence Engine → Qualification Engine → Strategy → Paper Trade → PnL
                     (rules-based)    (rules-based)         (rules-based) (rules-based) (rules-based)
```

### AI Involvement in Each Stage

| Stage | AI Role | AI Calculation? | Evidence |
|-------|---------|----------------|----------|
| Evidence evaluation | None | NO | EMA, RSI, VWAP, ADX — mathematical |
| Market state | None | NO | Regime detection — deterministic |
| AI outlook | INPUT | N/A | Generated separately by Groq LLM |
| Qualification | Validates AI fields | NO | Boolean checks on AI output |
| Strategy selection | None | NO | Bias → strategy mapping |
| Paper trade | None | NO | Entry/exit simulation |
| PnL calculation | None | NO | (exit-entry)×quantity |
| Statistics | None | NO | Deterministic formulas |

## What AI Contributes

1. **Bias**: BULLISH/BEARISH/RANGE/MIXED classification (AI-generated)
2. **Trade State**: TRADE/WAIT/NO_TRADE (AI-generated)
3. **Confidence**: Numeric confidence score (AI-generated)
4. **Confirmation/Invalidation**: Conditions (AI-generated)

## What AI Does NOT Do

1. Does NOT determine entry timing (qualification engine does)
2. Does NOT calculate stop/target (strategy engine does)
3. Does NOT calculate PnL (paper trade engine does)
4. Does NOT select strategy (strategy selection does)
5. Does NOT compute statistics (deterministic code does)
6. Does NOT decide trade frequency (evidence engine does)

## Critical Attribution Statements

### VALID
- "Rules-based framework achieved 38.43% win rate"
- "Evidence engine classified 61.4% of candles as directional"
- "Qualification pipeline passed 100% of directional signals"
- "BULLISH trades had 0.7% win rate in bearish market"
- "BEARISH trades had 50.2% win rate"

### INVALID
- "AI achieved 38.43% win rate" ← NO AI in decision-making
- "AI accuracy = 38.43%" ← AI not making accuracy decisions
- "AI produced 1,184 trades" ← Evidence engine produces signals
- "AI strategy returned 50.2% on BEARISH" ← Strategy selection is rules-based

### CORRECT ATTRIBUTION
- "The deterministic Phase 41 framework, using AI outlook as INPUT,
  simulated 1,184 trades with 38.43% win rate and -₹130,392 net PnL"
- "AI outlook bias was used as input; all trading decisions were rules-based"

## Historical AI Performance: NOT MEASURABLE

From `audit/phase41_current_state.md`:
> "No historical AI outputs stored: AI outlook generation during historical replay
> is NOT claimed as historical AI performance"

If there are no stored historical AI outputs for the replay period:
**AI predictive performance: NOT YET MEASURABLE**

## Performance Attribution Breakdown

### PnL Attribution

| Component | PnL | Attribution |
|-----------|-----|-------------|
| Gross profit | +₹69,892.73 | Deterministic framework |
| Gross loss | -₹200,284.47 | Deterministic framework |
| Net PnL | -₹130,391.72 | Deterministic framework |
| From BULLISH trades | -₹137,296.06 | Framework + bearish market |
| From BEARISH trades | +₹6,904.33 | Framework + bearish market |

### Win Rate Attribution

| Direction | Win Rate | Attribution |
|-----------|----------|-------------|
| BULLISH | 0.7% | Framework in bearish market |
| BEARISH | 50.2% | Framework in bearish market |
| Overall | 38.43% | Framework overall |

### Trade Frequency Attribution

| Metric | Value | Attribution |
|--------|-------|-------------|
| Trades/day | 45.54 | Evidence engine permissiveness |
| Directional rate | 61.4% | Evidence engine classification |
| Qualification pass rate | 100% | Qualification pipeline |

## Replay-Specific Notes

1. AI outlook was NOT generated during replay (would require Groq API calls for 1,184 candles)
2. Instead, synthetic AI outlook was created per candle with BULLISH/BEARISH bias
3. This means the replay does NOT measure AI prediction accuracy
4. The replay measures the DETERMINISTIC FRAMEWORK's behavior given directional inputs

## Conclusion

All performance metrics from this replay are attributable to the **deterministic framework**.
No AI predictive performance can be claimed from this replay.

For AI performance measurement, historical AI outputs would need to be stored
and then replayed alongside the framework.
