# Scanner docs — one page per strategy

The VM runs **5 active paper scanners** plus the isolated real-order
`sma9_live` service described in [`SCANNERS.md`](../../SCANNERS.md). One
duplicate paper scanner (`sma9_trail`) is stopped and disabled but kept on
disk. Each page below describes one strategy in logical
terms: why it exists, exactly when it enters, exactly when it exits, what it
persists, and where its runtime pieces live.

Start with [`SCANNERS.md`](../../SCANNERS.md) for the cross-cutting material
(host, broker-gateway setup, timing, isolation model, data model,
API/dashboard map, operations runbooks). These pages do not repeat it; they
explain the strategy.

> **Paper scanners are read-only.** The five scanners in the table below
> simulate BUYs at the sampled option LTP in SQLite and have no broker write
> path. The separate `sma9_live` service is not part of this paper fleet and
> is governed by its own execution gates.

## Active scanners

| Scanner | Logic in one line | Cadence | Initial stop | Doc |
|---|---|---|---|---|
| `sma9` | Baseline: previous 5m close above SMA9 and forming candle open above SMA9 | 5 s | 5% of premium | [`sma9.md`](sma9.md) |
| `sma9_5min` | Isolated copy of `sma9` with aligned 5-minute polling | aligned 5 m | 5% of premium | [`sma9_5min.md`](sma9_5min.md) |
| `sma9_adx` | Previous close above SMA9 **and** ADX(14) > 30 **and** +DI > -DI on completed option candles | 5 s | 5% of premium, HWM-5% trail | [`sma9_adx.md`](sma9_adx.md) |
| `sma9_high` | `sma9` plus a live break of the previous candle high | 5 s | 5% of premium | [`sma9_high.md`](sma9_high.md) |
| `sma9_atr` | Same entry as `sma9`, stop scaled to the option's own ATR | 5 s | `0.70 × ATR14`, clamped 5–30% | [`sma9_atr.md`](sma9_atr.md) |

Stopped duplicate (service disabled, code/DB/page kept on disk until
explicitly re-enabled):

| Scanner | Logic in one line | Doc |
|---|---|---|
| `sma9_trail` | Rule-level duplicate of `sma9`; self-contained entry with a 5-point trail | [`sma9_trail.md`](sma9_trail.md) |

Retired strategies (stopped, disabled, kept only as archives):
[`retired.md`](retired.md).

## The families

**SMA9 + ADX family** — `sma9_adx`. Replaces the forming-open gate with
Wilder ADX(14) > 30 with +DI > -DI on completed option premium 5m bars, and exits on a 5%
initial stop ratcheted to HWM - 5%. See [`sma9_adx.md`](sma9_adx.md).

**Base SMA family** — `sma9`, `sma9_5min`, `sma9_high`. The original premium
scanner rules. The signal is computed on each option's own 5-minute premium
candles. Exit is a trail stop with a fixed 5% floor. `sma9_5min` changes only
the polling cadence: it samples once per aligned 5m boundary (+10 s) instead of
every 5 seconds, so its stop/trail is observed once per bar.

**Sampling variants** — The former `sma9_slope_atr` (renamed from
`sma9_1min_atr`) and `sma9_1min_poll` were retired on 2026-11-24; see
[`retired.md`](retired.md).

**Volatility-scaled stops** — `sma9_atr`.
Replace the fixed 5% floor with a stop derived from the
bought option's average true range, so the stop stays outside normal premium
noise on cheap contracts. These scanners also use that ATR distance as the
trail width, with no +5 activation and no breakeven lock.

**Self-contained trail family** — `sma9_trail` (stopped
duplicate). They own both entry and exit; the historical "consume the base
scanner's position" design is gone. The `consumed_base_trades` table is a
legacy artefact.

`sma9_5min` polls on an aligned 5m cadence, but keeps `sma9`'s sampled-LTP
stop/trail rules.

## Isolation contract

The five active paper scanners and the isolated `sma9_live` service share
nothing except the host, the read-only broker gateway daemon/socket/rate
limiter, the Flask API process and nginx. The two stopped trail duplicates keep
their own stacks on disk. Each stack has:

```
/opt/tradingai/<key>_scanner/          code (root-owned, read-only for locked trees)
/opt/tradingai/database/<key>.db       database (owned by the service user)
/opt/tradingai/logs/live_<key>_scanner.log
/etc/systemd/system/<unit>.service     own unprivileged user
/api/<slug>/*                          own API namespace
/live/<slug>/                          own dashboard
```

## Common timing (all eight SMA-family scanners)

| Constant | Value |
|---|---|
| Scanning starts | 09:00 IST |
| Exchange opens | 09:15 IST |
| First entry | 09:20 IST |
| Last entry | before 15:15 IST |
| Candle size | 5 minutes |
| Market close (status only) | 15:30 IST |

No scanner has a time-based exit. If neither the trail nor the stop fires, the
position stays open across candles and overnight. The 09:15 candle is never
entered. Between 09:00 and 09:15 the scanners poll and refresh quotes/status,
but that window is **warm-up only**: no entries are evaluated and no exits are
managed (`EXCHANGE_OPEN = 09:15`).

Four active paper scanners poll every 5 seconds. `sma9_5min` polls at each 5m
boundary +10 s but keeps `sma9`'s LTP-sampled stop/trail exits. The two stopped
trail duplicates and the isolated live scanner use 5-second polling when
enabled.
