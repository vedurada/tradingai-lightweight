# TradingAI API Documentation

Base URL: `http://127.0.0.1:8000/api`
All responses use envelope: `{"state": "...", "timestamp": "...", "data": {}}`

## Health

### GET /api/health
Check application health.
```json
{"state": "LIVE", "timestamp": "...", "data": {"tables": 26, "database": "/opt/tradingai_new/database/tradingai.db"}}
```

## NIFTY

### GET /api/NIFTY/summary
Current NIFTY market state.
```json
{"state": "LIVE", "data": {"price": 25000.50, "change": 100.25, "state": "LIVE", "source": "yfinance", "timestamp": "..."}}
```

### GET /api/NIFTY/decision
Today's trade decision for NIFTY.
```json
{"state": "LIVE", "data": {"decision": {"decision": "NO_TRADE", "reasons": ["scenario_not_confirmed"], "trade": null}, "market_state": {...}, "ai": {...}}}
```

### GET /api/NIFTY/paper-trade
Active NIFTY paper trades.
```json
{"state": "LIVE", "data": {"trades": [...], "active": 0}}
```

### GET /api/NIFTY/scenario
Current NIFTY scenario status.

### GET /api/NIFTY/levels
Key NIFTY levels (support, resistance, pivot).

### GET /api/NIFTY/chart
5-minute NIFTY candle data.

### GET /api/NIFTY/options
NIFTY option chain data (when available).

### GET /api/NIFTY/research
Research data for NIFTY.

## BANKNIFTY
Same endpoints as NIFTY with `BANKNIFTY` replacing `NIFTY`.

## Backtest

### POST /api/backtest/run
Run historical backtest.
```json
// Request
{"instrument": "NIFTY", "date_start": "2026-09-01", "date_end": "2026-09-19"}
// Response
{"state": "COMPLETED", "data": {"run_id": "BT-XXXXXXXX", "decisions": [...], "trades": [...], "outcome": {...}, "lookahead_check": "PASS"}}
```

### GET /api/backtest/{run_id}
Get backtest results.
```json
{"state": "COMPLETED", "data": {"run": {...}, "decisions": [...], "trades": [...], "outcome": {...}}}
```

### GET /api/backtest/{run_id}/validation
No-look-ahead validation.
```json
{"state": "COMPLETED", "data": {"run_id": "...", "lookahead_violations": 0, "result": "PASS"}}
```

## Error Response

```json
{"state": "API_ERROR", "error": {"code": "MARKET_DATA_UNAVAILABLE", "message": "..."}}
```

## Rate Limits
- `/api/health`: unlimited
- Summary/paper-trade endpoints: 30/minute
- Decision: 10/minute
- Backtest: 5/minute
- Backtest detail: 30/minute
