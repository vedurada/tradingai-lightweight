"""Master runner for the setup-first study (Phase 3).

Order of operations (nothing outside the authorized run directory is written):

  1. capture the preflight state (git, protected hashes, services, live db),
  2. snapshot the live database into the run directory (read-only source,
     SQLite backup API) and point `TRADINGAI_DB_PATH` at a working copy of that
     snapshot BEFORE any `app.*` import, so the production engine module can
     only ever read the snapshot,
  3. data-quality report over the frozen range,
  4. production baseline run + independent re-simulation reconciliation,
  5. setup identification + state machine for every session,
  6. Experiments A-D, robustness, stop-out forensics, gates,
  7. reports, manifest and the final integrity verification.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

REPO = '/opt/tradingai'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from research.prevday_cpr_spread_study.stop_forensics.src import (prod, snapshot,
                                                                   data, accounting,
                                                                   metrics,
                                                                   candidates)

from . import config, setups, engine, integrity, deliverables, reporting

RUN_DIR = Path(__file__).resolve().parents[1]
OUT = RUN_DIR / 'outputs'
REPORTS = RUN_DIR / 'reports'
SNAPS = RUN_DIR / 'snapshots'
LIVE_DB = os.path.join(REPO, 'database', 'tradingai.db')
WORK_DB = SNAPS / 'working_copy.db'
SNAP_DB = SNAPS / 'tradingai_snapshot.db'

INSTRUMENTS = config.INSTRUMENTS
DATE_START = config.DATE_START
DATE_END = config.DATE_END


def log(msg):
    print(f"[setup_first] {msg}", flush=True)


def _period(day):
    for name, (a, b) in config.SPLITS.items():
        if a <= day <= b:
            return name
    return None


def prepare_snapshot():
    """Fresh consistent snapshot + writable working copy for the engine."""
    SNAPS.mkdir(parents=True, exist_ok=True)
    for p in (SNAP_DB,):
        if p.exists():
            p.unlink()
    for suffix in ('', '-wal', '-shm'):
        p = Path(str(WORK_DB) + suffix)
        if p.exists():
            p.unlink()
    meta = snapshot.create_snapshot(LIVE_DB, str(SNAP_DB))
    shutil.copyfile(str(SNAP_DB), str(WORK_DB))
    prod.ensure_db_env(str(WORK_DB))
    meta['work_copy'] = str(WORK_DB)
    return meta


def build_universe(conn, engine_mod):
    """Per-instrument session universe (all sessions, not only trigger days)."""
    out = {}
    for inst in INSTRUMENTS:
        sessions = {}
        for day in data.sessions(conn, inst, DATE_START, DATE_END):
            if day in config.EXCLUDED_DATES:
                continue
            sessions[day] = accounting.build_session(conn, engine_mod, inst, day)
        out[inst] = sessions
    return out


def identify_all_setups(universe, engine_mod):
    """Every setup of every session, point-in-time."""
    all_setups = []
    for inst in INSTRUMENTS:
        for day in sorted(universe[inst]):
            ctx = universe[inst][day]
            prev = ctx.get('prev')
            if not prev:
                continue
            period = _period(day)
            if period is None:
                continue
            scan = ctx['scan']
            if len(scan) < config.MIN_CANDLES:
                continue
            bundle = setups.level_bundle(engine_mod, prev)
            sess = setups.build_session_setups(inst, day, scan, bundle, period)
            for s in sess:
                s['ctx'] = ctx
                s['bundle'] = bundle
            all_setups.extend(sess)
    return all_setups


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    log('preflight capture')
    pre_state = integrity.capture('preflight')

    log('snapshot')
    snap_meta = prepare_snapshot()
    metrics.write_json(str(OUT / 'snapshot_meta.json'), snap_meta)
    integrity.write_preflight(RUN_DIR, pre_state, snap_meta)

    conn = data.ro_conn(str(SNAP_DB))
    engine_mod = prod.engine()

    log('data quality')
    dq = data.data_quality(conn, list(INSTRUMENTS), DATE_START, DATE_END)
    metrics.write_json(str(OUT / 'data_quality.json'), dq)
    log(f"  dq_status={dq.get('status')} problems={len(dq.get('problems') or [])}")

    log('baseline reproduction')
    univ_prod = {}
    base_records = []
    recon = {}
    for inst in INSTRUMENTS:
        u = accounting.build_universe(conn, engine_mod, inst, DATE_START, DATE_END)
        univ_prod[inst] = u
        recs = candidates.arm_baseline(u)
        base_records.extend(recs)
        recon[inst] = accounting.reconcile(u['run'], recs)
    recon_all = {
        'per_instrument': recon,
        'production_trades': sum(v['production_trades'] for v in recon.values()),
        'resimulated_trades': sum(v['resimulated_trades'] for v in recon.values()),
        'consistent': all(v['consistent'] for v in recon.values()),
        'issues': [i for v in recon.values() for i in v['issues']],
        'difference_R_total': round(sum(v['difference_R'] for v in recon.values()), 4),
        'note': ('the reconciliation is computed per instrument: the production '
                 'run of the two instruments is a single call and the records '
                 'must not be merged across instruments'),
    }
    metrics.write_json(str(OUT / 'baseline_reconciliation.json'), recon_all)
    log(f"  baseline {recon_all['production_trades']} trades, consistent="
        f"{recon_all['consistent']}")
    if not recon_all['consistent']:
        log('  BASELINE REPRODUCTION FAILED -> stopping before candidate work')
        metrics.write_json(str(OUT / 'run_manifest.json'), {
            'study': config.STUDY, 'verdict': 'BLOCKED_BASELINE_REPRODUCTION',
            'baseline_reconciliation': recon_all})
        return {'verdict': 'BLOCKED_BASELINE_REPRODUCTION'}
    metrics.write_csv(str(OUT / 'baseline_trades.csv'), base_records)

    log('session universe + setup identification')
    universe = build_universe(conn, engine_mod)
    all_setups = identify_all_setups(universe, engine_mod)
    log(f'  {len(all_setups)} setups identified over {len(universe[INSTRUMENTS[0]])} '
        f'{INSTRUMENTS[0]} sessions')

    log('experiments')
    results = deliverables.run_experiments(
        all_setups=all_setups, universe=universe, base_records=base_records,
        dq=dq, univ_prod=univ_prod, engine_mod=engine_mod, out=OUT,
        reports=REPORTS, run_dir=RUN_DIR)
    log(f"  verdict={results['verdict']} arm={results.get('candidate_arm')} "
        f"trades={results.get('candidate_trades')}")

    log('final integrity verification')
    post_state = integrity.capture('final')
    integrity.write_final(RUN_DIR, pre_state, post_state,
                           study_dir=str(RUN_DIR),
                           extra_notes=[
                               'the live database is written by the running service '
                               'on its normal schedule; this study only read a '
                               'snapshot of it',
                               'no alert, order, notification or deployment action '
                               'was triggered',
                           ])

    manifest = {
        'study': config.STUDY,
        'title': 'Phase 3 - setup-first trading, market swings, entry confirmation '
                 'and structural stop-loss',
        'verdict': results['verdict'],
        'candidate_arm': results.get('candidate_arm'),
        'selected_entry_policy': results.get('selected_entry_policy'),
        'selected_stop': results.get('selected_stop'),
        'candidate_trades': results.get('candidate_trades'),
        'experiment_d_run': results.get('experiment_d_run'),
        'frozen_config': {
            'splits': config.SPLITS,
            'instruments': list(INSTRUMENTS),
            'date_range': [DATE_START, DATE_END],
            'excluded_dates': list(config.EXCLUDED_DATES),
            'zone_pct': config.ZONE_PCT,
            'expiry_bars': config.EXPIRY_BARS,
            'max_entry_extension_pct': config.MAX_ENTRY_EXTENSION_PCT,
            'min_rr': config.MIN_RR,
            'min_stop_pct': config.MIN_STOP_PCT,
            'max_stop_pct': config.MAX_STOP_PCT,
            'eps_pct': config.EPS_PCT,
            'stop_pct': config.STOP_PCT,
            'target_pct': config.TARGET_PCT,
            'cost_r_per_trade': config.COST_R_PER_TRADE,
            'cost_grid': list(config.COST_GRID),
            'swing_m': config.SWING_M,
            'resistance_priority': list(config.RESISTANCE_PRIORITY),
            'support_priority': list(config.SUPPORT_PRIORITY),
            'setup_families': list(config.SETUP_FAMILIES),
        },
        'inputs': {
            'snapshot': snap_meta,
            'baseline_reconciliation': recon_all,
            'data_quality_status': dq.get('status'),
            'data_quality_problems': dq.get('problems'),
            'protected_hashes_preflight': pre_state['protected_hashes'],
        },
        'integrity': {
            'head_before': pre_state['git']['head'],
            'head_after': post_state['git']['head'],
            'branch_before': pre_state['git']['branch'],
            'branch_after': post_state['git']['branch'],
            'protected_hashes_identical': all(
                pre_state['protected_hashes'][k]['sha256']
                == post_state['protected_hashes'][k]['sha256']
                for k in pre_state['protected_hashes']),
            'git_status_lines_before': len(pre_state['git']['status'].splitlines()),
            'git_status_lines_after': len(post_state['git']['status'].splitlines()),
        },
        'production_change': 'NONE - research only, no production change is '
                             'authorised by this study',
        'outputs': sorted(p.name for p in OUT.iterdir()),
        'reports': sorted(p.name for p in REPORTS.iterdir()),
    }
    metrics.write_json(str(OUT / 'run_manifest.json'), manifest)
    log(f"  verdict={manifest['verdict']}")
    return results


if __name__ == '__main__':
    main()
