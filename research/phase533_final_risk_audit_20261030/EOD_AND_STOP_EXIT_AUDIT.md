# Phase 5.33 — EOD and Stop Exit Audit

## Finding
- 15 losing trades, all exited via EOD.
- Zero STOP exits recorded in candle-by-candle ledger.

## Interpretation
- Stop-loss exits appear not to have been triggered under the historical data.
- Strategy exit logic: stop = signal low - 1 (BULL) / high + 1 (BEAR); target = entry +/- 1.5R; EOD flat at last session close.
- Loss magnitudes small (gross losses 12.2 pts); consistent with EOD exits.
