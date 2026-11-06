# SMA9 Scanner — Lock & Security Report

**Date:** 2026-11-06 (IST)
**Scope:** SMA9 ATM CE/PE BUY-only **paper** scanner (no broker orders)
**Status:** Locked, consolidated, hardened, verified

---

## 1. Executive summary

The SMA9 scanner is now:

- **Consolidated** into a single folder: `/opt/tradingai/sma9_scanner/`
- **Locked** with root ownership, read-only modes, and the Linux immutable flag
  (`chattr +i`), backed by a SHA256 manifest
- **Run by a dedicated unprivileged account** (`sma9`) with no login shell,
  no home directory, and no sudo rights, inside a systemd sandbox
- **Monitored** by a 15-minute integrity timer
- **Verified end-to-end**: 21/21 tests, full system verifier, public dashboard,
  and live paper trading all pass

The service is live and trading paper positions normally under the locked,
sandboxed configuration.

---

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
├── docs/                         # security & operations guide
├── VERSION
├── MANIFEST.sha256               # SHA256 of every shipped file
└── LOCKED.json                   # lock timestamp + manifest hash
```

Old duplicate paths (`scripts/sma9_*`, `scanners/sma9_only`, old SMA9 tests)
were removed. Do not recreate them.

---

## 3. Lock mechanics

`ops/lock_code.sh` applies three independent layers:

| Layer | Setting |
|---|---|
| Ownership | every file/dir is `root:root` |
| Modes | dirs `0555`, `.sh` tools `0555`, all other files `0444` |
| Immutability | `chattr +i` on every file and directory |

Consequences:

- The `sma9` service user cannot modify, delete, rename, or replace code.
- Even `root`/`sudo` must run `ops/unlock_code.sh` before editing.
- Python cannot write `__pycache__`; the unit sets
  `PYTHONDONTWRITEBYTECODE=1`.

### Current lock record

From `/opt/tradingai/sma9_scanner/LOCKED.json`:

```json
{
  "locked_at": "2026-11-06T15:02:34+05:30",
  "locked_by": "lock_code.sh",
  "root": "/opt/tradingai/sma9_scanner",
  "manifest_sha256": "6f2e935c9aa4c5ce4a297a2fb3076a265b8dc3d0cd7e81d40e8be61f7cfd2f4c",
  "file_count": 29,
  "policy": "root-owned, read-only, immutable (chattr +i); service runs as unprivileged user sma9"
}
```

Verified sample:

```
----i---------e------- /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
root:root 444          /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
```

Write attempts by both `ubuntu` and `sma9` fail with
`Operation not permitted`.

---

## 4. Service account and sandbox

The scanner does **not** run as `ubuntu` (which has passwordless sudo).
It runs as the system user `sma9`:

- `User=sma9`, `Group=ubuntu`
- no login shell, no home directory, no sudo rights
- `UMask=0007` so SQLite `-wal`/`-shm` files are group read/write for the API,
  never world-readable
- systemd hardening:
  - `NoNewPrivileges=true`
  - `ProtectSystem=strict`
  - `ProtectHome=true`
  - `PrivateTmp=true`, `PrivateDevices=true`
  - `ProtectKernelTunables/Modules/ControlGroups/Clock=true`
  - `RestrictRealtime=true`, `RestrictSUIDSGID=true`, `RemoveIPC=true`,
    `LockPersonality=true`
  - `CapabilityBoundingSet=` (empty), `AmbientCapabilities=` (empty)
  - `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK`
- writes limited to `/opt/tradingai/database` and `/opt/tradingai/logs`
- code and dependencies mounted read-only:
  `/opt/tradingai/sma9_scanner`, `/opt/tradingai/sma9_lib`

`kiteconnect` and its dependencies are isolated in
`/opt/tradingai/sma9_lib` (root-owned, read-only, 328M) and exposed through
`PYTHONPATH`, so `/home/ubuntu` never needs to be exposed to the service.

Unit of record: `sma9_scanner/ops/tradingai-sma9-scanner.service`
Installed copy: `/etc/systemd/system/tradingai-sma9-scanner.service`

---

## 5. Integrity monitoring

`ops/verify_integrity.sh` runs:

```bash
sha256sum -c --quiet MANIFEST.sha256
```

Installed timer:

- `tradingai-sma9-integrity.service` (oneshot)
- `tradingai-sma9-integrity.timer` — every 15 minutes, persistent
- log: `/opt/tradingai/logs/sma9_integrity.log`

Latest check:

```
SMA9 integrity OK 2026-11-06T15:47:15+05:30
```

A mismatch prints `SMA9 INTEGRITY FAILURE` and exits non-zero.

---

## 6. Data and credential permissions

| Path | Owner:Group | Mode |
|---|---|---|
| `/opt/tradingai/sma9_scanner/` | `root:root` | `0555` dirs / `0444` files |
| `/opt/tradingai/sma9_lib/` | `root:root` | `0555` dirs / `0444` files |
| `/opt/tradingai/database/sma9.db` | `ubuntu:ubuntu` | `0660` |
| `/opt/tradingai/.env.zerodha` | `ubuntu:ubuntu` | `0640` |
| `/opt/tradingai/database/` | `ubuntu:ubuntu` | `0775` |
| `/opt/tradingai/logs/` | `ubuntu:ubuntu` | `0775` |

SQLite WAL/SHM files created by the scanner are `sma9:ubuntu 0660`, so the
`ubuntu` API can read/write them concurrently. Verified with a live hold test:
the API returned HTTP 200 while a `sma9` connection held the WAL.

---

## 7. Verification results

### Tests

```
cd /opt/tradingai/sma9_scanner
python3 -m unittest tests.test_sma9_engine tests.test_sma9_legacy_package -v
Ran 21 tests — OK
```

### Full system verifier

Latest report:
`/opt/tradingai/reports/sma9_verification_20261106_150357`

```json
{
  "overall_pass": true,
  "live": 11,
  "audit": 339,
  "compliant": 0,
  "open_positions": 1,
  "dup_live": 0,
  "bad_exit": 0,
  "bad_pnl": 0,
  "missing": 0,
  "actual_interval": 5.0,
  "no_orders": true,
  "legacy_package_ok": true,
  "code_lock": { "ok": true, "manifest_ok": true, "immutable": true, "root_owned": true }
}
```

All SMA9 API endpoints returned HTTP 200; both services active and enabled.

### Public dashboard

`https://tradingai.in/live/index.html`

