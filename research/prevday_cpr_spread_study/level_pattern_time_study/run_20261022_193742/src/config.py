"""Predeclared configuration for the level-pattern / entry-time study.

Everything in this file is fixed BEFORE any outcome is measured. No value
here is tuned on the data; the tolerance values, the time buckets, the
entry windows and the partition boundaries are declared once and applied
everywhere.
"""
import os

RUN_DIR = os.environ.get('LVL_RUN_DIR') or (
    '/opt/tradingai/research/prevday_cpr_spread_study/level_pattern_time_'
    'study/run_20261022_193742')

# The authoritative production source (read only, never written).
SOURCE_DB = '/opt/tradingai/database/tradingai.db'
SOURCE_WAL = '/opt/tradingai/database/tradingai.db-wal'
# The derived research copy. Every transformation in this study happens here.
RESEARCH_DB = os.path.join(RUN_DIR, 'research_copy', 'tradingai_research.db')

STRATEGY_SRC = '/opt/tradingai/app/research/cpr_strategy_engine.py'
TRIGGER_SRC = '/opt/tradingai/app/research/cpr_trigger_engine.py'

INSTRUMENTS = ('NIFTY', 'BANKNIFTY')

# --- predeclared tolerances (section 4) ----------------------------------
# A touch is "the bar's range comes within TOL of the level". Two tolerances
# are tested separately and never mixed: a fixed number of index points and
# a volatility-normalised tolerance derived from the previous session only.
TOL_FIXED_POINTS = {'NIFTY': 10.0, 'BANKNIFTY': 25.0}
TOL_VOL_MULT = 0.25          # x the mean 5-minute bar range of the previous
TOL_VOL_FLOOR = 2.0          # session (causal: the previous session is known)
TOL_VOL_CAP_PCT = 0.25       # never more than a quarter of the previous range

# --- session / entry eligibility (production convention) ----------------
SESSION_OPEN = '09:15'
SESSION_CLOSE = '15:30'
ENTRY_WINDOW_OPEN = '09:20'    # the production engine enters at the next open
ENTRY_WINDOW_CLOSE = '15:20'   # in [09:20, 15:20)
FORWARD_WINDOWS_BARS = (3, 6, 12)   # 15 / 30 / 60 minutes

# --- entry rules (section 6) --------------------------------------------
ENTRY_RULES = ('E0', 'E1', 'E2', 'E3', 'E4_3', 'E4_6', 'E4_12', 'E5', 'E6')

# --- predeclared filters -------------------------------------------------
MIN_ROOM_POINTS = {'NIFTY': 25.0, 'BANKNIFTY': 60.0}   # E5 room filter
CHOP_CROSSINGS = 3          # E6: >= this many CPR boundary crossings in the
CHOP_LOOKBACK = 12          # previous 12 completed bars -> chop regime
FRICTION_POINTS = (5.0, 10.0, 20.0)   # index-point friction sensitivity
MOVE_POINTS = {'NIFTY': 20.0, 'BANKNIFTY': 50.0}  # "favourable move" size
CLUSTER_MULT = 2            # D1 cluster tolerance = CLUSTER_MULT x tolerance

# --- time buckets (section 8, IST) --------------------------------------
TIME_BUCKETS = (
    ('09:15-09:30', '09:15', '09:30'),
    ('09:30-10:00', '09:30', '10:00'),
    ('10:00-10:30', '10:00', '10:30'),
    ('10:30-11:30', '10:30', '11:30'),
    ('11:30-12:30', '11:30', '12:30'),
    ('12:30-13:30', '12:30', '13:30'),
    ('13:30-14:30', '13:30', '14:30'),
    ('14:30-15:00', '14:30', '15:00'),
    ('15:00-15:20', '15:00', '15:20'),
)

# --- session-level partitions (section 10) ------------------------------
IS_FRACTION = 0.50
VALIDATION_FRACTION = 0.25
# the remainder is the out-of-sample partition

# --- statistics ----------------------------------------------------------
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261022
MIN_SESSIONS_FOR_CI = 20      # below this a cell is flagged as a weak sample
MIN_EVENTS_FOR_CI = 30

# --- protected production files (integrity) ------------------------------
PROTECTED_FILES = (
    'app/research/cpr_trigger_engine.py',
    'app/research/cpr_strategy_engine.py',
    'app/live/engine.py',
    'app/paper_trade/engine.py',
    'app/paper_trade/performance.py',
    'app/api/app.py',
    'app/research/backtest.py',
    'app/core/db.py',
    'scripts/tg_alerts.py',
    'scripts/paper_confluence.py',
    'config/settings.json',
)
