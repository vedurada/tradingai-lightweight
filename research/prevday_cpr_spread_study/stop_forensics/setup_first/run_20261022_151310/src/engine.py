"""Setup-first state machine.

Every setup advances through the frozen state sequence and every transition is
timestamped. The engine never enters a trade on a trigger: it waits for the
zone, waits for the confirmation and then applies the entry gates.

Causal ordering guaranteed here:

* a setup is only identified from candles that were already closed,
* the zone is fixed at identification time and never re-drawn,
* the confirmation timestamp is the close of the confirming candle,
* the earliest possible entry is the open of the candle AFTER that close.
"""
from __future__ import annotations

from . import config

CONFIRM_RULES = ('C1_CLOSE_BACK', 'C2_REJECTION_CLOSE')

FAM_REJECTION = ('F1_PREV_DAY_LEVEL_REJECTION', 'F2_CPR_BOUNDARY_REJECTION',
                 'F4_PULLBACK_TO_SWING_HIGH')
FAM_FAILED_BREAK = ('F5_FAILED_BREAK_REJECTION',)
FAM_RETEST = ('F3_BREAKDOWN_RETEST', 'F6_SWING_BREAK_RETEST')


def _ts(candle):
    return str(candle['timestamp'])


def _hhmm(candle):
    return str(candle['timestamp'])[11:16]


def _close(c):
    return float(c['close'])


def _high(c):
    return float(c['high'])


def _low(c):
    return float(c['low'])


def _open(c):
    return float(c['open'])


def _intersects_zone(candle, zone_low, zone_high):
    return _low(candle) <= zone_high and _high(candle) >= zone_low


class SetupTracker:
    """Drives one setup through the frozen state sequence."""

    def __init__(self, setup, candles):
        self.setup = setup
        self.candles = candles
        self.state = config.STATE_WATCHING

    def _to(self, state, idx, reason=None):
        self.setup['transitions'].append({
            'setup_id': self.setup['setup_id'],
            'from_state': self.state,
            'to_state': state,
            'bar_idx': idx,
            'ts': _ts(self.candles[idx]) if idx is not None and 0 <= idx < len(self.candles) else None,
            'reason': reason,
        })
        self.state = state
        self.setup['state'] = state

    # ------------------------------------------------------------------ arrival
    def _find_arrival(self):
        s = self.setup
        candles = self.candles
        fam = s['setup_family']
        L = s['level_price']
        zl, zh = s['zone_low'], s['zone_high']
        id_idx = s['identification_idx']
        expiry = s['expiry_bars']
        last = min(id_idx + expiry, len(candles) - 1)

        if fam in FAM_FAILED_BREAK:
            # arrival = a breakout attempt beyond the level (high only)
            for j in range(id_idx, last + 1):
                if _high(candles[j]) >= L * (1 + config.EPS_PCT):
                    return j, None
            return None, 'no_breakout_attempt_in_window'

        if fam in FAM_RETEST:
            # arrival = the retest of the broken level
            for j in range(id_idx + 1, last + 1):
                if _high(candles[j]) >= zl:
                    return j, None
            return None, 'no_retest_in_window'

        # rejection families: price must rally into the zone
        for j in range(id_idx, last + 1):
            c = candles[j]
            if _intersects_zone(c, zl, zh):
                if _close(c) > zh:
                    return None, 'closed_above_zone_before_arrival'
                return j, None
            if _close(c) > zh:
                return None, 'closed_above_zone_before_arrival'
        return None, 'no_arrival_in_window'

    # -------------------------------------------------------------- confirmation
    def _find_confirmation(self, arrival_idx):
        s = self.setup
        candles = self.candles
        fam = s['setup_family']
        L = s['level_price']
        zh = s['zone_high']
        expiry = s['expiry_bars']
        last = min(arrival_idx + expiry, len(candles) - 1)
        rule = s.get('confirm_rule', 'C1_CLOSE_BACK')
        for k in range(arrival_idx + 1, last + 1):
            c = candles[k]
            if _close(c) > zh:
                return None, 'closed_above_zone'
            if _close(c) < L:
                if rule == 'C2_REJECTION_CLOSE' and _high(c) < L:
                    continue
                return k, ('close_back_below_level' if rule == 'C1_CLOSE_BACK'
                           else 'rejection_close_below_level')
        return None, 'no_confirmation_in_window'

    def run(self):
        s = self.setup
        candles = self.candles
        L = s['level_price']
        zl, zh = s['zone_low'], s['zone_high']
        id_idx = s['identification_idx']
        expiry = s['expiry_bars']

        arrival_idx, fail = self._find_arrival()
        if arrival_idx is None:
            state = (config.STATE_INVALIDATED
                     if fail == 'closed_above_zone_before_arrival'
                     else config.STATE_EXPIRED)
            self._to(state, min(id_idx + expiry, len(candles) - 1), fail)
            s['rejection_reason'] = fail
            return s
        s['arrival_idx'] = arrival_idx
        s['arrival_ts'] = _ts(candles[arrival_idx])
        s['minutes_to_arrival'] = (arrival_idx - id_idx) * 5
        s['max_distance_from_zone_pts_before_arrival'] = round(
            min(abs(_high(candles[k]) - zl) if s['setup_family'] in FAM_RETEST
                else abs(_low(candles[k]) - zl)
                for k in range(id_idx, arrival_idx + 1)), 2)
        s['arrival_ambiguous_candle'] = bool(
            _low(candles[arrival_idx]) <= L and _high(candles[arrival_idx]) >= L)
        s['gap_skipped_zone'] = bool(_open(candles[arrival_idx]) > zh)
        s['moved_away_without_returning'] = False
        self._to(config.STATE_ZONE_REACHED, arrival_idx, 'price_reached_zone')

        confirm_idx, reason = self._find_confirmation(arrival_idx)
        if confirm_idx is None:
            state = (config.STATE_INVALIDATED if reason == 'closed_above_zone'
                     else config.STATE_EXPIRED)
            self._to(state, min(arrival_idx + expiry, len(candles) - 1), reason)
            s['rejection_reason'] = reason
            return s
        s['confirm_idx'] = confirm_idx
        s['confirm_ts'] = _ts(candles[confirm_idx])
        s['minutes_to_confirmation'] = (confirm_idx - arrival_idx) * 5
        s['confirmation_rule'] = s.get('confirm_rule', 'C1_CLOSE_BACK')
        self._to(config.STATE_CONFIRMED, confirm_idx, reason)
        return s