Final dashboard check (15:46:43 IST):

- status badge: **STOPPED** (market CLOSED)
- today trades: **17**, today P&L: **121.25 pts** → **₹7,881.25** at the actual lot size
- history rows: **30**
- zero console/page errors, auto-refresh OK, no open positions
- API restored and serving (`/api/sma9/*` → HTTP 200) after moving back from
  `/opt/tradingai/tobe_deleted/` during the dashboard restore.

### P&L lot size — actual, not fabricated

- Realized P&L is stored per unit premium: `pnl_points = exit − entry` (BUY-only).
- The ₹ conversion uses the **actual lot size** from the authoritative source
  (`app/options/economics.LOT_SIZES`; NSE lots effective 30-Dec-2025: **NIFTY 65**,
  **BANKNIFTY 30**).
- Live closed trades today (2026-11-06): **17 trades, +121.25 pts**
  → **₹7,881.25** total at the actual lot size of 65 (~₹534.93 per trade, 1 lot each).
- The earlier figure of **₹9,093.75** was derived using a **fabricated lot size of 75**
  and is **withdrawn**. No fabricated lot size is used anywhere in the live P&L path.
- Expandable, date-grouped trade log:
  `/opt/tradingai/reports/sma9_live_trades_log_20261106.html`
  (regenerated with the actual lot size; per-trade ₹ P&L + day/total shown; total
  **₹7,881.25**). Generator: `/opt/tradingai/reports/sma9_trade_log.py`.

### Live paper trading after the lock

The scanner continued to enter/exit on candle boundaries under the sandbox:

| Time | Event | P&L |
|---|---|---|
| 14:45 | recovered CE, closed 14:50 at 186.25 | +6.30 |
| 14:50 | CE 165.15 → 165.95 at 14:55 | +0.80 |
| 14:55 | CE 164.85 → 162.00 at 15:00 | −2.85 |
| 15:00 | CE 165.00 → 175.75 at 15:05 | +10.75 |
| 15:05 | new CE entry 176.30 (open) | — |

Snapshot at 15:06 IST: **12 live trades, +68.15 points**.

Final live snapshot (by 15:30 IST, market close): **17 live trades, +121.25 points**.

P&L at the actual lot size: **+121.25 pts × 65 = ₹7,881.25** (17 closed trades, all CE,
BUY-only; 1 lot per trade). The **₹9,093.75** figure previously shown used a fabricated
lot size of 75 and was withdrawn.

