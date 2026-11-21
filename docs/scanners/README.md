# Scanner docs — one page per strategy

The VM runs **8 independent paper scanners**. Each page below describes one
strategy in logical terms: why it exists, exactly when it enters, exactly when
it exits, what it persists, and where its runtime pieces live.

Start with [`SCANNERS.md`](../../SCANNERS.md) for the cross-cutting material
(host, broker-gateway setup, timing, isolation model, data model,
API/dashboard map, operations runbooks). These pages do not repeat it; they
explain the strategy.

> **Paper trading only.** No scanner has a broker write path. Entries are
> simulated BUYs at the sampled option LTP in SQLite; `pattern_scanner` exits use
> the documented conservative completed-5m OHLC proxy shared with its backtest.

## Active scanners

| Scanner | Logic in one line | Cadence | Initial stop | Doc |
|---|---|---|---|---|
| `sma9` | Baseline: previous 5m close above SMA9 and forming candle open above SMA9 | 5 s | 5% of premium | [`sma9.md`](sma9.md) |
| `sma9_high` | `sma9` plus a live break of the previous candle high | 5 s | 5% of premium | [`sma9_high.md`](sma9_high.md) |
| `sma9_1min_poll` | Same A+B entry as `sma9`, with `sma9_atr` ATR stop/trail | 5 s | `0.70 × ATR14`, clamped 5–30% | [`sma9_1min_poll.md`](sma9_1min_poll.md) |
| `sma9_atr` | Same entry as `sma9`, stop scaled to the option's own ATR | 5 s | `0.70 × ATR14`, clamped 5–30% | [`sma9_atr.md`](sma9_atr.md) |
| `sma9_5s_atr` | Rising-SMA9 entry + `sma9_atr` stop and ATR-only trail | 5 s | `0.70 × ATR14`, clamped 5–30% | [`sma9_5s_atr.md`](sma9_5s_atr.md) |
| `sma9_trail` | Self-contained `sma9` entry with a 5-point trailing exit | 5 s | 5% of premium | [`sma9_trail.md`](sma9_trail.md) |
| `sma9_high_trail` | Self-contained `sma9_high` entry with a 5-point trailing exit | 5 s | 5% of premium | [`sma9_high_trail.md`](sma9_high_trail.md) |
| `pattern_scanner` | Candlestick pattern on NIFTY **spot** → long ATM CE (bullish) or PE (bearish), exits on premium ATR from completed 5m option bars | aligned 5 m | `0.70 × ATR14`, clamped 5–30% | [`pattern_scanner.md`](pattern_scanner.md) |

Retired strategies (stopped, disabled, kept only as archives):
[`retired.md`](retired.md).

## The families

**Base SMA family** — `sma9`, `sma9_high`. The original premium scanners. The
signal is computed on each option's own 5-minute premium candles. Exit is a
trail stop with a fixed 5% floor.

**Sampling variants** — `sma9_1min_poll` keeps its original identity but now
polls every 5 seconds. `sma9_5s_atr` was renamed from `sma9_1min_atr` and also
samples every 5 seconds with a rising-SMA9 filter.

**Volatility-scaled stops** — `sma9_atr`, `sma9_5s_atr`, `sma9_1min_poll`,
`pattern_scanner`. Replace the fixed 5% floor with a stop derived from the
bought option's average true range, so the stop stays outside normal premium
noise on cheap contracts. These scanners also use that ATR distance as the
trail width, with no +5 activation and no breakeven lock.

**Self-contained trail family** — `sma9_trail`, `sma9_high_trail`. They own
both entry and exit; the historical "consume the base scanner's position"
design is gone. The `consumed_base_trades` table is a legacy artefact.

**Spot-signal, premium-exit** — `pattern_scanner`. The only scanner whose
*entry signal* comes from the NIFTY index; its stop and trail are computed from
the bought option's premium ATR. It is also the only one that can buy PE for a
bearish signal instead of evaluating CE and PE independently. It is the only
scanner on an aligned 5-minute poll cadence, with exits evaluated from the
previous completed 5m option OHLC bar so live matches the 5m backtest.

## Isolation contract

The 7 premium scanners share nothing except the host, the read-only broker
gateway, the Flask API process and nginx. Each has:

```
/opt/tradingai/<key>_scanner/          code (root-owned, read-only for locked trees)
/opt/tradingai/database/<key>.db       database (owned by the service user)
/opt/tradingai/logs/live_<key>_scanner.log
/etc/systemd/system/<unit>.service     own unprivileged user
/api/<slug>/*                          own API namespace
/live/<slug>/                          own dashboard
```

`pattern_scanner` shares the `app/` tree and the `ubuntu` user, but has its own
service, status file, tables and dashboard.

## Common timing (all 8)

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
managed (`EXCHANGE_OPEN = 09:15`). `pattern_scanner` ignores pre-09:15 ticks in
its candle buffer and pre-09:15 bar closes in its premium exit manager.

Seven scanners poll every 5 seconds. `pattern_scanner` is the exception: it
polls at each 5m boundary +10 s, uses that poll's option LTP only for entries,
and evaluates exits once from the previous completed 5m option OHLC bar via the
same `evaluate_bar()` helper used by the backtest.
