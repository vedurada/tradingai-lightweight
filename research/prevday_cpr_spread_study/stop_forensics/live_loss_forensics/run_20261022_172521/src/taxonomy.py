"""Phase 3 pattern taxonomy applied to the recorded trades.

Each dimension (entry timing, market structure, stop behaviour, setup-first
discipline) gets one primary category and any supported secondary categories.
Every rule is deterministic and uses only information that existed at or
before the entry, plus the recorded exit and the forward path after it.
"""
from . import config

# --- dimension A: entry timing ------------------------------------------------
A_TRIGGER_NO_RETEST = 'ENTRY_AT_TRIGGER_WITHOUT_ZONE_RETEST'
A_TOO_EXTENDED = 'ENTRY_AFTER_EXCESSIVE_EXTENSION'
A_BEFORE_CONFIRMATION = 'ENTRY_BEFORE_CONFIRMATION'
A_MOVE_ALREADY_DONE = 'ENTRY_AFTER_MARKET_COMPLETED_MOST_OF_MOVE'
A_NO_PROBLEM = 'NO_DEMONSTRABLE_TIMING_PROBLEM'
A_INSUFFICIENT = 'INSUFFICIENT_DATA'

# --- dimension B: market structure -------------------------------------------
B_FAILED_BREAK = 'FAILED_BREAKOUT_OR_BREAKDOWN'
B_CONTINUATION_AGAINST = 'DIRECTIONAL_CONTINUATION_AGAINST_POSITION'
B_ORDINARY_PULLBACK = 'ORDINARY_PULLBACK_WITHIN_LARGER_MOVE'
B_REJECTION_AT_LEVEL = 'REJECTION_AT_PRE_EXISTING_LEVEL'
B_CHOP = 'RANGE_CHOP_OR_REPEATED_LEVEL_CROSSINGS'
B_REVERSAL_AFTER_ENTRY = 'REVERSAL_AFTER_ENTRY'
B_CONFLICTING = 'CONFLICTING_OR_UNCLEAR_STRUCTURE'
B_NO_PROBLEM = 'NO_DEMONSTRABLE_STRUCTURE_PROBLEM'
B_INSUFFICIENT = 'INSUFFICIENT_DATA'

# --- dimension C: stop behaviour ---------------------------------------------
C_CONTINUED = 'STOP_HIT_THEN_PRICE_CONTINUED_AGAINST'
C_REVERSED = 'STOP_HIT_THEN_PRICE_REVERSED_TOWARD_TARGET'
C_CHOP = 'STOP_HIT_DURING_CHOPPY_PRICE_ACTION'
C_INSIDE_ORDINARY = 'STOP_APPEARS_TO_HAVE_BEEN_PLACED_WITHIN_ORDINARY_ADVERSE_MOVEMENT'
C_BEYOND_INVALIDATION = 'STOP_WAS_BEYOND_THE_AVAILABLE_STRUCTURAL_INVALIDATION_POINT'
C_NO_INVALIDATION = 'STRUCTURAL_INVALIDATION_WAS_UNAVAILABLE_AT_ENTRY'
C_NOT_ASSESSABLE = 'STOP_ADEQUACY_CANNOT_BE_ASSESSED'
C_NOT_APPLICABLE = 'NOT_A_STOP_EXIT'

# --- dimension D: setup-first discipline -------------------------------------
D_ELIGIBLE = 'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION'
D_NO_CONFIRMATION = 'ZONE_REACHED_BUT_CONFIRMATION_ABSENT'
D_TOO_EXTENDED = 'CONFIRMATION_OCCURRED_BUT_ENTRY_WAS_ALREADY_TOO_EXTENDED'
D_RR_FAILED = 'VALID_ENTRY_PLAN_EXISTED_BUT_RISK_REWARD_FAILED'
D_NA = 'NOT_APPLICABLE_ENGINE_ENTERS_AT_THE_ZONE_ITSELF'
D_UNKNOWN = 'HISTORICAL_RECORD_INSUFFICIENT_TO_DETERMINE_SETUP_FIRST_ELIGIBILITY'


def _safe(value, default=None):
    return default if value is None else value


