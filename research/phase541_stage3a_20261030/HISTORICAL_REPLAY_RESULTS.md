# Phase 5.41 Stage 3A Final Validation — Historical Replay Results

## Execution
- Command: `cd /opt/tradingai && timeout 280 python3 /tmp/phase541_hist_replay.py`
- Command: `cd /opt/tradingai && timeout 280 python3 /tmp/phase541_hist_replay2.py`
- VM: webserver (Oracle VM, Linux x86_64, Ubuntu 22.04.1)
- Storage: isolated temp DB copy (`/tmp/tradingai_hist_replay_*/tradingai.db`)
- Production DB: read-only (source opened `mode=ro`)

## Results (actual replay output)
- NIFTY: candles=6071, signals=516, trades=516.
- BANKNIFTY: candles=6071, signals=458, trades=458.

## Per-run final validation (Phase 5.41 Stage 3A Final Validation)
- RUN1 NIFTY: trades=516, wins=378, losses=138, flats=0, gross_win=9294.81, gross_loss=-2482.30, net=6812.51, PF=3.7444, dup=0, timestamps_ok=True, entry<=exit=True.
- RUN2 NIFTY: trades=516, wins=378, losses=138, flats=0, gross_win=9294.81, gross_loss=-2482.30, net=6812.51, PF=3.7444, dup=0, timestamps_ok=True, entry<=exit=True.
- RUN1 BANKNIFTY: trades=458, wins=332, losses=126, flats=0, gross_win=24854.56, gross_loss=-7368.60, net=17485.96, PF=3.3730, dup=0, timestamps_ok=True, entry<=exit=True.
- RUN2 BANKNIFTY: trades=458, wins=332, losses=126, flats=0, gross_win=24854.56, gross_loss=-7368.60, net=17485.96, PF=3.3730, dup=0, timestamps_ok=True, entry<=exit=True.

## Determinism
- TOTAL_MISMATCHES=0 across all compared fields (instrument, direction, trade_date, level, signal_time, entry_time, exit_time, entry, exit, stop, target, exit_reason, points, r_multiple, win_loss).
- Trade counts identical between runs.

## Status
HISTORICAL_REPLAY_EXECUTED_AND_VERIFIED
