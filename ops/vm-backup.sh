#!/usr/bin/env bash
# TradingAI daily off-site backup: VM -> git (branch vm-backup).
# Runs on the VM via cron: 30 18 * * * /opt/tradingai/ops/vm-backup.sh >> /opt/tradingai/logs/backup.log 2>&1
#
# DATA-SAFETY RULES (do not "optimize" these away):
#  1. Live DB is snapshotted with SQLite's online-backup API, NEVER raw-copied.
#  2. Snapshot is integrity-checked + row-count sanity-checked BEFORE commit.
#  3. Nothing is ever deleted from /opt/tradingai (mirror --delete applies to the
#     backup workdir only, never the source).
#  4. Push is verified (remote contains our commit). Failure exits non-zero loudly.
set -euo pipefail

SRC="/opt/tradingai"
WORK="/opt/tradingai-backup"
LOG_PREFIX="[vm-backup]"
BRANCH="vm-backup"
# Same repo as the app code, separate branch so main history stays clean.
REMOTE_URL="${BACKUP_REMOTE_URL:-git@github.com:vedurada/tradingai-lightweight.git}"
SSH_KEY="$HOME/.ssh/github_backup"

log() { echo "$LOG_PREFIX $(date '+%F %T %Z') $*"; }

# --- 0. SSH auth for git (key must be added to GitHub once as a deploy key) ---
if [ -f "$SSH_KEY" ]; then
    export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o BatchMode=yes"
    log "using deploy key $SSH_KEY"
else
    export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o BatchMode=yes"
    log "no $SSH_KEY; falling back to default ssh agent/config"
fi

# --- 1. Init backup workdir once ---
if [ ! -d "$WORK/.git" ]; then
    log "first run: initializing $WORK on branch $BRANCH"
    sudo mkdir -p "$WORK" && sudo chown -R "$(id -un):$(id -gn)" "$WORK"
    mkdir -p "$WORK"
    git -C "$WORK" init -q
    git -C "$WORK" remote add origin "$REMOTE_URL" 2>/dev/null || git -C "$WORK" remote set-url origin "$REMOTE_URL"
    git -C "$WORK" fetch origin "$BRANCH" 2>/dev/null && git -C "$WORK" checkout "$BRANCH" || git -C "$WORK" checkout -b "$BRANCH"
    git -C "$WORK" config user.name "tradingai-vm-backup"
    git -C "$WORK" config user.email "backup@tradingai.in"
fi
git -C "$WORK" checkout -q "$BRANCH" 2>/dev/null || git -C "$WORK" checkout -q -b "$BRANCH"

# --- 2. Crash-safe snapshot of the LIVE database (online backup API) ---
LIVE_DB="$SRC/database/tradingai.db"
SNAP_DIR="$WORK/database"
mkdir -p "$SNAP_DIR"
if [ ! -f "$LIVE_DB" ]; then
    log "FATAL: live DB missing at $LIVE_DB — refusing to back up an empty state"
    exit 1
fi
log "snapshotting live DB (online backup API)..."
python3 - "$LIVE_DB" "$SNAP_DIR/tradingai.db" <<'PYEOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
d.close(); s.close()
print("snapshot ok")
PYEOF

# --- 3. Verify snapshot BEFORE it can replace anything ---
VERIFY=$(python3 - "$SNAP_DIR/tradingai.db" <<'PYEOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
try:
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
    prices = c.execute("SELECT COUNT(*) FROM price_1m").fetchone()[0]
    hist = c.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    syms = c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    print(f"integrity={integ} prices={prices} history={hist} symbols={syms}")
    ok = (integ == "ok" and prices > 0 and syms > 0)
    print("VERIFY_PASS" if ok else "VERIFY_FAIL")
except Exception as e:
    print(f"VERIFY_FAIL: {e}")
PYEOF
)
log "snapshot verify: $VERIFY"
case "$VERIFY" in
    *VERIFY_PASS*) ;;
    *) log "FATAL: snapshot failed verification — aborting, source untouched"; exit 1 ;;
esac

# --- 4. Mirror code/data/config into workdir (delete only inside mirror) ---
log "syncing files into backup workdir..."
mkdir -p "$WORK/data" "$WORK/config" "$WORK/backend" "$WORK/ops" "$WORK/indices" "$WORK/stocks" "$WORK/static"
cp -f "$SRC"/*.html "$WORK/" 2>/dev/null || true
cp -rf "$SRC"/indices/* "$WORK/indices/" 2>/dev/null || true
cp -rf "$SRC"/stocks/* "$WORK/stocks/" 2>/dev/null || true
cp -rf "$SRC"/static/* "$WORK/static/" 2>/dev/null || true
cp -rf "$SRC"/config/* "$WORK/config/" 2>/dev/null || true
cp -rf "$SRC"/backend/*.py "$WORK/backend/" 2>/dev/null || true
cp -rf "$SRC"/ops/* "$WORK/ops/" 2>/dev/null || true
cp -f "$SRC"/deploy-vm.sh "$SRC"/KNOWLEDGE.md "$WORK/" 2>/dev/null || true
cp -rf "$SRC"/data/*.json "$WORK/data/" 2>/dev/null || true
find "$WORK" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$WORK" -name '*.pyc' -delete 2>/dev/null || true

# --- 5. Manifest: what, when, how big ---
{
    echo "backup_utc=$(date -u '+%FT%TZ')"
    echo "backup_ist=$(TZ=Asia/Kolkata date '+%FT%T%Z')"
    du -sh "$SNAP_DIR/tradingai.db" | awk '{print "db_size="$1}'
    echo "$VERIFY" | tr ' ' '\n' | grep -E '^(prices|history|symbols)='
    echo "files=$(find "$WORK" -type f -not -path '*/.git/*' | wc -l)"
} > "$WORK/backup-info.txt"

# --- 6. Commit only if something changed ---
git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet; then
    log "no changes since last backup — nothing to push"
    exit 0
fi
STAMP=$(TZ=Asia/Kolkata date '+%F %T IST')
git -C "$WORK" commit -q -m "vm backup $STAMP" || { log "FATAL: commit failed"; exit 1; }

# --- 7. Push + verify (fail LOUD if auth/network broken) ---
if ! git -C "$WORK" push -q origin "$BRANCH" 2>&1 | tee /tmp/vm-backup-push.log; then
    log "FATAL: git push failed. One-time setup needed on the VM:"
    log "  1) ssh-keygen -t ed25519 -f ~/.ssh/github_backup -N ''"
    log "  2) add ~/.ssh/github_backup.pub as a WRITE deploy key at github.com/vedurada/tradingai-lightweight/settings/keys"
    log "  3) re-run: /opt/tradingai/ops/vm-backup.sh"
    cat /tmp/vm-backup-push.log | head -5 | while read -r l; do log "push says: $l"; done
    exit 1
fi
LOCAL_REV=$(git -C "$WORK" rev-parse HEAD)
REMOTE_REV=$(git -C "$WORK" ls-remote origin "$BRANCH" | awk '{print $1}')
if [ "$LOCAL_REV" != "$REMOTE_REV" ]; then
    log "FATAL: push verification failed (remote $REMOTE_REV != local $LOCAL_REV)"
    exit 1
fi
log "backup pushed OK: $LOCAL_REV ($(du -sh "$SNAP_DIR/tradingai.db" | awk '{print $1}')) DB"
