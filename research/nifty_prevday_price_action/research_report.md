# Research Report - NIFTY 50 Previous-Day Price Action (Continuous Intraday)

## Scope
- Sessions loaded: 77
- Candles loaded: 5771
- Partial sessions excluded from trade sim: ['2026-09-21', '2026-10-15']
- Evaluated candles (signal log rows): 5771
- Qualifying setups: 2466
- Executable trades (one open at a time): 74
- Wins: 50 (67.6%)
- Total points: 4347.54
- Total R: 36.98

## Method
Previous-day context frozen at session start. Setups evaluated on every completed 5-minute candle using only data available at that time. Entry at next candle open. EOD exit at 15:20 open (fallback 15:15 close). Stop/target 0.5%/2.0%. One open trade at a time; no re-entry until closed. Partial sessions excluded from trade simulation but retained in signal log as INVALID_DATA.

## Entry-time distribution
- 09:15-10:00: trades=74, wins=50, win_rate=67.6%, total_R=36.98
- 10:00-11:00: trades=0, wins=0, win_rate=0.0%, total_R=0.0
- 11:00-12:00: trades=0, wins=0, win_rate=0.0%, total_R=0.0
- 12:00-13:00: trades=0, wins=0, win_rate=0.0%, total_R=0.0
- 13:00-14:00: trades=0, wins=0, win_rate=0.0%, total_R=0.0
- 14:00-15:00: trades=0, wins=0, win_rate=0.0%, total_R=0.0
- 15:00+: trades=0, wins=0, win_rate=0.0%, total_R=0.0

## Walk-forward
- train (2026-07-06 to 2026-08-07): sessions=25, trades=24, win_rate=66.7%, total_R=13.63
- validation (2026-08-10 to 2026-09-15): sessions=26, trades=26, win_rate=65.4%, total_R=4.27
- test (2026-09-16 to 2026-10-23): sessions=26, trades=24, win_rate=70.8%, total_R=19.08

## Limitations
- ~3.5 months of data (77 sessions); many condition cells are sparse.
- Simplified deterministic triggers; not an exhaustive search of all price-action patterns.
- Index points only; no option premium, charges, slippage beyond documented assumptions.
- Two partial sessions excluded from strict trade simulation.
- Thresholds are documented defaults, not optimized on the test period.

## Strategy Comparison (Primary vs Secondary)
- Primary: Price Action (prevday PA): trades=74, wins=50, win_rate=67.6%, total_points=4259.03, total_R=36.25, stops=7, targets=0, eods=67
- Secondary: CPR triggers (plain): trades=76, wins=45, win_rate=59.2%, total_points=1693.2, total_R=14.78, stops=3, targets=0, eods=0
