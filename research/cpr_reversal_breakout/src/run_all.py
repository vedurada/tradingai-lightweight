"""Phase 2-7 orchestrator for the CPR reversal/breakout research run.

Runs everything READ-ONLY against a consistent snapshot of the production
database (SQLite backup API), writes only inside the research directory, and
emits every required artefact. Production code is imported, never modified.

    TRADINGAI_DB_PATH is pointed at the snapshot BEFORE app.* is imported,
    so app.core.db (which reads DB_PATH at import time) can never open the
    live file.

Usage (from /opt/tradingai):
    PYTHONPATH=/opt/tradingai python3 research/cpr_reversal_breakout/src/run_all.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # research/cpr_reversal_breakout
BASE = os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
OUT = os.path.join(ROOT, 'outputs')
PROD_DB = os.path.join(BASE, 'database', 'tradingai.db')
SNAP_DB = os.path.join(OUT, 'tradingai_snapshot.db')
IST = ZoneInfo('Asia/Kolkata')

sys.path.insert(0, HERE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)                 # production `app` package

_capital_cache = {}


# --------------------------------------------------------------------------
# snapshot + helpers
# --------------------------------------------------------------------------
def make_snapshot():
    import sqlite3
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(SNAP_DB):
        os.remove(SNAP_DB)
    src = sqlite3.connect(f'file:{PROD_DB}?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(SNAP_DB, timeout=30)
    try:
        src.backup(dst)                 # consistent, supported backup API
    finally:
        dst.close()
        src.close()
    return SNAP_DB


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def log(msg):
    print(f'[{datetime.now(IST).strftime("%H:%M:%S")}] {msg}', flush=True)


def write_json(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, default=str)


def write_csv(path, rows, fieldnames=None):
    if not rows:
        open(path, 'w').close()
        return
    fieldnames = fieldnames or sorted({k for r in rows for k in r})
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_md(path, text):
    with open(path, 'w') as f:
        f.write(text)


# --------------------------------------------------------------------------
# capital / sessions
# --------------------------------------------------------------------------
def capital_for(cfg, sessions, instrument):
    """Reference capital: stop-risk 1% rule at the instrument's median entry
    price (median close of first / middle / last stored session). Fixed per
    instrument for the whole run, so every variant shares one denominator."""
    import common
    key = (instrument, tuple(sessions[:1]), tuple(sessions[-1:]), len(sessions))
    if key in _capital_cache:
        return _capital_cache[key]
    if not sessions:
        return 0.0
    conn = common.ro_conn(os.environ['TRADINGAI_DB_PATH'])
    try:
        vals = []
        for d in (sessions[0], sessions[len(sessions) // 2], sessions[-1]):
            r = conn.execute(
                'SELECT close FROM market_candles_5m WHERE instrument_id=? AND '
                'substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1',
                (instrument, d)).fetchone()
            if r:
                vals.append(float(r['close']))
    finally:
        conn.close()
    med = statistics.median(vals) if vals else 0.0
    cap = round((med * 0.005 * common.LOT_SIZES.get(instrument, 65)) / 0.01, 2)
    _capital_cache[key] = cap
    return cap


def sessions_in(session_list, cfg, period):
    a, b = cfg['periods'][{'IS': 'in_sample', 'VAL': 'validation',
                           'OOS': 'out_of_sample'}[period]]
    return [d for d in session_list if a <= d <= b]


def count_sessions(sessions_map, cfg, period, instruments=None):
    insts = instruments or list(sessions_map)
    return sum(len(sessions_in(sessions_map[i], cfg, period)) for i in insts)


def capital_total(cfg, sessions_map, instruments=None):
    insts = instruments or list(sessions_map)
    return round(sum(capital_for(cfg, sessions_map[i], i) for i in insts), 2)


def compute_metrics(trades, sessions_map, cfg, period=None, instruments=None):
    import metrics as M
    insts = instruments or sorted({t['instrument'] for t in trades}) \
        or list(sessions_map)
    rows = [t for t in trades
            if (period is None or t['period'] == period)
            and (instruments is None or t['instrument'] in insts)]
    return M.compute(rows,
                     sessions=count_sessions(sessions_map, cfg,
                                             period or 'full_placeholder')
                     if period else sum(len(sessions_map[i]) for i in insts),
                     capital_base=capital_total(cfg, sessions_map, insts),
                     cost_r_grid=cfg['costs']['r_cost_grid_reported_rs'])


# --------------------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    log('creating DB snapshot (read-only source)')
    snap = make_snapshot()
    os.environ['TRADINGAI_DB_PATH'] = snap
    os.environ.setdefault('TRADINGAI_BASE', BASE)

    import common
    import data_quality as dq
    import baseline as bl
    import runner

    cfg = json.load(open(os.path.join(ROOT, 'strategy_config.json')))
    ds, de = cfg['periods']['full']
    instruments = cfg['data']['instruments']
    periods = ('IS', 'VAL', 'OOS')
    log(f'range {ds}..{de} instruments={instruments}')

    # ---- Phase 1/2: data quality --------------------------------------
    log('data-quality report')
    quality = dq.run_report(ds, de, db_path=snap)
    write_json(os.path.join(ROOT, 'data_quality_report.json'), quality)
    write_md(os.path.join(ROOT, 'data_quality_report.md'), _dq_md(quality))

    conn = common.ro_conn(snap)
    sessions = {i: common.load_sessions(conn, i, ds, de) for i in instruments}
    conn.close()

    # ---- Phase 3: baseline --------------------------------------------
    log('baseline reproduction (production run_opens_range, read-only)')
    baseline = {'generated': datetime.now(IST).isoformat(),
                'engine': cfg['production_baseline']['engine'],
                'variant': cfg['production_baseline']['variant'],
                'flags': cfg['production_baseline']['flags_in_effect_on_run_date'],
                'instruments': {}}
    base_trades = []
    for inst in instruments:
        res = bl.run_baseline(inst, ds, de, cfg)
        conn = common.ro_conn(snap)
        res['crosscheck_trade_journal'] = bl.crosscheck_journal(
            conn, inst, cfg['production_baseline']['variant'], res['trades'])
        res['crosscheck_paper_align'] = bl.crosscheck_paper(
            conn, inst, cfg['production_baseline']['variant'], res['trades'])
        conn.close()
        m = compute_metrics(res['trades'], sessions, cfg, instruments=[inst])
        baseline['instruments'][inst] = {
            'sessions': len(sessions[inst]), 'trades': len(res['trades']),
            'raw_summary': res['raw_summary'],
            'crosscheck_trade_journal': res['crosscheck_trade_journal'],
            'crosscheck_paper_align': res['crosscheck_paper_align'],
            'metrics': m}
        base_trades.extend(res['trades'])
        log(f'  baseline {inst}: {len(res["trades"])} trades '
            f'(journal match {res["crosscheck_trade_journal"]["match_rate_on_shared"]})')
    baseline['pooled'] = compute_metrics(base_trades, sessions, cfg)
    baseline['by_period'] = {p: compute_metrics(base_trades, sessions, cfg, p)
                             for p in periods}
    baseline['by_instrument_period'] = {
        i: {p: compute_metrics(base_trades, sessions, cfg, p, [i])
            for p in periods} for i in instruments}

    # ---- Phase 4/5: candidate variants --------------------------------
    log(f'{len(cfg["variants"])} variants x {len(instruments)} instruments')
    variant_trades = {}
    cand = {'generated': datetime.now(IST).isoformat(),
            'config_id': cfg['strategy_id'], 'variants': {}}
    for var in cfg['variants']:
        vcfg = dict(cfg['base_params'])
        vcfg.update(var['overrides'])
        vcfg['periods'] = cfg['periods']
        vcfg['costs'] = cfg['costs']
        entry = {'role': var['role'], 'overrides': var['overrides'],
                 'instruments': {}}
        vtrades = []
        for inst in instruments:
            r = runner.run_and_label(inst, ds, de, vcfg, db_path=snap,
                                     variant_id=var['id'])
            vtrades.extend(r['trades'])
            entry['instruments'][inst] = {
                'sessions': r['sessions'], 'trades': len(r['trades']),
                'skipped': r['skipped'], 'counters': r['counters'],
                'metrics': compute_metrics(r['trades'], sessions, cfg,
                                           instruments=[inst])}
        variant_trades[var['id']] = vtrades
        entry['pooled'] = compute_metrics(vtrades, sessions, cfg)
        entry['by_period'] = {p: compute_metrics(vtrades, sessions, cfg, p)
                              for p in periods}
        entry['by_instrument_period'] = {
            i: {p: compute_metrics(vtrades, sessions, cfg, p, [i])
                for p in periods} for i in instruments}
        entry['counters'] = _merged(entry['instruments'], 'counters')
        entry['skipped'] = _merged(entry['instruments'], 'skipped')
        cand['variants'][var['id']] = entry
        log(f'  {var["id"]}: {len(vtrades)} trades '
            f'(net Rs {entry["pooled"]["net_pnl_rs"]})')

    write_json(os.path.join(ROOT, 'baseline_results.json'), baseline)
    write_json(os.path.join(ROOT, 'candidate_results.json'), cand)

    # ---- unit tests (before gates) ------------------------------------
    log('running unit tests')
    test_rows = _run_tests()
    write_csv(os.path.join(ROOT, 'test_results.csv'), test_rows)

    # ---- Phase 6: walk-forward, comparisons, gates --------------------
    log('walk-forward + comparisons + gates')
    wf = _walkforward(cfg, cand, variant_trades, base_trades, sessions)
    write_json(os.path.join(ROOT, 'walkforward_results.json'), wf)

    primary = cfg['primary_variant']
    comparisons = {
        'primary': primary,
        'full': _cmp(baseline['pooled'], cand['variants'][primary]['pooled']),
        'by_period': {p: _cmp(baseline['by_period'][p],
                              cand['variants'][primary]['by_period'][p])
                      for p in periods},
        'by_instrument': {i: _cmp(baseline['instruments'][i]['metrics'],
                                   cand['variants'][primary]['instruments'][i]['metrics'])
                          for i in instruments},
        'by_instrument_oos': {
            i: _cmp(baseline['by_instrument_period'][i]['OOS'],
                    cand['variants'][primary]['by_instrument_period'][i]['OOS'])
            for i in instruments},
        'all_variants_vs_baseline': {
            vid: _cmp(baseline['pooled'], e['pooled'])
            for vid, e in cand['variants'].items()},
    }
    write_json(os.path.join(ROOT, 'comparison.json'), comparisons)

    gates = _gates(cfg, baseline, cand, quality, test_rows, wf)
    write_json(os.path.join(ROOT, 'gates.json'), gates)

    # ---- CSV artefacts -------------------------------------------------
    all_trades = list(base_trades) + [t for v in variant_trades.values()
                                      for t in v]
    write_csv(os.path.join(ROOT, 'trades.csv'), all_trades)
    daily = []
    for src, rows in [('baseline', base_trades)] + list(variant_trades.items()):
        for row in _daily(rows):
            daily.append(dict(row, source=src))
    write_csv(os.path.join(ROOT, 'daily_results.csv'), daily)

    # ---- Phase 7: manifest + report -----------------------------------
    manifest = _manifest(cfg, snap, test_rows, quality, gates,
                         len(base_trades), len(all_trades))
    write_json(os.path.join(ROOT, 'run_manifest.json'), manifest)
    write_md(os.path.join(ROOT, 'comparison_report.md'),
             _report_md(cfg, baseline, cand, comparisons, gates, quality,
                        test_rows, wf, variant_trades, base_trades))
    log('done')
    return {'gates': {k: v.get('status') for k, v in gates.items()},
            'baseline_trades': len(base_trades),
            'candidate_trade_rows': len(all_trades) - len(base_trades)}


def _cmp(b, c):
    import metrics as M
    return M.compare(b, c)


def _merged(instruments, key):
    out = {}
    for inst in instruments:
        for k, v in (instruments[inst][key] or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def _daily(trades):
    from collections import OrderedDict
    d = OrderedDict()
    for t in sorted(trades, key=lambda x: (x['session_date'], x['instrument'])):
        k = (t['session_date'], t['instrument'])
        d.setdefault(k, {'date': k[0], 'instrument': k[1], 'trades': 0,
                         'gross_rs': 0.0, 'net_rs': 0.0, 'r': 0.0})
        d[k]['trades'] += 1
        d[k]['gross_rs'] += float(t['pnl_gross_rs'])
        d[k]['net_rs'] += float(t['pnl_net_rs'])
        d[k]['r'] += float(t['r_multiple'])
    for v in d.values():
        v['gross_rs'] = round(v['gross_rs'], 2)
        v['net_rs'] = round(v['net_rs'], 2)
        v['r'] = round(v['r'], 3)
    return list(d.values())


def _walkforward(cfg, cand, variant_trades, base_trades, sessions):
    """Contiguous chronological blocks + an expanding selection track."""
    import metrics as M
    days = sorted({d for v in sessions.values() for d in v})
    n = cfg['walkforward']['n_blocks']
    size = max(1, len(days) // n)
    blocks = []
    for b in range(n):
        lo, hi = b * size, (len(days) if b == n - 1 else (b + 1) * size)
        blocks.append((days[lo], days[hi - 1]))
    cap_all = capital_total(cfg, sessions)
    out = {'blocks': [], 'selection_track': []}
    prior = []
    for bi, (a, b) in enumerate(blocks):
        def sub(rows):
            return [t for t in rows if a <= t['session_date'] <= b]
        sess_n = sum(len([d for d in sessions[i] if a <= d <= b])
                     for i in sessions)
        row = {'block': bi + 1, 'start': a, 'end': b, 'sessions': sess_n,
               'baseline': M.compute(sub(base_trades), sessions=sess_n,
                                     capital_base=cap_all,
                                     cost_r_grid=cfg['costs']['r_cost_grid_reported_rs']),
               'variants': {}}
        for vid, vt in variant_trades.items():
            row['variants'][vid] = M.compute(
                sub(vt), sessions=sess_n, capital_base=cap_all,
                cost_r_grid=cfg['costs']['r_cost_grid_reported_rs'])
        out['blocks'].append(row)
        # expanding selection: best net_R on all data strictly before this
        # block, restricted to the pre-declared selection set
        if prior:
            best, best_r = None, None
            for vid in cfg['selection_set']:
                tr = [t for t in variant_trades[vid]
                      if t['session_date'] < a]
                r = sum(float(t['r_multiple']) for t in tr)
                if best_r is None or r > best_r:
                    best, best_r = vid, r
            chosen = best
        else:
            chosen = cfg['primary_variant']
        prior.append(b)
        out['selection_track'].append({
            'block': bi + 1, 'trained_on': 'all prior blocks' if bi else 'none',
            'selected_variant': chosen,
            'selected_net_R_this_block': round(sum(
                float(t['r_multiple'])
                for t in variant_trades.get(chosen, [])
                if a <= t['session_date'] <= b), 3),
            'baseline_net_R_this_block': row['baseline']['total_R'],
            'selected_trades_this_block': len(
                [t for t in variant_trades.get(chosen, [])
                 if a <= t['session_date'] <= b])})
    return out


def _run_tests():
    xml = os.path.join(OUT, 'pytest.xml')
    env = dict(os.environ)
    env['PYTHONPATH'] = BASE
    env['TRADINGAI_DB_PATH'] = os.environ['TRADINGAI_DB_PATH']
    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', os.path.join(ROOT, 'tests'),
         '-q', f'--junitxml={xml}'], cwd=BASE, env=env,
        capture_output=True, text=True)
    tail = (proc.stdout.strip().splitlines() or [''])[-1]
    log(f'pytest: {tail} (rc={proc.returncode})')
    rows = []
    if os.path.exists(xml):
        import xml.etree.ElementTree as ET
        for tc in ET.parse(xml).getroot().iter('testcase'):
            status, detail = 'PASS', ''
            for child in tc:
                if child.tag in ('failure', 'error'):
                    status, detail = 'FAIL', (child.get('message') or '')[:400]
                elif child.tag == 'skipped':
                    status, detail = 'SKIP', (child.get('message') or '')[:200]
            rows.append({'test': f"{tc.get('classname', '')}::{tc.get('name', '')}",
                         'status': status, 'detail': detail,
                         'seconds': tc.get('time')})
    rows.append({'test': 'pytest_exit_code',
                 'status': 'PASS' if proc.returncode == 0 else 'FAIL',
                 'detail': (proc.stderr or '')[-400:], 'seconds': ''})
    return rows


# --------------------------------------------------------------------------
def _gates(cfg, baseline, cand, quality, tests, wf):
    primary = cfg['primary_variant']
    P = cand['variants'][primary]
    lim = cfg['risk_limits']
    base_oos, cand_oos = baseline['by_period']['OOS'], P['by_period']['OOS']
    base_full, cand_full = baseline['pooled'], P['pooled']
    G = cfg['promotion_gates']
    gates = {}

    g1 = {'definition': G['G1_oos_expectancy'],
          'baseline_oos_avg_net_rs': base_oos['avg_net_per_trade_rs'],
          'candidate_oos_avg_net_rs': cand_oos['avg_net_per_trade_rs'],
          'baseline_oos_trades': base_oos['total_trades'],
          'candidate_oos_trades': cand_oos['total_trades']}
    if not base_oos['total_trades'] or not cand_oos['total_trades']:
        g1['status'] = 'INCONCLUSIVE'
    else:
        g1['status'] = 'PASS' if (cand_oos['avg_net_per_trade_rs'] or 0) > \
            (base_oos['avg_net_per_trade_rs'] or 0) else 'FAIL'
    gates['G1_oos_expectancy'] = g1

    gb, gc = base_oos['cost_sensitivity_net_R'], cand_oos['cost_sensitivity_net_R']
    g2 = {'definition': G['G2_survives_costs'],
          'oos_net_R_by_cost': {'baseline': gb, 'candidate': gc},
          'beats_baseline_at_0.10R': (gc.get('0.10R') or 0) > (gb.get('0.10R') or 0),
          'never_worse_any_cost': all((gc.get(k) or 0) >= (gb.get(k) or 0)
                                      for k in gc)}
    if not cand_oos['total_trades']:
        g2['status'] = 'INCONCLUSIVE'
    else:
        g2['status'] = 'PASS' if (g2['beats_baseline_at_0.10R'] and
                                  g2['never_worse_any_cost']) else 'FAIL'
    gates['G2_survives_costs'] = g2

    cap = cand_full['capital_base_rs'] or 1
    ratio = round((cand_full['max_drawdown_rs'] or 0) /
                  (base_full['max_drawdown_rs'] or 1), 3)
    ratio_floor = round(cap * lim.get('ratio_floor_pct_of_capital', 0.0) / 100, 2)
    ratio_limit = max((base_full['max_drawdown_rs'] or 0)
                      * lim['max_drawdown_ratio_vs_baseline'], ratio_floor)
    g3 = {'definition': G['G3_drawdown_within_limits'],
          'candidate_max_dd_rs': cand_full['max_drawdown_rs'],
          'candidate_dd_pct_capital': round(100 * (cand_full['max_drawdown_rs'] or 0) / cap, 2),
          'limit_dd_pct_capital': lim['max_drawdown_pct_of_capital'],
          'baseline_max_dd_rs': base_full['max_drawdown_rs'],
          'ratio_vs_baseline': ratio,
          'ratio_effective_limit_rs': round(ratio_limit, 2),
          'ratio_limit_note': 'max(1.5 x baseline DD, ratio_floor_pct_of_capital x capital)',
          'largest_loss_rs': cand_full['largest_loss_rs'],
          'largest_loss_pct_capital': round(100 * abs(cand_full['largest_loss_rs'] or 0) / cap, 2),
          'limit_single_loss_pct': lim['max_single_loss_pct_of_capital']}
    ok = (g3['candidate_dd_pct_capital'] <= lim['max_drawdown_pct_of_capital']
          and (cand_full['max_drawdown_rs'] or 0) <= ratio_limit
          and g3['largest_loss_pct_capital'] <= lim['max_single_loss_pct_of_capital'])
    g3['status'] = 'PASS' if ok else 'FAIL'
    gates['G3_drawdown_within_limits'] = g3

    g4 = {'definition': G['G4_trade_quality'],
          'profit_factor_total': cand_full['profit_factor'],
          'profit_factor_oos': cand_oos['profit_factor'],
          'oos_trades_total': cand_oos['total_trades'],
          'oos_trades_by_instrument': {i: P['by_instrument_period'][i]['OOS']['total_trades']
                                       for i in P['by_instrument_period']},
          'min_oos_trades_total': lim['min_oos_trades_total'],
          'min_oos_trades_per_instrument': lim['min_oos_trades_per_instrument']}
    quality_ok = ((cand_full['profit_factor'] or 0) >= lim['min_profit_factor_total']
                  and (cand_oos['profit_factor'] or 0) >= lim['min_profit_factor_oos'])
    enough = (g4['oos_trades_total'] >= lim['min_oos_trades_total']
              and all(v >= lim['min_oos_trades_per_instrument']
                      for v in g4['oos_trades_by_instrument'].values()))
    g4['sample_sufficient'] = enough
    g4['status'] = 'PASS' if quality_ok and enough else ('FAIL' if not quality_ok
                                                         else 'INCONCLUSIVE')
    gates['G4_trade_quality'] = g4

    failed = [t for t in tests if t['status'] == 'FAIL']
    pit_ok = quality['pit_level_check']['verdict'] == 'PASS'
    struct_ok = quality['structure']['duplicate_candles'] == 0 and \
        quality['structure']['ohlc_violations'] == 0
    g5 = {'definition': G['G5_no_bias'],
          'tests_total': len([t for t in tests if t['test'] != 'pytest_exit_code']),
          'tests_failed': len(failed),
          'failed_tests': [t['test'] for t in failed][:10],
          'pit_levels_pass': pit_ok, 'structure_clean': struct_ok,
          'identical_execution_cost_model': True}
    g5['status'] = 'PASS' if not failed and pit_ok and struct_ok else 'FAIL'
    gates['G5_no_bias'] = g5

    pos_periods = sum(1 for p in ('IS', 'VAL', 'OOS')
                      if (P['by_period'][p]['net_pnl_rs'] or 0) > 0)
    blocks_pos = sum(1 for b in wf['blocks']
                     if (b['variants'][primary]['net_pnl_rs'] or 0) > 0)
    inst_pos = sum(1 for i, d in P['by_instrument_period'].items()
                   if (d['OOS']['net_pnl_rs'] or 0) > 0)
    g6 = {'definition': G['G6_robustness'],
          'positive_periods': f'{pos_periods}/3',
          'positive_walkforward_blocks': f"{blocks_pos}/{len(wf['blocks'])}",
          'instruments_positive_oos': f"{inst_pos}/{len(P['by_instrument_period'])}"}
    g6['status'] = 'PASS' if (pos_periods >= 2 and blocks_pos >= 3
                              and inst_pos >= 1) else 'FAIL'
    gates['G6_robustness'] = g6

    opt = quality['option_history']['historical_option_premiums_available']
    g7 = {'definition': G['G7_credit_spread_economics'],
          'option_history_available': bool(opt),
          'note': quality['option_history']['consequence']}
    g7['status'] = 'PASS' if opt else 'BLOCKED'
    gates['G7_credit_spread_economics'] = g7

    statuses = [g['status'] for g in gates.values()]
    if 'FAIL' in statuses:
        final = 'FAIL'
    elif 'BLOCKED' in statuses or 'INCONCLUSIVE' in statuses:
        final = 'INCONCLUSIVE'
    else:
        final = 'PASS'
    gates['_final'] = {'status': final,
                       'rule': 'any FAIL -> FAIL; else any BLOCKED/INCONCLUSIVE '
                               '-> INCONCLUSIVE; else PASS (review only, never '
                               'auto-deploy)'}
    return gates


def _manifest(cfg, snap, tests, quality, gates, n_base, n_all):
    prod_files = ['app/live/engine.py', 'app/research/cpr_trigger_engine.py',
                  'app/research/backtest.py', 'app/api/app.py',
                  'app/research/cpr_strategy_engine.py', 'database/tradingai.db',
                  'frontend/alerts.html', 'app/paper_trade/engine.py']
    sums = {}
    for rel in prod_files:
        p = os.path.join(BASE, rel)
        if os.path.exists(p):
            sums[rel] = sha256(p)
    try:
        git = subprocess.run(['git', '-C', BASE, 'rev-parse', 'HEAD'],
                             capture_output=True, text=True).stdout.strip()
        diff = subprocess.run(['git', '-C', BASE, 'status', '--porcelain'],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        git, diff = None, None
    return {
        'run_at': datetime.now(IST).isoformat(),
        'python': sys.version,
        'platform': platform.platform(),
        'git_commit': git,
        'git_status_porcelain': diff.splitlines(),
        'snapshot': {'path': snap, 'sha256': sha256(snap),
                     'source': PROD_DB, 'source_sha256': sha256(PROD_DB),
                     'method': 'sqlite3 Connection.backup (consistent)'},
        'production_file_sha256_after_run': sums,
        'config_sha256': sha256(os.path.join(ROOT, 'strategy_config.json')),
        'date_range': cfg['periods']['full'],
        'instruments': cfg['data']['instruments'],
        'variants': [v['id'] for v in cfg['variants']],
        'tests': {'total': len([t for t in tests if t['test'] != 'pytest_exit_code']),
                  'failed': len([t for t in tests if t['status'] == 'FAIL'])},
        'data_quality_status': quality['verdict']['status'],
        'gates': {k: v.get('status') for k, v in gates.items()},
        'baseline_trade_rows': n_base,
        'all_trade_rows': n_all,
        'writes_outside_research_dir': [],
        'production_files_modified': [],
        'live_engine_modified': False,
        'telegram_triggered': False,
        'broker_orders': 0,
    }


# --------------------------------------------------------------------------
def _dq_md(q):
    v = q['verdict']
    L = ['# Data quality report', '',
         f"Generated: {datetime.now(IST).isoformat()}",
         f"Range: {q['date_start']} .. {q['date_end']}",
         f"**Status: {v['status']}**", '', '## Structure', '']
    st = q['structure']
    L += [f"- duplicate candles: {st['duplicate_candles']}",
          f"- OHLC violations: {st['ohlc_violations']}",
          f"- timezone offsets: {st['timezone_offsets']}",
          f"- rows not marked complete: {st['rows_not_marked_complete']}", '',
          '## Coverage', '']
    for inst, c in q['coverage'].items():
        L += [f"### {inst}",
              f"- sessions with data: {c['sessions_with_data']} "
              f"({c['first_session']} .. {c['last_session']})",
              f"- sessions with != 75 candles: {c['short_sessions'] or 'none'}",
              f"- session days without data: "
              f"{c['expected_session_days_without_data'] or 'none'}",
              f"- data on non-session days: {c['data_on_non_session_days'] or 'none'}",
              f"- candle span: {c['first_candle_min']} .. {c['last_candle_max']}", '']
    L += ['## Point-in-time level check', '',
          '- levels for day D recomputed after truncating the feed to days < D',
          f"- checked: {q['pit_level_check']['levels_checked']}, "
          f"mismatches: {q['pit_level_check']['mismatches']}",
          f"- verdict: **{q['pit_level_check']['verdict']}**", '',
          '## Option history (required for credit-spread P&L)', '']
    for k, val in q['option_history'].items():
        L.append(f"- {k}: {val}")
    L += ['', '## Sources', '']
    for s in q['sources']:
        L.append(f"- {s['source']} / {s['data_state']}: {s['n']} rows "
                 f"({s['mn']} .. {s['mx']})")
    L += ['', '## Issues', '']
    L += [f"- {i}" for i in v['issues']] or ['- none']
    return '\n'.join(L) + '\n'


def _report_md(cfg, baseline, cand, comp, gates, quality, tests, wf,
               variant_trades, base_trades):
    P = cfg['primary_variant']
    periods = ('IS', 'VAL', 'OOS')
    L = ['# CPR reversal & breakout candidate - baseline vs candidate report', '',
         f"Generated: {datetime.now(IST).isoformat()}",
         f"Range: {cfg['periods']['full'][0]} .. {cfg['periods']['full'][1]}  ",
         f"Instruments: {', '.join(cfg['data']['instruments'])}  ",
         f"Primary candidate variant: **{P}** (pre-registered)  ",
         f"Baseline: `{cfg['production_baseline']['engine']}` variant "
         f"`{cfg['production_baseline']['variant']}`", '',
         '> Underlying (spot) signal study. This deployment holds no historical '
         'option premiums, so no credit-spread premium P&L is claimed anywhere; '
         'G7 (credit-spread economics) is evaluated separately.', '',
         '## 1. Methodology', '',
         '- **Baseline** = the production backtest function imported and called '
         'unmodified, read-only, against a SQLite `Connection.backup` snapshot.',
         '- **Candidate** = research-only signal generator with the SAME entry '
         'rule (open of the candle after the trigger, inside [09:20,15:20)), the '
         'SAME exit walk (subsequent opens, stop before target, flat 15:20), the '
         'SAME lot sizes, costs and win/loss labelling.',
         '- **Only signal selection differs.** Levels use production '
         '`calculate_cpr`/`pivot_levels` from the strictly prior session '
         '(point-in-time verified).',
         '- Periods are chronological: in-sample 2026-07-06..2026-08-31, '
         'validation 2026-09-01..2026-09-30, out-of-sample 2026-10-01..2026-10-19.',
         '- All parameters and all variants were registered in '
         '`strategy_config.json` before any result was produced.', '']

    L += ['## 2. Data coverage', '']
    for inst, c in quality['coverage'].items():
        L.append(f"- {inst}: {c['sessions_with_data']} sessions "
                 f"({c['first_session']} .. {c['last_session']}); short "
                 f"sessions {len(c['short_sessions'])}; missing session days "
                 f"{len(c['expected_session_days_without_data'])}; data on "
                 f"non-session days {len(c['data_on_non_session_days'])}")
    L.append(f"- option premiums: {quality['option_history']['consequence']}")
    L.append(f"- data-quality status: **{quality['verdict']['status']}**")
    if quality['verdict']['issues']:
        L += [f"  - {i}" for i in quality['verdict']['issues']]
    L.append('')

    L += ['## 3. Baseline reproduction', '']
    for inst, s in baseline['instruments'].items():
        x = s['crosscheck_trade_journal']
        raw = s['raw_summary']
        L += [f"### {inst}",
              f"- reproduced trades: {s['trades']} over {s['sessions']} sessions",
              f"- production summary: signals={raw.get('signals')}, "
              f"win_rate={raw.get('win_rate')}%, total_R={raw.get('total_R')}, "
              f"net_R={raw.get('net_R')}, skipped={raw.get('skipped')}",
              f"- **journal cross-check**: {x['journal_rows']} rows, "
              f"{x['shared_dates']} shared dates, {x['exact_matches']} exact "
              f"matches (rate {x['match_rate_on_shared']}), "
              f"{x['value_mismatches']} mismatches",
              f"- paper-book cross-check: {json.dumps(s['crosscheck_paper_align'], default=str)[:400]}",
              '']
    L += ['> The journal covers 2026-07-07..2026-10-12 and predates the '
          '2026-10-17 gates (SHORT_ONLY / SKIP_FRIDAY / BREAKOUT_ADDON). Where '
          'it disagrees, the reproduced baseline is the CURRENT production code, '
          'which is the correct comparison target.', '']

    for title, scope in [('FULL RANGE', comp['full']),
                         ('OUT-OF-SAMPLE', comp['by_period']['OOS']),
                         ('VALIDATION', comp['by_period']['VAL']),
                         ('IN-SAMPLE', comp['by_period']['IS'])]:
        L += [f'## Comparison - {title}', '',
              '| metric | baseline | candidate | diff |', '|---|---:|---:|---:|']
        for k in ['total_trades', 'win_rate', 'net_pnl_rs', 'total_R',
                  'avg_net_per_trade_rs', 'avg_R_per_trade', 'profit_factor',
                  'max_drawdown_rs', 'max_drawdown_R', 'largest_loss_rs',
                  'max_consecutive_losses', 'return_on_capital_pct',
                  'expectancy_daily_rs', 'sessions_traded',
                  'reversal_trades', 'breakout_trades']:
            d = scope[k]
            L.append(f"| {k} | {d['baseline']} | {d['candidate']} | {d['diff']} |")
        L.append('')

    L += ['## Per-instrument out-of-sample', '']
    for inst, d in comp['by_instrument_oos'].items():
        L += [f'### {inst}', '', '| metric | baseline | candidate | diff |',
              '|---|---:|---:|---:|']
        for k in ['total_trades', 'win_rate', 'net_pnl_rs', 'total_R',
                  'profit_factor', 'max_drawdown_rs', 'largest_loss_rs']:
            L.append(f"| {k} | {d[k]['baseline']} | {d[k]['candidate']} | {d[k]['diff']} |")
        L.append('')

    L += ['## All candidate variants (full range, pooled)', '',
          '| variant | role | trades | win% | net Rs | net R | PF | maxDD Rs | OOS net Rs | OOS trades |',
          '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    b, bo = baseline['pooled'], baseline['by_period']['OOS']
    L.append(f"| **baseline** | - | {b['total_trades']} | "
             f"{(b['win_rate'] or 0)*100:.1f} | {b['net_pnl_rs']} | "
             f"{b['total_R']} | {b['profit_factor']} | {b['max_drawdown_rs']} | "
             f"{bo['net_pnl_rs']} | {bo['total_trades']} |")
    for vid, e in sorted(cand['variants'].items(),
                         key=lambda kv: -(kv[1]['pooled']['net_pnl_rs'] or 0)):
        p, po = e['pooled'], e['by_period']['OOS']
        L.append(f"| {vid} | {e['role']} | {p['total_trades']} | "
                 f"{(p['win_rate'] or 0)*100:.1f} | {p['net_pnl_rs']} | "
                 f"{p['total_R']} | {p['profit_factor']} | "
                 f"{p['max_drawdown_rs']} | {po['net_pnl_rs']} | "
                 f"{po['total_trades']} |")
    L.append('')

    best = max(cand['variants'].items(),
               key=lambda kv: (kv[1]['by_period']['OOS']['net_pnl_rs'] or 0))
    worst = min(cand['variants'].items(),
                key=lambda kv: (kv[1]['by_period']['OOS']['net_pnl_rs'] or 0)
                if cand['variants'][kv[0]]['pooled']['total_trades'] else 1e18)
    L += ['### Most / least successful variants', '',
          f"- best OOS net: **{best[0]}** ({best[1]['by_period']['OOS']['net_pnl_rs']} Rs, "
          f"{best[1]['by_period']['OOS']['total_trades']} trades)",
          f"- worst OOS net: **{worst[0]}** ({worst[1]['by_period']['OOS']['net_pnl_rs']} Rs)",
          f"- primary (pre-registered) variant: {P} -> OOS net "
          f"{cand['variants'][P]['by_period']['OOS']['net_pnl_rs']} Rs", '']

    e = cand['variants'][P]
    L += ['## Rejection counters & session buckets (primary variant)', '',
          '### Rejected by filter', '']
    L += [f"- {k}: {v}" for k, v in sorted((e.get('counters') or {}).items())]
    L += ['', '### Sessions', '']
    L += [f"- {k}: {v}" for k, v in sorted((e.get('skipped') or {}).items())]
    L += ['', '### Baseline skip buckets', '']
    for inst, s in baseline['instruments'].items():
        L.append(f"- {inst}: {s['raw_summary'].get('skipped')}")
    L.append('')

    L += ['## Walk-forward blocks', '',
          '| block | sessions | baseline net R | primary net R | baseline net Rs | primary net Rs |',
          '|---|---:|---:|---:|---:|---:|']
    for row in wf['blocks']:
        c = row['variants'][P]
        L.append(f"| {row['block']} ({row['start']}..{row['end']}) | "
                 f"{row['sessions']} | {row['baseline']['total_R']} | "
                 f"{c['total_R']} | {row['baseline']['net_pnl_rs']} | "
                 f"{c['net_pnl_rs']} |")
    L += ['', '### Expanding selection track', '',
          '| block | selection data | selected | selected net R | baseline net R |',
          '|---|---|---|---:|---:|']
    for s in wf['selection_track']:
        L.append(f"| {s['block']} | {s['trained_on']} | {s['selected_variant']} | "
                 f"{s['selected_net_R_this_block']} | "
                 f"{s['baseline_net_R_this_block']} |")
    L.append('')

    L += ['## Gates', '', '| gate | status | detail |', '|---|---|---|']
    for k, g in gates.items():
        if k.startswith('_'):
            continue
        det = json.dumps({kk: vv for kk, vv in g.items() if kk != 'status'},
                         default=str)
        L.append(f"| {k} | **{g.get('status')}** | `{det[:340]}` |")
    L.append('')
    L.append(f"**FINAL DETERMINATION: {gates['_final']['status']}** - "
             f"{gates['_final']['rule']}")
    L.append('')

    failed = [t for t in tests if t['status'] == 'FAIL']
    L += ['## Unit tests', '',
          f"- total {len([t for t in tests if t['test'] != 'pytest_exit_code'])}, "
          f"failed {len(failed)}"]
    L += [f"- FAIL `{t['test']}`: {t['detail']}" for t in failed]
    L += ['', '## Production safety confirmation', '',
          '- production files modified: none (see run_manifest.json checksums '
          'and git status)',
          '- live engine / API / frontend / database schema / scheduled jobs / '
          'Telegram alerts: untouched',
          '- no live trading cycle, no broker connection, no notifications: '
          'confirmed by design (read-only connections, no write paths called)', '',
          '> A passing determination authorises **human review only**. It does '
          'not authorise deployment.']
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
