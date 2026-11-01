# Phase 5.6A — Working-Tree Safety Audit

## Read-Only Inventory

### Git Status Summary

| Category | Count |
|----------|-------|
| Modified tracked files | 439 |
| Untracked files | 1,403 |
| Total dirty files | 1,842 |
| Branch | `production-2026-10-01` |
| Last commit | `7da4b21 feat(scalp): add 1m scalp backtest script` |

### Modified Files (Top 20)

| File | Type |
|------|------|
| app/api/app.py | Core API |
| app/live/engine.py | Live decision engine |
| app/market/provider.py | Market data provider |
| app/paper_trade/engine.py | Paper trade engine |
| app/research/scalp_engine.py | HLC canonical engine |
| app/research/scalp_signal_store.py | Signal store |
| data/veto_score_audit.jsonl | Data |
| frontend/*.html | Frontend assets (17 files) |
| frontend/indices/*.html | Frontend indices (2 files) |

### Untracked Files (Top Directories)

| Directory | Count | Type |
|-----------|-------|------|
| backups/ | 443 | Backup files |
| research/ | 433 | Research artifacts |
| backup/ | 345 | Backup files |
| frontend/ | 171 | Frontend files |
| tests/ | 4 | Test files |
| logs/ | 4 | Log files |
| scripts/ | 1 | Script files |
| deploy/ | 1 | Deploy files |
| app/ | 1 | App files |

### Key Observations

1. **No git commands were used to modify the working tree** — all inventory was read-only.
2. **No files were deleted, renamed, or overwritten.**
3. **No commits, stashes, or resets were performed.**
4. **The working tree is extremely dirty** — 1,842 uncommitted files.

### Non-Destructive Change-Management Approach

Since the working tree cannot be safely cleaned or committed:

1. **Do not commit or stash** — preserve all existing work.
2. **Do not reset or clean** — would lose untracked research and frontend files.
3. **For future deployments**, use a separate deployment branch or directory:
   - Create a new directory: `/opt/tradingai/deploy_YYYYMMDD/`
   - Copy only the files to be deployed (not the entire tree)
   - Use file-level diffing to identify what changed
   - Test in the deployment directory before switching

### File Collisions That Would Block Deployment

| Collision | Risk | Mitigation |
|-----------|------|------------|
| 439 modified tracked files | Git merge conflicts on deploy | Use file-level copy, not git merge |
| 1,403 untracked files | May overwrite existing files | Inventory hashes before deploy |
| Frontend files modified (17 HTML) | May conflict with new frontend | Deploy frontend separately |
| Research files (433) | Not needed for production | Exclude from deploy package |

### Hash Inventory

File hashes were recorded using `sha256sum` for all tracked files. The inventory is stored in the research directory but not included in this report (too large).

### Recommendation

Before any future deployment:
1. Create a complete backup of the working tree (using tar, not git)
2. Identify the minimal set of files to deploy
3. Copy those files to a staging directory
4. Test in staging before switching
5. Keep the original tree intact for rollback
