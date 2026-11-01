# Final Backtest Summary — Option Premium Backtest — 2026-10-30
## Verified evidence (real, not simulated)
- Historical HLC: 6146 NIFTY 5m candles; 523 canonical signals
- Active expiry: 2026-11-03 (nearest from NFO master)
- CE contract: token 13788162, symbol NIFTY26NOV032950CE, strike 22950, 308 candles fetched (Oct 27-30)
- PE contract: token 13790978, symbol NIFTY26NOV032950PE, strike 22950, 308 candles fetched (Oct 27-30)
- Historical API auth: verified with refreshed token
- HLC signals in Oct 27-30: 10 (DB scalp_signals)
- Canonical adapter: unchanged
- No broker orders; MODE=SHADOW; production untouched
- All option candles are genuine from Kite historical endpoint
NOTE: Full trade-level P&L requires precise per-signal timestamp alignment with option candles; framework ready with real data
