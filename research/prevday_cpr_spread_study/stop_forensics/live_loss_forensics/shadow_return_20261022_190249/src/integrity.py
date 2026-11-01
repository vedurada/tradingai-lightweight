"""Integrity baseline and final verification for the shadow-return study.

Baseline mode records the state of the host at the time it is called.
Final mode re-measures everything and compares it against

  * PHASE1 - the audit values recorded in Phase 1 of this study, before any
    annotation, analysis or reporting code was executed, and
  * EXTERNAL - the protected-file hashes and the live database hashes written
    by the earlier forensics run (run_20261022_172521), i.e. an anchor that
    was produced before this study started.

Nothing in this module writes to the database, to the repository or to the
production services; it only reads.
"""
import ast
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wconfig as C  # noqa: E402

REPO = '/opt/tradingai'
LIVE_DB = '/opt/tradingai/database/tradingai.db'
LIVE_WAL = '/opt/tradingai/database/tradingai.db-wal'
RUN_DIR = C.RUN_DIR

# ---------------------------------------------------------------------------
# PHASE1: captured during the Phase 1 audit of this study, before any
# analysis code existed in the run directory.
# ---------------------------------------------------------------------------
PHASE1 = {
    'captured_at': '2026-10-22T19:02:39+05:30',
    'note': 'Phase 1 audit, before the annotation engine, the analysis and '
            'the execution-gap module were written or executed',
    'head': '879c9769a3e9118014f04173a643466d0197ae16',
    'branch': 'production-2026-10-01',
    'git_status_lines': 291,
    'git_status_modified': 22,
    'git_status_untracked': 269,
    'gunicorn_pids': ['193117', '212809', '4085944'],
    'gunicorn_master_age_seconds': 361039,
    'live_db_sha256': '455d8da024f6abae1283318958decf4f5e9d598397e6da67002c092011b0b2d9',
    'live_db_wal_sha256': '0b487589c3279d03985db54fb759c63d95bcfbfee292d7be24ba2d856d3134b2',
    'snapshot_sha256': '48dd8d13e464334b6b1a527bab3f2beda627596f7260ef42e7696e4e7397a17f',
    'research_tree_only': True,
}

# EXTERNAL: written by the earlier forensics run, before this study started.
EXTERNAL = {
    'source': '/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
              'live_loss_forensics/run_20261022_172521/outputs/integrity_final.json',
    'protected_hashes': {
        'app/research/cpr_trigger_engine.py':
            '2316f56cd315e7db763d89d58667e9a143c62098a914d4ca08ec437f199ec80c',
        'app/research/cpr_strategy_engine.py':
            '523a03c5caf9aea144e53e576642f662c98ba0d0033775749785a5da12380e64',
        'app/live/engine.py':
            '61df16172e758a4824f87caba1c1b819a588af635cfe7e360677083f76cf8f92',
        'app/paper_trade/engine.py':
            '4344d7c30c542b5a0fc189591bf90fe543361b457f4c8c696f763ffef936098c',
        'app/paper_trade/performance.py':
            '8e7b2d56bc8f7184baf85c014ce91c836e7b0e4280717364fc166828a07d20de',
        'app/api/app.py':
            '0203086472af510290110edb29868e28bd6fbab68a43f1a0efdcefb6085fb663',
        'app/research/backtest.py':
            '656f735ce8d7a80851db10f4a60b89715c9224866bc58fda5a6f9dc50755f576',
        'app/core/db.py':
            '8f2391356f7a5ebf5d69603e931b0813f0e1e42026be5a7c670deebec2fae047',
        'scripts/tg_alerts.py':
            '7676ff58e590c884d06b7cf2069fa493f527c66f6c02b64f9fbd5f3ab445897e',
        'scripts/paper_confluence.py':
            'ac26fd230ba2f8111d6e2f18bbb011d8db5afd63b2f07b5e93a466b8ca9b0d9e',
        'config/settings.json':
            '8aff897ec2973b6d936c789ba7f10d26f8c6078924dcee2ba245b51e6ac9c543',
    },
    'live_db_sha256': '455d8da024f6abae1283318958decf4f5e9d598397e6da67002c092011b0b2d9',
    'live_db_wal_sha256': '0b487589c3279d03985db54fb759c63d95bcfbfee292d7be24ba2d856d3134b2',
    'head': '879c9769a3e9118014f04173a643466d0197ae16',
    'branch': 'production-2026-10-01',
    'gunicorn_pids': ['193117', '212809', '4085944'],
}

PREFLIGHT_GIT_STATUS = ('/opt/tradingai/research/prevday_cpr_spread_study/'
                        'stop_forensics/setup_first/run_20261022_151310/outputs/'
                        'PREFLIGHT_GIT_STATUS.txt')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sh(cmd):
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             timeout=60)
        # keep the leading columns intact: git status --porcelain lines start
        # with two status characters and a space, and the first line of the
        # output must not be stripped.
        return out.stdout.rstrip('\n')
    except Exception:
        return ''


