#!/usr/bin/env python3
"""Repair research summaries only; does not alter pattern or entry generation."""
import csv
import json
import os
import sqlite3
from collections import defaultdict
from statistics import mean, median

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(RUN, 'outputs')
REPORTS = os.path.join(RUN, 'reports')
DB = os.path.join(RUN, 'research_copy', 'tradingai_research.db')


def read_csv(name):
    with open(os.path.join(OUT, name), newline='') as f:
        return list(csv.DictReader(f))


def write_csv(name, rows, fields):
    with open(os.path.join(OUT, name), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def num(v):
    try:
        return float(v) if v not in (None, '') else None
    except (ValueError, TypeError):
        return None


def truth(v):
    return str(v).strip().lower() in ('1', 'true', 'yes')


def key(r, fields):
    return tuple(r.get(f, '') for f in fields)


def group(rows, fields):
    d = defaultdict(list)
    for r in rows:
        d[key(r, fields)].append(r)
    return d


def metrics(rows):
    out = {}
    for mins, bars in ((15, 3), (30, 6), (60, 12)):
        complete = [r for r in rows if truth(r.get('complete_' + str(mins)))]
        fwds = [num(r.get('fwd_' + str(mins))) for r in complete]
        fwds = [v for v in fwds if v is not None]
        mfes = [num(r.get('mfe_' + str(mins))) for r in complete]
        mfes = [v for v in mfes if v is not None]
        maes = [num(r.get('mae_' + str(mins))) for r in complete]
        maes = [v for v in maes if v is not None]
        out['n_complete_' + str(mins)] = len(fwds)
        out['n_incomplete_' + str(mins)] = len(rows) - len(fwds)
        out['mean_fwd' + str(mins) + '_signed_points'] = mean(fwds) if fwds else ''
        out['median_fwd' + str(mins) + '_signed_points'] = median(fwds) if fwds else ''
        out['positive_fwd' + str(mins) + '_fraction'] = (sum(v > 0 for v in fwds) / len(fwds)) if fwds else ''
        out['mean_mfe' + str(mins) + '_signed_points'] = mean(mfes) if mfes else ''
        out['mean_mae' + str(mins) + '_signed_points'] = mean(maes) if maes else ''
    return out


def add_group_summary(k, rows, dims):
    d = dict(zip(dims, k))
    entered = [r for r in rows if r.get('status') == 'ENTERED']
    all_dates = {r.get('date', '') for r in rows if r.get('date')}
    ent_dates = {r.get('date', '') for r in entered if r.get('date')}
    entry_keys = [(r.get('date', ''), r.get('entry_ts', '')) for r in entered]
    d.update({
        'n_entry_records': len(rows), 'n_entered': len(entered),
        'n_skipped': len(rows) - len(entered),
        'n_sessions_with_candidate': len(all_dates),
        'n_sessions_entered': len(ent_dates),
        'n_unique_entry_timestamps': len(set(entry_keys)),
        'n_duplicate_entry_rows_same_timestamp': len(entry_keys) - len(set(entry_keys)),
    })
    d.update(metrics(entered))
    return d


def calc_counterfactual(bars, entry_idx, direction):
    sign = 1 if direction == 'BULL' else -1
    start = bars[entry_idx]['open']
    out = {'counterfactual_entry_idx': entry_idx,
           'counterfactual_entry_ts': bars[entry_idx]['timestamp'],
           'counterfactual_entry_price': start}
    for mins, nbar in ((15, 3), (30, 6), (60, 12)):
        complete = entry_idx + nbar <= len(bars)
        end = min(len(bars), entry_idx + nbar)
        fwd = mfe = mae = ''
        if end > entry_idx:
            future = bars[entry_idx:end]
            favourable = [sign * ((b['high'] if sign > 0 else b['low']) - start) for b in future]
            adverse = [sign * ((b['low'] if sign > 0 else b['high']) - start) for b in future]
            mfe, mae = max(favourable), min(adverse)
            if complete:
                fwd = sign * (future[-1]['close'] - start)
        out['counterfactual_fwd_' + str(mins)] = round(fwd, 4) if fwd != '' else ''
        out['counterfactual_mfe_' + str(mins)] = round(mfe, 4) if mfe != '' else ''
        out['counterfactual_mae_' + str(mins)] = round(mae, 4) if mae != '' else ''
        out['counterfactual_complete_' + str(mins)] = int(complete)
    return out


def main():
    entries = read_csv('entries.csv')
    pats = read_csv('patterns_raw.csv')
    events = read_csv('level_events.csv')
    audit = json.load(open(os.path.join(OUT, 'data_audit.json')))
    meta_path = os.path.join(OUT, 'build_meta.json')
    meta = json.load(open(meta_path))

    # Session bars come only from the isolated research copy, opened read-only.
    con = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
    session_bars = defaultdict(list)
    q = ('select instrument_id,timestamp,open,high,low,close from market_candles_5m '
         'where instrument_id in (?,?) order by instrument_id,timestamp')
    for inst, ts, o, h, l, c in con.execute(q, ('NIFTY', 'BANKNIFTY')):
        session_bars[(inst, ts[:10])].append({'timestamp': ts, 'time': ts[11:16],
                                               'open': float(o), 'high': float(h),
                                               'low': float(l), 'close': float(c)})
    con.close()

    # Make the session split boundaries explicit and repair the metadata's
    # cumulative-index off-by-one error without changing partition assignments.
    dates = sorted({d for _, d in session_bars})
    n = len(dates)
    is_n = int(n * 0.50)
    val_n = int(n * 0.25)
    bounds = {'IS_first': dates[0], 'IS_last': dates[is_n - 1],
              'VALIDATION_first': dates[is_n], 'VALIDATION_last': dates[is_n + val_n - 1],
              'OOS_first': dates[is_n + val_n], 'OOS_last': dates[-1]}
    meta['partition_boundary_dates'] = bounds
    meta['partition_boundary_note'] = 'Corrected from observed session ordering; prior VALIDATION_last/OOS_first used validation count as absolute index. Session partition assignments in existing rows were already chronological.'
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write('\n')

    # Rule-aware candidate comparison. Only complete forward horizons enter
    # horizon averages; direction-signed movement is not called win rate.
    dims = ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition', 'rule']
    comp_rows = [add_group_summary(k, rows, dims) for k, rows in sorted(group(entries, dims).items())]
    comp_fields = dims + ['n_entry_records', 'n_entered', 'n_skipped',
                          'n_sessions_with_candidate', 'n_sessions_entered',
                          'n_unique_entry_timestamps', 'n_duplicate_entry_rows_same_timestamp']
    for mins in (15, 30, 60):
        comp_fields += ['n_complete_' + str(mins), 'n_incomplete_' + str(mins),
                        'mean_fwd' + str(mins) + '_signed_points',
                        'median_fwd' + str(mins) + '_signed_points',
                        'positive_fwd' + str(mins) + '_fraction',
                        'mean_mfe' + str(mins) + '_signed_points',
                        'mean_mae' + str(mins) + '_signed_points']
    write_csv('candidate_comparison.csv', comp_rows, comp_fields)

    # Pattern summary retains entry rule, so no row combines different fills.
    sdims = ['tol_variant', 'instrument', 'pattern_id', 'family', 'pattern_name',
             'level', 'direction', 'rule']
    p_rows = [add_group_summary(k, rows, sdims) for k, rows in sorted(group(entries, sdims).items())]
    write_csv('pattern_summary.csv', p_rows, sdims + comp_fields[len(dims):])

    # Time buckets also retain rule and partition.
    tb_entries = [r for r in entries if r.get('status') == 'ENTERED']
    tgroups = defaultdict(list)
    for r in tb_entries:
        t = r.get('entry_t', '')
        bucket = next((label for label, lo, hi in (
            ('09:15-09:30', '09:15', '09:30'), ('09:30-10:00', '09:30', '10:00'),
            ('10:00-10:30', '10:00', '10:30'), ('10:30-11:30', '10:30', '11:30'),
            ('11:30-12:30', '11:30', '12:30'), ('12:30-13:30', '12:30', '13:30'),
            ('13:30-14:30', '13:30', '14:30'), ('14:30-15:00', '14:30', '15:00'),
            ('15:00-15:20', '15:00', '15:20')) if lo <= t < hi), '')
        r2 = dict(r, bucket=bucket)
        tgroups[tuple(r2.get(x, '') for x in ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition', 'rule', 'bucket'])].append(r2)
    tdims = ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition', 'rule', 'bucket']
    time_rows = []
    for k, rows in sorted(tgroups.items()):
        d = add_group_summary(k, rows, tdims)
        d['family'] = rows[0].get('family', '')
        d['pattern_name'] = rows[0].get('pattern_name', '')
        d['entry_t'] = d['bucket']
        time_rows.append(d)
    time_fields = tdims + ['family', 'pattern_name', 'entry_t'] + comp_fields[len(dims):]
    write_csv('time_bucket_summary.csv', time_rows, time_fields)

    # Tolerance sensitivity is candidate-, rule-, partition-specific and
    # records realized per-session points as well as the declared variant.
    pat_counts = defaultdict(set)
    for p in pats:
        k = tuple(p.get(x, '') for x in ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition'])
        pat_counts[k].add((p.get('date', ''), p.get('anchor_idx', '')))
    tol_by_session = defaultdict(set)
    for ev in events:
        try:
            tol_by_session[(ev.get('tol_variant', ''), ev.get('instrument', ''), ev.get('date', ''))].add(float(ev.get('tolerance', '')))
        except (TypeError, ValueError):
            pass
    sens_dims = ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition', 'rule']
    sens_rows = []
    for k, rows in sorted(group(entries, sens_dims).items()):
        d = add_group_summary(k, rows, sens_dims)
        pk = tuple(d.get(x, '') for x in ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level', 'partition'])
        d['n_pattern_instances'] = len(pat_counts.get(pk, set()))
        vals = sorted({v for r in rows for v in tol_by_session.get((r.get('tol_variant', ''), r.get('instrument', ''), r.get('date', '')), set())})
        d['tolerance_definition'] = ('fixed: 10 NIFTY / 25 BANKNIFTY points' if d['tol_variant'] == 'fixed' else '0.25 x previous-session mean 5m bar range; 2-point floor; 25% previous-session range cap')
        d['tolerance_min_points'] = min(vals) if vals else ''
        d['tolerance_median_points'] = median(vals) if vals else ''
        d['tolerance_max_points'] = max(vals) if vals else ''
        sens_rows.append(d)
    write_csv('threshold_sensitivity.csv', sens_rows,
              sens_dims + ['n_pattern_instances', 'tolerance_definition', 'tolerance_min_points', 'tolerance_median_points', 'tolerance_max_points'] + comp_fields[len(dims):])

    # Skipped rows get a clearly labelled E0-next-open counterfactual, never
    # attributed to the skipped rule as a realized or eligible trade.
    skipped = []
    for e in entries:
        if e.get('status') != 'SKIPPED':
            continue
        bars = session_bars.get((e.get('instrument'), e.get('date')), [])
        try:
            idx = int(e.get('anchor_idx', '')) + 1
        except (TypeError, ValueError):
            idx = -1
        if idx < 0 or idx >= len(bars):
            cf_status = 'NO_NEXT_BAR'
        elif not ('09:20' <= bars[idx]['time'] < '15:20'):
            cf_status = 'OUTSIDE_ENTRY_WINDOW'
        else:
            cf_status = 'AVAILABLE'
        cf = calc_counterfactual(bars, idx, e.get('direction', '')) if cf_status == 'AVAILABLE' else {}
        rec = {
            'tol_variant': e.get('tol_variant', ''), 'instrument': e.get('instrument', ''),
            'date': e.get('date', ''), 'partition': e.get('partition', ''),
            'pattern_id': e.get('pattern_id', ''), 'pattern_name': e.get('pattern_name', ''),
            'family': e.get('family', ''), 'level': e.get('level', ''),
            'level_price': e.get('level_price', ''), 'direction': e.get('direction', ''),
            'entry_rule': e.get('rule', ''), 'skip_reason': e.get('skip_reason', ''),
            'anchor_idx': e.get('anchor_idx', ''), 'anchor_t': e.get('anchor_t', ''),
            'counterfactual_method': 'E0 next eligible bar open after anchor; directional index movement; not a trade under skipped rule',
            'counterfactual_status': cf_status,
            'became_eligible_later': 0,
            'eligibility_note': 'Rule qualification is terminal at its declared anchor/window/filter; a later unrelated same-level event does not make this skipped candidate eligible.',
            'future_window_incomplete': int(cf_status != 'AVAILABLE' or not cf.get('counterfactual_complete_60', 0)),
        }
        rec.update(cf)
        skipped.append(rec)
    skip_fields = ['tol_variant', 'instrument', 'date', 'partition', 'pattern_id',
                   'pattern_name', 'family', 'level', 'level_price', 'direction',
                   'entry_rule', 'skip_reason', 'anchor_idx', 'anchor_t',
                   'counterfactual_method', 'counterfactual_status', 'became_eligible_later',
                   'eligibility_note', 'counterfactual_entry_idx', 'counterfactual_entry_ts',
                   'counterfactual_entry_price', 'counterfactual_fwd_15', 'counterfactual_mfe_15',
                   'counterfactual_mae_15', 'counterfactual_complete_15',
                   'counterfactual_fwd_30', 'counterfactual_mfe_30', 'counterfactual_mae_30',
                   'counterfactual_complete_30', 'counterfactual_fwd_60', 'counterfactual_mfe_60',
                   'counterfactual_mae_60', 'counterfactual_complete_60', 'future_window_incomplete']
    write_csv('skipped_setups.csv', skipped, skip_fields)

    # Counts and bounds used in the report are computed from the source rows.
    row_part_dates = defaultdict(set)
    for r in entries:
        row_part_dates[r.get('partition', '')].add(r.get('date', ''))
    event_ids = [r.get('event_id', '') for r in events]
    unique_event_ids = len(set(event_ids))
    entry_id_list = [r.get('entry_id', '') for r in entries]
    unique_entry_ids = len(set(entry_id_list))
    out_of_bounds = {p: sorted(v) for p, v in row_part_dates.items()}
    skip_available = sum(r['counterfactual_status'] == 'AVAILABLE' for r in skipped)
    skip_complete60 = sum(bool(r.get('counterfactual_complete_60')) for r in skipped)
    complete60entered = sum(truth(r.get('complete_60')) for r in entries if r.get('status') == 'ENTERED')
    reports = {
        'REPORT.md': f'''# TradingAI.in — CPR Level and Pattern Study (Analysis Repair)\n\n## Verdict: INCONCLUSIVE\n\nThis repair changes only research summaries and skipped-setup counterfactual reporting. Pattern definitions, signal generation, entry eligibility, and production trading logic were not changed. The frozen baseline remains `PENDING_REPRODUCTION`; therefore candidate improvement versus the live engine is not established.\n\n## Corrected analysis outputs\n\n- `outputs/candidate_comparison.csv` is now grouped by tolerance variant, instrument, pattern, direction, level, chronological partition, **and entry rule**. Each forward horizon uses complete windows only. Direction-signed point movement and positive-movement fraction are reported; these are not trade win rate, expectancy, or P&L.\n- `outputs/pattern_summary.csv` and `outputs/time_bucket_summary.csv` retain entry rule; time buckets also retain partition.\n- `outputs/threshold_sensitivity.csv` separates tolerance variant, entry rule, candidate and partition. The fixed and volatility-normalized variants are observational sensitivity checks, not selected parameters.\n- `outputs/skipped_setups.csv` records a labelled counterfactual from the E0 next eligible bar open after the anchor. It is not the skipped rule's realized result or a trade. The “became eligible later” field is false for the original candidate because each rule is terminal at its declared time window or filter; an unrelated event at the same level no longer changes this flag.\n- `outputs/build_meta.json` now contains explicit session boundary dates. The actual row assignments were already chronological; the old boundary labels used the validation count as an absolute index.\n\n## Data and coverage\n\nThe run has {len(dates)} dated sessions, {len(events)} level-event records ({unique_event_ids} unique IDs), {len(pats)} pattern records, and {len(entries)} entry-rule records ({sum(r.get('status') == 'ENTERED' for r in entries)} entered; {sum(r.get('status') == 'SKIPPED' for r in entries)} skipped).\n\nActual chronological session partitions from the isolated research copy:\n\n| Partition | First session | Last session | Sessions with entry records |\n|---|---|---|---:|\n| IS | {bounds['IS_first']} | {bounds['IS_last']} | {len(row_part_dates.get('IS', set()))} |\n| Validation | {bounds['VALIDATION_first']} | {bounds['VALIDATION_last']} | {len(row_part_dates.get('VALIDATION', set()))} |\n| OOS | {bounds['OOS_first']} | {bounds['OOS_last']} | {len(row_part_dates.get('OOS', set()))} |\n\nThe first session has no prior-session levels, so it has no entries. Entry rows cover {complete60entered} complete 60-minute windows among entered records. The existing OOS dates were already examined in related research and are not a fresh independent holdout.\n\n## Interpretation and limitations\n\nPattern events and entry rows overlap across levels, pattern labels, tolerance variants, and entry rules. They are not independent trades. The new CSVs expose the dimensions and complete-window denominators but do not solve dependence; any confidence interval should resample sessions and account for repeated candidates. The baseline reference of 127 trades / 38.20 R has not been reproduced from its exact original rules and records. Historical option premiums are unavailable, so credit-spread profitability cannot be inferred.\n\n## Recommended next step\n\nRecover the exact frozen baseline definition and trade-level source, reproduce entries/exits and R trade by trade, then evaluate a small preselected candidate set on new untouched sessions. No production logic should be changed based on this run.\n''',
        'FINAL_VERDICT.md': f'''# Final Verdict — level_pattern_time_study\n\n## INCONCLUSIVE\n\nThe analysis-output defects have been corrected without changing signal or entry generation: entry-rule dimensions are retained, incomplete forward windows are excluded from horizon averages, skipped setups have clearly labelled E0-next-open counterfactual outcomes, and partition boundary metadata is corrected. The baseline remains `PENDING_REPRODUCTION`, so no candidate can be claimed to improve on the frozen live engine.\n\nThere are {len(entries)} rule-level entry records across {len(dates)} sessions, including overlapping candidate observations. {skip_available} skipped records have an eligible next-open counterfactual reference; {skip_complete60} of those have a complete 60-minute window. These are descriptive index outcomes, not trade results. The prior OOS dates are not a fresh holdout. Historical option premiums are unavailable.\n\nNext step: reproduce the frozen baseline from exact original rules and records, then collect new untouched sessions for confirmatory evaluation.\n''',
        'DATA_AUDIT.md': f'''# Data Audit — level_pattern_time_study\n\n- Authoritative source recorded in the audit: `{audit['authoritative_source']['path']}` (opened read-only during the original study).\n- Derived analysis source used for this repair: `{DB}`, opened with SQLite `mode=ro`; no production database was queried or written by this repair.\n- Candle counts and integrity details remain as recorded in `outputs/data_audit.json`; this repair does not alter candle data.\n- Sessions used for partitions: {n}; chronological boundaries: IS {bounds['IS_first']}–{bounds['IS_last']}, validation {bounds['VALIDATION_first']}–{bounds['VALIDATION_last']}, OOS {bounds['OOS_first']}–{bounds['OOS_last']}.\n- The entry/pattern row assignments were chronological. The prior `build_meta.json` boundary labels were wrong because the validation count was used as an absolute date index; these metadata values are corrected and the old file is preserved in `snapshots/pre_analysis_repair_20261022_2036/outputs/build_meta.json`.\n- Complete forward-window denominators are now explicit per horizon. Partial 15/30/60-minute observations do not enter the corresponding mean/median or positive-movement fraction.\n- Level-validation details, known incomplete sessions, weekday gaps, and source hashes remain in `outputs/data_audit.json` and the original audit snapshot.\n- Index candles do not establish historical option-premium fills, costs, or credit-spread P&L.\n''',
        'CAUSALITY_AUDIT.md': '''# Causality and Analysis Audit\n\n## Scope\n\nThis repair changed only research aggregation and reporting code in `src/repair_analysis_outputs.py` and generated files in this run directory. It did not change `src/patterns.py`, `src/entries.py`, production code, or signal-generation rules.\n\n## Corrections\n\n- Candidate summaries now group by entry rule, tolerance variant, instrument, pattern, direction, level, and partition.\n- Forward movement/MFE/MAE summaries use only complete windows at that horizon. Incomplete windows remain counted explicitly.\n- Signed index movement is labelled as such. Positive movement is not called win rate. No R, expectancy, drawdown, or option P&L is inferred.\n- Skipped setups are assigned an E0-next-eligible-open counterfactual from the same anchor, with a method label and completeness flags. This is not treated as a fill for the skipped rule. The old “later eligible” heuristic based on any later same-level event has been removed.\n- Partition boundary metadata is recomputed from sorted session dates. Existing row partition assignments remain intact.\n\n## Remaining limitations\n\n- Candidate signals overlap across levels, pattern IDs, rule variants, tolerance variants, and sessions. Counts are observations, not independent trades.\n- Exact baseline rules/trade records remain unavailable for reproduction in this run; the baseline is pending.\n- Prior OOS dates were examined in related research, so they are not a fresh holdout.\n- Historical option premiums are unavailable.\n'''
    }
    for name, content in reports.items():
        with open(os.path.join(REPORTS, name), 'w') as f:
            f.write(content)

    print(json.dumps({
        'sessions': len(dates), 'bounds': bounds,
        'events': len(events), 'unique_event_ids': unique_event_ids,
        'patterns': len(pats), 'entries': len(entries),
        'unique_entry_ids': unique_entry_ids,
        'candidate_comparison_rows': len(comp_rows), 'pattern_summary_rows': len(p_rows),
        'time_bucket_rows': len(time_rows), 'threshold_rows': len(sens_rows),
        'skipped_rows': len(skipped), 'skipped_cf_available': skip_available,
        'skipped_cf_complete60': skip_complete60,
        'entered_complete60': complete60entered,
        'entry_partition_dates': {k: [min(v), max(v), len(v)] for k, v in row_part_dates.items() if v}
    }, indent=2))


if __name__ == '__main__':
    main()
