"""Constants for the shadow-only setup-return measurement study.

Production constants are copied verbatim from
  /opt/tradingai/app/research/cpr_trigger_engine.py   (read 2026-10-22)
so the replica executes the same rules as the live engine. Study constants are
pre-declared here BEFORE any setup is annotated.
"""
import os

# ---------------------------------------------------------------- paths ----
RUN_DIR = os.environ.get('SHADOW_RUN_DIR') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DB = os.environ.get('SHADOW_SNAPSHOT_DB') or os.path.join(
    RUN_DIR, 'snapshots', 'tradingai_snapshot.db')
OUT_DIR = os.path.join(RUN_DIR, 'outputs')
REPORT_DIR = os.path.join(RUN_DIR, 'reports')
LIVE_DB = '/opt/tradingai/database/tradingai.db'
REPO = '/opt/tradingai'

# the previous study (read-only inputs for the cross-check)
PREV_WAIT_RUN = ('/opt/tradingai/research/prevday_cpr_spread_study/'
                 'stop_forensics/live_loss_forensics/'
                 'wait_for_setup_20261022_184500')
PREV_LIVE_RUN = ('/opt/tradingai/research/prevday_cpr_spread_study/'
                 'stop_forensics/live_loss_forensics/'
                 'run_20261022_172521')

INSTRUMENTS = ('NIFTY', 'BANKNIFTY')

# --------------------------------------------- production constants --------
# cpr_trigger_engine.py
SHORT_ONLY = True          # base scan emits BEAR only
SKIP_FRIDAY = True         # a BEAR signal on a Friday is dropped (2026-10-17)
BREAKOUT_ADDON = True      # close-cross breakout fallback when no base trigger
OPEN_STOP_PCT = 0.005      # stop distance from the entry price
OPEN_TARGET_PCT = 0.02     # target distance from the entry price
OPEN_MIN = '09:20'         # entry window opens
OPEN_EOD = '15:20'         # entry window closes (exclusive) / flat exit candle
SIGNAL_CUTOFF = '15:25'    # candles at or after this time are not scanned
MIN_CANDLES = 10           # fewer candles -> session skipped (short_day)
COST_R_PER_TRADE = 0.10    # display-only cost placeholder (brokerage+STT+slippage)
DECAY_TOL_POINTS = {'NIFTY': 30.0, 'BANKNIFTY': 60.0, 'INDIA_VIX': 0.02}
NO_CHASE_BAND_PCT = 0.0015   # production no-chase band (reference only)

# ------------------------------------------------- study constants ---------
# Pre-declared before any setup was annotated.
BAR_MINUTES = 5               # the stored candle granularity
RETURN_WINDOW_BARS = 12       # "within 12 completed bars" (1 hour) - the same
                              # window the previous wait-for-setup study used
WAIT_EXPIRY_BARS = RETURN_WINDOW_BARS   # alias: the copied cross-check
                                         # module (variants.py) uses this name
TOUCH_LEVELS = ('R1', 'R2', 'PDH', 'S1', 'S2', 'PDL')
BREAK_LEVELS = ('BELOW_CPR', 'ABOVE_CPR')
FAMILIES = ('TOUCH', 'BREAK', 'BREAKOUT')
BOARDS = ('A_RECORDED_BOOK', 'B_CURRENT_ENGINE_REPLAY', 'C_LIVE_TRADES')

# the bootstrap is seeded so every number in the report is reproducible
BOOTSTRAP_SEED = 20261022
BOOTSTRAP_DRAWS = 2000

# the wait rules that the annotation is compared against (the hypothetical
# filters - the annotation itself never trades)
FILTERS = ('WAIT_RETURN_12B', 'WAIT_CONFIRM_AFTER_RETURN')