def plan_entry_core(setup, candles):
    """Stop-independent part of the entry plan.

    The entry is always the open of the bar AFTER the confirming close. The
    entry window and the "do not chase" extension gate do not depend on the
    stop, so they are evaluated once and reused by every stop variant.
    """
    s = setup
    L = s['level_price']
    confirm_idx = s['confirm_idx']
    entry_idx = confirm_idx + 1
    out = {
        'entry_idx': entry_idx,
        'confirm_ts': s['confirm_ts'],
        'earliest_entry_ts': (_ts(candles[entry_idx])
                               if 0 <= entry_idx < len(candles) else None),
        'decision': None,
        'reasons': [],
        'level_price': L,
    }
    if entry_idx >= len(candles):
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('no_next_bar_after_confirmation')
        return out
    entry = _open(candles[entry_idx])
    hm = _hhmm(candles[entry_idx])
    if hm < config.ENTRY_OPEN_MIN:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('entry_before_window')
        return out
    if hm >= config.ENTRY_OPEN_MAX:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('entry_after_window')
        return out
    ext = (L - entry) / L if L else 0.0
    out['entry'] = entry
    out['entry_ts'] = _ts(candles[entry_idx])
    out['entry_time'] = _ts(candles[entry_idx])[:16].replace('T', ' ')
    out['entry_extension_pct'] = round(ext * 100, 4)
    out['distance_from_level_pts'] = round(abs(entry - L), 2)
    if ext > config.MAX_ENTRY_EXTENSION_PCT:
        out['decision'] = config.STATE_MISSED
        out['reasons'].append('too_extended_to_chase')
        return out
    out['decision'] = 'PENDING_STOP_GATES'
    return out


def apply_stop_gates(core, stop_price, target_price):
    """Stop-dependent entry gates: risk distance and reward/risk."""
    out = dict(core)
    out['reasons'] = list(core.get('reasons', []))
    if core.get('decision') not in (None, 'PENDING_STOP_GATES'):
        return out
    entry = core['entry']
    risk = stop_price - entry
    if risk <= 0:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('stop_not_above_entry')
        return out
    reward = entry - target_price
    out['stop_price'] = round(stop_price, 4)
    out['target_price'] = round(target_price, 4)
    out['risk_pts'] = round(risk, 2)
    out['risk_pct'] = round(risk / entry * 100, 4)
    out['reward_pts'] = round(reward, 2)
    out['rr'] = round(reward / risk, 3)
    if risk / entry > config.MAX_STOP_PCT:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('risk_distance_too_large')
        return out
    if risk / entry < config.MIN_STOP_PCT:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('risk_distance_too_small')
        return out
    if out['rr'] < config.MIN_RR:
        out['decision'] = config.STATE_NO_TRADE
        out['reasons'].append('reward_risk_below_minimum')
        return out
    out['decision'] = config.STATE_TRADE_ELIGIBLE
    return out
