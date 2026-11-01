# Phase 5.19 — Rollback Boundaries

## Production Files Affected by Future Feature Flag

| File | Change | Risk |
|------|--------|------|
| app/live/engine.py | Read HLC_ONLY_MODE, call _hlc or _cpr | Medium |
| app/api/app.py | Display HLC as primary when flag=true | Low |
| scripts/paper_scalp_live.py | Add daily trade limit check | Low |

## CPR Decision Path (Current)

```
app/live/engine.py: decision() → _cpr_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

## HLC Signal/Paper-Trade Path (Proposed)

```
app/live/engine.py: decision() → _hlc_book_signal() → if signal → paper_scalp_live.py → create_paper_trade()
```

## Shared Modules (Must Not Be Replaced)

- app/paper_trade/engine.py (shared persistence)
- app/core/db.py (shared DB access)
- app/market/provider.py (shared data provider)
- app/market/collector.py (shared collector)

## Database Tables

| Table | Purpose | Risk |
|-------|---------|------|
| paper_trades | Active paper trades | High (must preserve) |
| scalp_signals | Signal tracking | Medium |
| paper_scalp | EOD backtest | Low |
| market_candles_5m | Market data | High (must preserve) |

## Configuration Dependencies

- config/settings.json (proposed: HLC_ONLY_MODE, MAX_TRADES_PER_DAY)
- Environment variables (proposed: HLC_ONLY_MODE)
- systemd units (proposed: tradingai-paper-scalp-live.service)

## External Side Effects

- Telegram API (tg_alerts.py) — alerts for existing trades only
- yfinance API (collector, provider) — read-only
- No broker API calls
