# SMA9 Scanner — Security, Lock & Operations Guide

Last updated: 2026-11-06 (IST)

## 1. Scope

This guide covers the SMA9 ATM CE/PE **BUY-only paper scanner** only. It does
not send broker orders. It covers:

- the consolidated source folder `/opt/tradingai/sma9_scanner/`
- the `tradingai-sma9-scanner.service` systemd unit
- the dedicated database `/opt/tradingai/database/sma9.db`
- the code-integrity timer
- the public dashboard `/live/index.html` and `/api/sma9/*` endpoints

## 2. Single source of truth

All SMA9 code lives in `/opt/tradingai/sma9_scanner/`:

```
sma9_scanner/
├── app/
│   ├── live_sma9_scanner.py      # live paper trader (5s polling)
│   ├── sma9_engine.py            # pure BUY-only strategy engine
│   ├── sma9_historical_audit.py  # 339-trade audit + corrected dataset
│   ├── sma9_db_setup.py          # dedicated DB migration
│   └── sma9_scan_runner.py       # deprecated, no-write shim
├── sma9_only/                    # legacy signal-only package (BUY-only)
├── tests/                        # 21 regression / scenario tests
├── ops/                          # lock, unlock, integrity, status, units
├── docs/                         # this guide
├── VERSION
├── MANIFEST.sha256               # SHA256 of every shipped file
└── LOCKED.json                   # lock timestamp + manifest hash
```

Old paths under `scripts/` and `scanners/sma9_only/` were removed during
consolidation; the service points at the new folder. Do not recreate them.

## 3. What "locked" means

`ops/lock_code.sh` applies three layers:

1. **Ownership** — every file is `root:root`.
2. **Modes** — directories `0555`, shell tools `0555`, all other files `0444`.
3. **Immutability** — `chattr +i` on every file and directory.

Consequences:

- The scanner service user (`sma9`) cannot modify, delete, rename, or replace
  any code file.
- Even `root`/`sudo` cannot edit or delete a locked file until the immutable
  flag is removed with `ops/unlock_code.sh`.
- Python cannot write `__pycache__` into the folder; the service sets
  `PYTHONDONTWRITEBYTECODE=1`.

A SHA256 manifest is generated at lock time. Any change to any file is
detectable even after an unlock/re-lock cycle, because `LOCKED.json` records
the manifest hash.

## 4. Integrity monitoring

`ops/verify_integrity.sh` runs `sha256sum -c --quiet MANIFEST.sha256` from the
lock root. It is read-only and safe to run as any user.

`ops/install_integrity_timer.sh` installs:

- `tradingai-sma9-integrity.service` (oneshot)
- `tradingai-sma9-integrity.timer` (every 15 minutes, persistent)

Output is appended to `/opt/tradingai/logs/sma9_integrity.log`. A mismatch
prints `SMA9 INTEGRITY FAILURE` and the unit exits non-zero.

Manual check:

```bash
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
tail -n 20 /opt/tradingai/logs/sma9_integrity.log
```

## 5. Service account and sandbox

The scanner does **not** run as `ubuntu` (which has passwordless sudo). It runs
as the system user `sma9`:

- no login shell, no home directory, no sudo rights
- primary group `ubuntu`, shared with the API process, so SQLite `-wal`/`-shm`
  files it creates are group-readable/writable by the API; the unit sets
  `UMask=0007` (never world-readable)
- systemd hardening: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `PrivateDevices`, empty capability set,
  `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK`
- writes are limited to `/opt/tradingai/database` and `/opt/tradingai/logs`

The unit file of record is `ops/tradingai-sma9-scanner.service`; the installed
copy is `/etc/systemd/system/tradingai-sma9-scanner.service`.

## 6. Verification commands

```bash
# service is running as sma9
systemctl show tradingai-sma9-scanner.service -p User -p Group -p ExecStart

# code is immutable, root-owned, read-only
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
stat -c '%U:%G %a %n' /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py

# manifest matches
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh

# full system + dashboard verification
sudo /usr/bin/python3 /opt/tradingai/sma9_scanner/ops/verify_system.py
sudo /usr/bin/python3 /opt/tradingai/sma9_scanner/ops/verify_dashboard.py

# tests
cd /opt/tradingai/sma9_scanner
python3 -m unittest tests.test_sma9_engine tests.test_sma9_legacy_package -v
```

Expected lock state: `i` flag set, owner `root`, mode `444`; integrity `OK`.

## 7. Approved change procedure

Never edit a locked file in place. Use this sequence:

