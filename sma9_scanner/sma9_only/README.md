# SMA9 Only Scanner - ATM Option Strike (CE/PE) - 5 Minute - BUY ONLY

## Strategy Overview

Both ATM CE and ATM PE use the **same long-only rule set**. There is no
CE-bullish / PE-bearish split and no short option leg.

SMA9 is computed separately for ATM CE and ATM PE from each option's own
5-minute candles. Only **completed** candles are used; the current candle's
close is never included.

### Qualification (per option)

At a 5-minute candle boundary:

- **A)** previous completed candle CLOSE > SMA9
- **OR B)** current forming candle OPEN > SMA9

### Confirmation

- live option LTP > the same SMA9

### Entry / Exit

- **Entry:** paper BUY immediately when qualified and confirmed
- **Exit:** at the CLOSE of the entry 5-minute candle
- No carry-forward, no overnight positions, no later-candle substitution

## Rules

- Signal: evaluated on the option's own 5-minute candles
- Entry: live LTP at the moment of confirmation (paper only)
- Direction: **BUY** for both CE and PE
- Stop reference: entry candle LOW (below entry)
- Target reference: entry candle HIGH (above entry)
- Exit: same candle CLOSE (`SAME_CANDLE_EXIT`)
- Max positions: 2 (one independent long CE + one independent long PE)
- Polling: every 5 seconds during market hours (live scanner)

## P&L

- CE: `P&L = EXIT - ENTRY`
- PE: `P&L = EXIT - ENTRY` (identical BUY arithmetic)

## Files

- `config.py`: scanner configuration constants
- `scanner.py`: signal construction and scanner class
- `entry_rules.py`: BUY-only qualification / confirmation helpers
- `exit_rules.py`: same-candle exit and BUY P&L
- `position_manager.py`: position lifecycle (max two long positions)
- `risk_manager.py`: long-side risk calculations
- `models.py`: data models

## Production components

- Live paper scanner: `sma9_scanner/app/live_sma9_scanner.py`
  (`tradingai-sma9-scanner.service`, 5-second polling)
- Pure strategy engine: `sma9_scanner/app/sma9_engine.py`
- Corrected historical dataset + audit: `sma9_scanner/app/sma9_historical_audit.py`
- Dedicated database: `database/sma9.db`

`sma9_scanner/app/sma9_scan_runner.py` is deprecated and performs no database writes.

## Scanner metadata

- Scanner ID: `sma9_only`
- Display Name: `SMA9 Only - ATM Option Strike (BUY ONLY)`
- Strategy Type: `SMA9_BUY_ONLY`
- Instrument: NIFTY (ATM option strike)
- Timeframe: 5-minute
