# Retired scanners

These strategies are **stopped and disabled**. Their code trees, databases and
(in most cases) dashboards remain on disk as archives; they are not started at
boot, are not in `refresh_token.sh`, and are not part of the active scanner
count. Do not restart them to "compare" — the DBs are frozen snapshots and the
code is not maintained.

| Scanner | What it did | Why it was retired | Archive |
|---|---|---|---|
| `no_sma` | Previous-5m-high breakout on option premium; no SMA filter | Replaced by `sma9_1min_poll` on 2026-11-19, then retired with it on 2026-11-24 | `database/no_sma.db`, `/live/no-sma/`, API `/api/no-sma/*` |
| `no_sma_trail` | Previous-high breakout with a trailing exit | Replaced by `sma9_slope_atr` on 2026-11-19; the ATR stop/trail handled cheap premiums better | `database/no_sma_trail.db`, `/live/no-sma-trail/`, API `/api/no-sma-trail/*` |
| `sma9_1min_atr` | SMA9 A/B entry with ATR stop/trail, later upgraded to 5s + ATR-only trail + rising SMA9 | Renamed to `sma9_slope_atr` on 2026-11-20; DB history copied to the new DB, old service/API/page stopped and disabled | `database/sma9_1min_atr.db`, code `sma9_1min_atr_scanner/`, `/live/sma9-1min-atr/` |
| `sma9_slope_atr` | Rising-SMA9 SMA9 entry with an ATR-scaled stop and ATR-only trail, 5s poll | Its open paper position was closed at the sampled LTP on 2026-11-24 (`RETIREMENT_PAPER_CLOSE`, P&L 0.00), then the service, code, DB, API namespace and page were removed | `archives/sma9_slope_atr_20261124/`, API `/api/sma9-slope-atr/*` and `/live/sma9-slope-atr/` (404) |
| `sma9_1min_poll` | SMA9 A+B entry at a 5s cadence with an ATR-scaled stop and ATR-only trail, no regime gate | Retired on 2026-11-24 as a redundant ATR variant; no open position at retirement; service, code, DB, API namespace and page removed | `archives/sma9_1min_poll_20261124/`, API `/api/sma9-1min-poll/*` and `/live/sma9-1min-poll/` (404) |
| `green15` | Buy when the forming 15-minute candle was green (LTP > open), exit at that candle's close | Same-candle exit with no stop/target; superseded by the 5-minute SMA9 family | `database/green15.db`, code `green15_scanner/` |
| `atm` | Buy both ATM CE and PE at every 5-minute candle open, exit at that candle's close | Mechanical same-candle strategy with no filter; kept only as a research baseline | `database/atm.db`, code `atm_scanner/` |
| `sma9_avg` | SMA9 entry plus `LTP > average of last 3 completed closes`, trail exit | Extra confirmation added no durable edge over `sma9` | `database/sma9_avg.db`, code `sma9_avg_scanner/` |
| `sma3`, `sma3_high`, `sma3_trail`, `sma3_high_trail` | The SMA3 family (base, HIGH, trail, HIGH-trail) | Replaced by the SMA9 family in the 2026-11 scanner consolidation; code and DBs removed from the VM | legacy docs only |
| `sma20`, `sma20_high`, `sma20_trail`, `sma20_high_trail` | The SMA20 family (base, HIGH, trail, HIGH-trail) | Same consolidation; too slow for the intraday option moves being traded | legacy docs only |

## What "retired in place" means

- The systemd unit is **stopped and disabled**; it is not in the boot wants
  directory and not in `ALL_UNITS`.
- The database is **not deleted** and is not written any more.
- The dashboard page and API namespace may remain so old links still resolve
  (`no_sma`, `no_sma_trail`); `green15`, `sma9_1min_atr`, `sma9_slope_atr` and
  `sma9_1min_poll` namespaces return 404.
- The performance report no longer lists `no_sma` / `no_sma_trail` /
  `sma9_slope_atr` / `sma9_1min_poll`; their history stays in the archived DBs
  for audit. `sma9_1min_atr` was replaced by the `sma9_slope_atr` key on
  2026-11-20, and that key was retired on 2026-11-24.

## Replacing them

| Retired | Active replacement |
|---|---|
| `no_sma` | none (its replacement `sma9_1min_poll` was retired 2026-11-24) |
| `no_sma_trail` | none (research archive) |
| `sma9_1min_atr` | none (renamed to `sma9_slope_atr`, later retired) |
| `sma9_slope_atr` | none (retired 2026-11-24) |
| `sma9_1min_poll` | `sma9_atr` (same ATR exits, with a daily regime gate) |
| `sma3*` / `sma20*` | `sma9*` family |
| `green15`, `atm`, `sma9_avg` | none (research archives) |

If you need to resurrect one, treat it as a new deployment: re-enable the unit,
confirm its user and DB ownership, add it to `refresh_token.sh`, and re-check
the Kite rate-limit budget. Do not silently re-enable an archived unit.
