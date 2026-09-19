# Research Collector Repair

Date: 2026-09-19
Classification: REPLAY/VALIDATION

## Original Defect

`_record_evidence()` in `backend/research_collector.py` checked for existing evidence but NEVER INSERTED records:

```python
def _record_evidence(self, conn, result, symbol, ts) -> bool:
    row = conn.execute(
        "SELECT * FROM market_evidence_5m WHERE symbol=? AND timestamp=?",
        (symbol, ts),
    ).fetchone()
    if not row:
        return False  # ← BUG: Returns False but NEVER INSERTS
    return True  # evidence already exists
```

Also: `_record_snapshot()` used wrong column name `data_quality` for VM schema (table has `data_state`).

## Repair

### _record_snapshot
- Changed `data_quality` → `data_state` (matching VM schema)
- Removed `engine_version` from INSERT (not in VM schema)
- Used named parameter INSERT for clarity

### _record_evidence
Rewrote to:
1. Check for existing evidence (idempotent) using `SELECT 1`
2. Query data sources for the given timestamp:
   - market_regime (latest at or before timestamp)
   - indicators (latest at or before timestamp)
   - vix_data (latest at or before timestamp)
   - price_5m (exact match for OHLCV)
3. Build JSON evidence record:
   - trend_json: regime, confidence, trend, momentum, volatility, breadth, vix_regime
   - momentum_json: rsi, macd, adx, volume
   - structure_json: OHLCV from price_5m
   - volatility_json: atr, adx, vix
   - options_json: pcr from option_chain
   - overall_signal: BULLISH/BEARISH/RANGE/INSUFFICIENT_DATA
   - overall_strength: confidence as string
4. INSERT OR IGNORE into market_evidence_5m (idempotent)
5. Return True/False based on result

## Validation Results (REPLAY)

Tested against NIFTY 5m candle: 2026-09-18T04:25:00+00:00

### Snapshot
- Created: 1 record
- Data: close=23346.4, data_state=LIVE
- Idempotent: Second run created no duplicates

### Evidence
- Created: 1 record
- Signal: BEARISH
- Strength: 75
- Data quality: LIVE
- Trend: regime=BEARISH, confidence=75, trend=BEARISH
- Momentum: rsi=19.65, macd=-262.02, adx=48.2
- Structure: OHLCV from price_5m

### Idempotency
- First run: 1 snapshot, 1 evidence
- Second run: 0 new snapshots, 0 new evidence
- Total: 1 snapshot, 1 evidence (no duplicates)

## Data Sources Used

| Source | Table | Used For |
|--------|-------|----------|
| price_5m | OHLCV | Snapshot creation, evidence structure |
| market_regime | regime, confidence | Evidence trend |
| indicators | rsi, macd, adx, atr | Evidence momentum, volatility |
| vix_data | close | Evidence volatility |
| option_chain | pcr | Evidence options |