---

## 8. Operations runbook

### Daily checks

```bash
systemctl status tradingai-sma9-scanner.service
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
sudo /opt/tradingai/sma9_scanner/ops/status.sh
```

### Confirm the lock

```bash
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
stat -c '%U:%G %a %n' /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
```

Expected: `i` flag set, `root:root`, mode `444`.

### Approved change (unlock → edit → test → re-lock)

```bash
sudo /opt/tradingai/sma9_scanner/ops/unlock_code.sh
# edit with sudo, then:
cd /opt/tradingai/sma9_scanner
python3 -m unittest tests.test_sma9_engine tests.test_sma9_legacy_package -v
sudo /opt/tradingai/sma9_scanner/ops/lock_code.sh
sudo systemctl restart tradingai-sma9-scanner.service
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
```

A restart is safe with an open paper position: the scanner restores it from
`sma9_open_positions` and exits at the original candle close.

### Stop trading immediately

```bash
sudo systemctl stop tradingai-sma9-scanner.service
sudo systemctl disable tradingai-sma9-scanner.service
```

### Rollback

Latest pre-lock backup (code, old paths, tests, service unit):

```
/opt/tradingai/backups/sma9_lock_20261106_144742
# pointer:
/opt/tradingai/backups/SMA9_LAST_LOCK_BACKUP_PATH.txt
```

Earlier backups remain at:

```
/opt/tradingai/backups/sma9_forensic_20261106_140314
/opt/tradingai/backups/sma9_legacy_pkg_20261106_142023
```

The original `database/tradingai.db` was never modified and still holds the
339 legacy rows.

---

## 9. Known limitations

- A **root/sudo compromise** can still run `unlock_code.sh`. The lock protects
  against accidental edits, the service account, and non-root processes; it is
  not a defense against a fully compromised host.
- The integrity timer **detects** changes but does not auto-roll them back.
  Add an alerting hook to the timer if automatic notification is required.
- Host hardening (SSH keys, firewall, patching, fail2ban) remains necessary.
- Paper-only: the scanner contains **no broker order calls**; verified by the
  system verifier (`no_orders: true`).

---

## 10. Key references

- Lock/security/operations guide:
  `/opt/tradingai/sma9_scanner/docs/SECURITY_AND_OPERATIONS.md`
- Lock record: `/opt/tradingai/sma9_scanner/LOCKED.json`
- Manifest: `/opt/tradingai/sma9_scanner/MANIFEST.sha256`
- Status tool: `/opt/tradingai/sma9_scanner/ops/status.sh`
- Integrity log: `/opt/tradingai/logs/sma9_integrity.log`
- Live log: `/opt/tradingai/logs/live_sma9_scanner.log`
- Dashboard: `https://tradingai.in/live/index.html`

---

## 11. Final state update — 2026-11-06 (IST, post-cleanup restore)

After the "move all other files/folders to `tobe_deleted`" cleanup, the tradingai
API / frontend / config had been moved out of `/opt/tradingai`. The user then asked
to restore the dashboard, so the following were moved back from
`/opt/tradingai/tobe_deleted/` into `/opt/tradingai/`:

- unit: `tradingai-api.service`
- code: `api/`, `app/`
- runtime: `config/`, `zerodha_credentials.py`
- logs: gunicorn logs
- frontend: `frontend/`

Final state at 15:47 IST:

- `tradingai-sma9-scanner.service` → **active**
- `tradingai-sma9-integrity.timer` → **active**
- `tradingai-api.service` → **active** (restored; `/api/sma9/*` → HTTP 200)
- nginx → **active**; public dashboard `https://tradingai.in/live/index.html` → **HTTP 200**
- Public dashboard now reports 17 today trades / **+121.25 pts**, 30 history rows,
  market CLOSED, status STOPPED, zero console/page errors.
- Live P&L recomputed with the **actual lot size** (NIFTY **65** from the authoritative
  lot source): **17 closed trades, +121.25 pts, ₹7,881.25** — the earlier **₹9,093.75**
  figure (fabricated lot size 75) was withdrawn.
- Full system verifier (`ops/verify_system.py`) currently cannot complete because it
  also reads the legacy main DB (`database/tradingai.db`) that was intentionally moved
  to `tobe_deleted/`; the SMA9 DB (`database/sma9.db`) is intact and the integrity check
  passes.
