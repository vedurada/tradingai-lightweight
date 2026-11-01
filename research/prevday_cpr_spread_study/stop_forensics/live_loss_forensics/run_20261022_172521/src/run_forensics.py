"""Orchestrator for the live-engine loss forensics.

Read-only against the snapshot; writes only inside the run directory.
"""
import csv
import json
import os
import sys

from . import config, controls, dbutil, levels, ledger, paths, phase3, reporting, sources, taxonomy

LEDGER_FIELDS = [
    'population', 'source', 'source_row_id', 'instrument', 'session_date', 'direction',
    'level', 'strategy', 'objective', 'variant', 'status', 'path_status',
    'entry_time', 'entry_price', 'stop_price', 'target_price',
    'exit_time', 'exit_price', 'exit_reason', 'exit_kind', 'risk_pts',
    'recorded_result', 'recorded_r', 'recomputed_r', 'recorded_pnl', 'recomputed_pnl',
    'outcome_class', 'result_consistent', 'entry_index', 'entry_index_match',
    'exit_index', 'exit_index_match', 'bars_in_session', 'bars_held',
    'mae_ts', 'mfe_ts', 'entry_extension_pct', 'distance_to_level_pts',
    'level_price', 'level_price_source', 'prev_session_date',
    'prev_high', 'prev_low', 'running_high_at_entry', 'running_low_at_entry',
    'touches_before_entry', 'entry_is_first_touch', 'touch_condition',
    'nearest_invalidation', 'invalidation_name', 'invalidation_price',
    'stop_beyond_invalidation', 'stop_inside_ordinary_move',
    'mae_hl_pts', 'mfe_hl_pts', 'mae_hl_r', 'mfe_hl_r',
    'mae_open_r', 'mfe_open_r', 'intrabar_ambiguous_bars', 'first_touch_hl',
    'first_touch_open', 'both_levels_same_bar_hl', 'stop_bar_hl', 'target_bar_hl',
    'stop_overshoot_pts', 'stop_overshoot_r', 'fwd15_r', 'fwd30_r',
    'fwd60_r', 'fwd60_worst_r', 'fwd60_best_r', 'post_exit_category',
    'stop_then_continued_loose', 'stop_then_reversed_loose', 'pre_entry_move_pct',
    'pre_entry_range_pct', 'is_choppy', 'level_crossings_after_entry',
    'level_crossed_after_entry', 'level_crossed_back_after_entry',
    'failed_breakout_after_entry', 'minutes_to_entry',
    'entry_to_stop_pct', 'entry_to_target_pct', 'distance_to_nearest_level_pct',
    'rr_vs_frozen_target', 'rejection_close_before_entry', 'touch_before_entry',
    'bars_in_confirmation_window',
    'A_primary', 'A_secondary', 'B_primary', 'B_secondary', 'C_primary', 'C_secondary',
    'D_primary', 'D_secondary', 'setup_first_eligible', 'flags',
]


def _write_csv(path, rows, fields=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        with open(path, 'w', newline='') as fh:
            fh.write(','.join(fields or []) + '\n')
        return path
    fields = fields or sorted({k for r in rows for k in r})
    with open(path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _flat(row.get(k)) for k in fields})
    return path


def _flat(value):
    if isinstance(value, (list, tuple)):
        return ';'.join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return value


def enrich(rows, candles):
    for row in rows:
        path = paths.reconstruct(row, candles)
        level_info = levels.build(row, candles)
        confirmation = levels.confirmation_state(row, candles, level_info)
        row.update({k: v for k, v in path.items()})
        row.update({k: v for k, v in level_info.items()
                    if k not in ('swings', 'pivots', 'known_levels_at_entry')})
        row['known_levels_at_entry'] = level_info.get('known_levels_at_entry')
        row['rejection_close_before_entry'] = confirmation.get('rejection_close_before_entry')
        row['touch_before_entry'] = confirmation.get('touch_before_entry')
        features = paths.features(row, path, candles, level_info.get('level_price'))
        path.update(features)
        row.update(features)
        classification = taxonomy.classify(row, path, level_info, confirmation)
        row.update(classification)
        entry = row.get('entry_price')
        if entry:
            if row.get('stop_price'):
                row['entry_to_stop_pct'] = round(abs(entry - row['stop_price']) / entry * 100, 4)
            if row.get('target_price'):
                row['entry_to_target_pct'] = round(abs(entry - row['target_price']) / entry * 100, 4)
            known = row.get('known_levels_at_entry') or []
            if known:
                nearest = min(abs(k['price'] - entry) for k in known)
                row['distance_to_nearest_level_pct'] = round(nearest / entry * 100, 4)
            if row.get('entry_time'):
                t = row['entry_time'][11:16]
                row['minutes_to_entry'] = (int(t[:2]) * 60 + int(t[3:])) - (9 * 60 + 15)
    return rows


