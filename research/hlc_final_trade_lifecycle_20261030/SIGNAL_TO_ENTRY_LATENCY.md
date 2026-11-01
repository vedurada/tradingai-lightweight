# Signal to Entry Latency

## Date
2026-10-30

## Signal-to-Creation Delay: ~0 seconds (same poll cycle)
## Entry-to-Creation Delay: ~4 minutes (inherent next-candle execution)

The signal-to-creation delay is ~0 seconds because trades are created in the
same polling cycle as signal persistence. The entry-to-creation delay of ~4
minutes is inherent to the HLC 3-Bar strategy strategy rule (entry at next
candle open, 5 minutes after signal candle close).

No changes needed to timing behavior.
