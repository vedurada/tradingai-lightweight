"""Read-only access to the database snapshot and the production repository state."""
import hashlib
import json
import os
import sqlite3
import subprocess

from . import config


def connect(snapshot=None):
    """Open the snapshot strictly read-only."""
    path = snapshot or config.SNAPSHOT
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn, table, where=None, params=(), order=None):
    sql = f'SELECT * FROM "{table}"'
    if where:
        sql += f' WHERE {where}'
    if order:
        sql += f' ORDER BY {order}'
    return [dict(r) for r in conn.execute(sql, params)]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _git(args, cwd=config.REPO):
    try:
        return subprocess.run(['git'] + args, cwd=cwd, capture_output=True,
                              text=True, timeout=60).stdout
    except Exception as exc:                       # pragma: no cover - defensive
        return f'ERROR: {exc}'


def protected_hashes():
    """Hashes of the production files that must not change during the study."""
    files = [
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
    out = {}
    for rel in files:
        path = os.path.join(config.REPO, rel)
        try:
            out[rel] = sha256_file(path)
        except OSError as exc:
            out[rel] = f'ERROR: {exc}'
    return out


def service_state():
    """Process state of the production web service.

    Only real gunicorn processes are counted: the command line of a shell that
    merely mentions gunicorn (for example the shell that runs this study)
    must not be mistaken for a service process.
    """
    try:
        ps = subprocess.run(['ps', '-eo', 'pid=,etimes=,args='],
                            capture_output=True, text=True, timeout=30).stdout
    except Exception:                              # pragma: no cover - defensive
        ps = ''
    pids = []
    ages = {}
    for line in ps.splitlines():
        line = line.strip()
        if not line or 'gunicorn' not in line or 'app.api.app' not in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        if not parts[2].startswith('/usr/bin/python3') and \
                not parts[2].startswith('/usr/local/bin/gunicorn') and \
                not parts[2].startswith('python3'):
            # a shell or an editor that mentions gunicorn in its arguments
            continue
        pids.append(parts[0])
        ages[parts[0]] = parts[1]
    return {'gunicorn_pids': pids,
            'gunicorn_ages_seconds': ages,
            'gunicorn_count': len(pids)}


def db_meta(path):
    try:
        st = os.stat(path)
    except OSError as exc:
        return {'error': str(exc)}
    return {'path': path, 'size': st.st_size, 'mtime': st.st_mtime,
            'sha256': sha256_file(path)}


def capture_state(label):
    """Full read-only snapshot of the production state."""
    status = _git(['status', '--porcelain=v1', '-uall'])
    state = {
        'label': label,
        'branch': _git(['rev-parse', '--abbrev-ref', 'HEAD']).strip(),
        'head': _git(['rev-parse', 'HEAD']).strip(),
        'git_status': status,
        'git_status_lines': len([x for x in status.splitlines() if x.strip()]),
        'git_status_sha256': hashlib.sha256(status.encode()).hexdigest(),
        'protected_hashes': protected_hashes(),
        'live_db': db_meta(os.path.join(config.REPO, 'database/tradingai.db')),
        'live_db_wal': db_meta(os.path.join(config.REPO, 'database/tradingai.db-wal')),
        'services': service_state(),
    }
    return state


def baseline_status_diff():
    """Compare the current git status with the pre-study baseline.

    The baseline is the git status that was captured before the stop_forensics
    work started (Phase 3 preflight). It is the reference for the claim that
    the study only added files inside its own run directory.
    """
    baseline_path = os.path.join(config.P3_DIR, 'outputs', 'PREFLIGHT_GIT_STATUS.txt')
    if not os.path.exists(baseline_path):
        return None
    with open(baseline_path) as fh:
        base_lines = [l for l in fh.read().splitlines() if l.strip()]
    cur_lines = [l for l in _git(['status', '--porcelain=v1', '-uall']).splitlines()
                 if l.strip()]

    def path_of(line):
        return line[3:].strip() if len(line) > 3 else line.strip()

    base_map = {path_of(l): l for l in base_lines}
    cur_map = {path_of(l): l for l in cur_lines}
    added = sorted(cur_map[p] for p in set(cur_map) - set(base_map))
    removed = sorted(base_map[p] for p in set(base_map) - set(cur_map))
    changed_status = sorted(p for p in set(base_map) & set(cur_map)
                            if base_map[p][:2] != cur_map[p][:2])
    run_rel = os.path.relpath(config.RUN_DIR, config.REPO)
    inside = [l for l in added if run_rel in l]
    outside = [l for l in added if run_rel not in l]
    return {
        'baseline_file': baseline_path,
        'baseline_lines': len(base_lines),
        'current_lines': len(cur_lines),
        'added_count': len(added),
        'added_inside_run_dir': len(inside),
        'added_outside_run_dir': len(outside),
        'removed_count': len(removed),
        'removed_entries': removed,
        'changed_status_count': len(changed_status),
        'changed_status_entries': changed_status,
        'added_outside_run_dir_entries': outside,
    }


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write('\n')
    return path


def read_json(path):
    with open(path) as fh:
        return json.load(fh)
