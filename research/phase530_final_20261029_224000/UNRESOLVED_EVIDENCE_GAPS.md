# Phase 5.30 — Unresolved Evidence Gaps

## 2 Unmatched Scalp Signals

1. SS-DFD2B7DFE704 (NIFTY BEAR, Oct 27 11:10): Signal exists in DB, TRADED (PT-6C19D5601E). No exact replay match. Entry at 11:15 doesn't match replay entries (11:05, 11:10). Likely intermediate signal from candle-by-candle processing.

2. SS-55CC79460843 (BANKNIFTY BULL, Oct 29 09:30): Signal exists in DB, EXPIRED. No replay match. Signal fires one candle after replay signal (09:25). Expired because entry window closed. Likely intermediate signal.

## 4 Probable HLC Matches

All 4 are PROBABLE_MATCH (same day/instrument/direction, no exact entry time):
- PT-6C19D5601E: entry 11:15 (replay has 11:05, 11:10)
- PT-1AFB06CC01: entry 11:00 (replay has 09:45, 12:00, 12:45, 12:55, 14:50)
- PT-58E0E20BA3: entry 12:05 (replay has 12:00, 12:45)
- PT-7F4FF31032: entry 12:50 (replay has 12:45, 12:55)

## Missing Evidence

- Exact signal generation timestamps (not just candle timestamps)
- Live engine evaluation logs (to confirm intermediate signals)
- The first backtest script's actual output (timed out, partial CSV)

## Recommended Next Action

Modify replay to use candle-by-candle processing (matching live behavior) and re-run reconciliation. This would likely resolve all 6 cases.
