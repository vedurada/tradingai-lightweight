"""Shadow annotation engine.

Answers one question per setup, without touching production:

  does the price return to the original setup level within 12 completed bars,
  and does a rejection-close confirmation follow the return?

CAUSALITY CONTRACT
------------------
* The scan runs forward in time over the 5-minute bars of the signal session.
* A bar stamped T covers [T, T+5min) and is only *known* at T+5min. Every
  observation therefore carries the event time (the bar start) **and** the
  knowledge time (the bar close). Nothing is classified with information that
  was not available at that knowledge time.
* The return test for bar j uses bar j's own high/low only.
* The rejection test for bar j uses bar j's own close only.
* At signal time the only inputs are the level bundle (derived from the
  previous session) and the trigger bar.
* If the session ends before 12 completed bars have elapsed after the signal
  bar, a *negative* observation is right-censored (CENSORED_SESSION_END) and
  the setup leaves the complete-observation denominators. A positive
  observation (a return that did happen) is never censored.

Nothing here writes to the database and nothing here emits a signal, an order
or an alert: this module only produces labels.
"""
import datetime as dt

import prodlib as P
import wconfig as C


# ------------------------------------------------------------ helpers -----
def family_of(level):
    """TOUCH (the trigger is a touch of the level) / BREAK (a close beyond the
    CPR band) / BREAKOUT (a close-cross of a pivot)."""
    if level in C.TOUCH_LEVELS:
        return 'TOUCH'
    if level in C.BREAK_LEVELS:
        return 'BREAK'
    return 'BREAKOUT'


def bar_values(c):
    try:
        return (float(c['open']), float(c['high']), float(c['low']),
                float(c['close']))
    except (KeyError, TypeError, ValueError):
        return None


def covers_level(c, L):
    """True when the bar's range trades through the level price."""
    b = bar_values(c)
    if not b:
        return False
    return b[2] <= L <= b[1]


def rejection_close(c, L, direction):
    """The level rejects the price.

    The bar trades the level and closes back on the side the trade was taken
    from: below the level for a BEAR, above it for a BULL. For a BELOW_CPR
    breakdown the band edge acts as resistance on the retest; for an ABOVE_CPR
    breakout the band edge acts as support on the retest.
    """
    b = bar_values(c)
    if not b:
        return False
    _, hi, lo, cl = b
    if direction == 'BULL':
        return lo <= L and cl > L
    return hi >= L and cl < L


def rejection_v2_style(c, L, direction, level):
    """The confirmation rule of the previous study's V2 variant.

    Identical to rejection_close() for every level except BELOW_CPR, where V2
    fired on a *failed breakdown* (the price trades below the band and closes
    back above it). Kept so the report can state whether the conclusions move
    under the earlier definition.
    """
    if level == 'BELOW_CPR' and direction == 'BEAR':
        b = bar_values(c)
        if not b:
            return False
        _, hi, lo, cl = b
        return lo < L and cl > L
    return rejection_close(c, L, direction)


def level_kind(level):
    if level in C.BREAK_LEVELS:
        return 'CPR_BAND'
    if level.startswith('BRK_'):
        return 'PIVOT_CROSS'
    return 'PIVOT'


def cluster_of(level, lv):
    """The cluster of source levels that defines the setup."""
    if level in C.BREAK_LEVELS:
        key = 'bc' if level == 'BELOW_CPR' else 'tc'
        return {'kind': 'CPR_BAND',
                'levels': {k: lv.get(k) for k in ('pp', 'tc', 'bc')},
                'anchor': key}
    if level.startswith('BRK_'):
        key = {'BRK_R1': 'r1', 'BRK_R2': 'r2', 'BRK_PDH': 'pdh',
               'BRK_TC': 'tc', 'BRK_S1': 's1', 'BRK_S2': 's2',
               'BRK_PDL': 'pdl', 'BRK_BC': 'bc'}.get(level)
        return {'kind': 'PIVOT_CROSS', 'levels': {key: lv.get(key)},
                'anchor': key}
    key = {'R1': 'r1', 'R2': 'r2', 'PDH': 'pdh', 'S1': 's1', 'S2': 's2',
           'PDL': 'pdl'}.get(level)
    return {'kind': 'PIVOT', 'levels': {key: lv.get(key), 'pp': lv.get('pp')},
            'anchor': key}


