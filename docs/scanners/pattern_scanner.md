# `pattern_scanner` — candlestick patterns on NIFTY spot

**One line:** when a completed NIFTY **spot** 5-minute candle matches a known
bullish or bearish pattern, buy the ATM CE (bullish) or ATM PE (bearish) and
manage the exit with a **premium ATR(14) stop and ATR-width trail only**.

- **Status:** active
- **Cadence:** aligned 5-minute polls at `HH:MM:10` (`:00`, `:05`, `:10`, …);
  this is the only scanner that does not poll every 5 seconds
- **Stop:** premium ATR(14): `0.70 × ATR`, clamped to 5–30% of entry; 10% fallback
- **Exit data:** completed 5-minute option OHLC bars, shared with the backtest
- **First reported day:** 2026-11-18 (older rows are excluded from reports)

## Why it exists

Every scanner derives its exit levels from **option premium**. `pattern_scanner`
is the only strategy whose *signal* reads the underlying directly: patterns are
detected on NIFTY spot candles, while the stop and trail are computed from the
bought option's own premium ATR. It answers a different question — "does the
index pattern predict the option move?" — but its exit mechanics now match the
ATR premium scanners.

It is also the only scanner that is directional rather than independent-leg:
a bullish pattern buys CE, a bearish pattern buys PE. It is long-only on both
sides; there is no short CE and no short PE.

## Entry

- **Signal source:** completed NIFTY spot 5-minute candles only (the forming
  candle is never used for a signal). The runner wakes once per 5m boundary at
  +10 s, so each poll uses the bar that has just completed.
- **Patterns:** roughly 37 bullish and 37 bearish candlestick patterns.
- **Mapping:** bullish → long ATM CE (nearest weekly expiry); bearish → long
  ATM PE.
- **Entry price:** the chosen option's **LTP sampled at the aligned poll** that
  closes the spot candle — not the spot close, and never a stale or opposite-leg
  quote. Quotes older than `MAX_QUOTE_AGE_SEC` (20 s) are rejected, so a missed
  quote skips the entry rather than inventing a price.
- **Entry timestamp:** the actual poll time, not the signal candle's start.
- **Scan start:** the live runner starts at 09:00 IST to warm the feed and
  status, but 09:00–09:15 is warm-up only: its candle buffer ignores every tick
  before 09:15, and its premium exit manager ignores option bars starting before
  09:15 too. No synthetic pre-open candles are created and no pre-open exit can
  fire; the first completed signal candle is 09:15 and the first possible entry
  is at the 09:20 poll.
- **One per key:** at most one active position per `pattern_name:instrument`.
- **Entry bar skip:** a position entered at a bar-close poll is first managed
  from the next poll's completed bar, never from its own entry bar.
- No new entries at or after 15:15 IST.

## Exit

**Premium ATR only.** No fixed spot stop, no spot trail, no breakeven lock, and
no direction-dependent arithmetic: both long CE and long PE profit when the
option premium rises. At each aligned poll the runner fetches the **previous
completed 5-minute OHLC bar** for every current ATM option and every active
position's option, then calls the same `evaluate_bar()` helper used by the
5-minute backtest. Sampled option LTPs are used for entries only; NIFTY spot
ticks never manage an exit.

At entry, ATR(14) is computed from completed 5-minute bars of the exact bought
option. The final forming bar is excluded, so the stop is knowable at entry
time. If fewer than 15 completed bars exist, the fallback 10% distance is used.

```
distance = 0.70 * premium_atr
distance = max(distance, 0.05 * entry_premium)
distance = min(distance, 0.30 * entry_premium)
fallback_distance = 0.10 * entry_premium

initial_stop = round(entry_premium - distance, 2)   # STOP_LOSS_ATR

# Once per completed 5m option bar, via OptionPosition.evaluate_bar()
hwm = max(hwm, bar_high)
candidates = []
if hwm > entry_premium:
    trail_stop = max(current_stop, hwm - distance)  # ATR_TRAIL ratchet
    if bar_high <= trail_stop or bar_low <= trail_stop:
        candidates.append((trail_stop, TRAIL_STOP_EXIT))
if bar_low <= initial_stop:
    candidates.append((bar_low, STOP_LOSS_ATR))
exit_px, reason = min(candidates, key=price)        # conservative proxy
```

