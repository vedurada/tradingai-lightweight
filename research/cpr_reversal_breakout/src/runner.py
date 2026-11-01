"""Candidate variant runner: scan -> select -> execute -> normalise trades.

READ-ONLY against the market database (shared.common.ro_conn opens the SQLite
file in `mode=ro`). The execution model is the baseline's own:

    entry  = open of the candle after the trigger, inside [09:20, 15:20)
    exits  = subsequent OPENS only, stop checked before target
    flat   = the 15:20 open (session without a 15:20 candle is dropped, exactly
             like the baseline's `missing_eod` bucket)
    labels = production decay_win (short-premium tolerance labelling)
    R      = production semantics: STOP = -1.0, TARGET = target/stop, EOD = move/risk

`exit_model`:
  'parity'   -> 0.5% stop / 2% target (identical to the baseline) so that the
                comparison isolates SIGNAL SELECTION.
  'structure'-> stop/target taken from the level geometry (invalidation +
                next relevant level).
"""
from __future__ import annotations

from app.research.cpr_trigger_engine import exits_opens, decay_win

from common import (LOT_SIZES, MIN_SESSION_CANDLES, OPEN_EOD, STOP_PCT,
                    TARGET_PCT, load_candles, load_sessions, lot,
                    exits_opens_abs, period_of, prev_session_ohlc, ro_conn,
                    day_levels, scan_candles)
import candidate as cand_mod


def run_variant(instrument, date_start, date_end, cfg, db_path=None,
                variant_id='candidate'):
    """Run one candidate variant over the stored sessions. Returns a dict with
    trades, per-session skip buckets and rejection counters."""
    conn = ro_conn(db_path)
    try:
        days = load_sessions(conn, instrument, date_start, date_end)
        trades, skipped = [], {'no_levels': 0, 'short_day': 0,
                               'missing_eod': 0, 'invalid_stop': 0,
                               'no_signal': 0}
        counters = cand_mod.new_counters()
        daily_scan = {}
        for d in days:
            prev = prev_session_ohlc(conn, instrument, d)
            if not prev:
                skipped['no_levels'] += 1
                continue
            lv = day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                skipped['no_levels'] += 1
                continue
            all_candles = load_candles(conn, instrument, d)
            cands, c = cand_mod.scan_session(all_candles, lv, cfg)
            for k, v in c.items():
                counters[k] = counters.get(k, 0) + v
            daily_scan[d] = {'levels': lv, 'candidates': len(cands)}
            if c['rejected_short_day']:
                skipped['short_day'] += 1
                continue
            chosen = cand_mod.select_candidate(cands, cfg, counters)
            if chosen is None:
                skipped['no_signal'] += 1
                continue
            candles = scan_candles(all_candles)
            eod = [x for x in candles if str(x['timestamp'])[11:16] == OPEN_EOD]
            if not eod:
                skipped['missing_eod'] += 1
                continue
            t = _execute(chosen, candles, cfg)
            if t is None:
                skipped['invalid_stop'] += 1
                continue
            t.update(instrument=instrument, session_date=d, variant=variant_id,
                     period=period_of(d, cfg), level_price=chosen.level)
            t['signal_kind'] = chosen.kind
            t['family'] = chosen.family
            t['level'] = chosen.level_name
            t['structure_stop'] = chosen.structure_stop
            t['structure_target'] = chosen.structure_target
            t['next_level'] = chosen.next_level
            t['next_level_name'] = chosen.next_level_name
            t['signal_time'] = chosen.confirm_time
            t['trigger_time'] = chosen.trigger_time
            t['friday'] = _is_friday(d)
            trades.append(t)
        return {'variant': variant_id, 'instrument': instrument,
                'date_start': date_start, 'date_end': date_end,
                'sessions': len(days), 'trades': trades,
                'skipped': skipped, 'counters': counters,
                'daily_scan': daily_scan}
    finally:
        conn.close()


def _is_friday(day_iso):
    from datetime import datetime
    try:
        return datetime.fromisoformat(day_iso).weekday() == 4
    except (TypeError, ValueError):
        return False


