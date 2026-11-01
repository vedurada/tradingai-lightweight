"""Driver for the shadow-only setup-return measurement.

Reads only the sqlite snapshot of the live database (mode=ro) and writes only
into this study's own outputs/reports directories. No production table, file,
process or service is touched; no signal, order or alert is produced.

Populations
-----------
A_RECORDED_BOOK          the recorded live-engine signal book (paper_align)
B_CURRENT_ENGINE_REPLAY  the current production engine replayed over the
                         same sessions
C_LIVE_TRADES            the six real live trades (origin = live-watch)
"""
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import annotation as A
import prodlib as P
import wconfig as C


# ------------------------------------------------------------- data io -----
def connect(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_candles(con, inst):
    rows = con.execute(
        'SELECT timestamp,open,high,low,close,volume,source,is_complete '
        'FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp',
        (inst,)).fetchall()
    return [dict(r) for r in rows]


def group_sessions(candles):
    out = {}
    for c in candles:
        out.setdefault(c['timestamp'][:10], []).append(c)
    return out


def prev_session_ohlc(sessions, day):
    """Max high / min low / last close of the last session before `day`."""
    days = sorted(sessions)
    prior = [d for d in days if d < day]
    if not prior:
        return None
    d = prior[-1]
    cs = sessions[d]
    try:
        return {'date': d,
                'high': max(float(c['high']) for c in cs),
                'low': min(float(c['low']) for c in cs),
                'close': float(cs[-1]['close'])}
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------- signal replay -----
def replay_session(candles, lv):
    """Current production rules for one session -> (direction, level, index).

    Mirrors run_opens_range(variant='plain'): the SHORT_ONLY base scan (BEAR),
    the SKIP_FRIDAY gate, the entry window [09:20,15:20) and the breakout
    add-on fallback.
    """
    cs = [c for c in candles if c['timestamp'][11:16] < C.SIGNAL_CUTOFF]
    if len(cs) < C.MIN_CANDLES:
        return None, 'short_day'
    sig = None
    fri = False
    for i, c in enumerate(cs):
        b = P.bear_trigger(c, lv)
        if not b:
            continue
        dr = 'BEAR'
        if P.friday_skip(dr, c['timestamp'][:10]):
            fri = True
            break
        if i + 1 >= len(cs):
            continue
        nt = cs[i + 1]['timestamp'][11:16]
        if not (C.OPEN_MIN <= nt < C.OPEN_EOD):
            continue
        sig = (dr, b, i)
        break
    if not sig and C.BREAKOUT_ADDON:
        bs = P.breakout_signal(cs, lv)
        if bs is not None and not P.friday_skip(bs[0], cs[0]['timestamp'][:10]):
            sig = bs
    if not sig:
        return None, ('skip_friday' if fri else 'no_signal')
    return sig, None


# ---------------------------------------------------------------- books ----
def book_recorded(con, sessions_by_inst):
    """Book A: the recorded live-engine signal book (paper_align, plain)."""
    rows = con.execute(
        "SELECT session_date,instrument_id,direction,level,entry_time,"
        "entry_price,stop_price,target_price,exit_time,exit_price,"
        "exit_reason,r_multiple,result FROM paper_align "
        "WHERE variant='plain' AND instrument_id IN ('NIFTY','BANKNIFTY') "
        "ORDER BY session_date,instrument_id").fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        inst = rec['instrument_id']
        day = rec['session_date']
        candles = sessions_by_inst.get(inst, {}).get(day, [])
        if not candles:
            out.append((rec, None, None, 'NO_CANDLES'))
            continue
        prev = prev_session_ohlc(sessions_by_inst[inst], day)
        if not prev:
            out.append((rec, None, None, 'NO_PREV_SESSION'))
            continue
        lv = P.day_levels(prev['high'], prev['low'], prev['close'])
        if not lv:
            out.append((rec, None, None, 'NO_LEVELS'))
            continue
        et = str(rec['entry_time'] or '')[:16].replace('T', ' ')
        idx = next((k for k, c in enumerate(candles)
                    if c['timestamp'][:16].replace('T', ' ') == et), None)
        if idx is None or idx == 0:
            out.append((rec, None, None, 'NO_ENTRY_BAR'))
            continue
        out.append((rec, candles, idx - 1, 'OK'))
    return out


def book_replay(con, sessions_by_inst):
    """Book B: the current production engine replayed over every session."""
    out = []
    for inst in C.INSTRUMENTS:
        sessions = sessions_by_inst.get(inst, {})
        for day in sorted(sessions):
            candles = sessions[day]
            prev = prev_session_ohlc(sessions, day)
            if not prev:
                out.append((inst, day, None, None, 'NO_PREV_SESSION'))
                continue
            lv = P.day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                out.append((inst, day, None, None, 'NO_LEVELS'))
                continue
            sig, skip = replay_session(candles, lv)
            if not sig:
                out.append((inst, day, None, None, skip))
                continue
            dr, lvl, i = sig
            out.append((inst, day, (dr, lvl, i), candles, 'OK'))
    return out


def live_rows(con):
    out = []
    for r in con.execute('SELECT * FROM paper_trades').fetchall():
        rec = dict(r)
        try:
            ev = json.loads(rec['qualification_evidence'] or '{}')
        except (TypeError, ValueError):
            ev = {}
        if ev.get('origin') == 'live-watch':
            rec['_ev'] = ev
            out.append(rec)
    return out


def index_r(direction, entry, exit_px):
    """R of a trade from the index points (the production 0.5 % stop)."""
    try:
        risk = abs(float(entry) * C.OPEN_STOP_PCT)
        pts = (float(exit_px) - float(entry)) if direction == 'BULL' \
            else (float(entry) - float(exit_px))
        return round(pts / risk, 3) if risk else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- main -----
def main():
    os.makedirs(C.OUT_DIR, exist_ok=True)
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    con = connect(C.SNAPSHOT_DB)
    rows = []
    skip_buckets = {}
    try:
        sessions_by_inst = {i: group_sessions(load_candles(con, i))
                            for i in C.INSTRUMENTS}

        # ---- Book A: the recorded live-engine book
        for rec, candles, trig, status in book_recorded(con, sessions_by_inst):
            inst = rec['instrument_id']
            day = rec['session_date']
            if status != 'OK':
                rows.append({'book': 'A_RECORDED_BOOK', 'instrument': inst,
                             'session_date': day, 'setup_level': rec['level'],
                             'setup_id': '%s|%s|%s' % (inst, day, rec['level']),
                             'observation_status': status,
                             'censor_reason': status})
                continue
            prev = prev_session_ohlc(sessions_by_inst[inst], day)
            lv = P.day_levels(prev['high'], prev['low'], prev['close'])
            extra = {
                'book': 'A_RECORDED_BOOK',
                'session_date': day,
                'setup_id': '%s|%s|%s' % (inst, day, rec['level']),
                'baseline_source': 'RECORDED_PRODUCTION_RESULT',
                'recorded_entry': rec['entry_price'],
                'recorded_exit': rec['exit_price'],
                'recorded_exit_ts': rec['exit_time'],
                'recorded_exit_reason': rec['exit_reason'],
                'recorded_r': rec['r_multiple'],
                'recorded_label': rec['result'],
            }
            ann = A.annotate(candles, trig, lv, rec['direction'], rec['level'],
                             inst, extra)
            ann['recorded_entry_diff_pts'] = (round(ann['baseline_entry'] -
                                                     rec['entry_price'], 2)
                                              if ann['baseline_entry'] is not None
                                              and rec['entry_price'] is not None
                                              else None)
            # the production result is the reference for book A
            ann['outcome_source'] = 'RECORDED_PRODUCTION_RESULT'
            ann['outcome_label'] = rec['result']
            ann['outcome_r'] = rec['r_multiple']
            rows.append(ann)

        # ---- Book B: the current engine replayed
        for inst, day, sig, candles, status in book_replay(con, sessions_by_inst):
            if sig is None:
                skip_buckets[status] = skip_buckets.get(status, 0) + 1
                continue
            dr, lvl, i = sig
            prev = prev_session_ohlc(sessions_by_inst[inst], day)
            lv = P.day_levels(prev['high'], prev['low'], prev['close'])
            extra = {
                'book': 'B_CURRENT_ENGINE_REPLAY',
                'session_date': day,
                'setup_id': '%s|%s|%s' % (inst, day, lvl),
                'baseline_source': 'OPENS_MODEL_REPLAY',
                'recorded_entry': None,
            }
            ann = A.annotate(candles, i, lv, dr, lvl, inst, extra)
            ann['outcome_source'] = 'OPENS_MODEL_REPLAY'
            ann['outcome_label'] = ann['baseline_label']
            ann['outcome_r'] = ann['baseline_r']
            rows.append(ann)

        # ---- Book C: the six real live trades
        for rec in live_rows(con):
            inst = rec['instrument_id']
            ev = rec['_ev']
            day = str(ev.get('signal_time') or rec['entry_time'])[:10]
            candles = sessions_by_inst.get(inst, {}).get(day, [])
            prev = prev_session_ohlc(sessions_by_inst[inst], day) if candles else None
            lv = P.day_levels(prev['high'], prev['low'], prev['close']) if prev else None
            level = ev.get('scenario')
            # the live-watch rows store BEAR/BULL; the older test rows used
            # BEARISH/BULLISH - accept both spellings
            d_raw = str(rec['direction'] or '').upper()
            direction = ('BEAR' if d_raw in ('BEAR', 'BEARISH', 'SHORT')
                         else 'BULL')
            trig = None
            if candles and ev.get('signal_time'):
                st = str(ev['signal_time'])[:16].replace('T', ' ')
                trig = next((k for k, c in enumerate(candles)
                             if c['timestamp'][:16].replace('T', ' ') == st), None)
            extra = {
                'book': 'C_LIVE_TRADES',
                'session_date': day,
                'setup_id': '%s|%s' % (inst, rec['trade_id']),
                'live_trade_id': rec['trade_id'],
                'baseline_source': 'RECORDED_LIVE_TRADE',
                'recorded_entry': rec['entry'],
                'recorded_exit': rec['exit_price'],
                'recorded_exit_ts': rec['exit_time'],
                'recorded_exit_reason': rec['exit_reason'],
                'recorded_stop': rec['stop'],
                'recorded_target': rec['target'],
                'recorded_paper_pnl': rec['paper_pnl'],
                'recorded_entry_time': rec['entry_time'],
                'recorded_signal_time': ev.get('signal_time'),
                'recorded_forming_ts': ev.get('forming_ts'),
                'recorded_feed_n': ev.get('feed_n'),
            }
            if trig is None or lv is None:
                rows.append({'book': 'C_LIVE_TRADES', 'instrument': inst,
                             'session_date': day, 'setup_level': level,
                             'setup_id': '%s|%s' % (inst, rec['trade_id']),
                             'observation_status': 'NO_TRIGGER_BAR',
                             'censor_reason': 'NO_TRIGGER_BAR'})
                continue
            ann = A.annotate(candles, trig, lv, direction, level, inst, extra)
            # the recorded live trade is the production reference: keep the
            # opens-model values under model_* and put the live values in the
            # baseline_* fields.
            ann['model_entry'] = ann['baseline_entry']
            ann['model_exit'] = ann['baseline_exit']
            ann['model_exit_ts'] = ann['baseline_exit_ts']
            ann['model_exit_reason'] = ann['baseline_exit_reason']
            ann['model_r'] = ann['baseline_r']
            ann['model_label'] = ann['baseline_label']
            ann['baseline_entry'] = rec['entry']
            ann['baseline_entry_ts'] = rec['entry_time']
            ann['baseline_exit'] = rec['exit_price']
            ann['baseline_exit_ts'] = rec['exit_time']
            ann['baseline_exit_reason'] = rec['exit_reason']
            ann['baseline_r'] = index_r(direction, rec['entry'],
                                        rec['exit_price'])
            ann['baseline_points'] = (round((float(rec['entry']) -
                                             float(rec['exit_price'])), 2)
                                      if direction == 'BEAR' else
                                      round((float(rec['exit_price']) -
                                             float(rec['entry'])), 2))
            ann['baseline_label'] = 'WIN' if (ann['baseline_r'] or 0) > 0 else \
                ('LOSS' if (ann['baseline_r'] or 0) < 0 else 'FLAT')
            ann['baseline_status'] = 'AVAILABLE'
            ann['outcome_source'] = 'RECORDED_LIVE_TRADE'
            ann['outcome_label'] = ann['baseline_label']
            ann['outcome_r'] = ann['baseline_r']
            rows.append(ann)
    finally:
        con.close()

    # ---- the outputs
    fields = ['book', 'setup_id', 'instrument', 'session_date', 'setup_family',
              'setup_level', 'level_kind', 'direction', 'level_price',
              'cluster_kind', 'cluster_anchor', 'cluster_levels',
              'source_levels', 'signal_bar_ts', 'signal_known_at',
              'signal_price', 'signal_bar_index', 'bars_after_signal',
              'window_bars', 'window_complete', 'window_last_bar_ts',
              'return_observed', 'return_status', 'return_bars',
              'return_bar_ts', 'return_known_at', 'return_price',
              'return_bar_low', 'return_bar_high', 'return_tradeable',
              'return_after_entry_cutoff', 'rejection_at_return_bar',
              'rejection_after_return', 'confirm_status', 'confirm_bars',
              'confirm_bar_ts', 'confirm_known_at', 'confirm_price',
              'v2_style_confirm_bar_ts', 'v2_style_confirm_bars',
              'mfe_pts_from_signal', 'mae_pts_from_signal',
              'mfe_r_from_signal', 'mae_r_from_signal',
              'mfe_pts_after_return', 'mae_pts_after_return',
              'mfe_r_after_return', 'mae_r_after_return',
              'baseline_source', 'baseline_status', 'baseline_entry',
              'baseline_entry_ts', 'baseline_exit', 'baseline_exit_ts',
              'baseline_exit_reason', 'baseline_r', 'baseline_label',
              'baseline_points', 'baseline_mae_pts', 'baseline_mae_r',
              'risk_pts', 'cf_entry_diff_pts', 'cf_entry_diff_pts_raw',
              'filter_return_retained', 'filter_return_skip_reason',
              'filter_confirm_retained', 'filter_confirm_skip_reason',
              'cf_return_r', 'cf_return_label', 'cf_return_exit_reason',
              'cf_return_entry_ts', 'cf_confirm_r', 'cf_confirm_label',
              'cf_confirm_exit_reason', 'cf_confirm_entry_ts',
              'cf_return_entry_price', 'cf_confirm_entry_price',
              'cf_confirm_entry_diff_pts',
              'observation_status', 'censor_reason',
              'recorded_entry', 'recorded_exit', 'recorded_exit_ts',
              'recorded_exit_reason', 'recorded_r', 'recorded_label',
              'recorded_entry_diff_pts', 'live_trade_id', 'recorded_stop',
              'recorded_target', 'recorded_paper_pnl', 'recorded_entry_time',
              'recorded_signal_time', 'recorded_forming_ts', 'recorded_feed_n',
              'model_entry', 'model_exit', 'model_exit_ts',
              'model_exit_reason', 'model_r', 'model_label',
              'outcome_source', 'outcome_label', 'outcome_r']

    def fmt(v):
        if isinstance(v, (dict, list)):
            return json.dumps(v, sort_keys=True, default=str)
        return v

    csv_path = os.path.join(C.OUT_DIR, 'shadow_annotations.csv')
    with open(csv_path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(r.get(k)) for k in fields})

    payload = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'snapshot': C.SNAPSHOT_DB,
        'constants': {'return_window_bars': C.RETURN_WINDOW_BARS,
                      'bar_minutes': C.BAR_MINUTES,
                      'stop_pct': C.OPEN_STOP_PCT, 'target_pct': C.OPEN_TARGET_PCT,
                      'entry_window': [C.OPEN_MIN, C.OPEN_EOD]},
        'replay_skip_buckets': skip_buckets,
        'annotations': rows,
    }
    with open(os.path.join(C.OUT_DIR, 'shadow_annotations.json'), 'w') as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)

    print('annotations:', len(rows))
    for book in C.BOARDS:
        b = [r for r in rows if r.get('book') == book]
        if not b:
            continue
        print('\n==', book, len(b))
        for fam in C.FAMILIES:
            f = [r for r in b if r.get('setup_family') == fam]
            if not f:
                continue
            ok = [r for r in f if r.get('observation_status') == 'OK']
            ret = [r for r in ok if r.get('return_observed')]
            conf = [r for r in ok if r.get('rejection_after_return')]
            print('   %-9s n=%3d ok=%3d returned=%3d (%.1f%%) confirm=%3d'
                  % (fam, len(f), len(ok), len(ret),
                     100.0 * len(ret) / len(ok) if ok else 0,
                     len(conf)))
    return payload


if __name__ == '__main__':
    main()
