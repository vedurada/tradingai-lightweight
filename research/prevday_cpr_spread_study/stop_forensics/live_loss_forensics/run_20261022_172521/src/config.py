"""Pre-declared constants and paths for the live-engine loss forensics.

Every threshold used by the classification is declared here, once, before the
analysis runs. Nothing in this study is tuned to the data.
"""
import os

RUN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(RUN_DIR, 'snapshots', 'tradingai_snapshot.db')
OUT = os.path.join(RUN_DIR, 'outputs')
REPORTS = os.path.join(RUN_DIR, 'reports')

REPO = '/opt/tradingai'
P3_DIR = ('/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
          'setup_first/run_20261022_151310')
P3_ADDON_DIR = ('/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
                'addon_stop_placement')

# --- source tables -----------------------------------------------------------
T_PAPER_TRADES = 'paper_trades'
T_PAPER_ALIGN = 'paper_align'
T_PAPER_TRIGGER = 'paper_trigger'
T_PAPER_ALIGN_VETO = 'paper_align_veto'
T_TRADE_JOURNAL = 'trade_journal'
T_TRADE_MISTAKE = 'trade_mistake'
T_LIVE_OBS = 'live_observations'
T_QUALIFIED = 'qualified_trades'
T_CANDLES = 'market_candles_5m'

TRADED_INSTRUMENTS = ('NIFTY', 'BANKNIFTY')

# --- production semantics (app/paper_trade/performance.py, engine.py) --------
LOT_SIZES = {'NIFTY': 65, 'BANKNIFTY': 30}
BROKERAGE_RS = 40.0
SLIPPAGE_PTS = 0.5

# --- Phase 3 frozen parameters (spec_setup_first.md) -------------------------
PHASE3_TARGET_PCT = 0.02
PHASE3_MIN_RR = 1.5
PHASE3_MIN_STOP_PCT = 0.0025
PHASE3_MAX_STOP_PCT = 0.0150
PHASE3_MAX_ENTRY_EXTENSION_PCT = 0.0025
PHASE3_EXPIRY_BARS = 12
PHASE3_SWING_LOOKBACK = 20
PRE_ENTRY_MOVE_DONE_PCT = 0.5   # a pre-entry move above this % is "already done"

# --- forward-path horizons (mirrors parent stop_forensics execution.py) ------
FWD_HORIZONS = (15, 30, 60)

# --- mutually exclusive post-exit thresholds, in units of the trade's own risk
CONTINUATION_R = 0.5      # adverse move after exit >= 0.5R  -> continuation
REVERSAL_R = 0.5          # favourable move after exit >= 0.5R -> reversal
CHOP_R = 0.5              # whole post-exit range < 0.5R        -> chop
PRIMARY_HORIZON_MIN = 60   # primary post-exit window (minutes)

# --- structural / entry-time analysis ----------------------------------------
LEVEL_LOOKBACK_BARS = 20   # bars used for swing and prior-structure checks
CHOP_BARS = 12             # bars used for the chop test
CHOP_RANGE_PCT = 0.0025    # a 12-bar range below this is 'chop'
CONTINUATION_TRIGGER_PCT = 0.0010  # level cross beyond this = failed breakout

# --- verdict rule (declared before the analysis was run) -----------------------
VERDICT_RULES = {
    # a verdict needs at least this many actual live loss trades ...
    'min_live_losses_for_verdict': 10,
    # ... and at least this many engine-book losses ...
    'min_book_losses_for_verdict': 30,
    # ... and at least this many comparable Phase 3 pattern rows.
    'min_comparable_rows': 6,
    'supported_ratio_for_supported': 0.60,
    'supported_ratio_for_partial': 0.30,
}

# --- reconstruction tolerances ----------------------------------------------
R_TOLERANCE = 0.005        # recorded R vs recomputed R tolerance
PNL_TOLERANCE_RS = 1.0     # recorded pnl vs recomputed pnl tolerance (rupees)
PRICE_TOLERANCE = 0.51     # index point tolerance for price reconciliation


def lot(instrument):
    return LOT_SIZES.get((instrument or '').upper(), 65)


def direction_sign(direction):
    d = (direction or '').upper()
    return -1 if d in ('SHORT', 'BEARISH', 'BEAR') else 1


def fees(instrument):
    return BROKERAGE_RS + SLIPPAGE_PTS * lot(instrument)
