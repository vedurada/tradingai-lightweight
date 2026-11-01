"""Integrity checks for the wait-for-setup study (read-only).

Mirrors the checks of the previous forensics run so the two studies are
comparable:
  * the sha256 of every protected production file (before = the values recorded
    by the previous run, now = recomputed),
  * the live database and WAL hashes,
  * the gunicorn service pids and their ages (a restart would reset the age),
  * the git status compared with the Phase-3 pre-study baseline.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import wconfig as C  # noqa: E402

REPO = '/opt/tradingai'
P3_DIR = ('/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
          'setup_first/run_20261022_151310')
PREV_RUN = ('/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
            'live_loss_forensics/run_20261022_172521')
STUDY_TREE = 'research/prevday_cpr_spread_study/stop_forensics/'

PROTECTED = [
    'app/research/cpr_trigger_engine.py',
    'app/research/cpr_strategy_engine.py',
    'app/live/engine.py',
    'app/paper_trade/engine.py',
    'app/paper_trade/performance.py',
    'app/api/app.py',
    'app/research/backtest.py',
    'app/core/db.py',
    'scripts/tg_alerts.py',
    'scripts/paper_confluence.py',
    'config/settings.json',
]


def sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def git(args):
    return subprocess.run(['git', '-C', REPO] + args, capture_output=True,
                          text=True, check=False).stdout


def ps_services():
    out = subprocess.run(['ps', '-eo', 'pid=,etimes=,args='], capture_output=True,
                         text=True, check=False).stdout
    pids = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, args = parts
        if 'gunicorn' in args and 'grep' not in args:
            pids[pid] = int(etimes)
    return pids


def main():
    prev = json.load(open(os.path.join(PREV_RUN, 'outputs', 'integrity_final.json')))
    before_hashes = prev['before']['protected_hashes']

    now_hashes = {p: sha256(os.path.join(REPO, p)) for p in PROTECTED}
    unchanged_files = {p: (now_hashes[p] == before_hashes.get(p)) for p in PROTECTED}

    db = '/opt/tradingai/database/tradingai.db'
    wal = db + '-wal'
    live_now = {'db': sha256(db), 'wal': sha256(wal)}
    live_before = {'db': prev['before']['live_db']['sha256'],
                   'wal': prev['before']['live_db_wal']['sha256']}

    services_now = ps_services()
    services_before = prev['before']['services']

    # git status vs the Phase-3 pre-study baseline
    baseline_path = os.path.join(P3_DIR, 'outputs', 'PREFLIGHT_GIT_STATUS.txt')
    base_lines = [l for l in open(baseline_path).read().splitlines() if l.strip()]
    cur_lines = [l for l in git(['status', '--porcelain=v1', '-uall']).splitlines()
                 if l.strip()]

    def path_of(line):
        return line[3:].strip() if len(line) > 3 else line.strip()

    base_map = {path_of(l): l for l in base_lines}
    cur_map = {path_of(l): l for l in cur_lines}
    added = sorted(cur_map[p] for p in set(cur_map) - set(base_map))
    removed = sorted(base_map[p] for p in set(base_map) - set(cur_map))
    changed = sorted(p for p in set(base_map) & set(cur_map)
                     if base_map[p][:2] != cur_map[p][:2])
    run_rel = os.path.relpath(ROOT, REPO)
    inside_run = [l for l in added if run_rel in l]
    inside_tree = [l for l in added if STUDY_TREE in l]
    outside_tree = [l for l in added if STUDY_TREE not in l]

    result = {
        'generated_at': subprocess.run(['date', '-Is'], capture_output=True,
                                       text=True).stdout.strip(),
        'run_dir': ROOT,
        'snapshot': {'path': C.SNAPSHOT_DB, 'sha256': sha256(C.SNAPSHOT_DB)},
        'protected_files_unchanged': unchanged_files,
        'all_protected_files_unchanged': all(unchanged_files.values()),
        'live_db': {'before': live_before, 'now': live_now,
                    'unchanged': live_before == live_now},
        'services': {'before_pids': services_before['gunicorn_pids'],
                     'now_pids': sorted(services_now, key=int),
                     'now_ages_seconds': services_now,
                     'same_pids': sorted(services_before['gunicorn_pids']) ==
                     sorted(services_now, key=int),
                     'master_age_seconds': services_now.get('4085944')},
        'git': {'branch': git(['rev-parse', '--abbrev-ref', 'HEAD']).strip(),
                'head': git(['rev-parse', 'HEAD']).strip(),
                'branch_unchanged': git(['rev-parse', '--abbrev-ref', 'HEAD']).strip() ==
                prev['before'].get('branch'),
                'head_unchanged': git(['rev-parse', 'HEAD']).strip() ==
                prev['before'].get('head'),
                'baseline_file': baseline_path,
                'baseline_lines': len(base_lines),
                'current_lines': len(cur_lines),
                'added_count': len(added),
                'added_inside_this_run_dir': len(inside_run),
                'added_inside_study_tree': len(inside_tree),
                'added_outside_study_tree': len(outside_tree),
                'added_outside_study_tree_entries': outside_tree,
                'removed_count': len(removed),
                'removed_entries': removed,
                'changed_status_count': len(changed),
                'changed_status_entries': changed},
    }
    result['all_checks_pass'] = bool(
        result['all_protected_files_unchanged'] and result['live_db']['unchanged']
        and result['services']['same_pids']
        and result['git']['added_outside_study_tree'] == 0
        and result['git']['removed_count'] == 0
        and result['git']['changed_status_count'] == 0
        and result['git']['branch_unchanged'] and result['git']['head_unchanged'])

    os.makedirs(C.OUT_DIR, exist_ok=True)
    path = os.path.join(C.OUT_DIR, 'integrity.json')
    with open(path, 'w') as fh:
        json.dump(result, fh, indent=2, sort_keys=True, default=str)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result['all_checks_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
