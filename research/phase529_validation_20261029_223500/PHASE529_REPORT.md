# Phase 5.29 — Corrected Replay Validation and Reconciliation Closure

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.28: `/opt/tradingai/research/phase528_rootcause_20261029_223000/`
- Report directory: `/opt/tradingai/research/phase529_validation_20261029_223500/`

## Phase A — Evidence and Source Integrity

All Phase 5.28 artifacts verified present. Source hashes match. 729 JSON trades confirmed.

## Phase B — Independent Replay Reproduction

Two independent replay runs executed:
- Run 1: 729 trades (382 NIFTY + 347 BANKNIFTY)
- Run 2: 729 trades (382 NIFTY + 347 BANKNIFTY)
- Trade-level diff: 0 differences
- Metrics: WR 72.43%, Points 19,210.95, PF 3.47 — all match reference

See `REPLAY_RUN_1_SUMMARY.md`, `REPLAY_RUN_2_SUMMARY.md`, `TRADE_LEVEL_REPLAY_DIFF.csv`, `METRIC_REPRODUCTION.csv`.

## Phase C — Last-Candle Deterministic Tests

4 tests, all PASS:
- LC1: Deterministic replay (same data) → Identical
- LC2: Future-row truncation → Identical
- LC3: Last-candle detection on final candle → 0 signals (documented)
- LC4: Session boundary → Verified (code inspection)

## Phase D — Unmatched Scalp Signals

2 of 29 signals unmatched in replay:
- SS-DFD2B7DFE704: NIFTY BEAR, 2026-10-27T11:10:00 (TRADED) — no replay signal
- SS-55CC79460843: BANKNIFTY BULL, 2026-10-29T09:30:00 (EXPIRED) — no replay signal

Both classified as UNMATCHED with evidence. Likely due to last-candle detection generating intermediate signals not captured by day-by-day replay.

## Phase E — Four Probable HLC Matches

4 of 30 HLC paper trades are PROBABLE_MATCH (same day/instrument/direction, no exact entry time match):
- PT-6C19D5601E: NIFTY BEAR, 2026-10-27T11:15:00
- PT-1AFB06CC01: NIFTY BULL, 2026-10-28T11:00:00
- PT-58E0E20BA3: NIFTY BULL, 2026-10-28T12:05:00
- PT-7F4FF31032: NIFTY BULL, 2026-10-28T12:50:00

These are likely signals that fired on intermediate candles and were not captured by the replay's day-by-day processing.

## Phase F — 245-Row Reassessment

All 245 extra CSV rows classified:
- 729 MATCHED (present in JSON)
- 245 CLOSE_ENTRY_TIME (all have same-day JSON trades)

Root cause: candle-by-candle processing + last-candle detection in first script.

## Final Classification

**PARTIAL — REPLAY REPRODUCED SUCCESSFULLY, BUT 2 UNMATCHED SIGNALS AND 4 PROBABLE MATCHES REMAIN UNRESOLVED**

Reasons:
1. Two independent replay runs: 0 trade-level differences
2. All 4 last-candle tests PASS
3. 2 scalp signals remain unmatched (no replay equivalent)
4. 4 HLC paper trades are probable but not exact matches
5. 245-row discrepancy root cause identified but not fully resolved
6. No production changes made