def _execute(chosen, candles, cfg):
    """Fill the chosen candidate and run the exit walk. Returns a trade dict
    or None when the structure stop is already invalid at entry."""
    entry = chosen.entry
    direction = chosen.direction
    model = cfg.get('exit_model', 'parity')
    stop_px, tgt_px = None, None
    if model == 'structure':
        stop_px = chosen.structure_stop
        if stop_px is None:
            return None
        if direction == 'BULL' and not (stop_px < entry):
            return None
        if direction == 'BEAR' and not (stop_px > entry):
            return None
        tgt_px = chosen.structure_target
        if tgt_px is None:      # no next level -> run to the stop/EOD only
            tgt_px = float('inf') if direction == 'BULL' else float('-inf')
        stop_pct = abs(entry - stop_px) / entry if entry else STOP_PCT
        risk_pts = abs(entry - stop_px)
    else:
        stop_pct = STOP_PCT
        risk_pts = entry * STOP_PCT

    entry_idx = chosen.entry_idx
    opens = [(c['timestamp'], c['open']) for c in candles[entry_idx + 1:]]
    eod = [c for c in candles if str(c['timestamp'])[11:16] == OPEN_EOD][0]

    if model == 'structure':
        hit = exits_opens_abs(direction, entry, stop_px, tgt_px, opens)
    else:
        hit = exits_opens(direction, entry, STOP_PCT, TARGET_PCT, opens)

    if hit is None:
        last = float(eod['open'])
        r = round(((last - entry) if direction == 'BULL' else (entry - last))
                  / risk_pts, 3) if risk_pts else 0.0
        xp, how, xt = round(last, 2), 'EOD-1520', eod['timestamp']
    else:
        r, xp, how, xt = hit

    pts = round((xp - entry) if direction == 'BULL' else (entry - xp), 4)
    return {'entry_time': chosen.entry_time, 'entry': round(entry, 2),
            'stop': round(stop_px, 2) if model == 'structure'
                    else round(entry * (1 - STOP_PCT) if direction == 'BULL'
                               else entry * (1 + STOP_PCT), 2),
            'target': (round(tgt_px, 2) if model == 'structure'
                       else round(entry * (1 + TARGET_PCT) if direction == 'BULL'
                                  else entry * (1 - TARGET_PCT), 2)),
            'exit_time': xt or '', 'exit': xp, 'exit_reason': how,
            'r_multiple': round(r, 3), 'points': pts,
            'risk_pts': round(risk_pts, 2), 'direction': direction}


def run_and_label(instrument, date_start, date_end, cfg, db_path=None,
                  variant_id='candidate'):
    """run_variant + per-instrument ₹ P&L, win/loss labels and cost columns."""
    res = run_variant(instrument, date_start, date_end, cfg, db_path,
                      variant_id)
    for t in res['trades']:
        _label(t, instrument, cfg)
    return res


def _label(t, instrument, cfg):
    l = LOT_SIZES.get(instrument, 65)
    gross = t['points'] * l
    cost = float(cfg['costs'].get('brokerage_rs', 40.0)) + \
        float(cfg['costs'].get('slippage_pts', 0.5)) * l
    t['lot_size'] = l
    t['pnl_gross_rs'] = round(gross, 2)
    t['cost_rs'] = round(cost, 2)
    t['pnl_net_rs'] = round(gross - cost, 2)
    t['risk_rs'] = round(t['risk_pts'] * l, 2)
    t['r_net'] = round(t['r_multiple'] - (cost / t['risk_rs'])
                       if t['risk_rs'] else t['r_multiple'], 4)
    t['win_loss'] = decay_win(t['direction'], t['entry'], t['exit'],
                              t['r_multiple'], instrument)
    try:
        from datetime import datetime
        a = datetime.fromisoformat(t['entry_time'])
        b = datetime.fromisoformat(t['exit_time'])
        t['holding_minutes'] = round((b - a).total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        t['holding_minutes'] = None