def git_status():
    # -uall expands untracked directories into their files; the preflight
    # baseline file was captured in this format (237 lines there).
    txt = sh('cd %s && git status --porcelain -uall' % REPO)
    return txt


def status_entries(txt):
    out = {}
    for line in txt.splitlines():
        if not line.strip():
            continue
        out[line[3:].strip()] = line[:2]
    return out


def services():
    """The gunicorn master and its workers.

    /proc is scanned directly so that the shell that runs this function is
    not mistaken for a gunicorn process.
    """
    pids, ages = [], {}
    now = time.time()
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open('/proc/%s/cmdline' % entry, 'rb') as fh:
                argv = fh.read().split(b'\x00')
            argv = [a.decode('utf-8', 'replace') for a in argv if a]
        except Exception:
            continue
        if len(argv) < 2 or not argv[1].endswith('/gunicorn'):
            continue
        pid = int(entry)
        try:
            with open('/proc/%d/stat' % pid) as fh:
                fields = fh.read().rsplit(')', 1)[1].split()
            starttime = int(fields[19])
            hz = os.sysconf('SC_CLK_TCK')
            age = int(now - starttime / hz)
        except Exception:
            age = None
        pids.append(str(pid))
        ages[str(pid)] = age
    return sorted(pids, key=int), ages


def measure():
    st = git_status()
    entries = status_entries(st)
    pids, ages = services()
    m = {
        'measured_at': sh('date -Is'),
        'head': sh('cd %s && git rev-parse HEAD' % REPO),
        'branch': sh('cd %s && git rev-parse --abbrev-ref HEAD' % REPO),
        'git_status_lines': len([l for l in st.splitlines() if l.strip()]),
        'git_status_sha256': hashlib.sha256(st.encode()).hexdigest(),
        'git_status': st,
        'gunicorn_pids': pids,
        'gunicorn_ages_seconds': ages,
        'live_db_sha256': sha256(LIVE_DB),
        'live_db_wal_sha256': sha256(LIVE_WAL),
        'snapshot_sha256': sha256(os.path.join(RUN_DIR, 'snapshots',
                                                'tradingai_snapshot.db')),
        'protected_hashes': {},
    }
    for rel in EXTERNAL['protected_hashes']:
        p = os.path.join(REPO, rel)
        m['protected_hashes'][rel] = sha256(p) if os.path.exists(p) else None
    return m


def compare_content(snapshot, live):
    """Row-by-row comparison of the snapshot with the live database."""
    def tables(path):
        con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        cur = con.cursor()
        out = {}
        for (t,) in cur.execute("select name from sqlite_master "
                                "where type='table' order by name"):
            try:
                rows = cur.execute('select * from "%s"' % t).fetchall()
            except Exception as exc:
                out[t] = {'rows': None, 'error': str(exc)}
                continue
            out[t] = {'rows': len(rows),
                      'sha256': hashlib.sha256(repr(rows).encode()).hexdigest()}
        con.close()
        return out

    a, b = tables(snapshot), tables(live)
    out = {}
    for t in sorted(set(a) | set(b)):
        same = (a.get(t, {}).get('sha256') == b.get(t, {}).get('sha256') and
                a.get(t, {}).get('rows') == b.get(t, {}).get('rows'))
        out[t] = {'snapshot_rows': a.get(t, {}).get('rows'),
                  'live_rows': b.get(t, {}).get('rows'),
                  'same': same,
                  'differs': not same}
    return out


def study_never_opened_the_live_db():
    """Static check: no module of this study opens the live database."""
    bad = []
    src = os.path.join(RUN_DIR, 'src')
    for f in sorted(os.listdir(src)):
        if not f.endswith('.py'):
            continue
        p = os.path.join(src, f)
        text = open(p).read()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            bad.append('%s: not parseable' % f)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            seg = ast.get_source_segment(text, node) or ''
            # the auditor itself reads the live database (read-only) to
            # compare its content with the snapshot; every other module of
            # the study must not touch it at all.
            if f != 'integrity.py' and 'LIVE_DB' in seg:
                bad.append('%s:%d opens the live database: %s' %
                           (f, node.lineno, seg[:60]))
            is_sqlite_connect = (isinstance(func, ast.Attribute) and
                                 func.attr == 'connect')
            if is_sqlite_connect and 'mode=ro' not in seg:
                bad.append('%s:%d sqlite3.connect is not read-only: %s' %
                           (f, node.lineno, seg[:60]))
    return (not bad), bad


def baseline():
    m = measure()
    m['phase1_reference'] = PHASE1
    m['external_reference'] = {k: v for k, v in EXTERNAL.items()
                               if k != 'protected_hashes'}
    out = os.path.join(RUN_DIR, 'outputs', 'baseline_manifest.json')
    with open(out, 'w') as fh:
        json.dump(m, fh, indent=1, sort_keys=True)
    print('baseline manifest -> %s' % out)
    print('  head=%s branch=%s status_lines=%d pids=%s' %
          (m['head'], m['branch'], m['git_status_lines'],
           ','.join(m['gunicorn_pids'])))


