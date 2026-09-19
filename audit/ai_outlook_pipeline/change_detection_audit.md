# Change Detection & Material Change Audit

Date: 2026-09-18

## outlook_change_detector.py — evaluate()

File: backend/outlook_change_detector.py

### Function: evaluate(symbol)

Called by:
- `/api/outlook/5m/latest/<symbol>` (line 3587 of api_server.py)
- `/api/outlook/5m/changes/<symbol>` (line 3667 of api_server.py)
- `outlook_scheduler.py` (if triggered)

### Live API Response (verified)

```json
GET /api/outlook/5m/latest/NIFTY
{
  "success": true,
  "data": {
    "symbol": "NIFTY",
    "current_state": {
      "regime": "BEARISH",
      "trend": "BEARISH",
      "confidence": 75.0,
      "price_vs_vwap": "UNKNOWN",
      "vix": 11.39,
      "rsi": 20.92,
      "adx": 45.32,
      "captured_at": "2026-09-18T16:54:00.415Z"
    },
    "material_change": false,
    "change_reason": "no_significant_change",
    "changes": [],
    "regenerate_ai": false,
    "regenerate_reason": "no_change",
    "ai_outlook_age_minutes": 14,
    "max_age_minutes": 120
  }
}
```

### evaluate() Dependencies

`evaluate()` uses `get_current_state()` which reads:
- `market_regime` table (latest row for symbol)
- `indicators` table (latest row for symbol)
- `vix_data` table (latest row)
- `price_1m` table (latest row for symbol)

**These tables ARE populated** (data_fetcher_db.py runs every minute), so `evaluate()` works correctly when called.

### Function: needs_ai_outlook(symbol)

Checks if AI outlook regeneration is needed based on:
- AI outlook age (compared to MAX_OUTLOOK_AGE_MINUTES)
- Material changes detected
- Returns: `{needs_ai: bool, reason: str, material_changes: list, ai_outlook_age_minutes, max_age_minutes}`

### Material Change Detection

`is_material_change(current, previous)` from market_change.py:
- Compares current vs previous snapshot
- Checks: regime_change, confidence_swing (15%), vix_move_points (5), price_move_pct (1%), bias_reversal
- Returns: `{material: bool, reason: str, changes: list}`

### Finding: evaluate() Works, But Data Doesn't Exist to Evaluate Against

- `evaluate()` reads from market_regime, indicators, vix_data, price_1m — ALL populated
- `evaluate()` correctly reports: material_change=false, no significant changes
- **The problem is NOT in change detection** — the problem is that there's no 5-minute AI outlook to evaluate changes FROM
- The scheduler that would generate outlooks and detect changes is never triggered

## Market Change Detection (market_change.py)

File: backend/market_change.py

### Key Functions

- `get_current_state(conn, symbol)` — reads regime + indicators + vix + price_1m
- `get_previous_snapshot(conn, symbol)` — reads previous snapshot for comparison
- `is_material_change(current, previous)` — threshold-based comparison
- `should_regenerate_ai(symbol)` — decides if AI regeneration needed

### Material Thresholds

```python
MATERIAL_THRESHOLDS = {
    "regime_change": True,        # Any regime change triggers
    "confidence_swing": 15.0,     # 15% confidence swing
    "vix_move_points": 5.0,       # 5 point VIX move
    "price_move_pct": 1.0,        # 1% price move
    "bias_reversal": True,        # Any bias reversal
}
```

### Conclusion

Change detection infrastructure is functional and correct. The issue is upstream — no 5-minute outlooks are generated to feed into the change detection pipeline. The twice-daily `ai_outlooks` table IS used by `evaluate()` for the `ai_outlook_age_minutes` calculation.
