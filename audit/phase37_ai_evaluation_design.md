# AI Evaluation Framework Design — Phase 37
Generated: 2026-09-17

## Classification: Framework Design (NOT live evaluation)

This document describes the framework for evaluating AI predictions.
NO actual AI accuracy claims are made in this document.

## Current State: Rules-Based Proxy Only

The 30-day NIFTY backtest (audit/phase36_nifty_30d_5m_results.md) is a
**rules-based reconstruction** using EMA crossover signals, NOT a genuine
AI prediction reconstruction. Therefore, no AI accuracy metrics can be
derived from it.

The live market outlook endpoint (`/api/market-outlook`) currently serves
rule-based outlooks (ai_source: RULE_REPLAY). Genuine LLM-generated outlooks
are overlaid via `merge_llm_into_payload()` for narrative only.

## Future AI Evaluation Framework (When Live AI Active)

### Prediction Log Schema
For each AI prediction, store:
- prediction_id: UUID
- prediction_timestamp: ISO timestamp
- prediction_direction: BULLISH / BEARISH / RANGE / MIXED
- prediction_confidence: 0-100
- prediction_horizon: 5m / 15m / 30m / 60m
- instrument: NIFTY / BANKNIFTY / FINNIFTY / SENSEX
- regime_at_prediction: current market regime
- ai_source: LLM / RULE_REPLAY / HYBRID
- model_version: LLM model version identifier

### Outcome Measurement
At each prediction, calculate future returns at multiple horizons:

| Horizon | Calculation |
|---------|------------|
| 5 minutes | (price[t+5m] - price[t]) / price[t] * 100 |
| 15 minutes | (price[t+15m] - price[t]) / price[t] * 100 |
| 30 minutes | (price[t+30m] - price[t]) / price[t] * 100 |
| 60 minutes | (price[t+60m] - price[t]) / price[t] * 100 |

### Evaluation Metrics Per Prediction
- future_return: actual % return at each horizon
- correct: did price move in predicted direction? (within noise threshold)
- MFE (Maximum Favorable Excursion): best possible outcome from entry
- MAE (Maximum Adverse Excursion): worst possible outcome from entry
- outcome_at_5m: {future_return, correct, MFE, MAE}
- outcome_at_15m: {future_return, correct, MFE, MAE}
- outcome_at_30m: {future_return, correct, MFE, MAE}
- outcome_at_60m: {future_return, correct, MFE, MAE}

### Storage Schema
Table: ai_prediction_evaluations
- prediction_id: UUID (FK to predictions)
- horizon: 5m / 15m / 30m / 60m
- future_return_pct: REAL
- direction_correct: BOOLEAN
- mfe_pct: REAL
- mae_pct: REAL
- evaluated_at: TIMESTAMP (when outcome was measured)

### Aggregate Metrics (Require Minimum Sample Size)
After N predictions (minimum 30 recommended):
- accuracy_by_horizon: % correct at 5m, 15m, 30m, 60m
- avg_return_by_horizon: average return at each horizon
- sharpe_like: mean_return / std_return at each horizon
- mfe_mae_ratio: average favorable / adverse excursion
- accuracy_by_regime: accuracy broken down by market regime
- accuracy_by_confidence_bucket: accuracy for 0-25, 25-50, 50-75, 75-100 confidence

### Minimum Sample Size Protection
All aggregate metrics require minimum 30 predictions per bucket.
If below minimum, return INSUFFICIENT_DATA (same pattern as Phase 9C).

## What CANNOT Currently Be Measured
1. AI prediction accuracy (live AI not generating predictions yet)
2. MFE/MAE for AI predictions (requires live trade execution)
3. Confidence calibration (need many predictions to verify)
4. Regime-conditional accuracy (need diverse market conditions)
5. Horizon-specific performance (need predictions at multiple horizons)

## What CAN Currently Be Measured
1. Rules-based outlook accuracy (via 30-day proxy, documented separately)
2. Trade setup quality (via Phase 7 backtesting engine)
3. Historical evidence matching (via Phase 8 historical_evidence engine)
4. Walk-forward validation (via Phase 8 walkforward engine)

## Implementation Timeline
This framework requires:
1. Live AI generating genuine predictions (not RULE_REPLAY)
2. Storing predictions with unique IDs and timestamps
3. Post-hoc outcome measurement pipeline
4. Aggregate metric computation engine

None of these are implemented yet. This is a design document.
