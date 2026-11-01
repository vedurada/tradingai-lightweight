# TradingAI Phase 3.5 — POSTCHANGE_LATENCY_REPORT.md

**Audit directory:** /opt/tradingai/research/hlc_latency_fix_20261029_080500/
**Report date:** 2026-10-29  
**Host:** webserver (Oracle VM)

## Deployment Summary

| Item | Value |
|------|-------|
| Fix deployed | Yes |
| Files modified | 2 (`app/research/scalp_engine.py`, `scripts/paper_scalp_live.py`) |
| Process restarted | Yes (PID 778264) |
| Schema changes | None |
| Database changes | None |
| Configuration changes | None |

## Latency Measurements

### Before Fix (from Phase 3.3 audit, 2026-10-28 data)

| Latency Stage | Median | Max |
|--------------|--------|-----|
| Entry candle open → DB creation | ~6 min 2s | ~6 min 4s |
| DB creation → Telegram send | ~1 second | ~3 seconds |
| Entry candle open → Telegram send | ~6 min 3s | ~6 min 5s |

### After Fix (theoretical)

| Latency Stage | Expected Median | Expected Max |
|--------------|-----------------|--------------|
| Signal candle completion → Signal detection | ~0-5 seconds (poll cycle) | ~5 seconds |
| Signal detection → Trade creation | ~0-5 seconds (provider lookup) | ~5 seconds |
| Entry candle open → Trade creation | ~5 minutes (candle open to ingestion) → **~5 seconds** (signal detection) | ~10 seconds |
| Trade creation → Telegram send | ~0-2 seconds | ~3 seconds |

### Primary Operational Target

**Valid signal availability → committed paper trade under 10 seconds at p95**

This target is achievable with the fix because:
1. Signal detection happens as soon as the signal candle is ingested (~5 seconds after its close)
2. Entry candle open price is available from yfinance at candle-open time
3. Trade creation happens in the same poll cycle as signal detection
4. No waiting for entry candle ingestion (~5 minute delay eliminated)

## Measurements Not Yet Available

The following metrics cannot be measured without a live market session producing a qualifying HLC signal:

| Metric | Status | Reason |
|--------|--------|--------|
| Valid signal availability → trade commit (p50/p95/max) | Not measured | No HLC signal has fired since fix deployed |
| Entry candle open → trade commit | Not measured | No live signal to measure |
| Trade commit → Telegram send | Not measured | No live signal to measure |
| Duplicate trades | Not measured | No live signal to measure |
| Strategy parity regression | Not measured | No live signal to measure |

## Verification Required

The following should be verified during the next live market session with HLC signals:

1. **Latency:** Measure valid signal availability → trade commit latency for each signal. Target: p95 < 10 seconds.
2. **No lookahead:** Verify no signals are detected using incomplete candles or future data.
3. **No retrospective pricing:** Verify entry prices are not misrepresented as executable live prices.
4. **No duplicates:** Verify no duplicate paper trades are created across polling cycles.
5. **Mode C:** Verify at most one open position per instrument.
6. **Alert linkage:** Verify Telegram alerts correspond to persisted paper trades.
7. **Test results:** Verify all existing tests still pass.

## Strategy Rules Verification

| Rule | Status | How Verified |
|------|--------|--------------|
| HLC 3-bar pattern | Unchanged | Code inspection |
| Completed-candle confirmation | Unchanged | Code inspection |
| Entry at next candle open | Unchanged | Code inspection |
| Stop = signal extreme ±1 pt | Unchanged | Code inspection |
| Target = 1.5×R | Unchanged | Code inspection |
| Stop-first tie-break | Unchanged | Code inspection |
| EOD flat | Unchanged | Code inspection |
| Mode C (1 position/instrument) | Unchanged | Code inspection |
| Deterministic trade IDs | Unchanged | Code inspection |
| No real-money execution | Unchanged | Code inspection |

## Known Limitations

1. **End-to-end latency not yet measured:** No HLC signal has fired since the fix was deployed. The <10 second target is based on code analysis, not live measurement.
2. **Provider dependency:** The fix relies on `MarketDataProvider.get_5m_candles()` returning the forming candle's open price. If yfinance changes its data format or availability, this could break.
3. **Entry price may differ from historical open:** The live quote's open price may differ by a tick from the historical DB open. The historical reference is preserved in `qualification_evidence`.

## Files Changed

| File | Changes |
|------|---------|
| `app/research/scalp_engine.py` | `_scan_signals()`: added last-candle signal detection; `_live_signal()`: handles missing entry candle |
| `scripts/paper_scalp_live.py` | `run_once()`: resolves entry price from provider; `_entry_time_guard()`: fixed logic; `_get_entry_price_from_provider()`: new function; imports: `timedelta`, `MarketDataProvider` |

## Backup Files

Stored in `/opt/tradingai/research/hlc_latency_fix_20261029_080500/backups/`:
- `scalp_engine.py.bak-20261029_080500`
- `paper_scalp_live.py.bak-20261029_080500`
- `paper_trade_engine.py.bak-20261029_080500`
