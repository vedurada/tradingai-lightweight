# Phase 5.27 — HLC Overlap Reconciliation and 245-Row Discrepancy Audit

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Phase 5.26: `/opt/tradingai/research/phase526_replay_20261029_222000/`
- Report directory: `/opt/tradingai/research/phase527_reconciliation_20261029_222500/`

## Step 1 — Authoritative Source

Phase 5.12 JSON files are authoritative:
- `TRADE_LEDGER_NIFTY.json`: 382 trades
- `TRADE_LEDGER_BANKNIFTY.json`: 347 trades
- Total: 729 trades

TRADE_LEDGER.csv (974 rows) is unreliable (245 extra rows from buggy first script).

## Step 2 — 245-Row Discrepancy

See `245_ROW_DISCREPANCY_CLASSIFICATION.csv`.

- 729 MATCHED (present in JSON)
- 197 CLOSE_ENTRY_TIME (entry within 1 hour of JSON trade on same day/instrument)
- 48 NEW_SIGNAL_NOT_IN_JSON (no close JSON trade on that day/instrument)

Status: UNRESOLVED. Extra rows from candle-by-candle processing with last-candle detection.

## Step 3 — Overlap Period

- HLC paper trades: Sep 25 - Oct 28 (30 trades)
- Replay: Jul 6 - Oct 29 (729 trades)
- Overlap: Sep 25 - Oct 28
- 81 sessions total, 2 with missing candles (Sep 21, Oct 15)

## Step 4 — HLC 30-Trade Reconciliation

See `HLC_30_TRADE_RECONCILIATION.csv`.

- 26 EXACT_MATCH (instrument + entry_time + direction match replay)
- 4 PROBABLE_MATCH (same day/instrument/direction, no exact entry time match)
- 0 DATABASE_ONLY
- 0 REPLAY_ONLY
- 0 CONFLICTING
- 0 UNCLASSIFIABLE

## Step 5 — Scalp Signal Reconciliation

See `SCALP_SIGNALS_RECONCILIATION.csv`.

- 29 signals total (18 TRADED, 10 EXPIRED, 1 IGNORED)
- 27 matched in replay
- 2 unmatched (no corresponding replay signal)

## Step 6 — Overlap Performance

See `REPLAY_OVERLAP_PERFORMANCE.csv`.

- Replay trades in overlap period: NIFTY 382, BANKNIFTY 347 (full dataset, not filtered to overlap)
- Note: Replay covers full Jul-Oct period, not just overlap

## Final Classification

**PARTIAL — RECONCILIATION IS AUDITABLE BUT SOME RECORDS REMAIN UNRESOLVED**

Reasons:
1. 245-row discrepancy UNRESOLVED
2. 4 PROBABLE_MATCH trades (not exact)
3. 2 scalp signals unmatched
4. Only 3.5 months of data
