# Phase 5.30 — Final Signal and HLC Reconciliation

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.29: `/opt/tradingai/research/phase529_validation_20261029_223500/`
- Report directory: `/opt/tradingai/research/phase530_final_20261029_224000/`

## Phase A — Evidence

All Phase 5.29 artifacts verified present. Source hashes match.

## Phase B — Two Unmatched Signals

### SS-DFD2B7DFE704 (NIFTY BEAR, 2026-10-27T11:10:00)

- Status: TRADED → PT-6C19D5601E (NIFTY BEAR, entry 11:15)
- Replay: Has trades at 11:00→11:05 and 11:05→11:10 (BEAR, same day)
- No exact replay match for entry at 11:15
- Classification: **UNCLASSIFIABLE** — signal at 11:10, entry at 11:15, but replay has entries at 11:05 and 11:10. The DB entry at 11:15 doesn't match any replay entry time. Likely an intermediate signal from candle-by-candle processing.

### SS-55CC79460843 (BANKNIFTY BULL, 2026-10-29T09:30:00)

- Status: EXPIRED (no trade created)
- Replay: Has trade at 09:25→09:30 (BULL, entry 54351.5)
- The DB signal at 09:30 is one candle later than the replay signal at 09:25
- Classification: **UNCLASSIFIABLE** — the DB signal fires one candle after the replay signal. The DB signal was expired because entry window (09:30→09:35) closed before processing. The replay captures the earlier signal (09:25→09:30).

## Phase C — Four Probable HLC Matches

### PT-6C19D5601E (NIFTY BEAR, entry 11:15)
- Replay: No exact match (entries at 11:05, 11:10, 13:00, 13:05, 13:10)
- Classification: **PROBABLE_MATCH** — same day/instrument/direction, no exact entry time match

### PT-1AFB06CC01 (NIFTY BULL, entry 11:00)
- Replay: No exact match (entries at 09:45, 12:00, 12:45, 12:55, 14:50)
- Classification: **PROBABLE_MATCH** — same day/instrument/direction, no exact entry time match

### PT-58E0E20BA3 (NIFTY BULL, entry 12:05)
- Replay: No exact match (entries at 12:00, 12:45)
- Classification: **PROBABLE_MATCH** — same day/instrument/direction, no exact entry time match

### PT-7F4FF31032 (NIFTY BULL, entry 12:50)
- Replay: No exact match (entries at 12:45, 12:55)
- Classification: **PROBABLE_MATCH** — same day/instrument/direction, no exact entry time match

## Phase D — Consistency Checks

- 729-trade authoritative replay: verified unchanged
- Two-run trade-level diff: 0 (verified in Phase 5.29)
- 245-row classification: consistent with Phase 5.29
- No modifications to source artifacts

## Final Classification

**PARTIAL — 2 UNMATCHED SIGNALS AND 4 PROBABLE MATCHES REMAIN UNRESOLVED**

All 6 cases lack sufficient evidence for exact classification. The most likely explanation is that the live paper-trading engine (candle-by-candle, with last-candle detection) generates signals at intermediate positions that the day-by-day replay does not capture.

## Recommended Next Action

The discrepancy between live paper trading and historical replay is caused by different signal detection cadences (candle-by-candle vs day-by-day). A future phase should:
1. Modify the replay to use candle-by-candle processing (matching live behavior)
2. Re-run the reconciliation with the corrected replay
3. Verify that all 30 HLC paper trades match the corrected replay
