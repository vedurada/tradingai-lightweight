#!/usr/bin/env python3
"""Live loss-memory guard: suppress repeat (learned) loss setups.

Additive. Runs immediately BEFORE tg_alerts.py --watch in the same cron tick.
It reads the same /api/decision endpoints; when a live TRADE matches a learned
avoid-rule from data/loss_memory.plain.json it:

  1. freezes the trade (POST /decision/claim) so the alert key is stable, then
  2. pre-registers that key in data/tg_state.json['fired'].

The existing (unmodified) tg_alerts.do_watch() then sees the key as already
fired and does not emit the signal, and posts a clearly-labelled SKIP notice.
Uses the PLAIN engine memory (that is the live path).

Never edits engine/trigger/alert code. Writes only:
  data/tg_state.json           (fired key so tg_alerts skips)
  data/mistake_veto_log.jsonl  (audit)

Modes:
  (default)  enforce -> freeze + suppress + notify
  --check    dry run -> report only, no writes, no notify
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
import tg_alerts as tgm
from app.core.db import get_conn

IST = ZoneInfo('Asia/Kolkata')
VETO_LOG = '/opt/tradingai/data/mistake_veto_log.jsonl'
PAIRS = (('nifty', 'NIFTY'), ('banknifty', 'BANKNIFTY'))


def log_veto(rec):
    try:
        with open(VETO_LOG, 'a') as f:
            f.write(json.dumps(rec) + '\n')
    except OSError as e:
        print('veto log failed: %s' % e)


def registry_rules(engine='plain'):
    """ACTIVE rules that PASSED the walk-forward promotion gate.

    The registry is only trusted when rows carry walkforward_verdict='PASS'; if
    the column is absent, no registry rule is trusted (gate enforced)."""
    conn = get_conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(rule_registry)")]
        if 'walkforward_verdict' not in cols:
            print('rule_registry has no walkforward_verdict column; '
                  'run scripts/promote_rules.py --apply. Trusting no rules.')
            return []
        rows = conn.execute(
            "SELECT * FROM rule_registry WHERE engine=? AND status='ACTIVE'"
            " AND walkforward_verdict='PASS'",
            (engine,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def registry_verdict(fp, rules):
    """VETO iff the live fingerprint matches an ACTIVE gated rule."""
    hits = [r for r in rules
            if all(fp.get(k) == v for k, v in json.loads(r['keys_json']).items())]
    if not hits:
        return {'action': 'ALLOW', 'reason': 'NO_MATCH', 'matches': []}
    worst = min(hits, key=lambda r: r['total_r'])
    return {
        'action': 'VETO', 'reason': worst['reason'], 'matches': hits,
        'worst': {'reason': worst['reason'], 'n': worst['n'],
                  'wins': worst['wins'], 'losses': worst['losses'],
                  'total_r': worst['total_r']},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='dry run; no writes/no notify')
    args = ap.parse_args()
    check = args.check

    mem = lm.load_memory('plain')
    cfg = lm.load_config()
    if not cfg.get('enabled', True):
        print('memory guard disabled')
        return 0
    use_registry = cfg.get('use_registry', False)
    registry = registry_rules('plain') if use_registry else None
    if use_registry:
        print('registry mode: %d ACTIVE plain rule(s) loaded' % len(registry))
    elif not mem:
        print('no loss memory; run scripts/learn_losses.py first')
        return 0

    today = datetime.now(IST).date().isoformat()
    enforce = cfg.get('enforce', True) and not check
    notify = cfg.get('notify_skip', True) and not check
    st = tgm.state()
    fired = st.setdefault('fired', [])

    vix_dir = None
    try:
        vd = tgm.api('/api/decision/india_vix') or {}
        vix_dir = lm.vix_dir_from_pct(vd.get('change_pct'))
    except Exception as e:
        print('vix poll failed: %s' % e)

    for sym, inst in PAIRS:
        try:
            d = tgm.api('/api/decision/%s' % sym)
        except Exception as e:
            print('%s poll failed: %s' % (sym, e))
            continue
        if d.get('decision') != 'TRADE' or not d.get('trade'):
            continue
        trade = d['trade']
        key0 = '%s|%s|%s|%s' % (today, inst, trade.get('direction'), trade.get('entry'))
        if key0 in fired:
            continue
        fp = lm.fingerprint_live(d, trade, inst, today, vix_dir)
        verdict = (registry_verdict(fp, registry) if use_registry
                   else lm.evaluate(mem, fp))
        if verdict['action'] != 'VETO':
            print('%s ALLOW %s' % (inst, fp))
            continue

        try:
            ct = (tgm.api_post('/api/%s/decision/claim' % inst) or {}).get('trade') or trade
        except Exception as e:
            print('%s claim failed: %s' % (inst, e))
            ct = trade
        key = '%s|%s|%s|%s' % (today, inst, ct.get('direction'), ct.get('entry'))
        worst = verdict.get('worst') or {}
        print('%s VETO %s rule=%s n=%s R=%s' % (
            inst, fp, worst.get('reason'), worst.get('n'), worst.get('total_r')))

        if key in fired:
            continue
        fired.append(key)
        rec = {'ts_ist': datetime.now(IST).isoformat(timespec='seconds'),
               'date': today, 'instrument': inst, 'fingerprint': fp,
               'key': key, 'verdict': verdict, 'trade': ct}
        if enforce:
            tgm.save_state(st)
            log_veto(rec)
        if notify:
            text = ('\u26d4 %s\n%s\nSignal SKIPPED by loss-memory\n'
                    'Setup: %s %s %s %s vix=%s\nLearned: %s (%sW/%sL, %sR over %s)'
                    % (inst, today, fp.get('direction'), fp.get('level'),
                       fp.get('regime'), fp.get('dow'), fp.get('vix_dir'), worst.get('reason'),
                       worst.get('wins'), worst.get('losses'),
                       worst.get('total_r'), worst.get('n')))
            r = tgm.tg('sendMessage', {'chat_id': tgm.CHANNEL, 'text': text})
            print('skip notice ok=%s' % r.get('ok'))
    return 0


if __name__ == '__main__':
    sys.exit(main())