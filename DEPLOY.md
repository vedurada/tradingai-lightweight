# Deployment notes — SMA9 SHORT (paper)

## VM state

- Service: `tradingai-sma9-short-scanner.service` (enabled, active)
- Code: `/opt/tradingai/sma9_short_scanner/`
- Database: `/opt/tradingai/database/sma9_short.db`
- Log: `/opt/tradingai/logs/live_sma9_short_scanner.log`
- Service user: `sma9short` (group `ubuntu`)
- Scanner identity: `BROKER_GATEWAY_SCANNER=sma9_short`

The first startup loads the NFO instrument master through the broker gateway
and can take about a minute before the `SMA9 SHORT scanner ready` line appears.
After that, heartbeat rows are written every 5 seconds.

## Required environment

The scanner service must set:

```text
SMA9_SHORT_DB_PATH=/opt/tradingai/database/sma9_short.db
PYTHONPATH=/opt/tradingai/sma9_lib
BROKER_GATEWAY_SCANNER=sma9_short
```

`BROKER_GATEWAY_SCANNER` is essential. Without it the gateway defaults to the
Zerodha identity and the scanner cannot load instruments.

The mStock session remains operator-controlled. This code has no OTP/TOTP
handling and no daily auto-refresh. Manual checks on the VM:

```bash
sudo /usr/local/sbin/mstock_session.py --check
sudo /usr/local/sbin/broker-gateway probe --broker mstock
```

## Verified after deployment

- Unit tests: 5 passed on the VM.
- Python syntax and JSON config checks: passed.
- `systemctl is-active` for gateway, API, and short scanner: `active`.
- `GET /api/sma9-short/live-status` → HTTP 200, `status: IDLE_MARKET_CLOSED`
  during pre-market (expected).
- `GET /api/sma9-short/scanner-status` → HTTP 200, `strike_offsets:
  {"CE": 200.0, "PE": -200.0}`.
- `GET /api/sma9-short/open-positions` → HTTP 200, `count: 0`.
- `GET /api/live-atm?scanner=sma9-short` → HTTP 200. With ATM 25350 it returned
  CE strike 25550 and PE strike 25150, i.e. ATM+200 / ATM−200.
- `GET /live/sma9-short/` → HTTP 200.
- `GET /live/scalp/` contains
  `data-key="sma9-short" data-src="/live/sma9-short/"`.
- `GET /api/performance/daily?days=5` includes the `sma9_short` entry.
- `GET /api/live-atm?scanner=sma9` regression → HTTP 200 with unchanged ATM
  mapping.
- `GET /live/sma9/` regression → HTTP 200.

At pre-market the scanner heartbeat has `last_scan_at: null` and
`market_open: false`; the API reports `IDLE_MARKET_CLOSED`. The first live scan
after 09:15 IST will write the selected expiry and both option contracts to the
heartbeat.

## Contract selection check

A read-only check with ATM 25350 resolved:

```text
nearest_expiry 2026-12-01
CE target 25550.0 symbol NIFTY26D0125550CE token 47812
PE target 25150.0 symbol NIFTY26D0125150PE token 47781
```

These are the contracts the scanner itself will use. The pre-market
`/api/live-atm` fallback can show a farther-dated instrument from the master
until the scanner heartbeat contains the selected expiry; this is display-only
and matches the pre-existing behaviour of the `sma9` page.

## Rollback

```bash
sudo systemctl disable --now tradingai-sma9-short-scanner.service
```

Remove `/etc/systemd/system/tradingai-sma9-short-scanner.service` and reload
systemd if a full rollback is required. The live-only `sma9` service is not
modified by this branch's integration changes.
