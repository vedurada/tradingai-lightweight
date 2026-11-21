# sma9_5min

Isolated copy of `sma9` with one behavioural change: the runner polls on an
aligned 5-minute cadence (`POLL_SECONDS = 300`, `POLL_OFFSET_SEC = 10`) instead
of every 5 seconds.

- Strategy id: `sma9_5min`
- DB: `database/sma9_5min.db` (`SMA9_5MIN_DB_PATH` overrides)
- Log: `logs/live_sma9_5min_scanner.log`
- Service: `tradingai-sma9-5min-scanner.service`
- API: `/api/sma9-5min/*`
- Dashboard: `/live/sma9-5min/`

The A+B entry rule, 5% floor, 5-point trail, one-time BE lock, 09:20–15:15
entry window, nearest-expiry ATM contracts, CE/PE independence, and SQLite
state model are unchanged from `sma9`. Stop/trail state is observed once per
5-minute poll, not every 5 seconds.

Paper only. No broker order path exists. See `docs/scanners/sma9_5min.md` for
the full rule and runtime contract.
