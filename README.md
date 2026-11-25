# SMA9 SHORT — paper/shadow scanner

This branch contains only the new **paper/shadow** `sma9_short` strategy. It is
intentionally separate from `main` / `sma9-live-only-20261124` so the working
live-only snapshot is unchanged.

> No broker orders are placed. No OTP/TOTP handling is present. No credentials
> or secrets are stored here.

## Strategy

- Instrument: NIFTY options, read-only market data through the existing
  broker-gateway `KiteConnect` compatibility facade (`mStock` for scanner
  identity `sma9_short`).
- Contracts, evaluated independently:
  - CE: nearest ATM strike **+200**
  - PE: nearest ATM strike **−200**
- Entry: paper SHORT at the sampled live premium LTP when that leg's
  `LTP < SMA9`, where SMA9 is the mean of the last 9 completed 5-minute premium
  closes. The forming candle is never included in SMA9.
- One open position per leg. CE and PE may both be short at the same time.
- Initial stop: `round(entry * 1.05, 2)`.
- Trailing stop: track the lowest LTP since entry and ratchet the stop down to
  `round(lowest_ltp * 1.05, 2)`, never upward and never above the previous stop.
- A stop breach closes the short at the stop level:
  - `TRAIL_STOP_EXIT` after the stop has ratcheted
  - `STOP_LOSS_5PCT` otherwise
- Any position still open at 15:20 IST is flattened at the sampled LTP, with
  reason `EOD_15_20_FLAT`. A late scan after a restart uses the 15:20 candle
  open when the exact quote was missed.
- P&L is `entry_price - exit_price` in premium points.
- No target, candle-close or reverse-signal exit in the live loop.
- Entry window: 09:20–15:15 IST; at most one entry per 5-minute candle per leg.
- Poll interval: 5 seconds aligned to the wall clock.
- State is persisted in `/opt/tradingai/database/sma9_short.db`; restarts
  restore open shorts and their ratcheted stops.

## Contents

| Path | Purpose |
| --- | --- |
| `sma9_short_scanner/app/sma9_short_engine.py` | Pure engine: SMA9 evaluation, entry, stops, trail, P&L |
| `sma9_short_scanner/app/live_sma9_short_scanner.py` | 5-second paper scanner loop and SQLite persistence |
| `sma9_short_scanner/tests/test_sma9_short_engine.py` | Pure engine tests, including the 15:20 flat rule |
| `sma9_short_scanner/tests/test_live_sma9_short_scanner.py` | Scanner-level EOD exit tests with a temporary DB and fake feed |
| `app/api/sma9_short_api.py` | Read-only `/api/sma9-short/*` endpoints |
| `frontend/live/sma9-short/index.html` | Dashboard page |
| `systemd/tradingai-sma9-short-scanner.service` | Service unit |
| `docs/INTEGRATION.md` | Exact changes needed in the existing API/frontend/gateway files |
| `DEPLOY.md` | Deployment and verification notes |

## Local tests

```bash
cd sma9_short_scanner
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Expected: `Ran 5 tests ... OK`.

## Deployment status

Already deployed and enabled on the VM as
`tradingai-sma9-short-scanner.service`. See `DEPLOY.md` for verified endpoints.
