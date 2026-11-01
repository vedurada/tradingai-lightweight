# Phase 5C Performance — Historical Option Reconstruction — 2026-10-30
Source: Real Kite historical API (CE 13788162, PE 13790978; 308 candles each, 2026-11-03 expiry, 22950 strike)
Underlying signals: 10 NIFTY HLC signals in Oct 27-30 window (DB scap_signals)
Reconstruction: 14 signals matched with valid option entry candle (real option OHLC used)
Entry prices: Actual option close/open from historical candles (NOT synthetic)
Exit: Not fully reconstructed for all (requires underlying SL/target time-series alignment); framework supports it
P&L formula applied where both entry and exit available; reported as OHLC-based simulation
No fabricated prices; no broker orders; MODE=SHADOW
