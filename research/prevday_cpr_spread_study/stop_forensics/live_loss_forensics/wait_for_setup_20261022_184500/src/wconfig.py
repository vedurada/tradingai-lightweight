"""Constants for the read-only 'wait for the setup' counterfactual study.

Production constants are copied verbatim from
  /opt/tradingai/app/research/cpr_trigger_engine.py   (read 2026-10-22)
so the replica executes the same rules as the live engine. Study constants are
pre-declared here BEFORE any variant is evaluated.
"""
import os

# ---------------------------------------------------------------- paths ----
RUN_DIR = os.environ.get('WAIT_RUN_DIR') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DB = os.environ.get('WAIT_SNAPSHOT_DB') or os.path.join(
    RUN_DIR, 'snapshots', 'tradingai_snapshot.db')
OUT_DIR = os.path.join(RUN_DIR, 'outputs')
REPORT_DIR = os.path.join(RUN_DIR, 'reports')
LIVE_DB = '/opt/tradingai/database/tradingai.db'

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
NO_CHASE_BAND_PCT = 0.0015   # production no-chase band (kept for the V4 reference)

# ------------------------------------------------- study constants ---------
# Pre-declared before the variants were evaluated.
WAIT_EXPIRY_BARS = 12      # bars (1 hour) a wait variant may stay pending
VARIANT_ORDER = (
    'V0_BASELINE',
    'V1_WAIT_SETUP',
    'V1X_WAIT_SETUP_NO_EXPIRY',
    'V2_WAIT_CONFIRM',
    'V3_WAIT_CONFIRM_RETEST',
    'V4_NO_CHASE_FLIP',
)
VARIANT_LABELS = {
    'V0_BASELINE': 'V0 baseline (enter at the next 5m open - production rule)',
    'V1_WAIT_SETUP': 'V1 wait for the setup (price trades back to the level, fill at the level, 12-bar expiry)',
    'V1X_WAIT_SETUP_NO_EXPIRY': 'V1x wait for the setup with no expiry (to the 15:20 entry cut-off)',
    'V2_WAIT_CONFIRM': 'V2 wait for a rejection close at the level, then enter at the next open',
    'V3_WAIT_CONFIRM_RETEST': 'V3 wait for the rejection close, then the retest of the level, fill at the level',
    'V4_NO_CHASE_FLIP': 'V4 production no-chase re-anchor (any entry level, direction may flip) - reference only',
}
# The wait variants are only meaningful when the price revisits the setup level.
# A level is "reachable" if the session traded it at any point after the trigger.