def classify(record, path, level_info, confirmation):
    """Return the taxonomy classification for one trade."""
    out = {
        'A_primary': None, 'A_secondary': [],
        'B_primary': None, 'B_secondary': [],
        'C_primary': None, 'C_secondary': [],
        'D_primary': None, 'D_secondary': [],
        'rr_vs_frozen_target': None,
        'setup_first_eligible': None,
        'basis': [],
    }
    direction = record.get('direction')
    sign = config.direction_sign(direction)
    entry = record.get('entry_price')
    stop = record.get('stop_price')
    risk = record.get('risk_pts')
    target = record.get('target_price')

    # ---- risk / reward against the frozen 2 % target (Phase 3 rule) --------
    if entry and stop and target and risk:
        reward = abs(target - entry)
        out['rr_vs_frozen_target'] = round(reward / risk, 4)
    elif entry and stop and risk:
        out['rr_vs_frozen_target'] = round(config.PHASE3_TARGET_PCT * entry / risk, 4)

    # ---- dimension A: entry timing -----------------------------------------
    if path.get('path_status') != 'OK':
        out['A_primary'] = A_INSUFFICIENT
        out['B_primary'] = B_INSUFFICIENT
        out['C_primary'] = C_NOT_ASSESSABLE
        out['D_primary'] = D_UNKNOWN
        out['basis'].append('no candle path')
        return out

    extension = level_info.get('entry_extension_pct')
    a_secondary = []
    if extension is not None:
        adverse_extension = extension if sign < 0 else -extension
        if adverse_extension > config.PHASE3_MAX_ENTRY_EXTENSION_PCT * 100:
            a_secondary.append(A_TOO_EXTENDED)
    # how much of the move had already happened before the entry
    pre_move = _pre_entry_move(record, path, level_info)
    if pre_move is not None and abs(pre_move) > config.PRE_ENTRY_MOVE_DONE_PCT:
        a_secondary.append(A_MOVE_ALREADY_DONE)
    conf = confirmation or {}
    if conf.get('rejection_close_before_entry') is False:
        a_secondary.append(A_BEFORE_CONFIRMATION)
    # The production engine enters on the FIRST qualifying touch of the level:
    # no zone retest and no wait for a confirmation.
    if level_info.get('entry_is_first_touch') is True:
        a_secondary.append(A_TRIGGER_NO_RETEST)
    if path.get('entry_index_match') in ('price_match_other_bar',):
        a_secondary.append(A_TRIGGER_NO_RETEST)
    if a_secondary:
        out['A_primary'] = a_secondary[0]
        out['A_secondary'] = a_secondary[1:]
    else:
        out['A_primary'] = A_NO_PROBLEM
    out['pre_entry_move_pct'] = pre_move

    # ---- dimension B: market structure ------------------------------------
    b_secondary = []
    level_price = level_info.get('level_price')
    if path.get('failed_breakout_after_entry'):
        b_secondary.append(B_FAILED_BREAK)
    if path.get('mae_hl_r') is not None and path.get('mfe_hl_r') is not None:
        if path['mae_hl_r'] >= 1.0 and path['mae_hl_r'] > path['mfe_hl_r']:
            b_secondary.append(B_CONTINUATION_AGAINST)
        if path.get('mfe_hl_r', 0) >= 0.5 and path.get('mae_hl_r', 0) >= 1.0:
            b_secondary.append(B_REVERSAL_AFTER_ENTRY)
    if path.get('post_exit_category') == 'CONTINUATION_AGAINST':
        b_secondary.append(B_ORDINARY_PULLBACK)
    chop = _is_choppy(record, path, level_info)
    if chop:
        b_secondary.append(B_CHOP)
    if level_info.get('level_price_source') in ('PREV_DAY_HIGH', 'PREV_DAY_LOW',
                                               'PIVOT_R1', 'PIVOT_R2', 'PIVOT_S1'):
        b_secondary.append(B_REJECTION_AT_LEVEL)
    if b_secondary:
        out['B_primary'] = b_secondary[0]
        out['B_secondary'] = b_secondary[1:]
    else:
        out['B_primary'] = B_NO_PROBLEM
    out['is_choppy'] = chop

    # ---- dimension C: stop behaviour ---------------------------------------
    if record.get('exit_kind') != 'STOP':
        out['C_primary'] = C_NOT_APPLICABLE
    else:
        c_secondary = []
        post = path.get('post_exit_category')
        if post == 'CONTINUATION_AGAINST':
            c_secondary.append(C_CONTINUED)
        elif post == 'REVERSAL_TOWARD_TARGET':
            c_secondary.append(C_REVERSED)
        elif post in ('CHOP', 'MIXED'):
            c_secondary.append(C_CHOP)
        if level_info.get('stop_inside_ordinary_move'):
            c_secondary.append(C_INSIDE_ORDINARY)
        if level_info.get('stop_beyond_invalidation'):
            c_secondary.append(C_BEYOND_INVALIDATION)
        if level_info.get('nearest_invalidation') is None and level_info.get('known_levels_at_entry'):
            c_secondary.append(C_NO_INVALIDATION)
        if not c_secondary:
            c_secondary.append(C_NOT_ASSESSABLE)
        out['C_primary'] = c_secondary[0]
        out['C_secondary'] = c_secondary[1:]

    # ---- dimension D: setup-first discipline -------------------------------
    rr = out['rr_vs_frozen_target']
    touched = conf.get('touch_before_entry')
    rejection = conf.get('rejection_close_before_entry')
    if not level_price or level_info.get('level_price_source') in ('UNKNOWN', None):
        out['D_primary'] = D_UNKNOWN
        out['setup_first_eligible'] = None
    elif rejection is True:
        if extension is not None:
            adverse_extension = extension if sign < 0 else -extension
            if adverse_extension > config.PHASE3_MAX_ENTRY_EXTENSION_PCT * 100:
                out['D_primary'] = D_TOO_EXTENDED
                out['setup_first_eligible'] = False
            elif rr is not None and rr < config.PHASE3_MIN_RR:
                out['D_primary'] = D_RR_FAILED
                out['setup_first_eligible'] = False
            else:
                out['D_primary'] = D_ELIGIBLE
                out['setup_first_eligible'] = True
        else:
            out['D_primary'] = D_ELIGIBLE
            out['setup_first_eligible'] = True
    else:
        # The level was reached but the Phase 3 rejection close never appeared
        # before the entry: the engine entered without the confirmation the
        # setup-first rule requires.
        out['D_primary'] = D_NO_CONFIRMATION
        out['setup_first_eligible'] = False
    out['zone_touch_before_entry'] = touched
    return out


def _pre_entry_move(record, path, level_info):
    """Net move of the last 12 closed bars before the entry, in %, signed."""
    inst = record['instrument']
    date = record['session_date']
    entry_ts = (record.get('entry_time') or '')[:16]
    return path.get('pre_entry_move_pct')


def _level_crossed_after_entry(record, path, level_price):
    """True when price traded through the level by more than the trigger band."""
    return path.get('level_crossed_after_entry', False)


def _is_choppy(record, path, level_info):
    """A 12-bar range below 0.25 % with repeated level crossings."""
    return bool(path.get('is_choppy'))