```bash
# 1. unlock (explicit sudo action)
sudo /opt/tradingai/sma9_scanner/ops/unlock_code.sh

# 2. edit (files are root-owned; use sudo or chown temporarily)
sudo nano /opt/tradingai/sma9_scanner/app/sma9_engine.py

# 3. test the canonical folder
cd /opt/tradingai/sma9_scanner
python3 -m unittest tests.test_sma9_engine tests.test_sma9_legacy_package -v

# 4. re-lock (regenerates MANIFEST.sha256 + LOCKED.json)
sudo /opt/tradingai/sma9_scanner/ops/lock_code.sh

# 5. restart and verify
sudo systemctl restart tradingai-sma9-scanner.service
sudo systemctl restart tradingai-sma9-integrity.timer
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
sudo /opt/tradingai/sma9_scanner/ops/verify_system.py
```

Restart is safe with an open paper position: the scanner restores the position
from `sma9_open_positions` and exits at the original entry candle's close.

## 8. Stop, disable, and rollback

Stop trading immediately:

```bash
sudo systemctl stop tradingai-sma9-scanner.service
sudo systemctl disable tradingai-sma9-scanner.service
```

Restore the pre-lock code (backups):

```bash
# latest pre-lock snapshot (code, old paths, tests, service unit)
# path is also recorded in backups/SMA9_LAST_LOCK_BACKUP_PATH.txt
sudo cp -a /opt/tradingai/backups/sma9_lock_20261106_144742/scripts/. /opt/tradingai/scripts/
sudo cp -a /opt/tradingai/backups/sma9_lock_20261106_144742/scanners/sma9_only /opt/tradingai/scanners/
sudo cp -a /opt/tradingai/backups/sma9_lock_20261106_144742/tests/. /opt/tradingai/tests/
sudo cp -a /opt/tradingai/backups/sma9_lock_20261106_144742/systemd/tradingai-sma9-scanner.service /etc/systemd/system/

# earlier forensic / legacy backups (still available)
# /opt/tradingai/backups/sma9_forensic_20261106_140314
# /opt/tradingai/backups/sma9_legacy_pkg_20261106_142023
```

Restore the service unit from the backup or from
`/opt/tradingai/sma9_scanner/ops/tradingai-sma9-scanner.service` after
unlocking. The original `database/tradingai.db` was never modified and still
holds the 339 legacy rows.

## 9. Data and backups

- Dedicated DB: `/opt/tradingai/database/sma9.db`
  - `sma9_trades_legacy` — 339 original rows (preserved)
  - `sma9_trades_corrected` — 258 corrected historical rows
  - `sma9_audit` — 339 audit rows (0 compliant)
  - `sma9_trades` — `HISTORICAL_CORRECTED` + `LIVE` paper trades
  - `sma9_open_positions` — restart recovery
- Original DB: `/opt/tradingai/database/tradingai.db` (untouched, 339 rows)
- Code backups:
  - `/opt/tradingai/backups/sma9_lock_20261106_144742` (latest pre-lock)
  - `/opt/tradingai/backups/sma9_forensic_20261106_140314`
  - `/opt/tradingai/backups/sma9_legacy_pkg_20261106_142023`
  - pointer file: `/opt/tradingai/backups/SMA9_LAST_LOCK_BACKUP_PATH.txt`
- Reports: `/opt/tradingai/reports/sma9_*`
- Logs: `/opt/tradingai/logs/live_sma9_scanner.log`,
  `/opt/tradingai/logs/sma9_integrity.log`

Back up the DB before any migration or schema change:

```bash
sudo sqlite3 /opt/tradingai/database/sma9.db ".backup '/opt/tradingai/backups/sma9_$(date +%Y%m%d_%H%M%S).db'"
```

## 10. Credentials

Kite credentials live in `/opt/tradingai/.env.zerodha` (owner `ubuntu`, group
`ubuntu`, mode `640`). Only the owner and the shared service group can read it.
Never commit or print this file. The scanner is paper-only and contains no
broker order calls.

## 11. Security limitations

- A root or sudo compromise can still run `unlock_code.sh`. The lock protects
  against accidental edits, the service account, and non-root processes; it is
  not a defense against a fully compromised host.
- Host hardening (SSH keys, firewall, patching, fail2ban) remains necessary.
- The integrity timer detects changes but does not automatically roll them
  back; an alerting hook can be added to the timer if required.

## 12. Current lock record

See `/opt/tradingai/sma9_scanner/LOCKED.json` for the authoritative lock time,
file count, and manifest SHA256. Do not edit that file manually.
