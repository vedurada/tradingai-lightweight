# TradingAI — `sma9_live` only

This repository is a curated source snapshot of the **one working real-order
service**: the isolated `sma9_live` scanner and the mStock broker gateway it
uses. It intentionally contains no paper scanners, research archives,
dashboards/API, or Zerodha authentication code.

The deployed VM is a file-copy installation under `/opt/tradingai`. This branch
is the source of truth for those files; pushing it does **not** restart or
redeploy any service.

## Contents

| Path | Purpose |
|------|---------|
| `scripts/sma9_live_scanner/app/` | Signal engine, LTP/quote feed, and risk-controlled order execution |
| `scripts/sma9_live_scanner/ops/` | systemd units for dry-run and armed operation |
| `broker_gateway/` | Shared read-only market-data daemon plus the gated mStock order path |
| `broker_gateway/compat/kiteconnect.py` | Read-only socket facade for `from kiteconnect import KiteConnect`; not Zerodha auth |
| `broker_gateway/config/scanners.json` | mStock-only broker alias map |
| `scripts/ops/` | mStock session, key rotation, gateway install, and pre-market check |
| `tests/` | Focused execution and gateway tests |
| `requirements.txt` | Python dependencies used by the deployment |

## Live trading contract

These are the invariants of the armed service; the tests cover the critical
parts:

- **Broker:** mStock **Type A** only. No Zerodha/Kite auth, token exchange, or
  OTP/TOTP handling lives in the scanner.
- **Order type:** `MARKET` for both entry and exit. There is no price collar;
  `SMA9_LIVE_PRICE_COLLAR_PCT=0` disables the client-side LTP gate entirely.
- **Lot size:** resolved per contract from mStock's instrument master; there is
  no static lot-size assumption in the armed unit.
- **Daily cap:** disabled (`SMA9_LIVE_MAX_ORDERS_PER_DAY=0` means unlimited).
- **BUY collar:** removed; `SMA9_LIVE_PRICE_COLLAR_PCT=0` in both units, so no
  sampled-LTP price gate rejects an entry.
- **Exits:** only the 5% initial stop loss (`STOP_LOSS_5PCT`) and the trailing
  stop (`TRAIL_STOP_EXIT`). No candle-close, target, time-based or
  restart-recovery exit exists.
- **Kill switch:** `SMA9_LIVE_KILLED=1` or the operator-created kill file
  `/opt/tradingai/run/sma9_live.KILL` stops trading. The service cannot remove
  the file itself.
- **Position control:** at most one open position per leg; a restart restores
  the saved high-water mark/stop and leaves exits to the two stop conditions.
- **Arming:** `SMA9_LIVE_EXECUTOR=mstock`, `SMA9_LIVE_ORDERS_ENABLED=true`,
  and `SMA9_LIVE_ARM_REAL_ORDERS=ARMED` must all be set. The default unit is
  dry-run and disarmed.
- **Retries:** bounded retries only for **terminal, broker-confirmed no-fill**
  outcomes, with a new `rN` client tag and an explicit `retry_of` pointer.
  Ambiguous outcomes are never retried by default
  (`SMA9_LIVE_RETRY_AMBIGUOUS` unset/false).
- **Reconciliation:** read-only order-status polling confirms fills.
- **Gateway isolation:** the daemon, socket and rate limiter are shared, but
  `BROKER_GATEWAY_SCANNER=sma9live` in the unit keeps alias selection isolated
  to this scanner.
- **Secrets:** mStock API key, client id, password and daily access token live
  only in root-only `/opt/tradingai/secrets/mstock.env` (or equivalent env
  vars). Nothing in this repository contains credentials or keys.

## Quick checks

```bash
python3 -m pytest -q \
  tests/test_sma9_live_execution.py \
  tests/test_broker_gateway_freshness.py \
  tests/test_broker_gateway_orders.py \
  tests/test_broker_gateway_quote_bars.py \
  tests/test_broker_gateway_quote_freshness.py \
  tests/test_broker_gateway_quote_safety.py \
  tests/test_broker_gateway_socket_backlog.py
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for installation, arming, session refresh,
and kill-switch procedures.