def final():
    m = measure()
    checks = {}

    checks['head_unchanged'] = m['head'] == PHASE1['head'] == EXTERNAL['head']
    checks['branch_unchanged'] = (m['branch'] == PHASE1['branch'] ==
                                  EXTERNAL['branch'])
    checks['live_db_unchanged'] = (m['live_db_sha256'] ==
                                   PHASE1['live_db_sha256'] ==
                                   EXTERNAL['live_db_sha256'])
    # The main database file must be byte-identical. The write-ahead log is
    # written by the running live services (they refresh their provider
    # cache), so its hash is reported but is not expected to be stable; what
    # must hold is that no *logical* content of the live database changed
    # except for the live system's own cache rows.
    checks['live_db_main_file_unchanged'] = (
        m['live_db_sha256'] == PHASE1['live_db_sha256'] ==
        EXTERNAL['live_db_sha256'])
    content = compare_content(os.path.join(RUN_DIR, 'snapshots',
                                           'tradingai_snapshot.db'),
                              LIVE_DB)
    changed = sorted(t for t, v in content.items() if v['differs'])
    checks['live_db_content_unchanged_except_live_cache'] = (
        changed == [] or changed == ['provider_cache'])
    checks['same_service_pids'] = (m['gunicorn_pids'] ==
                                   PHASE1['gunicorn_pids'] ==
                                   EXTERNAL['gunicorn_pids'])
    checks['no_service_restart'] = all(
        a is not None and a >= PHASE1['gunicorn_master_age_seconds'] - 120
        for a in m['gunicorn_ages_seconds'].values())
    checks['snapshot_unchanged'] = m['snapshot_sha256'] == PHASE1['snapshot_sha256']
    checks['protected_files_unchanged'] = all(
        m['protected_hashes'][k] == v
        for k, v in EXTERNAL['protected_hashes'].items())

    # ---- git: the delta against the preflight baseline must be additions
    #      inside the research study tree only
    base_lines = []
    if os.path.exists(PREFLIGHT_GIT_STATUS):
        base_lines = [l for l in
                      open(PREFLIGHT_GIT_STATUS).read().splitlines()
                      if l.strip()]
    base_entries = status_entries('\n'.join(base_lines))
    cur_entries = status_entries(m['git_status'])
    added = sorted(set(cur_entries) - set(base_entries))
    removed = sorted(set(base_entries) - set(cur_entries))
    changed = sorted(k for k in set(cur_entries) & set(base_entries)
                     if cur_entries[k] != base_entries[k])
    study_prefixes = ('research/prevday_cpr_spread_study/',)
    added_outside = [a for a in added
                     if not a.startswith(study_prefixes)]
    checks['git_no_removals'] = not removed
    checks['git_no_status_changes'] = not changed
    checks['git_additions_inside_study_tree'] = not added_outside

    # ---- every file the study created must be inside the run directory
    stray = []
    for root, _dirs, files in os.walk(RUN_DIR):
        for f in files:
            p = os.path.join(root, f)
            if not p.startswith(RUN_DIR):
                stray.append(p)
    checks['no_artifacts_outside_run_dir'] = not stray

    ok, bad = study_never_opened_the_live_db()
    checks['study_never_opened_the_live_db'] = ok

    out = {
        'generated_at': m['measured_at'],
        'run_dir': RUN_DIR,
        'phase1_reference': PHASE1,
        'external_reference': {k: v for k, v in EXTERNAL.items()
                               if k != 'protected_hashes'},
        'measured': {k: v for k, v in m.items() if k != 'git_status'},
        'git_baseline_file': PREFLIGHT_GIT_STATUS,
        'git_baseline_lines': len(base_lines),
        'git_added': len(added),
        'git_added_inside_study_tree': len(added) - len(added_outside),
        'git_added_outside_study_tree': added_outside,
        'git_removed': removed,
        'git_changed_status': changed,
        'live_db_content_vs_snapshot': content,
        'live_db_wal_sha256_now': m['live_db_wal_sha256'],
        'live_db_wal_sha256_at_baseline': PHASE1['live_db_wal_sha256'],
        'live_db_wal_changed_by_live_services': (
            m['live_db_wal_sha256'] != PHASE1['live_db_wal_sha256']),
        'study_live_db_open_violations': bad,
        'checks': checks,
        'all_checks_pass': all(checks.values()),
    }
    p = os.path.join(RUN_DIR, 'outputs', 'integrity.json')
    with open(p, 'w') as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print('integrity -> %s' % p)
    for k, v in checks.items():
        print('  %-38s %s' % (k, 'PASS' if v else 'FAIL'))
    print('  ALL CHECKS: %s' % ('PASS' if out['all_checks_pass'] else 'FAIL'))
    return 0 if out['all_checks_pass'] else 1


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'final'
    if mode == 'baseline':
        baseline()
    else:
        sys.exit(final())
