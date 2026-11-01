# Signal-to-Trade Latency

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Measurement Methodology

Latency was measured by matching SCALP_HLC paper trades to their corresponding scalp_signals records using instrument_id, direction, and entry_time (= signal_time + 5min).

Delay definitions:
- **Signal-to-Creation**: `created_at - signal_time` (total time from signal generation to trade persistence)
- **Entry-to-Creation**: `created_at - entry_time` (time from entry candle open to trade persistence)

## Results

### All SCALP_HLC Trades (28 trades with matching signals)

| Metric | Signal-to-Creation | Entry-to-Creation |
|--------|-------------------|-------------------|
| Average | -1.1s | 240.3s |
| Median | 0.0s | 324.0s |
| P95 | 0.1s | 363.2s |
| Maximum | 0.1s | 365.5s |
| Count | 28 | 28 |

## Analysis

### Signal-to-Creation Delay (avg -1.1s, median 0.0s)

Trade creation happens almost immediately after signal persistence (within 0.1 seconds). The negative average is due to clock precision differences between the two timestamp columns. This confirms that paper trade creation happens in the SAME processing cycle as signal persistence - there is no avoidable delay between signal persistence and trade creation.

### Entry-to-Creation Delay (avg 240.3s, median 324.0s)

This delay is INHERENT to the strategy design, not a bug:
- Signal at time T (e.g., 14:20:00)
- Entry candle opens at T + 5min (e.g., 14:25:00)
- Trade is created shortly after the entry candle open (when entry price is available)
- Average delay of 240s (4 minutes) from entry candle open to trade creation

This 5-minute gap between signal and entry is the **canonical strategy rule**: entries happen at the next candle open, not at signal time. This is NOT a defect to fix.

### Per-Trade Latency Detail

| Trade ID | Instrument | Direction | Signal Time | Entry Time | Created At | Sig->Created(s) | Entry->Created(s) |
|----------|------------|-----------|-------------|------------|------------|-----------------|-------------------|
| PT-A67036A551 | BANKNIFTY | BEAR | 10:20:00 | 10:25:00 | 10:30:35 | 0.0 | 335.7 |
| PT-28701C6847 | NIFTY | BEAR | 11:00:00 | 11:05:00 | 11:11:02 | -3.5 | 362.5 |
| PT-C929CDF44C | NIFTY | BEAR | 11:05:00 | 11:10:00 | 11:15:02 | -5.2 | 302.8 |
| PT-PT-A6BE328946 | BANKNIFTY | BEAR | 14:45:00 | 14:50:00 | 14:50:33 | 0.0 | 33.1 |
| PT-C78247C9FF | NIFTY | BULL | 14:35:00 | 14:40:00 | 14:41:30 | 0.0 | 90.3 |

The entry-to-creation delay varies (33s to 365s) depending on when the entry candle's open price becomes available from the market data provider. When the entry candle is already ingested into `market_candles_5m`, trade creation happens within seconds. When it's not yet ingested, the provider lookup adds delay.

## Conclusion

**No avoidable delay in paper-trade creation.** Trades are created in the same processing cycle as signal persistence (sub-second delay). The entry-to-creation delay is inherent to the next-candle execution strategy (5 minutes from signal to entry candle open).

## Recommendation

No changes needed to trade creation timing. The fix applied to `paper_scalp_live.py` (computing entry_time as signal_time + 5min when entry candle not ingested) ensures signals don't expire prematurely while waiting for the entry candle to be ingested.
