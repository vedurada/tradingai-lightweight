# Production DB Integrity — Phase 42A.10A

## Pre-Replay Check
- [ ] Backup created BEFORE replay
- [ ] PRAGMA integrity_check = ok
- [ ] Backup verified restorable

## During Replay
- [ ] Replay data written to SEPARATE tables/database
- [ ] Production tables NOT modified
- [ ] Or replay uses isolated replay_session_id

## Post-Replay Check
- [ ] PRAGMA integrity_check = ok
- [ ] Production tables unchanged
- [ ] No unexpected rows added to production tables
- [ ] Backup still valid

## Verification
Production tables that must NOT be modified by replay:
- market_snapshots_5m (production data, not replay)
- market_evidence_5m (production data, not replay)
- paper_trades (production data, not replay)
- ai_outlooks_5m (production data, not replay)
- All other production tables

## Result
Integrity check: [ok/failed]
Production tables modified: [count] (should be 0 or explicitly intended)