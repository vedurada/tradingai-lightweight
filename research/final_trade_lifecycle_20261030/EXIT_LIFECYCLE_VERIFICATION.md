# Exit Lifecycle Verification

## Date
2026-10-30

## Status
Entry delivery verified. Exit delivery pending (no trades closed since fix deployed).

## Exit Pipeline Implementation

PaperTradeEngine.monitor() runs every 5 seconds:
- Fetches all ACTIVE/OPEN paper_trades
- Evaluates stop/target hits using exits_opens() routine
- Calls _exit_trade() to persist the exit

do_watch() EXIT sweep:
- For each open trade in st.get(open, {}):
  - Calls PaperTradeEngine().monitor() to check if trade closed
  - If trade closed (_m.get(filled) == True):
    - Checks if EXIT already delivered via notification_events
    - If not delivered: INSERT PENDING record into notification_events
    - Sends Telegram message via tg(sendMessage, ...)
    - On success: UPDATE notification_events to DELIVERED with message_id
    - On failure: UPDATE notification_events to FAILED with error
    - Removes trade from st.get(open, {}) to prevent re-processing

## Exit Alert Message Format

BANKNIFTY
30 Oct 2026
Direction: BEAR
Entry (ref): 54,767.15
Exit (ref): 54,713.90
Result: STOP (+54.30 pts)

## Exit Detection Logic

| Condition | BULL | BEAR |
|-----------|------|------|
| Stop Hit | low <= stop | high >= stop |
| Target Hit | high >= target | low <= target |
| Both Hit | STOP takes priority | STOP takes priority |
| EOD | Last candle close if neither hit | Last candle close if neither hit |

## Exit Detection Code Path

PaperTradeEngine.monitor() [runs every 5s in run_once()]
  │
  ├─ SELECT * FROM paper_trades WHERE status IN (ACTIVE, OPEN)
  │   
  └─ For each trade:
    ├─ SELECT candle OPENS with timestamp > entry_time
    ├─ Evaluate stop/target hits using exits_opens()
    │   ├─ BULL: stop if low <= stop, target if high >= target
    │   └─ BEAR: stop if high >= stop, target if low >= target
    ├─ If exit detected:
    │   ├─ _exit_trade() updates paper_trades (status=CLOSED)
    │   ├─ record_performance() writes to paper_trade_events
    │   └─ Returns trade result
    │   
    └─ do_watch() EXIT sweep:
      ├─ Check if EXIT already delivered (notification_events)
      ├─ If not: INSERT PENDING, send Telegram, UPDATE DELIVERED
      └─ Remove from st.get(open, {})

## Remaining Issue

Exit alert delivery not verified: No trades have closed since the fix was deployed.
The exit alert pipeline is implemented and tested in isolated tests (15/15 passed)
but has not been exercised with a genuine live trade closure.
