# Broker Gateway — connect any broker without changing scanners

The scanners still import `KiteConnect` and call only four read-only methods:

```text
set_access_token()
instruments(exchange)
quote(symbols)
historical_data(token, start, end, interval)
```

The broker gateway satisfies those calls through a Kite-compatible shim. Broker
selection is configuration, not scanner code.

## Components

```text
scanner (unchanged)
  -> kiteconnect.KiteConnect shim
      -> Unix socket /run/tradingai/broker_gateway.sock
          -> root-owned gateway daemon
              -> broker adapter: zerodha | mstock | <future>
                  -> root-only /opt/tradingai/secrets/<broker>.env
```

- The daemon runs as `root`, so scanner users never read broker secrets.
- The socket is `660 root:ubuntu`; scanner users are in `ubuntu`.
- The shim exposes no `place_order`, `modify_order`, or `cancel_order`.
- All fills remain simulated in each scanner's own SQLite database.

## Install

```bash
sudo bash scripts/ops/install_broker_gateway.sh /path/to/tradingai_sync
```

This installs code, config, the CLI, the systemd unit, and a `.pth` file that
puts the shim on every Python process's path. It does **not** restart scanners.

## Select a broker

```bash
sudo broker-gateway adapters
sudo broker-gateway status
sudo broker-gateway use --scanner sma9_atr --broker mstock
sudo systemctl restart tradingai-sma9-atr-scanner
```

Config lives at `/opt/tradingai/broker_gateway/config/scanners.json` and
contains no secrets. Default is `zerodha`, so existing scanners are unchanged
until explicitly switched.

## Add another broker

1. Add `broker_gateway/adapters/<name>.py` implementing `instruments`, `quote`,
   and `historical_data`.
2. Register it in `broker_gateway/adapters/__init__.py`.
3. Store credentials in `/opt/tradingai/secrets/<name>.env` (`600 root:root`).
4. Run `sudo broker-gateway probe --broker <name>`.

No scanner file changes.

## Verify

```bash
sudo broker-gateway probe --broker mstock
sudo broker-gateway probe --broker zerodha
sudo journalctl -u tradingai-broker-gateway -n 50
```

Restart only the scanner whose broker was changed; other scanners keep running.
