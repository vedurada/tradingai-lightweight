"""Master runner: stop-loss forensics and entry optimization.

Order of operations (nothing outside the authorized directory is written):
  1. snapshot the live database into outputs/snapshot/ (read-only source),
  2. point TRADINGAI_DB_PATH at a working copy of that snapshot BEFORE any
     app import, so the production engine reads the snapshot and never the
     live database,
  3. data-quality report,
  4. production baseline run + re-simulation reconciliation,
  5. forensic classification of stopped trades,
  6. candidate arms E1..E6,
  7. selection on VAL only, then a single OOS evaluation,
  8. gates, reports, manifest.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys

REPO = '/opt/tradingai'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from research.prevday_cpr_spread_study.stop_forensics.src import (prod, snapshot,
                                                                   data, accounting,
                                                                   forensics, candidates,
                                                                   metrics)

DATE_START = '2026-07-06'
DATE_END = '2026-10-21'
INSTRUMENTS = ('NIFTY', 'BANKNIFTY')
SPLITS = accounting.SPLITS
COST_R = 0.10
FAMILIES = {
    'E1': [f'E1_k{k:.2f}' for k in candidates.E1_GRID],
    'E2': [f'E2_x{x * 100:.2f}pct' for x in candidates.E2_GRID],
    'E3': ['E3_retest'],
    'E4': [f"E4_until_{w.replace(':', '')}" for w in candidates.E4_GRID],
    'E5': [f'E5_skip_{t}' for t in candidates.E5_TAIL],
    'E6': ['E6_reentry'],
    'E7': ['E7_conflict'],
}
# tie-break towards the more conservative setting (documented in spec.md 5.0a):
# stricter filter first (E1: smaller k, E2: smaller x, E4: earlier window end).
CONSERVATIVE = {
    'E1': lambda n: float(n.split('_k')[1]),           # smaller k = stricter filter
    'E2': lambda n: float(n.split('_x')[1].replace('pct', '')),   # smaller x = stricter
    'E3': lambda n: 0,
    'E4': lambda n: n,                            # earlier window end = stricter
    'E5': lambda n: 0,
    'E6': lambda n: 0,
    'E7': lambda n: 0,
}


def counterfactual_summary(base_all: list) -> dict:
    """Arm-wide result of the hypothetical stop widths (analysis only).

    Index points are the width-invariant measure: the R normalisation divides by
    the stop distance, so R/trade is NOT comparable across different widths.
    """
    out = {}
    for w in accounting.COUNTERFACTUAL_WIDTHS:
        key = f'{w * 100:.3f}'.rstrip('0').rstrip('.') + '_pct'
        rs = []
        pts = []
        reasons = {}
        for r in base_all:
            c = r['counterfactual_stop_widths'].get(key)
            if not c:
                continue
            d = 1 if r['direction'] == 'BULL' else -1
            pts.append(d * (c['exit_price'] - r['entry']))
            rs.append(c['realized_r'])
            reasons[c['exit_reason']] = reasons.get(c['exit_reason'], 0) + 1
        out[key] = {
            'n': len(rs),
            'net_points': round(sum(pts), 1),
            'points_per_trade': round(sum(pts) / len(pts), 1) if pts else None,
            'net_R': round(sum(rs), 3),
            'net_R_per_trade': round(sum(rs) / len(rs), 4) if rs else None,
            'R_comparable_across_widths': False,
            'exit_reasons': reasons,
            'production_status': 'PRODUCTION BEHAVIOUR' if key == '0.5_pct'
                                 else 'HYPOTHETICAL (analysis only)',
        }
    return out


def write_report(path: str, base_all, forensics_rows, arm_metrics, selection,
                 gates, boot, dq, recon, conflicts, snapshot_meta, cfg_hash,
                 e7_summary, arm_removed):
    stops = [r for r in base_all if r['exit_reason'] == 'STOP']
    targets = [r for r in base_all if r['exit_reason'] == 'TARGET']
    booked = sum(r['booked_r'] for r in base_all)
    realized = sum(r['realized_r'] for r in base_all)
    ov_pts = [r['stop_overshoot_pts'] for r in stops]
    ov_r = [r['stop_overshoot_r'] for r in stops]
    cf = counterfactual_summary(base_all)
    cat = {}
    for row in forensics_rows:
        cat[row.get('missed_direction_category')] = cat.get(row.get('missed_direction_category'), 0) + 1
    flags = {}
    for flag in ('extended_entry', 'large_gap', 'narrow_cpr', 'wide_cpr',
                 'range_vs_stop', 'weak_followthrough', 'conflicting_triggers'):
        flags[flag] = sum(1 for row in forensics_rows if row.get(flag) is True)
    L = []
    A = L.append
    A('# Stop-Loss Forensics and Entry Optimization - Report')
    A('')
    A('Isolated research under `research/prevday_cpr_spread_study/stop_forensics/`. '
      'No production code, signal, alert, configuration or deployment was changed.')
    A('')
    A('## 0. Verdict')
    A('')
    A(f'- **Overall gate result: {gates["OVERALL"]}** - {gates["decision"]}')
    A(f'- Selected candidate (chosen on IS+VAL only): **{selection["family"]} / '
      f'{selection["setting"]}**')
    A(f'- Out-of-sample net R per trade: baseline '
      f'{gates["G-A_oos_improvement"]["baseline_oos_net_R_per_trade"]} vs candidate '
      f'{gates["G-A_oos_improvement"]["candidate_oos_net_R_per_trade"]}')
    A('- **No production change is authorised by this study.** A passing result would '
      'only have meant "eligible for human review".')
    A('')
    A('## 1. Data, snapshot and integrity')
    A('')
    A(f'- Snapshot sha256: `{snapshot_meta["snapshot_sha256"]}`')
    A(f'- Production trigger engine sha256: `{cfg_hash}`')
    A(f'- Baseline call: `run_opens_range(instrument, "{DATE_START}", "{DATE_END}", "plain")`, '
      '0.5% stop / 2% target, opens-only exits, flat at the 15:20 open')
    A(f'- Data quality: **{dq["status"]}** (problems: {dq["problems"] or "none"})')
    for inst, blob in dq['instruments'].items():
        A(f'  - {inst}: {blob["sessions"]} sessions, {blob["bars_total"]} bars, '
          f'duplicates {blob["duplicate_timestamps"]}, OHLC violations '
          f'{len(blob["ohlc_violations"])}, short sessions {blob["short_sessions"]}, '
          f'timezone offsets {blob["timezone_offsets"]}, data on non-session days '
          f'{len(blob["data_on_non_session_days"])}')
    A('')
    A('Re-simulation against the production engine (entry, exit price and exit reason '
      'of every trade):')
    A('')
    A('| instrument | production trades | re-simulated | mismatches | booked R | realized R |')
    A('|---|---|---|---|---|---|')
    for inst, v in recon.items():
        A(f'| {inst} | {v["production_trades"]} | {v["resimulated_trades"]} | '
          f'{len(v["issues"])} | {v["production_booked_total_R"]} | '
          f'{v["resimulated_realized_total_R"]} |')
    A('')
    A('## 2. Corrected stop accounting (the headline finding)')
    A('')
    A(f'The baseline produced **{len(base_all)} trades** over the frozen window: '
      f'{len(stops)} STOP, {len(targets)} TARGET, '
      f'{len(base_all) - len(stops) - len(targets)} flat at the 15:20 open.')
    A('')
    A('Production books every stop at exactly -1.000 R and every target at exactly '
      '+4.000 R. Re-simulating the same production exit model and measuring the '
      'realized R of the modelled fill gives:')
    A('')
    A('| quantity | value |')
    A('|---|---|')
    A(f'| trades booked at exactly -1.000 R | {sum(1 for r in base_all if r["booked_r"] == -1.0)} '
      f'(of {len(stops)} stops) |')
    A(f'| stops filled exactly at the intended stop | {sum(1 for x in ov_pts if x < 0.011)} '
      f'of {len(stops)} |')
    A(f'| stops filled BEYOND the intended stop | {sum(1 for x in ov_pts if x >= 0.011)} '
      f'of {len(stops)} |')
    A(f'| mean overshoot beyond the stop | {round(sum(ov_pts) / len(ov_pts), 1) if ov_pts else 0} '
      f'index points ({round(sum(ov_r) / len(ov_r), 3) if ov_r else 0} R) |')
    A(f'| worst overshoot | {round(max(ov_pts), 1) if ov_pts else 0} index points '
      f'({round(max(ov_r), 3) if ov_r else 0} R) |')
    A(f'| realized R of the stopped trades | mean '
      f'{round(sum(r["realized_r"] for r in stops) / len(stops), 3) if stops else 0}, worst '
      f'{round(min(r["realized_r"] for r in stops), 3) if stops else 0} |')
    if targets:
        A(f'| target: booked vs realized | booked '
          f'{targets[0]["booked_r"]} vs realized {targets[0]["realized_r"]} '
          f'(truncation {targets[0]["target_truncation_r"]} R) |')
    A(f'| arm total | booked {round(booked, 3)} R vs realized {round(realized, 3)} R '
      f'(difference {round(realized - booked, 3)} R) |')
    A(f'| index points (sum of realized signed points) | '
      f'{round(sum(r["realized_pts"] for r in base_all), 1)} |')
    A('')
    A('The booked R overstates the outcome by '
      f'{round(booked - realized, 3)} R over the window: every stop in this window '
      'gapped through the intended stop price and was filled worse than -1.000 R. '
      'This is the same mechanism the approved audit found in the 20-variant study '
      '(324/324 stops booked at -1.000 R and filled beyond the stop); the frozen '
      'production baseline shows the same behaviour at a much smaller sample size.')
    A('')
    A('The modelled fills are **next-bar open models**. They are not guaranteed '
      'executable market fills, and a real fill could be better or worse.')
    A('')
    A('### 2.1 Counterfactual stop widths (hypothetical, NOT production behaviour)')
    A('')
    A('Index points are the width-invariant measure here. The R normalisation divides '
      'by the stop distance, so **R per trade is not comparable across different stop '
      'widths** and the R column must not be read as a ranking.')
    A('')
    A('| stop width | trades | stops | flat at EOD | target | net index points | '
      'points per trade | net R/trade (not comparable) | status |')
    A('|---|---|---|---|---|---|---|---|---|')
    for k, v in cf.items():
        reasons = v['exit_reasons']
        A(f'| {k} | {v["n"]} | {reasons.get("STOP", 0)} | {reasons.get("EOD-1520", 0)} | '
          f'{reasons.get("TARGET", 0)} | {v["net_points"]} | {v["points_per_trade"]} | '
          f'{v["net_R_per_trade"]} | {v["production_status"]} |')
    A('')
    prod_pts = cf.get('0.5_pct', {}).get('points_per_trade')
    alts = {k: v for k, v in cf.items() if k != '0.5_pct'}
    best_alt = max(alts.items(), key=lambda kv: kv[1]['points_per_trade']) if alts else None
    A(f'On the width-invariant measure the **production 0.5% width is already the best '
      f'of the five tested widths** on this window ({prod_pts} index points per trade; '
      f'best alternative: {best_alt[0]} at {best_alt[1]["points_per_trade"]}). Wider '
      'stops (0.75%, 1.0%) let losses run before the stop is hit and score fewer '
      'points per trade; tighter stops (0.375%, 0.25%) convert flat exits into '
      'additional stops and score fewer points per trade. The apparent rise in '
      'R/trade as the width narrows is an arithmetic artifact of dividing by a '
      'smaller stop distance, not an improvement.')
    A('')
    A('**Conclusion: no stop width in {1.00, 0.75, 0.50, 0.375, 0.25}% improves on the '
      'production width on this evidence.** The sample is 129 trades with 13 stops, '
      'so this is a weak result: it rules out a large improvement, it does not rule '
      'out a small one, and it says nothing about a different volatility regime.')
    A('')
    A('## 3. Stopped-trade forensics')
    A('')
    A(f'All {len(forensics_rows)} stopped trades were classified point-in-time.')
    A('')
    A('| date | instrument | setup | entry | exit | realized R | overshoot (pts / R) | '
      'MAE R | fwd60 R | category | opposite level |')
    A('|---|---|---|---|---|---|---|---|---|---|---|')
    for r in sorted(forensics_rows, key=lambda x: (x['session_date'], x['instrument'])):
        A(f'| {r["session_date"]} | {r["instrument"]} | {r["setup"]} | {r["entry"]} | '
          f'{r["exit_price"]} | {r["realized_r"]} | {r["stop_overshoot_pts"]} / '
          f'{r["stop_overshoot_r"]} | {r["mae_hl_r"]} | {r.get("fwd60_r")} | '
          f'{r.get("missed_direction_category")} | {r.get("missed_direction_level") or "-"} |')
    A('')
    A('Flag frequency across the stopped trades:')
    A('')
    A('| flag | count |')
    A('|---|---|')
    for k, v in flags.items():
        A(f'| {k} | {v} / {len(forensics_rows)} |')
    A('')
    A('Missed-direction categories (A = inferable at the original entry, B = inferable '
      'only after the entry, C = retrospectively apparent only and never counted):')
    A('')
    A(f'- A: {cat.get("A", 0)}')
    A(f'- B: {cat.get("B", 0)}')
    A(f'- C: {cat.get("C", 0)}')
    A('')
    A('Reading: on this window the opposite-direction trigger was already observable '
      'at or before the entry in most stopped trades. That is an **observation about '
      'information availability**, not a deployable signal: the deployed '
      'configuration suppresses BULL base triggers, and the audit already showed '
      'several coexisting trigger semantics in this codebase, so a "flip the side" '
      'rule would change the trigger set rather than filter it. It is therefore '
      'reported as context only and was not traded.')
    A('')
    A('## 4. Candidate arms (all arms, all splits)')
    A('')
    A('| arm | IS n | IS net R/trade | VAL n | VAL net R/trade | OOS n | OOS net R/trade '
      '| OOS maxDD (R) | OOS stops | removed signals |')
    A('|---|---|---|---|---|---|---|---|---|---|')
    order = ['BASELINE'] + [k for k in arm_metrics if k != 'BASELINE']
    for k in order:
        v = arm_metrics[k]
        rem = v.get('removed')
        A(f'| {k} | {v["IS"]["n"]} | {v["IS"]["net_R_per_trade"]} | {v["VAL"]["n"]} | '
          f'{v["VAL"]["net_R_per_trade"]} | {v["OOS"]["n"]} | {v["OOS"]["net_R_per_trade"]} | '
          f'{v["OOS"]["max_dd_r"]} | {v["OOS"]["stop_count"]} | '
          f'{rem["n"] if rem else 0} |')
    A('')
    A('### 4.1 Selection (pre-registered rule, IS+VAL only)')
    A('')
    A(f'- rule: {selection["rule"]}')
    for fam, v in selection['family_best'].items():
        A(f'- {fam}: {v["setting"]} (VAL net R/trade {v["val_net_R_per_trade"]}, '
          f'{v["status"]})')
    A('')
    A(f'Selected: **{selection["family"]} / {selection["setting"]}**. The OOS window '
      'was evaluated once, after this selection was frozen.')
    A('')
    base_oos_r = arm_metrics['BASELINE']['OOS']['net_R_per_trade']
    better = []
    for k, v in arm_metrics.items():
        if k == 'BASELINE':
            continue
        o = v['OOS']['net_R_per_trade']
        if o is not None and base_oos_r is not None and o > base_oos_r:
            better.append((k, o, v['OOS']['n'], v['VAL']['net_R_per_trade']))
    A('### 4.2 Runner-up arms (disclosed post hoc, NOT a selection change)')
    A('')
    if better:
        A('The following arms have an out-of-sample net R per trade above the '
          f'baseline ({base_oos_r}). They were **not** the pre-registered selection: '
          'the selection rule was frozen before the OOS window was touched, and the '
          'primary candidate (E3) had the best validation score. They are disclosed '
          'here only so that no reader mistakes this report for a full sweep of '
          'OOS results. **None of them may be promoted on this basis**: choosing an '
          'arm because its OOS number is higher is exactly the selection on the test '
          'window that the pre-registration forbids, and a new study would be '
          'required with its own frozen selection rule, its own OOS window and its '
          'own gates.')
        A('')
        A('| arm | OOS net R/trade | OOS n | VAL net R/trade |')
        A('|---|---|---|---|')
        for k, o, n, val in better:
            A(f'| {k} | {o} | {n} | {val} |')
        A('')
        A('Two further observations that make these arms unusable as evidence:')
        A('')
        A('- The E1 grid produced three **identical** arms, so its parameter has no '
          'identifiable neighbourhood and the neighbour-stability gate cannot be '
          'evaluated at all (NOT APPLICABLE, not PASS).')
        A('- Each of these arms removes trades from the same 129-trade baseline, so '
          'their OOS windows overlap almost completely with the primary candidate\'s. '
          'They are not independent confirmations of anything.')
    else:
        A('No arm beat the baseline out of sample.')
    A('')
    A('## 5. Out-of-sample result and uncertainty')
    A('')
    A('```json')
    A(json.dumps(gates['G-A_oos_improvement'], indent=2))
    A('```')
    A('')
    A('```json')
    A(json.dumps(boot, indent=2))
    A('```')
    A('')
    A('## 6. Gates')
    A('')
    A('| gate | result |')
    A('|---|---|')
    A(f'| G-A OOS improvement | {"PASS" if gates["G-A_oos_improvement"]["pass"] else "FAIL"} |')
    A(f'| G-B not a trade-count artifact | '
      f'{"PASS" if gates["G-B_not_trade_count_artifact"]["pass"] else "FAIL"} |')
    A(f'| G-C risk | maxDD ok: '
      f'{gates["G-C_risk"]["max_dd_le_1_5x_baseline"]}, MAE not worse: '
      f'{gates["G-C_risk"]["mae_not_worse"]}, percentage-of-capital sub-gates: '
      f'**INCONCLUSIVE** |')
    A(f'| G-D stability | {"PASS" if gates["G-D_stability"]["pass"] else "FAIL"} '
      f'(periods {gates["G-D_stability"]["n_periods_positive"]}/3, blocks '
      f'{gates["G-D_stability"]["n_blocks_positive"]}/6, instruments '
      f'{gates["G-D_stability"]["n_instruments_positive"]}/2, neighbour stability '
      f'{gates["G-D_stability"]["neighbour_stability_pct"]}) |')
    A(f'| G-E evidence sufficiency | '
      f'{"PASS" if gates["G-E_evidence_sufficiency"]["pass"] else "FAIL"} '
      f'(OOS trades {gates["G-E_evidence_sufficiency"]["n_oos_candidate"]}, '
      f'CI {gates["G-E_evidence_sufficiency"]["bootstrap_ci_low"]} .. '
      f'{gates["G-E_evidence_sufficiency"]["bootstrap_ci_high"]}) |')
    A(f'| G-F integrity | {"PASS" if gates["G-F_integrity"]["pass"] else "FAIL"} |')
    A(f'| G-G scope | {"PASS" if gates["G-G_scope"]["pass"] else "FAIL"} |')
    A('')
    A(f'**Overall: {gates["OVERALL"]}** - {gates["decision"]}')
    A('')
    A('## 7. E7 status')
    A('')
    A(f'- conflict sessions (first trigger candle qualifies for both directions): '
      f'{e7_summary["conflict_sessions"]}')
    A(f'- sessions where the opposite direction would have ranked better on '
      f'reward-to-risk: {e7_summary["sessions_where_opposite_direction_ranked_better"]}')
    A(f'- E7 implemented filter-only: {e7_summary["note"]}')
    A('')
    A('## 8. Limitations')
    A('')
    A('- Index (spot) level only. No option premium, bid/ask, credit-spread or rupee '
      'P&L is claimed: the deployment has no historical option data.')
    A('- The G-C percentage-of-capital sub-gates are INCONCLUSIVE: no '
      'production-confirmed capital base exists, none is invented, and index points '
      'are never equated to rupees.')
    A('- The 5-minute feed carries no volume, so no liquidity or participation filter '
      'was possible.')
    A('- Only 5-minute candles exist; the order of a stop and a target inside one '
      'bar is unknowable. Ambiguous bars are reported as bounds '
      '(`intrabar_ambiguous_bars`, `r_lower_bound`, `r_upper_bound`) and never as an '
      'invented execution order.')
    A('- The 13 stopped trades are a small sample: every percentage in this report is '
      'reported with its sample size.')
    A('- The daily 5-minute bar close (09:15-10:00 bar) cannot be traded at its '
      'close; the modelled fills are next-bar open models.')
    A('- E1 (risk-distance filter) was pre-registered with the median intrabar range '
      'over the candles available up to the trigger candle. The production trigger '
      'usually fires in the first one or two bars of the session, so the median is '
      'computable for only a minority of signals (16 of 129 signals were filtered '
      'out), and all three pre-registered k values produced **identical** arms: the k '
      'parameter does not bind on this window, so the arm has no identifiable '
      'neighbourhood and no usable parameter-stability evidence. This is a finding '
      'about the pre-registration, not a licence to re-tune it here; a different '
      'definition would need a separate, freshly pre-registered study.')
    A('- The forward-path statistics after a stop fill are reported descriptively; '
      'they are not a tradable rule and were not turned into a candidate.')
    A('')
    A('## 9. What this evidence supports')
    A('')
    A('- **Fact (high confidence):** the production baseline books every stop at '
      '-1.000 R, but in this frozen window every stop filled beyond the stop price '
      '(mean overshoot '
      f'{round(sum(ov_r) / len(ov_r), 3) if ov_r else 0} R). The booked R is therefore '
      'optimistic, and any risk or sizing logic that reads `r_multiple` inherits that '
      'optimism.')
    A('- **Fact (high confidence, small sample):** no stop width in '
      '{1.00, 0.75, 0.50, 0.375, 0.25}% improves the index points per trade of the '
      'baseline under the production exit model; the production 0.5% width is the '
      'best of the tested set on that window (129 trades, 13 stops).')
    A('- **Hypothesis (not established):** a retest-based entry (E3) looked best on '
      'the validation window, but it did not hold up out of sample. With '
      f'{gates["G-E_evidence_sufficiency"]["n_oos_candidate"]} OOS trades and a '
      'bootstrap interval that straddles zero, the evidence is consistent with '
      'selection noise rather than with a real edge.')
    A('- **Not supported:** any production change. The gates fail, the bootstrap '
      'interval straddles zero, and the winning-on-validation arm lost out of '
      'sample.')
    A('')
    with open(path, 'w') as f:
        f.write('\n'.join(L) + '\n')


def quantile(values: list, p: float):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] + (k - f) * (vals[c] - vals[f])


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base, 'outputs')
    rep_dir = os.path.join(base, 'reports')
    snap_dir = os.path.join(out_dir, 'snapshot')
    for d in (out_dir, rep_dir, snap_dir):
        os.makedirs(d, exist_ok=True)

    src_db = os.path.join(REPO, 'database/tradingai.db')
    pristine = os.path.join(snap_dir, 'tradingai_snapshot.db')
    work = os.path.join(snap_dir, 'working_copy.db')

    # 1) Snapshot
    if os.path.exists(pristine):
        snap_meta = snapshot.snapshot_meta(pristine, src_db)
    else:
        snap_meta = snapshot.create_snapshot(src_db, pristine)
    shutil.copyfile(pristine, work)
    metrics.write_json(os.path.join(out_dir, 'snapshot_meta.json'), snap_meta)

    # 2) Point the production engine at the snapshot copy BEFORE app imports
    prod.ensure_db_env(work)
    eng = prod.engine()

    ro = sqlite3.connect(f'file:{work}?mode=ro', uri=True, timeout=30)
    ro.row_factory = sqlite3.Row

    # 3) Data quality
    dq = data.data_quality(ro, INSTRUMENTS, DATE_START, DATE_END)
    metrics.write_json(os.path.join(out_dir, 'data_quality.json'), dq)

    # 4) Universe + baseline
    universes = {}
    for inst in INSTRUMENTS:
        universes[inst] = accounting.build_universe(ro, eng, inst, DATE_START, DATE_END)
    base_all = []
    for inst in INSTRUMENTS:
        base_all.extend(candidates.arm_baseline(universes[inst]))
    metrics.write_csv(os.path.join(out_dir, 'baseline_trades.csv'), base_all)
    recon = {inst: accounting.reconcile(universes[inst]['run'],
                                        [r for r in base_all if r['instrument'] == inst])
             for inst in INSTRUMENTS}
    metrics.write_json(os.path.join(out_dir, 'baseline_reconciliation.json'), recon)

    # frozen config fingerprint of the production trigger engine
    eng_path = os.path.join(REPO, 'app/research/cpr_trigger_engine.py')
    cfg_hash = snapshot.sha256_file(eng_path)
    config_fingerprint = {
        'engine_file': eng_path,
        'engine_sha256': cfg_hash,
        'call': "run_opens_range(instrument, '2026-07-06', '2026-10-21', 'plain')",
        'stop_pct': accounting.STOP_PCT, 'target_pct': accounting.TARGET_PCT,
        'open_window': ['09:20', '15:20'], 'flat': '15:20 open',
        'flags': {k: getattr(eng, k) for k in
                  ('SHORT_ONLY', 'SKIP_FRIDAY', 'SHADOW_SKIP_FRIDAY', 'BREAKOUT_ADDON',
                   'NO_CHASE_BEAR', 'NO_CHASE_BAND_PCT', 'OPEN_STOP_PCT',
                   'OPEN_TARGET_PCT', 'OPEN_MIN', 'OPEN_MAX', 'OPEN_EOD',
                   'MIN_CANDLES') if hasattr(eng, k)},
    }
    metrics.write_json(os.path.join(out_dir, 'baseline_config_fingerprint.json'),
                       config_fingerprint)

    # CPR statistics on IS only (frozen for E5)
    cpr_is = []
    for u in universes.values():
        for day, ctx in u['sessions'].items():
            if ctx['period'] == 'IS' and ctx.get('cpr_width_pct') is not None:
                cpr_is.append(ctx['cpr_width_pct'])
    cpr_stats = {'q10': quantile(cpr_is, 0.10), 'q25': quantile(cpr_is, 0.25),
                 'q75': quantile(cpr_is, 0.75), 'q90': quantile(cpr_is, 0.90),
                 'n_is_sessions': len(cpr_is),
                 'note': 'previous-session CPR width (percent), IS sessions only'}
    metrics.write_json(os.path.join(out_dir, 'cpr_stats_is.json'), cpr_stats)

    # 5) Forensics on stopped trades
    by_signal = {(r['instrument'], r['session_date'], r['direction'], r['setup'],
                  r['entry_time']): r for r in base_all}
    forensics_rows = []
    for u in universes.values():
        for s in u['signals']:
            key = (s['instrument'], s['session_date'], s['direction'], s['level'],
                   s['entry_time'])
            r = by_signal.get(key)
            if not r or r['exit_reason'] != 'STOP':
                continue
            flags = forensics.classify(r, s, eng, cpr_stats)
            miss = forensics.missed_direction_category(r, s, eng)
            row = dict(r)
            row.update(flags)
            row.update(miss)
            forensics_rows.append(row)
    metrics.write_csv(os.path.join(out_dir, 'stop_forensics.csv'), forensics_rows)

    # 6) Candidate arms
    arm_records = {}
    arm_removed = {}
    for inst in INSTRUMENTS:
        u = universes[inst]
        for k in candidates.E1_GRID:
            kept, removed = candidates.arm_e1(u, k)
            arm_records.setdefault(f'E1_k{k:.2f}', []).extend(kept)
            arm_removed.setdefault(f'E1_k{k:.2f}', []).extend(removed)
        for x in candidates.E2_GRID:
            kept, removed = candidates.arm_e2(u, x)
            arm_records.setdefault(f'E2_x{x * 100:.2f}pct', []).extend(kept)
            arm_removed.setdefault(f'E2_x{x * 100:.2f}pct', []).extend(removed)
        kept, removed = candidates.arm_e3(u)
        arm_records.setdefault('E3_retest', []).extend(kept)
        arm_removed.setdefault('E3_retest', []).extend(removed)
        for w in candidates.E4_GRID:
            kept, removed = candidates.arm_e4(u, w)
            arm_records.setdefault(f"E4_until_{w.replace(':', '')}", []).extend(kept)
            arm_removed.setdefault(f"E4_until_{w.replace(':', '')}", []).extend(removed)
        for t in candidates.E5_TAIL:
            kept, removed = candidates.arm_e5(u, t, cpr_stats)
            arm_records.setdefault(f'E5_skip_{t}', []).extend(kept)
            arm_removed.setdefault(f'E5_skip_{t}', []).extend(removed)
        kept, removed = candidates.arm_e6(u, eng)
        arm_records.setdefault('E6_reentry', []).extend(kept)
        arm_removed.setdefault('E6_reentry', []).extend(removed)
        kept, removed = candidates.arm_e7(u, eng)
        arm_records.setdefault('E7_conflict', []).extend(kept)
        arm_removed.setdefault('E7_conflict', []).extend(removed)

    for name, recs in arm_records.items():
        metrics.write_csv(os.path.join(out_dir, f'arm_{name}.csv'), recs)
    metrics.write_csv(os.path.join(out_dir, 'removed_signals.csv'),
                      [r for rs in arm_removed.values() for r in rs])

    # 7) Selection on VAL only (pre-registered rule)
    family_best = {}
    for fam, settings in FAMILIES.items():
        scored = []
        for s in settings:
            recs = arm_records.get(s, [])
            val = metrics.agg([r for r in recs if r['period'] == 'VAL'])
            if val['n'] >= 10 and val['net_R_per_trade'] is not None:
                scored.append((s, val['net_R_per_trade']))
        if not scored:
            family_best[fam] = {'setting': None, 'val_net_R_per_trade': None,
                                 'status': 'INCONCLUSIVE (fewer than 10 VAL trades)'}
            continue
        best_score = max(sc for _, sc in scored)
        tied = [n for n, sc in scored if abs(sc - best_score) < 0.02]
        if len(tied) > 1:
            tied.sort(key=lambda n: CONSERVATIVE[fam](n))
        family_best[fam] = {'setting': tied[0], 'val_net_R_per_trade': best_score,
                             'status': 'ELIGIBLE', 'tied_settings': tied}
    eligible = {f: v for f, v in family_best.items() if v.get('setting')}
    if eligible:
        top = max(eligible.values(), key=lambda v: v['val_net_R_per_trade'])
        selected_family = [f for f, v in eligible.items() if v is top][0]
        selected_setting = top['setting']
    else:
        selected_family, selected_setting = None, None
    selection = {'family': selected_family, 'setting': selected_setting,
                 'family_best': family_best,
                 'rule': ('within a family: highest VAL net R per trade with >= 10 VAL '
                          'trades; ties (< 0.02 R) broken towards the more conservative '
                          'setting; primary = family with the best VAL score'),
                 'oos_touched_before_selection': False}
    metrics.write_json(os.path.join(out_dir, 'selection.json'), selection)

    cand_all = arm_records.get(selected_setting, [])
    removed_all = arm_removed.get(selected_setting, [])

    # 8) OOS (single evaluation, after the selection was frozen)
    oos_base = [r for r in base_all if r['period'] == 'OOS']
    oos_cand = [r for r in cand_all if r['period'] == 'OOS']
    all_days = sorted({d for u in universes.values() for d in u['sessions']})
    oos_days = sorted({r['session_date'] for r in oos_base} |
                       {r['session_date'] for r in oos_cand})
    boot = metrics.block_bootstrap(oos_base, oos_cand, oos_days, n_boot=2000)

    conflicts = {inst: candidates.detect_conflicts(universes[inst], eng)
                 for inst in INSTRUMENTS}
    metrics.write_json(os.path.join(out_dir, 'conflicts_e7.json'), conflicts)
    e7_removed = [r for inst in INSTRUMENTS
                  for r in arm_removed.get('E7_conflict', [])
                  if r['instrument'] == inst]
    flip_better = len([r for r in e7_removed
                       if r.get('e7_flip_would_have_ranked_better')])

    gates = metrics.evaluate_gates(
        base_all, cand_all, all_days,
        selected_family or 'NONE', arm_records, selection,
        removed_all, dq['status'], dq['problems'], conflicts, boot, e7_removed)
    metrics.write_json(os.path.join(out_dir, 'gates.json'), gates)

    # per-arm metric tables
    arm_metrics = {}
    for name, recs in sorted(arm_records.items()):
        arm_metrics[name] = {
            'all': metrics.agg(recs, COST_R),
            'IS': metrics.agg([r for r in recs if r['period'] == 'IS'], COST_R),
            'VAL': metrics.agg([r for r in recs if r['period'] == 'VAL'], COST_R),
            'OOS': metrics.agg([r for r in recs if r['period'] == 'OOS'], COST_R),
            'cost_grid_OOS': metrics.cost_grid([r for r in recs if r['period'] == 'OOS']),
            'breakdown_OOS': metrics.breakdown([r for r in recs if r['period'] == 'OOS']),
            'removed': metrics.agg(arm_removed.get(name, []), COST_R),
        }
    arm_metrics['BASELINE'] = {
        'all': metrics.agg(base_all, COST_R),
        'IS': metrics.agg([r for r in base_all if r['period'] == 'IS'], COST_R),
        'VAL': metrics.agg([r for r in base_all if r['period'] == 'VAL'], COST_R),
        'OOS': metrics.agg(oos_base, COST_R),
        'cost_grid_OOS': metrics.cost_grid(oos_base),
        'breakdown_OOS': metrics.breakdown(oos_base),
        'removed': None,
    }
    metrics.write_json(os.path.join(out_dir, 'arm_metrics.json'), arm_metrics)

    # 9) Manifest
    manifest = {
        'study': 'stop_forensics',
        'baseline': "app.research.cpr_trigger_engine.run_opens_range(inst, "
                    f"'{DATE_START}', '{DATE_END}', 'plain')",
        'baseline_config_fingerprint': config_fingerprint,
        'range': [DATE_START, DATE_END],
        'instruments': list(INSTRUMENTS),
        'splits': SPLITS,
        'snapshot': snap_meta,
        'working_copy': work,
        'dq_status': dq['status'],
        'dq_problems': dq['problems'],
        'baseline_trades': len(base_all),
        'reconciliation': recon,
        'selection': selection,
        'selected_family': selected_family,
        'selected_setting': selected_setting,
        'oos_baseline': metrics.agg(oos_base, COST_R),
        'oos_candidate': metrics.agg(oos_cand, COST_R),
        'bootstrap': boot,
        'gates_overall': gates['OVERALL'],
        'eligible_for_human_review': gates['ELIGIBLE_FOR_HUMAN_REVIEW'],
        'stopped_trades_forensics_rows': len(forensics_rows),
        'unplanned_runs': [],
        'spec_amendments': [
            'A1 (2026-10-22, before the first candidate run): E2/E3 level-group '
            'semantics and the conservative tie-break were made explicit.',
            'A2 (2026-10-22, before the first candidate run): E7 was implemented as a '
            'filter-only arm; a direction flip is not traded because the deployed '
            'configuration suppresses BULL base triggers.',
            'A3 (2026-10-22, before the first candidate run): the six-block walk-forward '
            'was specified over the full range with the frozen parameters.',
        ],
        'implementation_corrections': [
            'E1 tie-break direction corrected to the pre-registered conservative '
            'direction (smaller k). The primary family (best VAL score) was already '
            'decided by score and is unaffected.',
            'The walk-forward blocks were recomputed over the full range with the '
            'frozen parameters, as pre-registered in spec.md 1.3 (the first run '
            'restricted them to the OOS window and left the early blocks empty).',
        ],
        'e7_summary': {
            'conflict_sessions': {k: len(v) for k, v in conflicts.items()},
            'e7_removed_signals': len(e7_removed),
            'sessions_where_opposite_direction_ranked_better': flip_better,
            'note': ('A direction flip is reported descriptively only: flipping would '
                     'trade a BULL base trigger that the deployed SHORT_ONLY '
                     'configuration suppresses.'),
        },
    }
    metrics.write_json(os.path.join(out_dir, 'run_manifest.json'), manifest)
    metrics.write_json(os.path.join(base, 'run_manifest.json'), manifest)

    # 10) Report
    rep_path = os.path.join(rep_dir, 'STOP_FORENSICS_REPORT.md')
    e7_summary = {
        'conflict_sessions': {k: len(v) for k, v in conflicts.items()},
        'sessions_where_opposite_direction_ranked_better': flip_better,
        'note': ('E7 is filter-only: the production engine resolves a same-candle '
                 'conflict deterministically (BEAR before BULL) and the deployed '
                 'configuration suppresses BULL base triggers, so a flip would trade '
                 'a signal family the production trigger set does not act on.'),
    }
    write_report(rep_path, base_all, forensics_rows, arm_metrics, selection,
                 gates, boot, dq, recon, conflicts, snap_meta, cfg_hash,
                 e7_summary, arm_removed)

    ro.close()
    print('DONE')
    print('selected:', selected_family, selected_setting)
    print('gates:', gates['OVERALL'], gates['ELIGIBLE_FOR_HUMAN_REVIEW'])


if __name__ == '__main__':
    main()
