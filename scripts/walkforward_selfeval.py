#!/usr/bin/env python3
"""Walk-forward self-evaluation of the learned veto layer (READ-ONLY).

Question it answers: do the loss-memory avoid-rules actually improve
out-of-sample results, or do they only curve-fit the training book?

Method (strictly no lookahead): for each test session D, rebuild the engine
memory using ONLY sessions before D (scripts/loss_memory.build_memory with
as_of=D), then replay that session's paper_align trades through the exact gate
the live path uses (loss_memory.fingerprint_book + loss_memory.evaluate).
Compare the FILTERED book (trades the rules allow) against the BASELINE (all
trades).

Read-only. Never writes the DB, engine, trigger, alert or frontend code.

  python3 scripts/walkforward_selfeval.py                 # last 90 sessions
  python3 scripts/walkforward_selfeval.py --days 180
  python3 scripts/walkforward_selfeval.py --engine plain --min-train 30

Writes: reports/walkforward_selfeval_<date>.md   (one markdown report)
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')

import loss_memory as lm
from app.core.db import get_conn

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')


def load_trades(conn, engine, insts):
    ph = ','.join('?' * len(insts))
    rows = conn.execute(
        "SELECT session_date, instrument_id, direction, level, entry_time, "
        "variant, r_multiple, result FROM paper_align "
        "WHERE variant=? AND state='SIGNAL' AND instrument_id IN (%s) "
        "AND result IN ('WIN','LOSS') AND r_multiple IS NOT NULL "
        "ORDER BY session_date" % ph, (engine,) + tuple(insts)).fetchall()
    return [dict(r) for r in rows]


def veto_decision(mem, fp, use_decay):
    """Pure learner OR logic, without contaminating history with today's decay.

    use_decay=False scores the rules the walk-forward step actually trained.
    use_decay=True applies the shipped guard (active_rules, i.e. minus decay)."""
    rules = lm.active_rules(mem) if use_decay else (mem or {}).get('rules', [])
    matches = [r for r in rules
               if all(fp.get(k) == v for k, v in r['keys'].items())]
    if not matches:
        return {'action': 'ALLOW'}
    worst = min(matches, key=lambda r: r['total_r'])
    return {'action': 'VETO', 'reason': worst['reason'], 'keys': worst['keys']}


def evaluate_rule_effectiveness(conn, engine, days, min_train, use_decay):
    cfg = lm.load_config()
    insts = tuple(cfg['instruments'])
    trades = load_trades(conn, engine, insts)
    sessions = sorted({t['session_date'] for t in trades})
    test_sessions = sessions[-days:]

    # Baseline = all trades in the test window.
    test = [t for t in trades if t['session_date'] in set(test_sessions)]
    base_R = round(sum(float(t['r_multiple']) for t in test), 2)
    base_wins = sum(1 for t in test if t['result'] == 'WIN')

    taken_R = 0.0
    taken_wins = taken_n = 0
    vetoed = []            # {fp, result, r}
    rules_seen = 0
    per_session = []

    for d in test_sessions:
        mem = lm.build_memory(engine, as_of=d)
        train_n = mem.get('trained_trades', 0)
        n_rules = len(mem.get('rules', []))
        rules_seen = max(rules_seen, n_rules)
        day_r = 0.0
        day_veto = day_take = 0
        for t in [x for x in trades if x['session_date'] == d]:
            fp = lm.fingerprint_book(conn, t)
            v = veto_decision(mem, fp, use_decay) if train_n >= min_train \
                else {'action': 'ALLOW'}
            r = float(t['r_multiple'])
            if v.get('action') == 'VETO':
                vetoed.append({'fp': fp, 'session_date': t['session_date'],
                               'result': t['result'], 'r': r,
                               'reason': v.get('reason'), 'rule': v.get('keys')})
                day_veto += 1
            else:
                taken_R += r
                taken_n += 1
                taken_wins += 1 if t['result'] == 'WIN' else 0
                day_r += r
                day_take += 1
        per_session.append((d, train_n, n_rules, day_take, day_veto,
                            round(day_r, 2)))
    return {
        'engine': engine, 'insts': insts, 'sessions': test_sessions,
        'base_n': len(test), 'base_R': base_R, 'base_wins': base_wins,
        'taken_n': taken_n, 'taken_R': round(taken_R, 2), 'taken_wins': taken_wins,
        'vetoed': vetoed, 'max_rules': rules_seen, 'per_session': per_session,
        'use_decay': use_decay,
    }


def rule_scores(conn, engine, days, min_train, decay_cfg):
    """Per-rule out-of-sample verdicts for the promotion gate.

    For each test session, rebuild memory from prior sessions only; for every
    learned rule present at that step, score the trades it would have vetoed on
    that session: right = a loss avoided, costly = a winner skipped.

    verdict: PASS  -> learned accuracy > engine accuracy (owner rule) AND
                      n>=min_vetoes AND accuracy>=floor AND net_r>=net_floor
             FAIL  -> scored but below the engine accuracy or the OOS floors
             UNVERIFIED -> too few scored vetoes
    """
    trades = load_trades(conn, engine, tuple(lm.load_config()['instruments']))
    sessions = sorted({t['session_date'] for t in trades})
    test_sessions = sessions[-days:]
    window = [t for t in trades if t['session_date'] in set(test_sessions)]
    base_n = len(window)
    base_wins = sum(1 for t in window if t['result'] == 'WIN')
    engine_acc = (base_wins / base_n) if base_n else None
    agg = defaultdict(lambda: {'keys': None, 'reason': None, 'right': 0,
                               'costly': 0, 'neutral': 0, 'avoided': 0.0,
                               'foregone': 0.0, 'latest': None})
    for d in test_sessions:
        mem = lm.build_memory(engine, as_of=d)
        if mem.get('trained_trades', 0) < min_train:
            continue
        day_trades = [x for x in trades if x['session_date'] == d]
        for t in day_trades:
            fp = lm.fingerprint_book(conn, t)
            for r in mem.get('rules', []):
                if not all(fp.get(k) == v for k, v in r['keys'].items()):
                    continue
                rid = lm.rule_id(r['keys'])
                a = agg[rid]
                a['keys'] = r['keys']
                a['reason'] = r['reason']
                a['latest'] = d
                rr = float(t['r_multiple'])
                if t['result'] == 'LOSS':
                    a['right'] += 1
                    a['avoided'] += abs(rr)
                elif t['result'] == 'WIN':
                    a['costly'] += 1
                    a['foregone'] += rr
                else:
                    a['neutral'] += 1
    out = {}
    for rid, a in agg.items():
        nv = a['right'] + a['costly']
        acc = (a['right'] / nv) if nv else None
        net_r = round(a['avoided'] - a['foregone'], 2)
        # Existing engine rules may only be changed when the learned rule is
        # MORE accurate than the engine itself (owner rule). A veto rule's
        # "accuracy" = share of skipped trades that really were losses; the
        # engine's accuracy = its own win rate over the same window.
        beats_engine = (acc is not None and engine_acc is not None
                        and acc > engine_acc)
        if nv < decay_cfg['min_vetoes']:
            verdict, why = 'UNVERIFIED', 'TOO_FEW'
        elif not beats_engine:
            verdict, why = 'FAIL', 'NOT_ABOVE_ENGINE_ACC'
        elif acc < decay_cfg['accuracy_floor'] or net_r < decay_cfg['net_r_floor']:
            verdict, why = 'FAIL', 'BELOW_OOS_FLOOR'
        else:
            verdict, why = 'PASS', 'PASS'
        out[rid] = {
            'keys': a['keys'], 'reason': a['reason'],
            'right': a['right'], 'costly': a['costly'], 'neutral': a['neutral'],
            'n_veto': nv, 'accuracy': (round(acc, 3) if acc is not None else None),
            'net_r': net_r, 'latest': a['latest'], 'verdict': verdict,
            'gate': why, 'engine_accuracy': (round(engine_acc, 3)
                                             if engine_acc is not None else None),
            'beats_engine': beats_engine,
        }
    return out


def summarize(res):
    b = res
    v_right = [x for x in b['vetoed'] if x['result'] == 'LOSS']
    v_costly = [x for x in b['vetoed'] if x['result'] == 'WIN']
    avoided = round(sum(abs(x['r']) for x in v_right), 2)
    foregone = round(sum(x['r'] for x in v_costly), 2)
    net_saved = round(avoided - foregone, 2)
    nv = len(v_right) + len(v_costly)
    acc = round(len(v_right) / nv, 3) if nv else None
    def wr(w, n):
        return round(100.0 * w / n, 1) if n else 0.0
    return {
        'base_wr': wr(b['base_wins'], b['base_n']),
        'taken_wr': wr(b['taken_wins'], b['taken_n']),
        'vetoed_n': len(b['vetoed']), 'veto_right': len(v_right),
        'veto_costly': len(v_costly), 'veto_acc': acc,
        'avoided_r': avoided, 'foregone_r': foregone, 'net_saved_r': net_saved,
        'delta_r': round(b['taken_R'] - b['base_R'], 2),
    }


def render(res, s):
    L = ['# Walk-forward self-evaluation of the learned veto layer', '',
         'Generated %s IST. Engine: **%s**. Mode: **%s decay**. '
         'Read-only analysis; not advice.' %
         (datetime.now(IST).strftime('%Y-%m-%d %H:%M'), res['engine'],
          'with' if res.get('use_decay') else 'without'), '',
         'Each test session rebuilds the memory from **prior sessions only**, then '
         'replays that session through the same gate the live path uses. No lookahead.',
         '',
         '## Headline', '',
         '| Metric | Baseline (all trades) | Filtered (rules allow) |',
         '|---|---|---|',
         '| Trades | %d | %d |' % (res['base_n'], res['taken_n']),
         '| Win rate | %.1f%% | %.1f%% |' % (s['base_wr'], s['taken_wr']),
         '| Total R | %+.2f | %+.2f |' % (res['base_R'], res['taken_R']),
         '',
         'Vetoed %d trades: **%d correct** (loss avoided), **%d costly** (winner '
         'skipped). Veto accuracy %.0f%%. Net R effect of the filter: **%+.2fR** '
         '(avoided %+.2fR, foregone %+.2fR).' % (
             s['vetoed_n'], s['veto_right'], s['veto_costly'],
             100 * (s['veto_acc'] or 0), s['net_saved_r'], s['avoided_r'],
             s['foregone_r']), '',
         'Out-of-sample delta vs baseline: **%+.2fR**. Max rules active in any '
         'walk-forward step: %d.' % (s['delta_r'], res['max_rules']), '',
         '## Per-session detail (last 40 test sessions)', '',
         '| Session | trained | rules | taken | vetoed | taken R |',
         '|---|---|---|---|---|---|']
    for d, tn, nr, take, veto, dr in res['per_session'][-40:]:
        L.append('| %s | %d | %d | %d | %d | %+.2f |' % (d, tn, nr, take, veto, dr))
    L.append('')
    L.append('## Vetoed trades (last 40)')
    L.append('')
    L.append('| Session | Inst | Dir | Level | Regime | DOW | VIX | Result | R | Reason |')
    L.append('|---|---|---|---|---|---|---|---|---|---|')
    for x in res['vetoed'][-40:]:
        fp = x['fp']
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %+.2f | %s |' % (
            x.get('session_date', ''), fp.get('instrument_id'), fp.get('direction'),
            fp.get('level'), fp.get('regime'), fp.get('dow'), fp.get('vix_dir'),
            x['result'], x['r'], x.get('reason')))
    L.append('')
    L.append('> Educational, hypothetical, read-only. Not investment advice.')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default=lm.DEFAULT_ENGINE, choices=lm.ENGINES)
    ap.add_argument('--days', type=int, default=90,
                    help='number of most-recent sessions to test (default 90)')
    ap.add_argument('--min-train', type=int, default=8,
                    help='min prior trades before rules are trusted (default 8)')
    ap.add_argument('--use-decay', action='store_true',
                    help='apply the shipped guard incl. current decay file '
                         '(default: score the pure walk-forward learner only)')
    args = ap.parse_args()

    conn = get_conn()
    try:
        res = evaluate_rule_effectiveness(conn, args.engine, args.days,
                                          args.min_train, args.use_decay)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    s = summarize(res)
    os.makedirs('%s/reports' % BASE, exist_ok=True)
    out = ('%s/reports/walkforward_selfeval_%s.md'
           % (BASE, datetime.now(IST).strftime('%Y-%m-%d')))
    with open(out, 'w') as f:
        f.write(render(res, s))

    print('walk-forward self-eval [%s] over %d sessions '
          '(%s..%s)' % (args.engine, len(res['sessions']),
                        res['sessions'][0] if res['sessions'] else '-',
                        res['sessions'][-1] if res['sessions'] else '-'))
    print('  baseline : n=%-3d wr=%.1f%% R=%+.2f' %
          (res['base_n'], s['base_wr'], res['base_R']))
    print('  filtered : n=%-3d wr=%.1f%% R=%+.2f  (delta %+.2fR)' %
          (res['taken_n'], s['taken_wr'], res['taken_R'], s['delta_r']))
    print('  vetoes   : %d  right=%d costly=%d acc=%s net_saved=%+.2fR' %
          (s['vetoed_n'], s['veto_right'], s['veto_costly'],
           ('%.0f%%' % (100 * s['veto_acc']) if s['veto_acc'] is not None else 'n/a'),
           s['net_saved_r']))
    print('  report   : %s' % out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
