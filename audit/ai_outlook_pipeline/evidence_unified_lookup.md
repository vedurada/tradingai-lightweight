# Evidence Unified Lookup & Live AI Outlook API

Date: 2026-09-18

## Unified Evidence Lookup

### Current Evidence Sources
| Source | Table | Status | Notes |
|--------|-------|--------|-------|
| 5-minute evidence | market_evidence_5m | EMPTY | Bug in _record_evidence |
| Market regime | market_regime | POPULATED | Updated every minute by data_fetcher_db.py |
| Indicators | indicators | POPULATED | Updated every minute |
| VIX | vix_data | POPULATED | Updated periodically |
| Options data | options tables | PARTIAL | FINNIFTY only historical |

### Evidence Hierarchy
```
Market Evidence (preferred for AI):
  ├── market_evidence_5m → EMPTY (broken)
  └── Fallback: market_regime + indicators + vix + price_1m → POPULATED

Trade Evidence (for backtesting/replay):
  ├── paper_trades → POPULATED
  ├── research_outcome_tracking → POPULATED (61,672 rows)
  └── research_setup_identity → EMPTY

Historical Evidence:
  └── Used in Phase 8 (walk-forward, historical evidence engine)
```

### Evidence Unification Status
**No unified evidence lookup exists.** Each source is queried independently:
- outlook_change_detector.evaluate() reads market_regime, indicators, vix, price_1m
- research_collector.collect() reads price_5m, paper_trades
- No single query combines all evidence sources

### Missing Unified Evidence Components
| Component | Status |
|-----------|--------|
| Unified evidence view | DOES NOT EXIST |
| Evidence cross-referencing | NO |
| Evidence quality scoring | Only data_quality field in individual tables |
| Evidence versioning | NO |
| Evidence conflict resolution | NO |

## Live AI Outlook API Specification

### Current Live API (Verified Working)

#### /api/ai-outlook/<symbol>
Returns current AI outlook for a symbol.
```json
{
  "success": true,
  "data": {
    "instrument": "NIFTY",
    "current": {
      "outlook_id": "...",
      "instrument": "NIFTY",
      "bias": "BEARISH",
      "confidence": 75,
      "market_regime": "BEARISH",
      "trade_state": "ACTIVE",
      "data_state": "LIVE",
      "age_minutes": 14,
      "age_status": "FRESH",
      "summary": "..."
    },
    "previous": { ... },
    "change": {
      "bias_changed": false,
      "confidence_changed": false,
      "regime_changed": false,
      "trade_state_changed": false
    },
    "timeline": [ ... ],
    "data_state": "LIVE",
    "market_status": { "session": "CLOSED" },
    "current_candle": null
  }
}
```

#### /api/market-outlook?symbol=<symbol>
Returns daily market outlook.
```json
{
  "date": "...",
  "symbol": "NIFTY",
  "payload": { ... },
  "outlook": {
    "bias": "...",
    "confidence": ...,
    "primary_view": "...",
    "key_drivers": [...],
    "regime": "...",
    "decision": "...",
    "date": "...",
    "symbol": "..."
  },
  "created_at": "..."
}
```

#### /api/<symbol> (e.g., /api/NIFTY)
Returns index data including ai_outlook (rule-based from data_fetcher_db.py).
```json
{
  "success": true,
  "data": {
    "symbol": "NIFTY",
    "ai_outlook": { ... },
    ...
  }
}
```

#### /api/outlook/5m/latest/<symbol>
Returns current 5-minute outlook status (computed, not stored).
```json
{
  "success": true,
  "data": {
    "symbol": "NIFTY",
    "current_state": { "regime": "BEARISH", "confidence": 75, ... },
    "material_change": false,
    "change_reason": "no_significant_change",
    "changes": [],
    "regenerate_ai": false,
    "ai_outlook_available": true,
    "ai_outlook_age_minutes": 14,
    "max_age_minutes": 120
  }
}
```

### API Contract Issues

| Issue | Impact | Resolution |
|-------|--------|------------|
| /api/market-outlook raw vs wrapped | today/index.html expects {outlook:...} | Need field mapping fix |
| /api/key-levels missing | today/index.html calls it | Need VM investigation |
| /api/intraday-conditions missing | today/index.html calls it | Need VM investigation |
| /api/risk/NIFTY missing | today/index.html calls it | Need VM investigation |
| ai_outlooks_5m empty | /api/ai-outlook uses fallback | Mitigated by cbb2641 |

## Recommendations

1. Create unified evidence lookup view combining market_regime, indicators, vix, options
2. Fix /api/market-outlook to return {outlook: ...} wrapper
3. Resolve missing endpoints per Phase 29 audit (VM investigation required)
4. Add evidence quality scoring to unified view
5. Add evidence version tracking
