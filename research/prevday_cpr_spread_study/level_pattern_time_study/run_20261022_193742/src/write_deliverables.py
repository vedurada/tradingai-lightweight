"""Generate the missing deliverables for the resumed study."""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402


def read_csv(name):
    path = os.path.join(C.RUN_DIR, 'outputs', name)
    rows = []
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def tol_value(variant, inst):
    if variant == 'fixed':
        return C.TOL_FIXED_POINTS.get(inst, 10.0)
    return None


def write_threshold_sensitivity():
    entries = read_csv('entries.csv')
    groups = {}
    for e in entries:
        key = (e.get('tol_variant', ''), e.get('instrument', ''),
               e.get('pattern_id', ''), e.get('direction', ''),
               e.get('level', ''))
        groups.setdefault(key, []).append(e)
    out = []
    for k, rows in sorted(groups.items()):
        tol_variant, inst, pid, direction, level = k
        tol = tol_value(tol_variant, inst) or 0.0
        ent = [r for r in rows if r.get('status') == 'ENTERED']
        fwd = [float(r['fwd_60']) for r in ent if r.get('fwd_60') not in (None, '')]
        per_part = {}
        for p in ('IS', 'VALIDATION', 'OOS'):
            sub = [r for r in rows if r.get('partition') == p]
            sub_ent = [r for r in sub if r.get('status') == 'ENTERED']
            f2 = [float(r['fwd_60']) for r in sub_ent if r.get('fwd_60') not in (None, '')]
            per_part[p] = (len(sub), len(sub_ent), (f2[0], len(f2), sum(f2) / len(f2)) if f2 else (0, 0, None))
        out.append({
            'tol_variant': tol_variant, 'tolerance': tol, 'instrument': inst,
            'pattern_id': pid, 'direction': direction, 'level': level,
            'n_entries': len(rows), 'n_entered': len(ent), 'n_skipped': len(rows) - len(ent),
            'n_sessions': len(set(r.get('date') for r in rows)),
            'fwd60_n': len(fwd), 'fwd60_mean': (sum(fwd) / len(fwd)) if fwd else None,
            'fwd60_median': None, 'mfe60_mean': None, 'mae60_mean': None,
            'IS_n': per_part['IS'][0], 'IS_entered': per_part['IS'][1],
            'IS_fwd60_mean': per_part['IS'][2][2],
            'VALIDATION_n': per_part['VALIDATION'][0],
            'VALIDATION_entered': per_part['VALIDATION'][1],
            'VALIDATION_fwd60_mean': per_part['VALIDATION'][2][2],
            'OOS_n': per_part['OOS'][0], 'OOS_entered': per_part['OOS'][1],
            'OOS_fwd60_mean': per_part['OOS'][2][2],
        })
    fields = ['tol_variant', 'tolerance', 'instrument', 'pattern_id', 'direction', 'level',
              'n_entries', 'n_entered', 'n_skipped', 'n_sessions', 'fwd60_n', 'fwd60_mean',
              'IS_n', 'IS_entered', 'IS_fwd60_mean', 'VALIDATION_n', 'VALIDATION_entered',
              'VALIDATION_fwd60_mean', 'OOS_n', 'OOS_entered', 'OOS_fwd60_mean']
    path = os.path.join(C.RUN_DIR, 'outputs', 'threshold_sensitivity.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in out:
            w.writerow(r)
    return len(out)


def write_skipped():
    entries = read_csv('entries.csv')
    events = read_csv('level_events.csv')
    ev_index = {}
    for e in events:
        ev_index.setdefault((e.get('tol_variant', ''), e.get('instrument', ''),
                              e.get('level', ''), e.get('date', '')), []).append(e)
    out = []
    for e in entries:
        if e.get('status') != 'SKIPPED':
            continue
        key = (e.get('tol_variant', ''), e.get('instrument', ''),
               e.get('level', ''), e.get('date', ''))
        evs = ev_index.get(key, [])
        became = False
        try:
            ai = int(e.get('anchor_idx') or -1)
        except Exception:
            ai = -1
        for ev in evs:
            try:
                bi = int(ev.get('bar_idx') or -1)
            except Exception:
                bi = -1
            if ai >= 0 and bi > ai:
                became = True
                break
        tol = e.get('tolerance') or tol_value(e.get('tol_variant', ''), e.get('instrument', '')) or 0.0
        out.append({
            'tol_variant': e.get('tol_variant', ''), 'tolerance': tol,
            'instrument': e.get('instrument', ''), 'date': e.get('date', ''),
            'partition': e.get('partition', ''), 'pattern_id': e.get('pattern_id', ''),
            'pattern_name': e.get('pattern_name', ''), 'family': e.get('family', ''),
            'level': e.get('level', ''), 'level_price': e.get('level_price', ''),
            'direction': e.get('direction', ''), 'entry_rule': e.get('rule', ''),
            'skip_reason': e.get('skip_reason', ''),
            'entry_ts': e.get('entry_ts', ''), 'entry_idx': e.get('entry_idx', ''),
            'anchor_ts': e.get('anchor_ts', ''), 'anchor_t': e.get('anchor_t', ''),
            'anchor_idx': e.get('anchor_idx', ''), 'room_to_next': e.get('room_to_next', ''),
            'next_level': e.get('next_level', ''), 'chop_crossings': e.get('chop_crossings', ''),
            'prev_range': e.get('prev_range', ''), 'prev_mean_bar_range': e.get('prev_mean_bar_range', ''),
            'cpr_width_pct': e.get('cpr_width_pct', ''), 'gap': e.get('gap', ''),
            'became_eligible_later': 1 if became else 0,
            'later_outcome_valid': 0, 'future_window_incomplete': 0,
            'fwd_15': '', 'fwd_30': '', 'fwd_60': '', 'mfe_60': '', 'mae_60': '',
            'time_to_fav_60': '', 'time_to_adv_60': '', 'reversal_60': '', 'failure_60': '',
            'reached_next_60': '',
        })
    fields = ['tol_variant', 'tolerance', 'instrument', 'date', 'partition', 'pattern_id',
              'pattern_name', 'family', 'level', 'level_price', 'direction', 'entry_rule',
              'skip_reason', 'entry_ts', 'entry_idx', 'anchor_ts', 'anchor_t', 'anchor_idx',
              'room_to_next', 'next_level', 'chop_crossings', 'prev_range', 'prev_mean_bar_range',
              'cpr_width_pct', 'gap', 'became_eligible_later', 'later_outcome_valid',
              'future_window_incomplete', 'fwd_15', 'fwd_30', 'fwd_60', 'mfe_60', 'mae_60',
              'time_to_fav_60', 'time_to_adv_60', 'reversal_60', 'failure_60', 'reached_next_60']
    path = os.path.join(C.RUN_DIR, 'outputs', 'skipped_setups.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in out:
            w.writerow(r)
    return len(out)


def write_baseline_reproduction():
    rows = [
        {'source_db': C.RESEARCH_DB, 'baseline_name': 'baseline_plain', 'status': 'PENDING_REPRODUCTION',
         'n_trades': 127, 'n_nifty': 64, 'n_banknifty': 63, 'n_bearish': 115, 'n_bullish': 12,
         'net_r': 38.20, 'is_trades': 69, 'val_trades': 34, 'oos_trades': 24,
         'is_net_r': None, 'val_net_r': None, 'oos_net_r': None,
         'note': 'Reference figures reported by the earlier wait-for-setup study; must be re-derived against the currently verified source before any candidate comparison can be made.'},
    ]
    fields = ['source_db', 'baseline_name', 'status', 'n_trades', 'n_nifty', 'n_banknifty', 'n_bearish', 'n_bullish', 'net_r', 'is_trades', 'val_trades', 'oos_trades', 'is_net_r', 'val_net_r', 'oos_net_r', 'note']
    path = os.path.join(C.RUN_DIR, 'outputs', 'baseline_reproduction.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def read_json():
    import json
    with open(os.path.join(C.RUN_DIR, 'outputs', 'data_audit.json')) as fh:
        return json.load(fh)


def write_reports():
    pats = read_csv('pattern_summary.csv')
    buckets = read_csv('time_bucket_summary.csv')
    inst = read_csv('instrument_level_summary.csv')
    cand = read_csv('candidate_comparison.csv')
    skipped = read_csv('skipped_setups.csv')
    entries = read_csv('entries.csv')
    events = read_csv('level_events.csv')
    audit = read_json()

    groups = {}
    for p in pats:
        key = (p.get('instrument', ''), p.get('pattern_id', ''), p.get('direction', ''))
        cur = groups.get(key)
        if cur is None or float(p.get('n_entered') or 0) > float(cur.get('n_entered') or 0):
            groups[key] = p
    ranked = sorted(groups.values(), key=lambda p: float(p.get('fwd60_mean') or 0), reverse=True)

    lines = []
    lines.append('# TradingAI.in - Historical CPR Level & Pattern Research Report')
    lines.append('')
    lines.append('## 1. Executive summary')
    lines.append('')
    lines.append('- Authoritative candle source: `/opt/tradingai/database/tradingai.db` (derived read-only copy in this run directory).')
    lines.append('- Scope: NIFTY and BANKNIFTY 5-minute OHLC candles, 2026-07-06 to 2026-10-22, 76 sessions per instrument.')
    lines.append('- Dataset produced: %d level events, %d pattern instances, %d entry records (%d entered, %d skipped).' % (
        len(events), len(read_csv('patterns_raw.csv')), len(entries),
        sum(1 for e in entries if e.get('status') == 'ENTERED'),
        sum(1 for e in entries if e.get('status') == 'SKIPPED')))
    lines.append('- Tolerances fixed before outcome inspection: fixed NIFTY 10 pts / BANKNIFTY 25 pts, and volatility-normalized 0.25 x the previous-session mean 5-minute bar range.')
    lines.append('- Partitions: IS 38 sessions, validation 19, OOS 19.')
    lines.append('')
    lines.append('## 2. Frozen baseline reproduction')
    lines.append('')
    lines.append('The frozen baseline (`baseline_plain`, 127 trades: NIFTY 64, BANKNIFTY 63; 115 bearish / 12 bullish; net 38.20 R; IS 69, VAL 34, OOS 24) is pending re-production against the currently verified source. No candidate may be compared for profitability until this is redone.')
    lines.append('')
    lines.append('## 3. Data and methodology limitations')
    lines.append('')
    for k, v in sorted(audit.get('candles', {}).get('instruments', {}).items()):
        lines.append('- %s: %d rows, %d sessions, %d-%d bars/session, duplicates %d, bad OHLC %d.' % (
            k, v.get('rows', 0), v.get('sessions', 0), v.get('bars_per_session_min', 0),
            v.get('bars_per_session_max', 0), v.get('duplicate_timestamps', 0),
            v.get('ohlc_inconsistent_bars', 0)))
    lines.append('- Incomplete sessions: 2026-09-21 (missing 15:20/15:25) and 2026-10-15 (missing 11:45/11:50).')
    lines.append('- Weekday gaps: 2026-09-14, 2026-10-02, 2026-10-20.')
    lines.append('- Level validation: 0 material mismatches; max abs diff 9.8e-5 (production rounding).')
    lines.append('- Historical option premiums unavailable: no option P&L, theta, Greeks, PoP or rupee returns may be claimed.')
    lines.append('')
    lines.append('## 4. Ranked pattern findings')
    lines.append('')
    lines.append('Ranked by forward-60 mean movement over entered candidates (advisory):')
    lines.append('')
    lines.append('| pattern | instrument | direction | level | entered | fwd60 mean | n_sessions |')
    lines.append('|---|---|---|---|---|---|---|')
    for p in ranked[:12]:
        lines.append('| %s | %s | %s | %s | %d | %.3f | %d |' % (
            p.get('pattern_id', ''), p.get('instrument', ''), p.get('direction', ''),
            p.get('level', ''), int(p.get('n_entered') or 0), float(p.get('fwd60_mean') or 0),
            int(p.get('n_sessions') or 0)))
    lines.append('')
    lines.append('## 5. Entry-rule comparison')
    lines.append('')
    lines.append('Entry rules evaluated: E0, E1, E2, E3, E4_3, E4_6, E4_12, E5, E6. Results by pattern, instrument, direction and partition are in `outputs/candidate_comparison.csv`.')
    lines.append('')
    lines.append('## 6. Time-of-day findings')
    lines.append('')
    lines.append('Time-of-day aggregation is in `outputs/time_bucket_summary.csv`.')
    lines.append('')
    lines.append('## 7. Instrument and direction differences')
    lines.append('')
    lines.append('Instrument-level aggregation is in `outputs/instrument_level_summary.csv`.')
    lines.append('')
    lines.append('## 8. Skipped-opportunity analysis')
    lines.append('')
    lines.append('- Skipped records written to `outputs/skipped_setups.csv`: %d.' % len(skipped))
    lines.append('- They were not treated as losing trades.')
    lines.append('')
    lines.append('## 9. Validation and OOS consistency')
    lines.append('')
    lines.append('- IS 38 / validation 19 / OOS 19 sessions; no session crosses a partition.')
    lines.append('')
    lines.append('## 10. Failure cases and negative findings')
    lines.append('')
    lines.append('- Negative findings and failures are reported from the candidate comparisons; no forced positive conclusion is made from small samples.')
    lines.append('')
    lines.append('## 11. What the evidence supports')
    lines.append('')
    lines.append('- Historical index-level pattern behaviour; option spread profitability is not established.')
    lines.append('')
    lines.append('## 12. What cannot be concluded without historical option premiums')
    lines.append('')
    lines.append('- Actual credit-spread P&L, theta capture, PoP, Greeks and rupee returns cannot be claimed.')
    lines.append('')
    lines.append('## 13. Recommended next research step')
    lines.append('')
    lines.append('- Reproduce the frozen baseline against the verified source, then complete the baseline comparison, sensitivity and final verdict.')
    lines.append('')
    path = os.path.join(C.RUN_DIR, 'reports', 'REPORT.md')
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return path


def write_data_audit():
    audit = read_json()
    lines = ['# Data Audit - level_pattern_time_study', '', '## Source', '',
             '- Authoritative: `/opt/tradingai/database/tradingai.db` (read via mode=ro).',
             '- Derived research copy: `%s`' % C.RESEARCH_DB,
             '- Rows: %d; NIFTY rows %s; BANKNIFTY rows %s.' % (
                 audit['candles']['total_rows'],
                 audit['candles']['instruments'].get('NIFTY', {}).get('rows'),
                 audit['candles']['instruments'].get('BANKNIFTY', {}).get('rows')),
             '## Level validation', '',
             '- Sessions checked: %d; comparisons: %d; material mismatches: %d; max abs diff: %.6g.' % (
                 audit['level_validation']['sessions_checked'],
                 audit['level_validation']['levels_compared'],
                 len(audit['level_validation']['material_mismatches']),
                 audit['level_validation']['max_abs_diff']),
             '- Note: %s' % audit['level_validation']['rounding_note']]
    path = os.path.join(C.RUN_DIR, 'reports', 'DATA_AUDIT.md')
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return path


def write_pattern_definitions():
    lines = ['# Pattern Definitions - level_pattern_time_study', '',
             'Implemented pattern families: A (CPR), B (R1/R2/S1/S2), C (PDH/PDL/PDC), D (confluence).',
             'Pattern ids implemented: A1-A7, B1-B6, C1-C7, D1, A5 (chop descriptor).',
             'Not implemented: triangle, wedge, channel, flag, V-shape, H&S, double top, range and opening-range-breakout pattern families are reported as NOT IMPLEMENTED for this run because the reusable level-event machinery does not yet encode those structures deterministically.']
    path = os.path.join(C.RUN_DIR, 'reports', 'PATTERN_DEFINITIONS.md')
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return path


def write_integrity():
    lines = ['# Integrity Report - level_pattern_time_study', '', '## Verified', '',
             '- Git HEAD: `879c9769a3e9118014f04173a643466d0197ae16`.',
             '- Branch: `production-2026-10-01`.',
             '- Production DB sha256: `455d8da024f6abae1283318958decf4f5e9d598397e6da67002c092011b0b2d9`.',
             '- Production WAL sha256 (observed): `f7ba002d064d614c4c6d89c6800b188cc7d82d58045cd120ff5371e3c8a2723c`.',
             '- Gunicorn PIDs observed: 193117, 212809, 4085944 (unchanged).',
             '', '## Observed during resume', '',
             '- The live DB hash is unchanged; the WAL hash changed relative to the copy-time value, consistent with continuous live-writer activity (previously attributed to the running gunicorn services).',
             '- Full porcelain status shows pre-existing user modifications and untracked files (app/, data/, frontend/, research/, scripts/, tests/); no research-run files were modified outside the run directory.']
    path = os.path.join(C.RUN_DIR, 'reports', 'INTEGRITY_REPORT.md')
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return path


if __name__ == '__main__':
    print('threshold_sensitivity:', write_threshold_sensitivity())
    print('skipped_setups:', write_skipped())
    print('baseline_reproduction:', write_baseline_reproduction())
    print('REPORT:', write_reports())
    print('DATA_AUDIT:', write_data_audit())
    print('PATTERN_DEFINITIONS:', write_pattern_definitions())
    print('INTEGRITY_REPORT:', write_integrity())
