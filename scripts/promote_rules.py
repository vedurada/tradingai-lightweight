#!/usr/bin/env python3
"""Gated promotion of learned rules into the live rule registry (additive).

The walk-forward verdict is the ONLY path to ACTIVE. A learned rule is promoted
to rule_registry(status='ACTIVE') only when walkforward_selfeval.rule_scores()
says PASS out-of-sample (n>=min_vetoes, accuracy>=floor, net_r>=floor). Rules
that fail are marked REJECTED; unproven ones PROPOSED. Existing ACTIVE rows that
no longer carry a PASS verdict are demoted.

mistake_guard only trusts ACTIVE rows whose walkforward_verdict='PASS', so the
gate is enforced at consumption as well as at write time.

  python3 scripts/promote_rules.py                 # dry run (default)
  python3 scripts/promote_rules.py --apply         # write to rule_registry
  python3 scripts/promote_rules.py --apply --days 180

Writes only: rule_registry rows + data/rule_promotion_audit.jsonl.
Never touches engine/trigger/alert/frontend code.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')

import loss_memory as lm
import walkforward_selfeval as wf
from app.core.db import get_conn

IST = ZoneInfo('Asia/Kolkata')
AUDIT = '/opt/tradingai/data/rule_promotion_audit.jsonl'


def ensure_column(conn):
    try:
        conn.execute("ALTER TABLE rule_registry ADD COLUMN walkforward_verdict TEXT")
    except sqlite3.OperationalError:
        pass


def decide(verdict):
    return {'PASS': 'ACTIVE', 'FAIL': 'REJECTED'}.get(verdict, 'PROPOSED')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default=lm.DEFAULT_ENGINE, choices=lm.ENGINES)
    ap.add_argument('--days', type=int, default=120,
                    help='walk-forward test window in sessions (default 120)')
    ap.add_argument('--min-train', type=int, default=8)
    ap.add_argument('--apply', action='store_true', help='write (default: dry run)')
    args = ap.parse_args()

    cfg = lm.load_config()
    decay_cfg = cfg.get('decay', lm.DEFAULTS['decay'])
    mem = lm.load_memory(args.engine) or {'rules': []}

    conn = get_conn()
    try:
        scores = wf.rule_scores(conn, args.engine, args.days, args.min_train,
                                decay_cfg)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    rows = []
    for r in mem.get('rules', []):
        rid = lm.rule_id(r['keys'])
        s = scores.get(rid) or {}
        verdict = s.get('verdict', 'UNVERIFIED')
        rows.append({
            'rule_id': '%s|%s' % (args.engine, rid),
            'engine': args.engine, 'keys_json': rid, 'keys': r['keys'],
            'reason': r['reason'], 'status': decide(verdict),
            'walkforward_verdict': verdict, 'n': r['n'], 'wins': r['wins'],
            'losses': r['losses'], 'win_rate': r['win_rate'],
            'total_r': r['total_r'],
            'oos': s,
        })

    print('promotion gate [%s] over %d sessions%s' %
          (args.engine, args.days, '' if args.apply else ' (dry run)'))
    ea = next((r['oos'].get('engine_accuracy') for r in rows if r['oos']), None)
    if ea is not None:
        print('  engine win-rate (accuracy) in window: %.1f%%. Learned rules may '
              'change engine behavior only if their accuracy EXCEEDS this.' % (100 * ea))
    print('  %-44s %-11s %s' % ('rule', 'verdict', 'oos right/costly net_r acc %s gate'
                                % ('vs eng' if ea is not None else '')))
    for row in rows:
        s = row['oos']
        if s:
            acc = s.get('accuracy')
            print('  %-44s %-11s %d/%-3d %+.2fR %-6s %-5s %s' % (
                json.dumps(row['keys']), row['walkforward_verdict'],
                s.get('right', 0), s.get('costly', 0), s.get('net_r', 0.0),
                ('%.0f%%' % (100 * acc) if acc is not None else 'n/a'),
                ('yes' if s.get('beats_engine') else 'no'), s.get('gate', '')))
        else:
            print('  %-44s %-11s %s' % (json.dumps(row['keys']),
                                        row['walkforward_verdict'],
                                        'no OOS evidence'))

    if args.apply and rows:
        conn = get_conn()
        now = datetime.now(IST).isoformat(timespec='seconds')
        ensure_column(conn)
        promoted = 0
        for row in rows:
            conn.execute(
                "INSERT INTO rule_registry (rule_id, engine, keys_json, reason,"
                " status, n, wins, losses, win_rate, total_r, created_at,"
                " updated_at, walkforward_verdict)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(rule_id) DO UPDATE SET reason=excluded.reason,"
                " status=excluded.status, n=excluded.n, wins=excluded.wins,"
                " losses=excluded.losses, win_rate=excluded.win_rate,"
                " total_r=excluded.total_r, updated_at=excluded.updated_at,"
                " walkforward_verdict=excluded.walkforward_verdict",
                (row['rule_id'], row['engine'], row['keys_json'], row['reason'],
                 row['status'], row['n'], row['wins'], row['losses'],
                 row['win_rate'], row['total_r'], now, now,
                 row['walkforward_verdict']))
            promoted += 1 if row['status'] == 'ACTIVE' else 0
        # Demote ACTIVE rows that don't currently carry a PASS verdict.
        cur = conn.execute(
            "UPDATE rule_registry SET status='REJECTED', updated_at=?"
            " WHERE engine=? AND status='ACTIVE'"
            " AND (walkforward_verdict IS NULL OR walkforward_verdict!='PASS')",
            (now, args.engine))
        conn.commit()
        conn.close()
        try:
            with open(AUDIT, 'a') as f:
                f.write(json.dumps({'ts_ist': now, 'engine': args.engine,
                                    'days': args.days, 'promoted': promoted,
                                    'demoted': cur.rowcount,
                                    'rows': rows}) + '\n')
        except OSError as e:
            print('audit write failed: %s' % e)
        print('  applied: %d rule(s) evaluated, %d ACTIVE, %d demoted' %
              (len(rows), promoted, cur.rowcount))
    elif not args.apply:
        print('  (dry run — re-run with --apply to write)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
