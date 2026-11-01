# API and Frontend Verification

## Verification Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai

## API Endpoint: GET /api/paper/scalp
Verified via live HTTP request to http://127.0.0.1:8000/api/paper/scalp

Response structure:
{
  "state": "LIVE",
  "timestamp": "2026-10-30T13:2X:XX+05:30",
  "data": {
    "trades": [...],
    "count": 30
  }
}

Each trade object contains:
- trade_id, instrument, direction, level
- entry, stop, target
- entry_time, exit_time, exit, exit_reason
- points, pnl, status, r_multiple, win_loss, result
- trade_date, created_at, source

Verified: 30 SCALP_HLC trades returned for NIFTY/BANKNIFTY, all CLOSED.

## API Endpoint: GET /api/strategy/scalp
Returns today's scalp trigger state (signals, WATCH, or NO_DATA).
Verified: returns signals for NIFTY and BANKNIFTY.

## Frontend: /opt/tradingai/frontend/scalp.html
Endpoint called: /api/paper/scalp (via runLive() JavaScript function)
Polling: setInterval(runLive, 60000) - every 60 seconds
Parsing: d.trades array from API response
Rendering: Table with columns: Date, Instrument, Source, Direction, Level,
Entry time, Entry, Exit/mark date and time, Exit/mark, Spot P&L, Outcome,
Exit reason
Empty state: "No live trades." when no trades exist

Frontend field mapping vs API response:
- Date -> trade_date or created_at[:10]
- Instrument -> instrument
- Source -> source (default "LIVE")
- Direction -> direction
- Level -> level
- Entry time -> entry_time
- Entry -> entry
- Exit/mark date and time -> exit_time
- Exit/mark -> exit
- Spot P&L -> points
- Outcome -> win_loss or result or status
- Exit reason -> exit_reason

All API fields are present in the response. Frontend correctly parses and
renders the data. No frontend changes needed.

## Backtest Endpoint: POST /api/backtest/scalp
Called by frontend runBacktest() function.
Verified: run_opens_range returns 5 signals, 5 trades, no IndexError
(was crashing before Fix 3).

## Conclusion
API and frontend are working correctly. No changes needed to either.
The pipeline issue was entirely in the paper trade creation layer
(paper_scalp_live.py), not in the API or frontend.