- The trail activates as soon as the premium makes a new high above entry —
  there is no fixed +5 activation threshold. It can never ratchet down.
- **Exit price:** the shared helper chooses the lower of the adverse completed
  bar's low (initial-stop fill) and the ratcheted trail level. This is the
  conservative 5m OHLC proxy used by the backtest, not the sampled poll LTP.
- Only the position's **own option bar** can manage it. After an ATM reband,
  the runner still fetches bars for every instrument with an open position, so
  an older strike keeps receiving its own exits.
- Forming bars are never evaluated: the runner requests the bar whose start is
  the previous 5m boundary and rejects a mismatched timestamp; the engine also
  refuses a bar whose end is after the current poll time.
- No target, no candle-close exit besides the completed-bar exit check, and no
  session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Live runner | `/opt/tradingai/scripts/pattern_scanner_live.py` |
| Engine | `/opt/tradingai/app/research/pattern_scanner.py` |
| Poll constants | `POLL_INTERVAL_SEC = 300`, `POLL_OFFSET_SEC = 10` |
| User / unit | `ubuntu` / `pattern-scanner-live.service` |
| Working dir / PYTHONPATH | `/opt/tradingai` |
| DB | `/opt/tradingai/database/tradingai.db` |
| Tables | `pattern_scanner_positions`, `pattern_scanner_stop_changes` |
| Status file | `/opt/tradingai/data/pattern_scanner_status.json` |
| Log | `/opt/tradingai/logs/pattern_scanner_live.log` |
| API | `/api/pattern_scanner/*` (own namespace, not the 9-endpoint set) |
| Dashboard | `/live/pattern_scanner/` |
| Performance report | key `pattern_scanner`, label `Pattern`, from 2026-11-18 |

Unlike the premium scanners, it shares the main `app/` tree and the `ubuntu`
user. Its log line is `[ps-live] Kite connected...` followed by
`NFO instruments cached: <n> rows`.

## API

```
GET  /api/pattern_scanner/status
GET  /api/pattern_scanner/instruments
GET  /api/pattern_scanner/active-trades
GET  /api/pattern_scanner/closed-trades
GET  /api/pattern_scanner/pattern-summary
GET  /api/pattern_scanner/history
POST /api/pattern_scanner/start
POST /api/pattern_scanner/stop
```

The `start`/`stop` POSTs are ops-only and wrap `systemctl`; the dashboard does
not use them.

## State and restart behaviour

`stop_price`, `stop_loss`, `hwm`, `lwm`, `trail_distance`, `stop_distance_pct`,
`stop_source`, `atr_at_entry`, `trailing_update_cnt`, `mfe_points` and
`mae_points` are written on every trail/MFE change and again on exit. The old
`initial_sl`, `entry_spot` and `be_locked` columns remain for compatibility but
no longer drive exits. Each ratchet is appended to
`pattern_scanner_stop_changes` with method `ATR_TRAIL`; the initial stop uses
`ATR_STOP`. Open positions are reloaded on startup, so a restart resumes the
premium trail correctly.

Legacy open rows written by the old spot-stop engine are migrated on load:
their spot-valued `hwm`/`lwm`/`stop_loss` are discarded and replaced with a
premium fallback stop derived from `entry_price`, so a restart never applies
spot levels to a premium ATR exit.

On every 5m poll the runner quotes the current ATM CE/PE **and** every
instrument with an active position, so an older strike still gets its own
completed bar. Quotes are recorded before the spot tick for entry pricing;
the completed option bars are appended and evaluated via `evaluate_bar()`
before spot candle completion triggers a new entry. The status file reports
`poll_interval_sec = 300`, `poll_alignment = 5m_boundary_plus_10s` and
`exit_data = completed_5m_option_ohlc`, so a stale 5s deployment is obvious.

## Ops

```bash
systemctl status pattern-scanner-live
tail -f /opt/tradingai/logs/pattern_scanner_live.log
curl -s https://tradingai.in/api/pattern_scanner/status
```

The token is read once at process start. `pattern-scanner-live` is in
`ALL_UNITS` of `refresh_token.sh`; a token refresh without a restart would
leave it logging `Incorrect api_key or access_token` (this happened on
2026-11-19 before the unit was added to the restart list).
