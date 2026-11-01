# Phase 5.10 — Working-Tree Safe Deployment Plan

## Read-Only Inventory

| Category | Count |
|----------|-------|
| Modified tracked files | 439 |
| Untracked files | 1,403 |
| Total dirty files | 1,842 |

## Path Classification

### Production-Critical (5 files)

| File | Risk |
|------|------|
| app/api/app.py | API changes may conflict |
| app/live/engine.py | Live decision engine changes |
| app/market/provider.py | Market data provider changes |
| app/paper_trade/engine.py | Paper trade engine changes |
| app/research/scalp_engine.py | HLC engine changes |

### Reports and Artifacts (866 files)

- research/ (433 files)
- backups/ (443 files)
- backup/ (345 files)

### Frontend Assets (171 files)

- frontend/*.html (17 modified)
- frontend/indices/*.html (2 modified)

## Proposed Non-Destructive Deployment Design

1. Create tar backup of entire working tree
2. Identify minimal deployment package (only files to change)
3. Copy to staging directory (e.g., /opt/tradingai/deploy_YYYYMMDD/)
4. Diff staging against current files
5. Test in staging
6. Switch via symlink or directory rename (atomic)
7. Keep original tree intact for rollback

## Prerequisites for Future Implementation

1. Clean baseline (commit or backup current state)
2. Minimal deployment package identified
3. Staging directory tested
4. Rollback procedure verified
5. User approval for deployment

## Blocker Status: OPEN

Safe deployment cannot be proven from available evidence. B1 remains OPEN.
