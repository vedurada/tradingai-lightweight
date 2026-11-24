# Deploying `sma9_live` (mStock only)

This repository is a source snapshot for the file-copy deployment at
`/opt/tradingai`. There is no git checkout on the VM. The commands below are
run on the VM as `ubuntu` with `sudo` where noted; they describe how the
current deployment is assembled, not an automatic deploy step.

## Layout

```
/opt/tradingai/
  sma9_live_scanner/            # scanner source from this branch
  broker_gateway/               # gateway source from this branch
  database/sma9_live.db         # scanner state (writable by sma9live)
  logs/live_sma9_live_scanner.log
  run/sma9_live.KILL            # operator-created kill file only
  secrets/mstock.env            # root-only 0600; never in git
```

Services:

- `tradingai-broker-gateway.service` — root, shared socket/daemon and rate limiter.
- `tradingai-sma9-live-scanner.service` — dry-run, disarmed default.
- `tradingai-sma9-live-scanner.armed.service` — the armed real-order unit.
- `tradingai-token-check.service` — 08:45 IST read-only pre-market mStock probe.

## Install / refresh source

```bash
# From a copy of this branch on the VM:
sudo scripts/ops/install_broker_gateway.sh /path/to/this/repo
sudo install -d -m 755 -o root -g root /opt/tradingai/sma9_live_scanner
sudo cp -a scripts/sma9_live_scanner/. /opt/tradingai/sma9_live_scanner/
sudo chown -R root:root /opt/tradingai/sma9_live_scanner
sudo find /opt/tradingai/sma9_live_scanner -type d -exec chmod 755 {} +
sudo find /opt/tradingai/sma9_live_scanner -type f -exec chmod 644 {} +

sudo install -m 644 -o root -g root \
  scripts/sma9_live_scanner/ops/tradingai-sma9-live-scanner.service \
  /etc/systemd/system/
sudo install -m 644 -o root -g root \
  scripts/sma9_live_scanner/ops/tradingai-sma9-live-scanner.armed.service \
  /etc/systemd/system/

sudo systemctl daemon-reload
```

`install_broker_gateway.sh` copies `broker_gateway/config/scanners.json` too.
Verify the alias map is mStock-only:

```bash
sudo broker-gateway status
sudo broker-gateway adapters   # should list only: mstock
sudo cat /opt/tradingai/broker_gateway/config/scanners.json
```

The scanner resolves `from kiteconnect import KiteConnect` through
`broker_gateway/compat/kiteconnect.py`, a read-only socket facade. It is not a
Zerodha login/token client.

## mStock secrets and session

Secrets are never committed and never passed on a command line. Store them in
`/opt/tradingai/secrets/mstock.env` with mode `0600`, owner `root:root`:

```bash
sudo install -d -m 700 -o root -g root /opt/tradingai/secrets
sudo /usr/local/sbin/rotate_mstock_key.sh          # prompts hidden for all values
```

To create/verify the daily session (OTP/TOTP is prompted and never stored or
printed by the operator script):

```bash
sudo /usr/local/sbin/mstock_session.py --mode totp   # or --mode otp
sudo /usr/local/sbin/mstock_session.py --check
sudo broker-gateway probe --broker mstock
sudo /usr/local/sbin/premarket_token_check.sh       # read-only, safe to rerun
```

The scanner itself contains no OTP/TOTP handling and never reads the secret
file. mStock tokens are refreshed manually; nothing in this repo automates an
expired-token refresh.

## Run modes

Dry run (default unit):

```bash
sudo systemctl disable --now tradingai-sma9-live-scanner.armed.service 2>/dev/null || true
sudo systemctl enable --now tradingai-sma9-live-scanner.service
```

Armed real orders:

```bash
sudo systemctl disable --now tradingai-sma9-live-scanner.service
sudo systemctl enable --now tradingai-sma9-live-scanner.armed.service
sudo systemctl status tradingai-sma9-live-scanner.armed.service --no-pager
sudo journalctl -u tradingai-broker-gateway -n 50 --no-pager
```

Armed settings are fixed in the unit: `SMA9_LIVE_EXECUTOR=mstock`,
`SMA9_LIVE_ORDERS_ENABLED=true`, `SMA9_LIVE_ARM_REAL_ORDERS=ARMED`,
`SMA9_LIVE_PRODUCT=MIS`, `SMA9_LIVE_PRICE_COLLAR_PCT=1.0`, no daily cap
(`SMA9_LIVE_MAX_ORDERS_PER_DAY=0`), lot size from mStock master, and bounded
retries for terminal broker-confirmed no-fill only. Leave
`SMA9_LIVE_RETRY_AMBIGUOUS` unset/false.

## Kill switch

The gateway service and scanner cannot remove the kill file. To halt trading:

```bash
sudo touch /opt/tradingai/run/sma9_live.KILL
```

To resume, an operator removes it explicitly and restarts the armed unit:

```bash
sudo rm /opt/tradingai/run/sma9_live.KILL
sudo systemctl restart tradingai-sma9-live-scanner.armed.service
```

`SMA9_LIVE_KILLED=1` in the environment is an equivalent stop flag.

## Verification checklist

- `broker-gateway adapters` lists only `mstock`.
- `broker-gateway probe --broker mstock` passes profile, NFO master, and quote.
- `systemctl is-active tradingai-broker-gateway tradingai-sma9-live-scanner.armed.service`.
- Log shows `executor=mstock`, `dry_run=False`, `armed=True`, `killed=False`,
  collar `1.0`, max orders `0`, `retry_enabled=true`,
  `retry_ambiguous=false`.
- `SMA9_LIVE_DB_PATH` database shows no unexpected open positions.

Do not change other scanner units or the shared gateway rate limiter when
working only on `sma9_live`.
