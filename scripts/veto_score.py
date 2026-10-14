#!/usr/bin/env python3
"""Score learned loss-memory rules against their real-world veto outcomes.

Additive. Reads scripts/veto_paper_book.py's paper_align_veto table (every
row holds the ACTUAL result/r_multiple of a trade the rule would have vetoed)
and scores each current rule of an engine memory:

  right   = vetoed trade ended LOSS   -> avoidance was correct
  costly  = vetoed trade ended WIN    -> a winner was foregone
  neutral = any other exit (FLAT/EOD/OPEN)
  accuracy= right / (right + costly)
  net_r   = -sum(r_multiple of scored vetoes)  (R the rule saved or cost)

Verdict per rule:
  ACTIVE      scored vetoes support the avoidance
  UNVERIFIED  too few scored vetoes to judge (kept active)
  WRONG       accuracy/net below floors  -> decay
  STALE       no recent veto evidence    -> decay

With --decay it writes the WRONG + STALE rules to data/loss_memory_decay.json,
which scripts/loss_memory.evaluate() honours so the live guard (mistake_guard)
and the book overlay (veto_paper_book) stop applying them. The memory itself
and paper_align are never edited.

Writes only:
  data/loss_memory_decay.json  (atomic)
  data/veto_score_audit.jsonl  (append-only)
"""
import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')
import loss_memory as lm
from app.core.db import get_conn

IST = ZoneInfo('Asia/Kolkata')
AUDIT = '/opt/tradingai/data/veto_score_audit.jsonl'
DECAY = '/opt/tradingai/data/loss_memory_decay.json'


def vetoed(conn, engine):
    return [dict(r) for r in conn.execute(
        "SELECT session_date, instrument_id, direction, level, regime, dow,"
        " vix_dir, r_multiple, result FROM paper_align_veto WHERE variant=? AND result IS NOT NULL",
        (engine,))]


def matches(row, keys):
    fp = {k: row.get(k) for k in ('instrument_id', 'direction', 'level', 'regime', 'dow', 'vix_dir')}
    return all(fp.get(k) == v for k, v in keys.items())


def days_between(day, other):
    try:
        return (datetime.strptime(day, '%Y-%m-%d')
                - datetime.strptime(str(other or ''), '%Y-%m-%d')).days
    except (ValueError, TypeError):
        return None


def score_rule(rule, vetoes, day, decay_cfg):
    rows = [v for v in vetoes if matches(v, rule['keys'])]
    right = [v for v in rows if v['result'] == 'LOSS']
    costly = [v for v in rows if v['result'] == 'WIN']
    neutral = len(rows) - len(right) - len(costly)
    avoided_r = round(sum(abs(float(v['r_multiple'] or 0.0)) for v in right), 2)
    foregone_r = round(sum(float(v['r_multiple'] or 0.0) for v in costly), 2)
    net_r = round(avoided_r - foregone_r, 2)
    nv = len(right) + len(costly)
    accuracy = round(len(right) / nv, 4) if nv else None
    latest = max((v['session_date'] for v in rows), default=None)

    if nv == 0:
        verdict = 'UNVERIFIED'
    elif nv < decay_cfg['min_vetoes']:
        verdict = 'UNVERIFIED'
    elif accuracy < decay_cfg['accuracy_floor'] or net_r < decay_cfg['net_r_floor']:
        verdict = 'WRONG'
    else:
        gap = days_between(day, latest)
        verdict = 'STALE' if gap is not None and gap > decay_cfg['recent_sessions'] else 'ACTIVE'

    return {
        'keys': rule['keys'], 'reason': rule['reason'],
        'n': rule['n'], 'wins': rule['wins'], 'losses': rule['losses'],
        'total_r': rule['total_r'],
        'veto_rows': len(rows),
        'right': len(right), 'costly': len(costly), 'neutral': neutral,
        'avoided_r': avoided_r, 'foregone_r': foregone_r, 'net_r': net_r,
        'accuracy': accuracy, 'latest_veto': latest, 'verdict': verdict,
    }


def audit(rec):
    try:
        with open(AUDIT, 'a') as f:
            f.write(json.dumps(rec) + '\n')
    except OSError as e:
        print('audit write failed: %s' % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default=None, choices=lm.ENGINES,
                    help='engine to score (default both)')
    ap.add_argument('--date', default=None,
                    help='as-of session date YYYY-MM-DD (default today IST)')
    ap.add_argument('--decay', action='store_true',
                    help='write WRONG/STALE rules to loss_memory_decay.json '
                         '(default is report-only)')
    args = ap.parse_args()
    day = args.date or datetime.now(IST).date().isoformat()
    engines = [args.engine] if args.engine else list(lm.ENGINES)
    cfg = lm.load_config()
    decay_cfg = cfg.get('decay', lm.DEFAULTS['decay'])
    all_scores = []

    for engine in engines:
        mem = lm.load_memory(engine)
        if not mem:
            print('[%s] no loss memory; run scripts/learn_losses.py first' % engine)
            continue
        conn = get_conn()
        try:
            vetoes = vetoed(conn, engine)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        scores = [score_rule(r, vetoes, day, decay_cfg) for r in mem['rules']]
        all_scores.append({'engine': engine, 'scores': scores})
        for s in scores:
            print('[%s] %-14s n=%-3d %dW/%dL | vetoes=%-3d %dR/%dW/%dN '
                  'acc=%s savedR=%+.2f (avoided %+.2f / foregone %+.2f) latest=%s -> %s'
                  % (engine, json.dumps(s['keys'], sort_keys=True), s['n'],
                     s['wins'], s['losses'], s['veto_rows'], s['right'],
                     s['costly'], s['neutral'],
                     '%.0f%%' % (100 * s['accuracy']) if s['accuracy'] is not None else '-',
                     s['net_r'], s['avoided_r'], s['foregone_r'],
                     s['latest_veto'] or '-', s['verdict']))
        if not scores:
            print('[%s] no rules to score' % engine)

    rec = {'ts_ist': datetime.now(IST).isoformat(timespec='seconds'), 'date': day,
           'engines': all_scores, 'decay_applied': args.decay}
    audit(rec)

    if not args.decay:
        print('report-only; re-run with --decay to suppress WRONG/STALE rules')
        return 0

    suppressed = []
    for block in all_scores:
        e = block['engine']
        for sc in block['scores']:
            if sc['verdict'] in ('WRONG', 'STALE'):
                suppressed.append({
                    'engine': e, 'keys': sc['keys'], 'reason': sc['reason'],
                    'decay': sc['verdict'], 'accuracy': sc['accuracy'],
                    'net_r': sc['net_r'], 'veto_rows': sc['veto_rows'],
                    'right': sc['right'], 'costly': sc['costly'],
                    'latest_veto': sc['latest_veto'],
                })
    tmp = DECAY + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'as_of': day,
                   'generated_at': datetime.now(IST).isoformat(timespec='seconds'),
                   'suppressed': suppressed}, f, indent=2, sort_keys=True)
    os.replace(tmp, DECAY)
    print('decay written: %d suppressed rule(s) -> %s' % (len(suppressed), DECAY))
    for r in suppressed:
        print('  DROP [%s] %s (%s, acc=%s, savedR=%+.2f)'
              % (r['engine'], json.dumps(r['keys'], sort_keys=True), r['decay'],
                 '%.0f%%' % (100 * r['accuracy']) if r['accuracy'] is not None else '-',
                 r['net_r']))
    return 0


if __name__ == '__main__':
    sys.exit(main())