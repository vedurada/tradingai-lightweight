# SMA9 Scanner — Locked, Consolidated Source

This folder is the single source of truth for the SMA9 ATM CE/PE BUY-only
paper scanner. The code is **root-owned, read-only, and immutable**.

- Live entrypoint: `app/live_sma9_scanner.py`
- Strategy engine: `app/sma9_engine.py`
- Corrected historical audit: `app/sma9_historical_audit.py`
- Legacy signal-only package: `sma9_only/`
- Tests: `tests/`
- Lock / integrity / status tools: `ops/`
- Security and change-control guide: `docs/SECURITY_AND_OPERATIONS.md`

## Daily checks

```bash
sudo systemctl status tradingai-sma9-scanner.service
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
sudo /opt/tradingai/sma9_scanner/ops/status.sh
```

## Lock status

```bash
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
stat -c '%U:%G %a %n' /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
```

Expected: the `i` (immutable) flag is set, owner is `root`, mode is `444`.

## Approved changes only

```bash
sudo /opt/tradingai/sma9_scanner/ops/unlock_code.sh
# edit + test
sudo /opt/tradingai/sma9_scanner/ops/lock_code.sh
sudo systemctl restart tradingai-sma9-scanner.service
```

The scanner runs as the unprivileged `sma9` user with no sudo rights, inside a
systemd sandbox. See `docs/SECURITY_AND_OPERATIONS.md` for the full policy,
verification commands, and rollback steps.
