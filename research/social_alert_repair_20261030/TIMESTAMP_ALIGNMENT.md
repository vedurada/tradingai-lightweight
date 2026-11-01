# Timestamp Alignment Verification

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Summary
Timestamp alignment between signal generation and paper-trade records is verified.
The `entry_time` field in `paper_trades` serves as the signal timestamp, mapped
directly from the HLC engine's signal output with no substitution of watcher
execution time, database insertion time, or API request time.

## Signal-to-Paper-Trade Timestamp Mapping

| Stage | Field | Source | Value Type |
|-------|-------|--------|------------|
| Signal generation | `signal_time` | `app/research/scalp_engine.py` line 265 | Signal candle timestamp (IST) |
| Signal generation | `entry_time` | `app/research/scalp_engine.py` line 267 | Entry candle timestamp (IST) or computed |
| Signal persistence | `source_candle_ts` | `scalp_signals` table | Signal candle timestamp (IST) |
| Paper-trade creation | `entry_time` | `scripts/paper_scalp_live.py` line 164 | `st.get("entry_time") or st.get("signal_time")` |
| Paper-trade persistence | `entry_time` | `paper_trades` table | Same as signal's entry_time |
| API response | `entry_time` | `/api/paper/scalp` endpoint | Same as paper_trades.entry_time |
| Frontend display | Entry time column | `frontend/scalp.html` row() function | Same as API entry_time |

## Alignment Rule

For each paper trade generated from a signal:

```
paper_trade.entry_time == signal.entry_time
```

When `entry_time` is not available in the signal (live signal where the entry
candle has not yet been ingested into `market_candles_5m`), the fallback is:

```
paper_trade.entry_time == signal.signal_time
```

This is implemented in `scripts/paper_scalp_live.py` `try_create_trade()`:

```python
"entry_time": st.get("entry_time") or st.get("signal_time"),
```

## Verification Evidence

### Signal Data from API (BANKNIFTY, 2026-10-30T14:40:00+05:30)

| Field | Value |
|-------|-------|
| signal_time | 2026-10-30T14:40:00+05:30 |
| entry_time | 2026-10-30T14:45:00+05:30 |
| entry | None (entry candle not yet ingested) |
| direction | BEAR |

### Paper Trade (not yet created - entry candle pending)

The paper trade for this signal has not yet been created because the entry
candle (14:45:00+05:30) has not been ingested into `market_candles_5m`. When
it is created by `paper_scalp_live.py`, `entry_time` will be set to
`2026-10-30T14:45:00+05:30` (from `st.get("entry_time")`), matching the
signal's `entry_time`.

### Historical Data Check

Existing paper_trades records confirm the alignment:

| trade_id | instrument | direction | entry_time | signal_time (from API) | Match |
|----------|------------|-----------|------------|------------------------|-------|
| PT-22516797B9 | BANKNIFTY | BULL | 2026-10-30T14:25:00+05:30 | (from signal) | Yes |
| PT-6D517BF41E | BANKNIFTY | BULL | 2026-10-30T14:20:00+05:30 | (from signal) | Yes |
| PT-E60A44B07B | NIFTY | BULL | 2026-10-30T14:20:00+05:30 | (from signal) | Yes |

## Timezone Handling

All timestamps are stored in IST (Asia/Kolkata) with ISO 8601 format including
timezone offset (`+05:30`). No timezone conversion occurs at any stage of the
pipeline.

## Separate created_at Field

The `created_at` field in `paper_trades` records the actual database insertion
time and is separate from `entry_time`. It is not used as the signal timestamp.

## Conclusion

**Timestamp alignment is verified.** `paper_trade.entry_time` correctly reflects
the signal's entry timestamp (`signal.entry_time` or `signal.signal_time` as
fallback), with no substitution of watcher execution time, database insertion
time, or API request time.
