"""Reconciliation layer for ScanLP live vs EOD paper trades (derived view)."""
from datetime import datetime

def _key_live(t):
    return (t.get('instrument'), (t.get('entry_time') or '')[:10], t.get('direction'))

def _key_eod(t):
    return (t.get('instrument'), t.get('trade_date'), t.get('direction'))


def reconcile(conn):
    live = []
    try:
        for r in conn.execute(
                "SELECT trade_id, instrument_id, direction, entry, stop, target, entry_time, exit_time, exit_price, exit_reason, paper_pnl, status, created_at FROM paper_trades "
                "WHERE scenario='SCALP_HLC' OR qualification_evidence LIKE '%SCALP_HLC%'"):
            live.append({'trade_id': r[0], 'instrument': r[1], 'direction': r[2],
                         'entry': r[3], 'stop': r[4], 'target': r[5],
                         'entry_time': r[6], 'exit_time': r[7], 'exit': r[8],
                         'exit_reason': r[9], 'pnl': r[10], 'status': r[11],
                         'created_at': r[12], 'source': 'LIVE'})
    except Exception:
        pass
    eod = []
    try:
        for r in conn.execute(
                "SELECT session_date, instrument_id, direction, level, entry_price, entry_time, exit_price, exit_time, exit_reason, r_multiple, result, points, created_at FROM paper_scalp"):
            eod.append({'trade_date': r[0], 'instrument': r[1], 'direction': r[2],
                        'level': r[3], 'entry': r[4], 'entry_time': r[5],
                        'exit': r[6], 'exit_time': r[7], 'exit_reason': r[8],
                        'r_multiple': r[9], 'result': r[10], 'points': r[11],
                        'created_at': r[12], 'source': 'EOD'})
    except Exception:
        pass

    matched_eod = set()
    canonical = []
    for lt in live:
        match_idx = None
        for i, et in enumerate(eod):
            if i in matched_eod:
                continue
            if _key_live(lt) == _key_eod(et):
                # conservative: also require close entry price if available
                if lt.get('entry') is not None and et.get('entry') is not None and abs(lt['entry'] - et['entry']) > 1e-6:
                    continue
                match_idx = i
                break
        if match_idx is not None:
            matched_eod.add(match_idx)
            et = eod[match_idx]
            canonical.append({**lt, 'provenance': 'LIVE_EXECUTION',
                             'matched_eod': True, 'eod_points': et.get('points')})
        else:
            canonical.append({**lt, 'provenance': 'LIVE_EXECUTION', 'matched_eod': False})

    # unmatched EOD rows are independent research observations
    for i, et in enumerate(eod):
        if i in matched_eod:
            continue
        canonical.append({**et, 'provenance': 'INDEPENDENT_BACKTEST', 'matched_eod': False})

    # open trades flagged
    for c in canonical:
        st = (c.get('status') or '').upper()
        if st in ('ACTIVE', 'OPEN'):
            c['finalized'] = False
        else:
            c['finalized'] = True

    return canonical
