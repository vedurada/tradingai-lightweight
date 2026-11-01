# Live Observation

## Observation Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Market Session Status
- Market: OPEN (09:15-15:30 IST)
- VM time at observation: 13:30 IST
- Latest DB candle: 2026-10-30T13:20:00+05:30 (NIFTY, BANKNIFTY, INDIA_VIX)
- Market data provider (^NSEI, ^NSEBANK): state=LIVE, 100 candles each

## Signal Generation Today (2026-10-30)
- Total HLC signals generated: 7 (5 NIFTY, 2 BANKNIFTY)
- Signal times: 10:00, 10:05, 10:10, 10:55, 11:00, 11:05, 11:10, 11:35
- All signals: EXPIRED (none converted to paper trades)
- No new HLC 3-bar alignments detected on 13:15 or 13:20 candles

## Paper Trade Creation Today
- New SCALP_HLC paper trades: 0
- Total SCALP_HLC trades in DB: 30 (all from Oct 27-28, all CLOSED)
- All 7 today's signals marked EXPIRED before trade creation

## Service Status
- tradingai-paper-scalp-live.service: ACTIVE (running)
- Main PID: 944550
- Single instance (no crash loop)
- Logs show run_once() completing every 5 seconds: signals=5 created=0

## Live Verification Status
LIVE_GENERATION_NOT_YET_VERIFIED

Reason: No new HLC 3-bar alignment signals have occurred on candles after
11:35 IST on 2026-10-30. All signals from today's session (10:00-11:35)
expired before the paper_scalp_live.service was stabilized with the fix.

The fixed pipeline will correctly process new signals when they occur:
1. is_stale() check removed — signals no longer prematurely skipped
2. _entry_time_guard() handles expiration with correct 5-minute entry window
3. yfinance symbol mapping (^NSEI/^NSEBANK) enables entry price resolution
4. _trade_for() bounds check prevents IndexError in run_opens_range()

## What Needs to Happen for Full Live Verification
A new HLC 3-bar alignment signal must occur on a future 5-minute candle
during market hours (before 15:30 IST). When it does:
1. today_signals() will return the signal with entry price (from DB candle)
2. _entry_time_guard() will validate the entry window
3. try_create_trade() will create the paper trade
4. The trade will be visible in /api/paper/scalp
5. The frontend scalp.html will display it on next poll (60s)