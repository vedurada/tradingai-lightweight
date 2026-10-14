#!/usr/bin/env python3
"""Rebuild the loss-memory for the plain backtest engine.

Additive. Reads paper_align only, writes:
  data/loss_memory.plain.json     (no-filter engine)
  data/loss_memory_audit.jsonl    (append-only audit)
Never touches engine/trigger/alert/frontend code.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')
import loss_memory as lm

IST = ZoneInfo('Asia/Kolkata')
AUDIT = '/opt/tradingai/data/loss_memory_audit.jsonl'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include-today', action='store_true',
                    help='train through today (use after the 15:45 book close)')
    args = ap.parse_args()
    as_of = None
    if args.include_today:
        as_of = (datetime.now(IST).date() + timedelta(days=1)).isoformat()

    for engine in lm.ENGINES:
        mem = lm.build_memory(engine, as_of)
        path = lm.save_memory(mem)
        print('loss-memory rebuilt [%s]: trained=%d rules=%d -> %s'
              % (engine, mem['trained_trades'], len(mem['rules']), path))
        for r in mem['rules']:
            print('  VETO %-46s n=%-3d %dW/%dL wr=%3.0f%% R=%+.2f (%s)'
                  % (json.dumps(r['keys']), r['n'], r['wins'], r['losses'],
                     100 * r['win_rate'], r['total_r'], r['reason']))
        try:
            with open(AUDIT, 'a') as f:
                f.write(json.dumps({'ts_ist': datetime.now(IST).isoformat(timespec='seconds'),
                                    'engine': engine,
                                    'trained_trades': mem['trained_trades'],
                                    'rules': mem['rules']}) + '\n')
        except OSError as e:
            print('audit write failed: %s' % e)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())