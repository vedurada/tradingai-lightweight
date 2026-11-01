# HLC Strategy Audit
Source: /opt/tradingai/app/research/scalp_engine.py
Rules: 3 consecutive 5m candles; high/low/close all move same direction (up>0/down<0); entry at next candle open; SL/target from canonical logic (COST_POINTS=1.0 points reference); no strategy parameter changes.
Instruments: NIFTY, BANKNIFTY, INDIA_VIX
Backtest instrument: NIFTY only (as requested)
No strategy modification performed.