def main():
    os.makedirs(config.OUT, exist_ok=True)
    os.makedirs(config.REPORTS, exist_ok=True)

    pre = dbutil.capture_state('preflight')
    dbutil.write_json(os.path.join(config.OUT, 'preflight.json'), pre)
    snapshot_meta = {
        'path': config.SNAPSHOT,
        'size': os.path.getsize(config.SNAPSHOT),
        'sha256': dbutil.sha256_file(config.SNAPSHOT),
        'source_db': os.path.join(config.REPO, 'database/tradingai.db'),
        'source_db_sha256_at_backup': pre['live_db']['sha256'],
        'backup_method': 'sqlite3 .backup (consistent online backup)',
    }
    dbutil.write_json(os.path.join(config.OUT, 'snapshot_meta.json'), snapshot_meta)

    conn = dbutil.connect()
    src = sources.load_sources(conn)
    src_description = sources.describe(src, conn)
    dbutil.write_json(os.path.join(config.OUT, 'source_inventory.json'), src_description)

    rows, pops = ledger.build_ledger(src)
    candles = paths.load_candles(conn)
    enrich(rows, candles)

    book_rows = [r for r in rows if r['population'] == ledger.POP_BOOK]
    live_rows = [r for r in rows if r['population'] == ledger.POP_LIVE]

    p3 = phase3.reproduce()
    dbutil.write_json(os.path.join(config.OUT, 'phase3_reproduced.json'), p3)

    live_loss_rows = [r for r in (live_rows + book_rows)]
    book_loss_rows = [r for r in book_rows if r['outcome_class'] == 'LOSS']
    stop_loss_rows = [r for r in book_loss_rows if r['exit_kind'] == 'STOP']
    book_win_rows = [r for r in book_rows if r['outcome_class'] == 'WIN']
    comparison = phase3.comparison_table(p3, book_loss_rows, stop_loss_rows,
                                          book_win_rows)
    dbutil.write_json(os.path.join(config.OUT, 'phase3_comparison.json'), comparison)

    control = controls.build(book_rows)
    dbutil.write_json(os.path.join(config.OUT, 'winner_control_summary.json'), control)

    ledger_rows = []
    for r in live_loss_rows:
        rec = dict(r)
        rec.pop('known_levels_at_entry', None)
        ledger_rows.append(rec)
    _write_csv(os.path.join(config.OUT, 'LIVE_LOSS_TRADE_LEDGER.csv'), ledger_rows, LEDGER_FIELDS)

    pattern_rows = []
    for r in live_loss_rows:
        if r['outcome_class'] != 'LOSS':
            continue
        pattern_rows.append({
            'trade_id': r['source_row_id'], 'population': r['population'],
            'instrument': r['instrument'], 'session_date': r['session_date'],
            'direction': r['direction'], 'level': r['level'],
            'entry_time': r['entry_time'], 'entry_price': r['entry_price'],
            'stop_price': r['stop_price'], 'exit_price': r['exit_price'],
            'exit_reason': r['exit_reason'], 'recorded_result': r['recorded_result'],
            'recomputed_r': r.get('recomputed_r'),
            'A_primary': r.get('A_primary'), 'A_secondary': r.get('A_secondary'),
            'B_primary': r.get('B_primary'), 'B_secondary': r.get('B_secondary'),
            'C_primary': r.get('C_primary'), 'C_secondary': r.get('C_secondary'),
            'D_primary': r.get('D_primary'), 'D_secondary': r.get('D_secondary'),
            'setup_first_eligible': r.get('setup_first_eligible'),
            'rr_vs_frozen_target': r.get('rr_vs_frozen_target'),
            'level_price_source': r.get('level_price_source'),
            'flags': ';'.join(r.get('flags') or []),
        })
    _write_csv(os.path.join(config.OUT, 'LOSS_PATTERN_CLASSIFICATION.csv'), pattern_rows)

    control_rows = controls.per_trade_rows(book_rows)
    _write_csv(os.path.join(config.OUT, 'WINNER_CONTROL_COMPARISON.csv'), control_rows)

    _write_csv(os.path.join(config.OUT, 'PHASE3_PATTERN_COMPARISON.csv'), comparison)

    post_stop = []
    for r in live_loss_rows:
        if r['exit_kind'] != 'STOP':
            continue
        post_stop.append({
            'trade_id': r['source_row_id'], 'population': r['population'],
            'instrument': r['instrument'], 'session_date': r['session_date'],
            'direction': r['direction'], 'entry_time': r['entry_time'],
            'entry_price': r['entry_price'], 'stop_price': r['stop_price'],
            'exit_time': r['exit_time'], 'exit_price': r['exit_price'],
            'exit_reason': r['exit_reason'],
            'stop_overshoot_pts': r.get('stop_overshoot_pts'),
            'stop_overshoot_r': r.get('stop_overshoot_r'),
            'mae_hl_r': r.get('mae_hl_r'), 'mfe_hl_r': r.get('mfe_hl_r'),
            'fwd15_r': r.get('fwd15_r'), 'fwd30_r': r.get('fwd30_r'), 'fwd60_r': r.get('fwd60_r'),
            'fwd60_worst_r': r.get('fwd60_worst_r'), 'fwd60_best_r': r.get('fwd60_best_r'),
            'post_exit_category': r.get('post_exit_category'),
            'stop_then_continued_loose': r.get('stop_then_continued_loose'),
            'stop_then_reversed_loose': r.get('stop_then_reversed_loose'),
            'intrabar_ambiguous_bars': r.get('intrabar_ambiguous_bars'),
            'bars_held': r.get('bars_held'),
        })
    _write_csv(os.path.join(config.OUT, 'POST_STOP_PRICE_PATH_ANALYSIS.csv'), post_stop)

    reporting.write_all(pre, snapshot_meta, src_description, pops, rows, p3, comparison,
                         control, post_stop, pattern_rows)

    post = dbutil.capture_state('final')
    integrity = {
        'before': pre, 'after': post,
        'code_files_identical': pre['protected_hashes'] == post['protected_hashes'],
        'git_status_identical': pre['git_status'] == post['git_status'],
        'branch_unchanged': pre['branch'] == post['branch'],
        'head_unchanged': pre['head'] == post['head'],
        'service_pids_unchanged': pre['services']['gunicorn_pids'] == post['services']['gunicorn_pids'],
        'live_db_unchanged_by_study': pre['live_db'] == post['live_db'],
        'baseline_status_diff': dbutil.baseline_status_diff(),
    }
    dbutil.write_json(os.path.join(config.OUT, 'integrity_final.json'), integrity)
    reporting.write_integrity_final(pre, post, snapshot_meta,
                                    integrity.get('baseline_status_diff'))

    manifest = {
        'run_dir': config.RUN_DIR,
        'snapshot': snapshot_meta,
        'sources': {k: v['rows'] for k, v in src_description.items() if 'rows' in v},
        'populations': pops,
        'phase3_checks': p3['checks'],
        'outputs': sorted(os.listdir(config.OUT)),
        'reports': sorted(os.listdir(config.REPORTS)),
    }
    dbutil.write_json(os.path.join(config.OUT, 'run_manifest.json'), manifest)
    print('[live_loss_forensics] done')
    print('[live_loss_forensics] populations: ' + json.dumps(
        {k: v.get('total') for k, v in pops.items() if isinstance(v, dict)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
