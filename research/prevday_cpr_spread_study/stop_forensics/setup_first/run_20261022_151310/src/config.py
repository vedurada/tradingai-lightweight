"""Frozen configuration for the setup-first study (Phase 3).

Every value here is pre-registered before any candidate is computed. Nothing in
this module may be changed after a result has been observed.
"""
from __future__ import annotations

STUDY = 'setup_first'

# ---------------------------------------------------------------- sessions ---
SPLITS = {
    'IS': ('2026-07-06', '2026-08-31'),
    'VAL': ('2026-09-01', '2026-09-30'),
    'OOS': ('2026-10-01', '2026-10-21'),
}
PERIOD_OF = {
    'in_sample': 'IS',
    'validation': 'VAL',
    'out_of_sample': 'OOS',
}
INSTRUMENTS = ('NIFTY', 'BANKNIFTY')
DATE_START = '2026-07-06'
DATE_END = '2026-10-21'
EXCLUDED_DATES = ('2026-10-22',)      # incomplete live session at study time

# ------------------------------------------------------- frozen baseline ---
STOP_PCT = 0.005                     # production stop, 0.5 % of entry
TARGET_PCT = 0.02                    # production target, 2 % of entry
COST_R_PER_TRADE = 0.10              # round-trip cost assumption (modeled)
COST_GRID = (0.00, 0.10, 0.20, 0.30)
MIN_CANDLES = 10
ENTRY_OPEN_MIN = '09:20'
ENTRY_OPEN_MAX = '15:20'             # entry window end (exclusive), production
EOD_OPEN = '15:20'                   # flat at the open of this bar
SCAN_CUTOFF = '15:25'

# -------------------------------------------------- setup definition -------
ZONE_PCT = 0.0010                    # zone half-width, 0.10 % of the level
EXPIRY_BARS = 12                     # 12 x 5 min = 60 min validity window
MAX_ENTRY_EXTENSION_PCT = 0.0025     # do not chase more than 0.25 % past level
MIN_RR = 1.5                         # minimum reward/risk for an entry
MIN_STOP_PCT = 0.0025                # 0.25 % - narrower stop is not structural
MAX_STOP_PCT = 0.0150                # 1.50 % - wider stop is not acceptable
EPS_PCT = 0.0002                     # buffer beyond a structural level
K_VOL = 0.5                          # volatility buffer multiplier (S5)
VOL_MIN_BARS = 3
SWING_M = 2                          # strict fractal: m bars each side
SWING_LOOKBACK = 20                  # bars searched back for a swing

# Level families, fixed priority order (never chosen by outcome)
RESISTANCE_PRIORITY = ('PDH', 'PIVOT', 'R1', 'R2')
SUPPORT_PRIORITY = ('PDL', 'PIVOT', 'S1', 'S2', 'BC')

SETUP_FAMILIES = (
    'F1_PREV_DAY_LEVEL_REJECTION',
    'F2_CPR_BOUNDARY_REJECTION',
    'F3_BREAKDOWN_RETEST',
    'F4_PULLBACK_TO_SWING_HIGH',
    'F5_FAILED_BREAK_REJECTION',
    'F6_SWING_BREAK_RETEST',
)

# ---------------------------------------------------------------- states ----
STATE_WATCHING = 'WATCHING'
STATE_ZONE_REACHED = 'ZONE_REACHED'
STATE_CONFIRMED = 'CONFIRMED'
STATE_TRADE_ELIGIBLE = 'TRADE_ELIGIBLE'
STATE_ENTERED = 'ENTERED_HYPOTHETICAL'
STATE_EXPIRED = 'EXPIRED'
STATE_INVALIDATED = 'INVALIDATED'
STATE_MISSED = 'MISSED'
STATE_NO_TRADE = 'NO_TRADE'
TERMINAL_STATES = (STATE_EXPIRED, STATE_INVALIDATED, STATE_MISSED, STATE_NO_TRADE)
