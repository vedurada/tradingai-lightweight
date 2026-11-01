# Phase 5.27 — Count Reconciliation

## Source Counts

| Source | Count | Status |
|--------|-------|--------|
| TRADE_LEDGER_NIFTY.json | 382 | Authoritative |
| TRADE_LEDGER_BANKNIFTY.json | 347 | Authoritative |
| TRADE_LEDGER.csv | 974 | Unreliable (245 extra) |
| paper_trades (SCALP_HLC) | 30 | Production DB |
| scalp_signals | 29 | Production DB |
| HLC paper trades matched | 26 exact + 4 probable | Reconciliation |

## Classification Totals

| Classification | Count | Source |
|----------------|-------|--------|
| MATCHED (in JSON) | 729 | CSV vs JSON |
| CLOSE_ENTRY_TIME | 197 | Extra CSV rows |
| NEW_SIGNAL_NOT_IN_JSON | 48 | Extra CSV rows |
| EXACT_MATCH (paper vs replay) | 26 | 30 HLC paper trades |
| PROBABLE_MATCH | 4 | 30 HLC paper trades |
| Signal matched in replay | 27 | 29 scalp signals |
| Signal unmatched | 2 | 29 scalp signals |

## Totals Reconcile

- 729 + 245 = 974 (CSV rows) ✓
- 26 + 4 = 30 (HLC paper trades) ✓
- 27 + 2 = 29 (scalp signals) ✓
