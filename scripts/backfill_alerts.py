"""Backfill data/tg_alerts_archive.jsonl from the existing session ledger.

The archive starts recording with this change, so the alerts already sent
earlier (held only in data/tg_state.json) are reconstructed once, marked
source='ledger-backfill' so the page can show that the original engine
explanation text was not stored for those dates. Idempotent: existing
records are never duplicated.
"""
import io
import json
import os

BASE = '/opt/tradingai'
STATE = os.path.join(BASE, 'data', 'tg_state.json')
ARCHIVE = os.path.join(BASE, 'data', 'tg_alerts_archive.jsonl')


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pts(v):
    v = num(v)
    return '' if v is None else '{:+,.2f} pts'.format(v)


def existing_keys():
    keys = set()
    total = 0
    try:
        with io.open(ARCHIVE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                total += 1
                if r.get('key'):
                    keys.add(r['key'])
    except FileNotFoundError:
        pass
    return keys, total


def main():
    st = json.load(io.open(STATE, encoding='utf-8'))
    have, total = existing_keys()
    new = []

    for c in st.get('closed', []):
        date = c.get('date')
        if not date:
            continue
        key = '%s|%s|%s|%s' % (date, c.get('inst'), c.get('direction'), c.get('entry'))
        if key in have:
            continue
        direction = (c.get('direction') or '').upper() or '—'
        strategy = c.get('strategy') or '—'
        reason = c.get('reason') or '—'
        base = {'date': date, 'ts_ist': date + 'T00:00:00+05:30',
                'source': 'ledger-backfill', 'key': key,
                'inst': c.get('inst'), 'sym': c.get('sym')}
        ctx = {'direction': direction, 'trigger': c.get('entry'),
               'strategy': strategy, 'session': '—'}
        new.append(dict(base, type='signal', direction=direction, ctx=ctx,
                        explanation='Reconstructed from the session ledger: the model classified a %s record '
                                    'at %s, recorded as a %s structure.'
                                    % (direction, c.get('entry'), strategy)))
        new.append(dict(base, type='update',
                        outcome={'reason': reason, 'exit': c.get('exit'),
                                 'points_text': pts(c.get('points'))},
                        explanation='Reconstructed from the session ledger: the record was closed as %s '
                                    'at exit reference %s.' % (reason, c.get('exit'))))
        have.add(key)

    for k in sorted(st.get('fired', [])):
        if k in have:
            continue
        parts = k.split('|')
        date = parts[0] if parts else ''
        inst = parts[1] if len(parts) > 1 else ''
        direction = parts[2] if len(parts) > 2 else ''
        entry = parts[3] if len(parts) > 3 else ''
        if not date:
            continue
        new.append({'date': date, 'ts_ist': date + 'T00:00:00+05:30',
                    'source': 'ledger-backfill', 'type': 'signal', 'inst': inst,
                    'sym': (inst or '').lower(), 'key': k, 'direction': direction,
                    'ctx': {'direction': direction, 'trigger': entry, 'session': '—'},
                    'explanation': 'Reconstructed from the session ledger: a record was classified on this '
                                   'date and no exit is recorded in the ledger yet.'})
        have.add(k)

    if new:
        with io.open(ARCHIVE, 'a', encoding='utf-8') as f:
            for r in new:
                f.write(json.dumps(r) + '\n')
    print('archive before:', total, '| added:', len(new), '| total:', total + len(new))
    return len(new)


if __name__ == '__main__':
    main()
