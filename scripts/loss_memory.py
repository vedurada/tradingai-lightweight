#!/usr/bin/env python3
"""Loss-memory learner for the plain CPR paper book (READ-ONLY).

Additive layer. It mines closed NIFTY/BANKNIFTY paper trades of the plain
engine variant (no filter), groups them into configurable slices (instrument /
direction / level / regime / day-of-week) and records every slice with negative
expectancy as a learned "avoid rule". Slices that include the ``vix_dir``
dimension are trained on all stored variants pooled (so small VIX-conditional
samples are not halved). The live guard (scripts/mistake_guard.py) consumes this
memory; the paper-book overlay (scripts/veto_paper_book.py) annotates the same
book.

It reads the database only. Never touches engine, trigger, alert or frontend
code.

  memory plain   : data/loss_memory.plain.json
  config         : data/loss_memory_config.json   (optional; defaults below)

Decay: scripts/veto_score.py can suppress rules into data/loss_memory_decay.json;
evaluate() and active_rules() skip suppressed rules so the live guard and the
book overlay stop applying them.
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
ENGINES = ('plain',)
DEFAULT_ENGINE = 'plain'
CFG_PATH = os.path.join(BASE, 'data', 'loss_memory_config.json')
DECAY_PATH = os.path.join(BASE, 'data', 'loss_memory_decay.json')

DEFAULTS = {
    "enabled": True,
    "enforce": True,
    "notify_skip": True,
    "instruments": ["NIFTY", "BANKNIFTY"],
    "min_samples": 8,
    "win_rate_floor": 0.45,
    "negative_r_samples": 15,
    "negative_r_threshold": -2.0,
    "zero_win_min_losses": 5,
    "slices": [
        ["instrument_id"],
        ["direction"],
        ["level"],
        ["regime"],
        ["dow"],
        ["instrument_id", "direction", "level", "regime"],
        ["direction", "vix_dir"],
        ["direction", "level", "vix_dir"],
        ["instrument_id", "direction", "level", "vix_dir"]
    ],
    "decay": {
        "min_vetoes": 3,
        "accuracy_floor": 0.5,
        "net_r_floor": 0.5,
        "recent_sessions": 21
    }
}


def memory_path(engine=DEFAULT_ENGINE):
    return os.path.join(BASE, 'data', 'loss_memory.%s.json' % engine)


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CFG_PATH) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def _prev_session_width(conn, inst, day):
    """CPR width % of the session immediately before ``day`` (same rule as
    weekly_review.width_of, so regime labels match the reviewed book)."""
    row = conn.execute(
        'SELECT MAX(high) h, MIN(low) l FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)=(SELECT MAX(substr(timestamp,1,10)) FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)<?)', (inst, inst, day)).fetchone()
    if not row or row['h'] is None:
        return None
    last = conn.execute(
        'SELECT close FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)='
        '(SELECT MAX(substr(timestamp,1,10)) FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)<?) ORDER BY timestamp DESC LIMIT 1', (inst, inst, day)).fetchone()
    if not last or last['close'] is None:
        return None
    try:
        from app.research.cpr_strategy_engine import calculate_cpr
        return calculate_cpr(float(row['h']), float(row['l']), float(last['close']))['width_pct']
    except Exception:
        return None


def _regime(width):
    if width is None:
        return 'UNKNOWN'
    try:
        from app.research.cpr_strategy_engine import classify_cpr
        return classify_cpr(width)
    except Exception:
        return 'UNKNOWN'


def _dow(session_date):
    try:
        return datetime.strptime(session_date, '%Y-%m-%d').strftime('%a')
    except (ValueError, TypeError):
        return 'UNK'


VIX_FLAT = 0.25


def vix_dir_from_pct(pct):
    """RISING / FALLING / FLAT from an India VIX percent move."""
    if pct is None:
        return None
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return None
    if pct > VIX_FLAT:
        return 'RISING'
    if pct < -VIX_FLAT:
        return 'FALLING'
    return 'FLAT'


def _ts_norm(ts, day):
    s = str(ts or '')
    if 'T' in s:
        return s
    if len(s) >= 16:
        return '%sT%s:00+05:30' % (s[:10], s[11:16])
    return day + 'T09:15:00+05:30'


def vix_dir_for(conn, day, upto_ts=None):
    """India VIX direction from the prior session close to the entry instant
    (``upto_ts``) or, if absent, to the session close. Live-knowable at entry and
    reproducible historically. Returns RISING / FALLING / FLAT or None."""
    try:
        prev = conn.execute(
            "SELECT close FROM market_candles_5m WHERE instrument_id='INDIA_VIX' "
            "AND substr(timestamp,1,10) < ? ORDER BY timestamp DESC LIMIT 1",
            (day,)).fetchone()
        if not prev or not prev['close']:
            return None
        if upto_ts:
            cur = conn.execute(
                "SELECT open FROM market_candles_5m WHERE instrument_id='INDIA_VIX' "
                "AND substr(timestamp,1,10)=? AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
                (day, _ts_norm(upto_ts, day))).fetchone()
        else:
            cur = None
        if not cur:
            cur = conn.execute(
                "SELECT open FROM market_candles_5m WHERE instrument_id='INDIA_VIX' "
                "AND substr(timestamp,1,10)=? ORDER BY timestamp ASC LIMIT 1",
                (day,)).fetchone()
        if not cur or not cur['open']:
            return None
        return vix_dir_from_pct((float(cur['open']) / float(prev['close']) - 1.0) * 100.0)
    except Exception:
        return None


def fingerprint_book(conn, row):
    """Slice vocabulary for a stored paper_align row (used by the learner and
    the paper-book veto overlay)."""
    try:
        entry = row['entry_time']
    except (KeyError, IndexError, TypeError):
        entry = None
    return {
        'instrument_id': row['instrument_id'],
        'direction': row['direction'],
        'level': row['level'],
        'regime': _regime(_prev_session_width(conn, row['instrument_id'], row['session_date'])),
        'dow': _dow(row['session_date']),
        'vix_dir': vix_dir_for(conn, row['session_date'], entry),
    }


def build_memory(engine=DEFAULT_ENGINE, as_of=None):
    cfg = load_config()
    as_of = as_of or datetime.now(IST).date().isoformat()
    from app.core.db import get_conn
    conn = get_conn()
    try:
        insts = tuple(cfg['instruments'])
        placeholders = ','.join('?' * len(insts))
        rows = conn.execute(
            "SELECT session_date, instrument_id, direction, level, entry_time, "
            "variant, r_multiple, result "
            "FROM paper_align WHERE variant='plain' AND state='SIGNAL' "
            "AND instrument_id IN (%s) AND result IN ('WIN','LOSS') "
            "AND r_multiple IS NOT NULL AND session_date < ? ORDER BY session_date"
            % placeholders, insts + (as_of,)).fetchall()
        recs = []
        for r in rows:
            fp = fingerprint_book(conn, r)
            fp['r'] = float(r['r_multiple'] or 0.0)
            fp['result'] = r['result']
            fp['_variant'] = r['variant']
            recs.append(fp)
        mine = [x for x in recs if x['_variant'] == engine]
    finally:
        try:
            conn.close()
        except Exception:
            pass

    rules = []
    for keys in cfg['slices']:
        # plain-only learner: every slice is trained on the plain book.
        pool = mine
        groups = defaultdict(list)
        for rec in pool:
            if 'vix_dir' in keys and rec.get('vix_dir') is None:
                continue
            groups[tuple(rec[k] for k in keys)].append(rec)
        for value, grp in groups.items():
            n = len(grp)
            wins = sum(1 for x in grp if x['result'] == 'WIN')
            losses = n - wins
            total_r = round(sum(x['r'] for x in grp), 2)
            wr = round(wins / n, 4) if n else 0.0
            reason = None
            if losses >= cfg['zero_win_min_losses'] and wins == 0:
                reason = 'ZERO_WIN'
            elif n >= cfg['min_samples'] and wr < cfg['win_rate_floor'] and total_r < 0:
                reason = 'LOW_WIN_RATE'
            elif n >= cfg['negative_r_samples'] and total_r <= cfg['negative_r_threshold']:
                reason = 'NEGATIVE_R'
            if reason:
                rules.append({
                    'engine': engine,
                    'keys': dict(zip(keys, value)),
                    'n': n, 'wins': wins, 'losses': losses,
                    'win_rate': wr, 'total_r': total_r, 'reason': reason,
                })
    rules.sort(key=lambda r: (r['total_r'], -len(r['keys'])))
    return {
        'engine': engine,
        'generated_at': datetime.now(IST).isoformat(timespec='seconds'),
        'as_of': as_of,
        'trained_trades': len(mine),
        'pooled_trades': len(recs),
        'config': cfg,
        'rules': rules,
    }


def save_memory(memory, engine=None):
    engine = engine or memory.get('engine', DEFAULT_ENGINE)
    p = memory_path(engine)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(memory, f, indent=2, sort_keys=True)
    os.replace(tmp, p)
    return p


def load_memory(engine=DEFAULT_ENGINE):
    try:
        with open(memory_path(engine)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def rule_id(keys):
    return json.dumps(keys, sort_keys=True)


def load_decay():
    try:
        with open(DECAY_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'suppressed': []}


def suppressed_ids(engine=DEFAULT_ENGINE):
    return {rule_id(r.get('keys', {}))
            for r in load_decay().get('suppressed', []) if r.get('engine') == engine}


def suppressed(engine=DEFAULT_ENGINE):
    return [r for r in load_decay().get('suppressed', []) if r.get('engine') == engine]


def active_rules(memory, engine=None):
    engine = engine or (memory or {}).get('engine', DEFAULT_ENGINE)
    ids = suppressed_ids(engine)
    return [r for r in (memory or {}).get('rules', []) if rule_id(r.get('keys', {})) not in ids]


def fingerprint_live(decision, trade, instrument, day=None, vix_dir=None):
    """Same slice vocabulary as the trained book, from a live /api/decision."""
    day = day or datetime.now(IST).date().isoformat()
    cpr = decision.get('cpr') or {}
    return {
        'instrument_id': instrument,
        'direction': trade.get('direction'),
        'level': trade.get('scenario') or trade.get('level'),
        'regime': cpr.get('cpr_type') or 'UNKNOWN',
        'dow': _dow(day),
        'vix_dir': vix_dir,
    }


def evaluate(memory, fingerprint):
    """ALLOW or VETO a live fingerprint against the learned rules (OR-logic)."""
    if not memory:
        return {'action': 'ALLOW', 'reason': 'NO_MEMORY', 'matches': []}
    if not memory.get('config', {}).get('enabled', True):
        return {'action': 'ALLOW', 'reason': 'DISABLED', 'matches': []}
    matches = [r for r in active_rules(memory)
               if all(fingerprint.get(k) == v for k, v in r['keys'].items())]
    if not matches:
        return {'action': 'ALLOW', 'reason': 'NO_MATCH', 'matches': []}
    worst = min(matches, key=lambda r: r['total_r'])
    return {'action': 'VETO', 'reason': worst['reason'],
            'matches': matches, 'worst': worst}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default=DEFAULT_ENGINE, choices=ENGINES)
    ap.add_argument('--as-of', default=None, help='train on sessions before this date')
    args = ap.parse_args()
    mem = build_memory(args.engine, args.as_of)
    path = save_memory(mem)
    print('loss-memory rebuilt [%s]: trained=%d rules=%d -> %s'
          % (mem['engine'], mem['trained_trades'], len(mem['rules']), path))
    for r in mem['rules']:
        print('  VETO %-46s n=%-3d %dW/%dL wr=%3.0f%% R=%+.2f (%s)'
              % (json.dumps(r['keys']), r['n'], r['wins'], r['losses'],
                 100 * r['win_rate'], r['total_r'], r['reason']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())