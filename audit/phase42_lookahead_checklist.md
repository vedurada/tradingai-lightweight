# Phase 42 — Look-Ahead Prevention Checklist

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Ensure Phase 42 replay uses only information available at decision timestamp

---

## Formal Look-Ahead Prevention Checklist

For every Phase 42 replay run, ALL of the following must be verified:

### 1. Indicator Computation

- [ ] EMA computed only from prices ≤ current timestamp
- [ ] RSI computed only from closes ≤ current timestamp
- [ ] MACD computed only from prices ≤ current timestamp
- [ ] ADX computed only from prices ≤ current timestamp
- [ ] ATR computed only from prices ≤ current timestamp
- [ ] VWAP computed only from trades ≤ current timestamp (NOT session-to-date average that includes future)
- [ ] Volume computed only from candles ≤ current timestamp
- [ ] CPR (Pivot) computed only from previous day's data

### 2. Market State

- [ ] Regime classification uses only data ≤ current timestamp
- [ ] Support/Resistance levels use only data ≤ current timestamp
- [ ] VIX reading is from current timestamp (not future)
- [ ] Market status (open/closed) is accurate at timestamp

### 3. Evidence Groups

- [ ] Trend direction computed only from data ≤ current timestamp
- [ ] Momentum direction computed only from data ≤ current timestamp
- [ ] Structure direction computed only from data ≤ current timestamp
- [ ] Volatility state computed only from data ≤ current timestamp
- [ ] Options state (if available) computed only from data ≤ current timestamp
- [ ] Confirmation computed only from data ≤ current timestamp

### 4. AI Outlook

- [ ] AI outlook timestamp ≤ trade entry timestamp
- [ ] AI outlook based on data ≤ outlook timestamp
- [ ] AI confidence reflects information available at that time
- [ ] No future market outcome known to AI at generation time

### 5. Trade Qualification

- [ ] All qualification checks use data ≤ entry timestamp
- [ ] Trade status (GO/WAIT/NO_SETUP) determined at entry timestamp
- [ ] Strategy selection uses data ≤ entry timestamp
- [ ] No look-ahead in strategy parameters

### 6. Trade Exit

- [ ] Exit decision uses only data ≤ exit timestamp
- [ ] Stop/target levels set at entry, evaluated at exit
- [ ] Exit reason is based on data ≤ exit timestamp
- [ ] No future information used to determine exit

### 7. Data Pipeline

- [ ] No future normalization (e.g., z-score using future data)
- [ ] No future scaling (e.g., min/max using future data)
- [ ] No feature construction using future data
- [ ] No label leakage (trade outcome not used as feature)
- [ ] Replay-generated labels are not used in training features

### 8. Replay-Specific Checks

- [ ] Each candle's analysis is independent (no batch processing that leaks forward)
- [ ] Strategy determination happens AFTER all data for that timestamp is processed
- [ ] Indicator warmup period is handled correctly (no indicators before warmup)
- [ ] Trading day boundaries are respected (no overnight data in day session)
- [ ] Contract changes/expiry transitions handled correctly

### 9. Validation Tests

- [ ] Unit test: indicator values match manual calculation for known timestamp
- [ ] Unit test: AI outlook timestamp < trade entry timestamp for all trades
- [ ] Unit test: no NaN or undefined values from future data
- [ ] Integration test: full replay produces deterministic results on same input
- [ ] Integration test: changing a single candle only affects results at/after that candle

## Verification Method

For each Phase 42 replay:
1. Pick a random trade
2. List every data point used in entry decision
3. Verify each data point timestamp ≤ trade timestamp
4. Repeat for exit decision
5. Log any violations found

## Common Sources of Look-Ahead Bias

| Source | How to Prevent |
|--------|---------------|
| VWAP using session total | Use only trades ≤ timestamp |
| RSI using full series | Use only closes ≤ timestamp |
| EMA of full series | Compute recursively up to timestamp |
| Z-score normalization | Use only statistics ≤ timestamp |
| Future market state | Never include future regime |
| Future outcome as feature | Exclude P&L, exit reason from features |
| AI using future data | Verify AI prompt scope |
| Data leakage in labels | Separate feature/label computation |
