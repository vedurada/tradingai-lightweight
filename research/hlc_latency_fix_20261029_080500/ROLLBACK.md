# TradingAI Phase 3.5 — ROLLBACK.md

**Audit directory:** /opt/tradingai/research/hlc_latency_fix_20261029_080500/
**Rollback date:** 2026-10-29  
**Host:** webserver (Oracle VM)

## Rollback Procedure

If the fix needs to be rolled back, restore the backup files and restart the `paper_scalp_live.py` process.

### Step 1: Stop the running process

```bash
# Find the PID of the running paper_scalp_live.py
ps -ef | grep paper_scalp_live | grep -v grep

# Kill the process
kill <PID>
```

### Step 2: Restore backup files

```bash
cd /opt/tradingai/research/hlc_latency_fix_20261029_080500/backups

cp -p scalp_engine.py.bak-20261029_080500 /opt/tradingai/app/research/scalp_engine.py
cp -p paper_scalp_live.py.bak-20261029_080500 /opt/tradingai/scripts/paper_scalp_live.py
cp -p paper_trade_engine.py.bak-20261029_080500 /opt/tradingai/app/paper_trade/engine.py
```

### Step 3: Verify file integrity

```bash
# Verify MD5 checksums match the originals
md5sum /opt/tradingai/app/research/scalp_engine.py
# Expected: c0ffd9401b0e8ffb8e16300306000313

md5sum /opt/tradingai/scripts/paper_scalp_live.py
# Expected: a874be1e84e40c024c3aecc5703772ac

md5sum /opt/tradingai/app/paper_trade/engine.py
# Expected: b8da0ea1a8b2fee9cc4b736c39598a25
```

### Step 4: Restart the process

```bash
cd /opt/tradingai
nohup /usr/bin/python3 /opt/tradingai/scripts/paper_scalp_live.py > /opt/tradingai/logs/paper_scalp_live.out 2>&1 &
```

### Step 5: Verify restart

```bash
ps -ef | grep paper_scalp_live | grep -v grep
```

## Rollback Impact

- Live paper trading reverts to ~5-6 minute entry-to-record delay
- All strategy rules remain unchanged (this was never modified)
- No database changes were made, so no data rollback is needed
- No configuration changes were made
- No cron or systemd changes were made

## When to Rollback

Rollback if any of the following occur:
- Paper trades are not being created after the fix
- Duplicate paper trades are being created
- Entry prices are incorrect (not matching candle opens)
- The process crashes repeatedly
- Any unexpected behavior in paper trading or alert generation
