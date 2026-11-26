# SMA9 HIGH - Security, Lock & Operations

- Code root: `/opt/tradingai/sma9_high_scanner` (root-owned, read-only, immutable)
- Service: `tradingai-sma9-high-scanner.service`, runs as unprivileged user `sma9high`
- DB: `/opt/tradingai/database/sma9_high.db`
- Libs: `/opt/tradingai/sma9_high_lib` (root-owned, non-writable)
- Integrity timer: `tradingai-sma9-high-integrity.timer`

## Approved change procedure

```
sudo /opt/tradingai/sma9_high_scanner/ops/unlock_code.sh
# edit + test
sudo /opt/tradingai/sma9_high_scanner/ops/lock_code.sh
sudo systemctl restart tradingai-sma9-high-scanner.service
```

## Verification

```
sudo /opt/tradingai/sma9_high_scanner/ops/verify_integrity.sh
python3 /opt/tradingai/sma9_high_scanner/ops/verify_system.py
```
