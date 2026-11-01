# Phase 5B Alignment Methodology
Source: market_candles_5m (DB), option_ce_13788162.csv, option_pe_13790978.csv
Canonical HLC: unmodified scalp_engine.py
Normalization: Asia/Kolkata
Entry: next candle open after confirmed signal (per engine)
Exit: underlying SL/target triggers; option candle at/after trigger
Ambiguous same-candle SL+target: conservative/ambiguous
No look-ahead; no missing candle fabrication; no invented premiums
