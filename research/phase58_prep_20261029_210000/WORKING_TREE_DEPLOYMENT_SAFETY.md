# Phase 5.8 — Working-Tree Deployment Safety

## Read-Only Inventory

### Git Status Summary

| Category | Count |
|----------|-------|
| Modified tracked files | 439 |
| Untracked files | 1,403 |
| Total dirty files | 1,842 |
| Branch | `production-2026-10-01` |
| Last commit | `7da4b21 feat(scalp): add 1m scalp backtest script` |

### Modified Core Application Files (5)

| File | Risk |
|------|------|
| app/api/app.py | API changes may conflict with new deployment |
| app/live/engine.py | Live decision engine changes |
| app/market/provider.py | Market data provider changes |
| app/paper_trade/engine.py | Paper trade engine changes |
| app/research/scalp_engine.py | HLC engine changes |
| app/research/scalp_signal_store.py | Signal store changes |

### Untracked Directories

| Directory | Count | Type | Risk |
|-----------|-------|------|------|
| backups/ | 443 | Backup files | Low (not needed for deploy) |
| research/ | 433 | Research artifacts | Low (not needed for deploy) |
| backup/ | 345 | Backup files | Low |
| frontend/ | 171 | Frontend assets | Medium (may need deploy) |
| tests/ | 4 | Test files | Low |
| logs/ | 4 | Log files | Low |
| scripts/ | 1 | Script files | Low |
| deploy/ | 1 | Deploy files | Low |
| app/ | 1 | App files | Low |

### Path Collisions

No file path collisions identified that would block deployment. The 5 modified core app files are the primary collision risk — a deployment that overwrites these files would lose the current (uncommitted) changes.

### Non-Destructive Deployment Strategy

1. **Do NOT use git merge or git pull** — would conflict with 1,842 dirty files
2. **Do NOT clean or reset** — would lose uncommitted work
3. **Use file-level copy:**
   a. Identify minimal set of files to deploy (e.g., feature flag changes)
   b. Copy only those files to a staging directory
   c. Diff against current files to identify conflicts
   d. Test in staging before switching
   e. Keep original files intact for rollback
4. **Preserve all existing files** — no deletions or overwrites

### Blocker Status

**B1 (Dirty working tree): UNRESOLVED**

Safe deployment cannot be established from evidence alone. The working tree has 1,842 uncommitted files, including 5 modified core application files. No clean baseline exists for comparison.

### Recommendation

Before any future deployment:
1. Create a tar backup of the entire working tree
2. Identify the minimal deployment package
3. Test in a separate staging directory
4. Use file-level diffing to verify no unintended overwrites