def _known_at(ts):
    """The time a bar stamped `ts` becomes known (bar start + 5 minutes)."""
    try:
        t = dt.datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return (t + dt.timedelta(minutes=C.BAR_MINUTES)).isoformat()


def _excursion(direction, ref, bars):
    """(mfe, mae) in index points for a position of `direction` entered at
    `ref`, measured over `bars` (the bars after the reference bar)."""
    mfe = 0.0
    mae = 0.0
    for c in bars:
        b = bar_values(c)
        if not b:
            continue
        _, hi, lo, _ = b
        if direction == 'BULL':
            fav, adv = hi - ref, ref - lo
        else:
            fav, adv = ref - lo, hi - ref
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
    return round(mfe, 2), round(mae, 2)


# ---------------------------------------------------------- annotation -----
def annotate(candles, i, lv, direction, level, instrument, extra=None):
    """Annotate one setup.

    `i` is the index of the trigger bar, `candles` the full session list
    (ordered), `lv` the day level bundle, `direction` BEAR/BULL and `level`
    the trigger level name.
    """
    out = {
        'instrument': instrument,
        'setup_level': level,
        'setup_family': family_of(level),
        'direction': direction,
        'level_kind': level_kind(level),
    }
    if extra:
        out.update(extra)

    L = P.level_price(level, lv)
    out['level_price'] = round(L, 2) if L is not None else None
    cl = cluster_of(level, lv)
    out['cluster_kind'] = cl['kind']
    out['cluster_anchor'] = cl['anchor']
    out['cluster_levels'] = cl['levels']
    out['source_levels'] = {k: lv.get(k) for k in
                            ('pp', 'tc', 'bc', 'r1', 's1', 'r2', 's2',
                             'pdh', 'pdl', 'prev_close')}

    trig = candles[i]
    b = bar_values(trig)
    out['signal_bar_ts'] = trig['timestamp']
    out['signal_known_at'] = _known_at(trig['timestamp'])
    out['signal_price'] = round(b[3], 2) if b else None
    out['signal_bar_index'] = i
    out['bars_after_signal'] = max(0, len(candles) - 1 - i)

    if L is None:
        out['observation_status'] = 'NO_LEVEL'
        out['censor_reason'] = 'NO_LEVEL_PRICE'
        out['return_status'] = 'NOT_ANNOTATED'
        out['confirm_status'] = 'NOT_ANNOTATED'
        out['baseline_status'] = 'NOT_ANNOTATED'
        return out

    window = list(range(i + 1, min(len(candles), i + 1 + C.RETURN_WINDOW_BARS)))
    out['window_bars'] = len(window)
    out['window_complete'] = len(window) >= C.RETURN_WINDOW_BARS
    out['window_last_bar_ts'] = candles[window[-1]]['timestamp'] if window else None

    # ---- the return: the first bar after the signal that trades the level
    ret_idx = None
    for j in window:
        if covers_level(candles[j], L):
            ret_idx = j
            break
    out['return_observed'] = ret_idx is not None
    out['return_bars'] = (ret_idx - i) if ret_idx is not None else None
    out['return_bar_ts'] = candles[ret_idx]['timestamp'] if ret_idx is not None else None
    out['return_known_at'] = _known_at(candles[ret_idx]['timestamp']) if ret_idx is not None else None
    out['return_price'] = round(L, 2)
    if ret_idx is not None:
        rb = bar_values(candles[ret_idx])
        out['return_bar_low'] = round(rb[2], 2) if rb else None
        out['return_bar_high'] = round(rb[1], 2) if rb else None
        out['return_tradeable'] = candles[ret_idx]['timestamp'][11:16] < C.OPEN_EOD
        out['return_after_entry_cutoff'] = not out['return_tradeable']
    else:
        out['return_bar_low'] = None
        out['return_bar_high'] = None
        out['return_tradeable'] = False
        out['return_after_entry_cutoff'] = None

    # ---- the rejection close at or after the return
    # The confirmation chain is "the price came back to the level and the level
    # rejected it". The rejection may happen in the return bar itself (the bar
    # that traded the level and closed back on the trade's side) or in a later
    # bar of the window; the strictly-later variant is recorded separately.
    conf_idx = None
    conf_strictly_after = None
    conf_at_return = False
    if ret_idx is not None:
        if rejection_close(candles[ret_idx], L, direction):
            conf_at_return = True
            conf_idx = ret_idx
        for j in range(ret_idx + 1, window[-1] + 1):
            if rejection_close(candles[j], L, direction):
                conf_strictly_after = j
                if conf_idx is None:
                    conf_idx = j
                break
    out['rejection_at_return_bar'] = conf_at_return
    out['rejection_after_return'] = conf_strictly_after is not None
    out['rejection_at_or_after_return'] = conf_idx is not None
    out['confirm_bar_ts'] = candles[conf_idx]['timestamp'] if conf_idx is not None else None
    out['confirm_known_at'] = _known_at(candles[conf_idx]['timestamp']) if conf_idx is not None else None
    out['confirm_bars'] = (conf_idx - i) if conf_idx is not None else None
    if conf_idx is not None:
        cb = bar_values(candles[conf_idx])
        out['confirm_price'] = round(cb[3], 2) if cb else None
    else:
        out['confirm_price'] = None

    # ---- the previous study's V2-style confirmation (for the comparison)
    v2_idx = None
    for j in window:
        if rejection_v2_style(candles[j], L, direction, level):
            v2_idx = j
            break
    out['v2_style_confirm_bar_ts'] = candles[v2_idx]['timestamp'] if v2_idx is not None else None
    out['v2_style_confirm_bars'] = (v2_idx - i) if v2_idx is not None else None

    # ---- excursions
    fwd = candles[i + 1:]
    mfe, mae = _excursion(direction, out['signal_price'], fwd)
    out['mfe_pts_from_signal'] = mfe
    out['mae_pts_from_signal'] = mae
    if ret_idx is not None:
        mfe2, mae2 = _excursion(direction, L, candles[ret_idx + 1:])
        out['mfe_pts_after_return'] = mfe2
        out['mae_pts_after_return'] = mae2
    else:
        out['mfe_pts_after_return'] = None
        out['mae_pts_after_return'] = None

    # ---- the production baseline (opens model): enter at the next open
    base = None
    base_status = 'NO_ENTRY_BAR'
    if i + 1 < len(candles):
        nxt = candles[i + 1]
        if C.OPEN_MIN <= nxt['timestamp'][11:16] < C.OPEN_EOD:
            base = P.evaluate_outcome(direction, float(nxt['open']), i + 1,
                                      candles, instrument)
            base_status = 'AVAILABLE' if base else 'NO_EOD_BAR'
    out['baseline_status'] = base_status
    out['baseline_entry'] = base['entry'] if base else None
    out['baseline_entry_ts'] = base['entry_time'] if base else None
    out['baseline_exit'] = base['exit'] if base else None
    out['baseline_exit_ts'] = base['exit_time'] if base else None
    out['baseline_exit_reason'] = base['exit_reason'] if base else None
    out['baseline_r'] = base['r_multiple'] if base else None
    out['baseline_label'] = base['win_loss'] if base else None
    out['baseline_points'] = base['points'] if base else None
    out['baseline_mae_pts'] = base['mae_pts'] if base else None
    out['baseline_mae_r'] = base['mae_r'] if base else None
    risk = abs((base['entry'] if base else 0.0) * C.OPEN_STOP_PCT)
    out['risk_pts'] = round(risk, 2) if risk else None
    out['mfe_r_from_signal'] = round(mfe / risk, 3) if risk else None
    out['mae_r_from_signal'] = round(mae / risk, 3) if risk else None
    if ret_idx is not None and risk:
        out['mfe_r_after_return'] = round(out['mfe_pts_after_return'] / risk, 3)
        out['mae_r_after_return'] = round(out['mae_pts_after_return'] / risk, 3)
    else:
        out['mfe_r_after_return'] = None
        out['mae_r_after_return'] = None

    # ---- counterfactual entry price difference (index points)
    if base and base['entry'] is not None:
        raw = L - base['entry']
        out['cf_entry_diff_pts_raw'] = round(raw, 2)
        out['cf_entry_diff_pts'] = round(raw if direction == 'BEAR' else -raw, 2)
    else:
        out['cf_entry_diff_pts_raw'] = None
        out['cf_entry_diff_pts'] = None

    # ---- the hypothetical filters (the annotation itself never trades)
    # WAIT_RETURN_12B: keep the setup only if the price came back to the level
    # within 12 bars and the return is tradeable (the engine's 15:20 cut-off).
    if ret_idx is None:
        out['filter_return_retained'] = False
        out['filter_return_skip_reason'] = ('CENSORED_SESSION_END'
                                            if not out['window_complete']
                                            else 'NO_RETURN_IN_12_BARS')
    elif not out['return_tradeable']:
        out['filter_return_retained'] = False
        out['filter_return_skip_reason'] = 'RETURN_AFTER_ENTRY_CUTOFF'
    else:
        out['filter_return_retained'] = True
        out['filter_return_skip_reason'] = None

    # WAIT_CONFIRM_AFTER_RETURN: keep the setup only if a rejection close
    # follows the return inside the window and an entry at the next open is
    # still inside the engine's entry window.
    if conf_idx is None:
        out['filter_confirm_retained'] = False
        if ret_idx is None:
            out['filter_confirm_skip_reason'] = ('CENSORED_SESSION_END'
                                                 if not out['window_complete']
                                                 else 'NO_RETURN')
        else:
            out['filter_confirm_skip_reason'] = ('CENSORED_SESSION_END'
                                                 if not out['window_complete']
                                                 else 'NO_REJECTION_AFTER_RETURN')
    else:
        nxt_idx = conf_idx + 1
        if nxt_idx >= len(candles):
            out['filter_confirm_retained'] = False
            out['filter_confirm_skip_reason'] = 'NO_NEXT_BAR'
        elif not (C.OPEN_MIN <= candles[nxt_idx]['timestamp'][11:16] < C.OPEN_EOD):
            out['filter_confirm_retained'] = False
            out['filter_confirm_skip_reason'] = 'ENTRY_CUTOFF'
        else:
            out['filter_confirm_retained'] = True
            out['filter_confirm_skip_reason'] = None

    # ---- the counterfactual trades of the two filters (opens-execution model)
    out['cf_return_r'] = None
    out['cf_return_label'] = None
    out['cf_return_exit_reason'] = None
    if out['filter_return_retained']:
        cf = P.evaluate_outcome(direction, L, ret_idx, candles, instrument)
        if cf:
            out['cf_return_r'] = cf['r_multiple']
            out['cf_return_label'] = cf['win_loss']
            out['cf_return_exit_reason'] = cf['exit_reason']
            out['cf_return_entry_ts'] = cf['entry_time']
    out['cf_confirm_r'] = None
    out['cf_confirm_label'] = None
    out['cf_confirm_exit_reason'] = None
    out['cf_return_entry_price'] = None
    out['cf_confirm_entry_price'] = None
    out['cf_confirm_entry_diff_pts'] = None
    if out['filter_confirm_retained']:
        nxt_idx = conf_idx + 1
        nb = bar_values(candles[nxt_idx])
        if nb:
            cf = P.evaluate_outcome(direction, nb[0], nxt_idx, candles, instrument)
            if cf:
                out['cf_confirm_r'] = cf['r_multiple']
                out['cf_confirm_label'] = cf['win_loss']
                out['cf_confirm_exit_reason'] = cf['exit_reason']
                out['cf_confirm_entry_ts'] = cf['entry_time']
                out['cf_confirm_entry_price'] = round(nb[0], 2)
                if base and base['entry'] is not None:
                    raw = nb[0] - base['entry']
                    out['cf_confirm_entry_diff_pts'] = round(
                        raw if direction == 'BEAR' else -raw, 2)
    if out['filter_return_retained']:
        out['cf_return_entry_price'] = round(L, 2)

    # ---- the observation status
    if out['window_complete']:
        out['observation_status'] = 'OK'
        out['censor_reason'] = None
    elif ret_idx is not None:
        # a positive observation is never censored
        out['observation_status'] = 'OK'
        out['censor_reason'] = ('WINDOW_TRUNCATED_%d_OF_%d_BARS_BUT_RETURN_OBSERVED'
                                % (out['window_bars'], C.RETURN_WINDOW_BARS))
    else:
        out['observation_status'] = 'CENSORED_SESSION_END'
        out['censor_reason'] = ('ONLY_%d_OF_%d_BARS_AFTER_SIGNAL'
                                % (out['window_bars'], C.RETURN_WINDOW_BARS))
    out['return_status'] = ('OBSERVED' if ret_idx is not None
                            else ('CENSORED' if not out['window_complete']
                                  else 'NOT_RETURNED'))
    if conf_idx is not None:
        out['confirm_status'] = 'OBSERVED'
    elif ret_idx is None:
        out['confirm_status'] = 'NO_RETURN'
    elif not out['window_complete']:
        out['confirm_status'] = 'CENSORED'
    else:
        out['confirm_status'] = 'NOT_CONFIRMED'
    return out
