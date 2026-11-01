# TradingAI Phase 3.5 — CHANGELOG

**Audit directory:** /opt/tradingai/research/hlc_latency_fix_20261029_080500/
**Fix date:** 2026-10-29  
**Host:** webserver (Oracle VM)

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `app/research/scalp_engine.py` | `_scan_signals()` | Added last-candle signal detection: when the signal candle is the last candle in DB data (entry candle not yet ingested), the signal is still detected using only the 3 most recent completed candles. Previously `_scan_signals()` required `len(candles) >= 7` (range(5, len(feats))), meaning the entry candle had to be in DB before any signal could be detected. |
| `app/research/scalp_engine.py` | `_live_signal()` | Handles missing entry candle (not yet ingested): returns signal with `entry=None`, `entry_time` computed as signal_time + 5min, `stop` from signal candle, `target=None`, `risk=None`. The caller resolves the entry price from the live provider at trade creation time. |
| `scripts/paper_scalp_live.py` | `run_once()` | For signals with `entry=None`, obtains entry candle open from `MarketDataProvider.get_5m_candles()` (forming candle's open is available at candle-open time, before the candle is ingested as completed data). Computes `risk` and `target` from the live entry price. Updates `st["entry"]` and `st["target"]` before passing to `create_paper_trade()`. |
| `scripts/paper_scalp_live.py` | `_entry_time_guard()` | Fixed guard logic: previously required `entry_time > now` (impossible for next-candle-open strategy where signal is detected when previous candle completes at same time next candle opens). Now allows entry when `now <= entry_time + 5min` (entry candle's 5-minute interval hasn't closed). Guard still prevents entry on closed candles. |
| `scripts/paper_scalp_live.py` | `_get_entry_price_from_provider()` | New function: fetches all 5m candles from `MarketDataProvider.get_5m_candles()` (includes forming candle), finds the candle matching `entry_time`, returns its `open` price. |

## Imports Added

- `scripts/paper_scalp_live.py`: `timedelta` from datetime, `MarketDataProvider` from `app.market.provider`

## Strategy Rules Preserved

- HLC 3-bar pattern: 3 consecutive completed candles with aligned H/L/C
- Completed-candle confirmation for signal detection (signal candle must be completed)
- Entry at next candle open (price from live quote at open time)
- Stop = signal candle extreme ±1 pt
- Target = 1.5×R
- Stop-first tie-break on same candle
- EOD flat at session close
- Mode C: one open position per instrument
- Deterministic trade IDs (SHA-1 of link_key), duplicate prevention
- `entry_time` and `created_at` semantics unchanged
- No broker, no real-money execution

## Files Not Modified

- `app/paper_trade/engine.py` — no changes needed
- `app/market/provider.py` — no changes needed (already provides forming candle data)
- `app/market/collector.py` — no changes needed
- `scripts/tg_alerts.py` — no changes needed (alerts still fire after trade creation)
- All configuration files

## Backup Location

`/opt/tradingai/research/hlc_latency_fix_20261029_080500/backups/`

- `scalp_engine.py.bak-20261029_080500` (md5: c0ffd9401b0e8ffb8e16300306000313)
- `paper_scalp_live.py.bak-20261029_080500` (md5: a874be1e84e40c024c3aecc5703772ac)
- `paper_trade_engine.py.bak-20261029_080500` (md5: b8da0ea1a8b2fee9cc4b736c39598a25)

## Rollback

Restore the three backup files over the modified originals and restart the `paper_scalp_live.py` process. See ROLLBACK.md for details.
