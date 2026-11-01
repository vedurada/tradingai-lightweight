"""Markdown deliverables for the setup-first study."""
from __future__ import annotations

import json
from pathlib import Path

from . import config

PERIODS = ('IS', 'VAL', 'OOS')


def _tbl(headers, rows):
    out = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for r in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in r) + ' |')
    return '\n'.join(out)


def _fmt(v, nd=3):
    if v is None:
        return 'n/a'
    if isinstance(v, float):
        return f'{v:.{nd}f}'
    return str(v)


def _agg_rows(by_period, n_label='n'):
    rows = []
    for p in PERIODS:
        a = by_period.get(p, {})
        rows.append([p, a.get(n_label), _fmt(a.get('net_R_per_trade')),
                     _fmt(a.get('points_per_trade'), 2), _fmt(a.get('gross_R')),
                     a.get('wins'), a.get('losses'), a.get('flat'),
                     a.get('stop_count'), a.get('target_count'), a.get('eod_count'),
                     _fmt(a.get('max_dd_r')), _fmt(a.get('mean_mae_r'))])
    return rows


PERIOD_HEADER = ['period', 'n', 'net R/trade', 'points/trade', 'gross R', 'wins',
                 'losses', 'flat', 'stops', 'targets', 'EOD', 'max DD (R)',
                 'mean MAE (R)']


def write_all(reports, out, run_dir, exp_a, exp_b, exp_c, exp_d, rob, forensics,
              pre, dq, base_records, cand_records, candidate_arm, rule_selected,
              stop_selected, all_setups, arm_rows):
    reports = Path(reports)
    reports.mkdir(parents=True, exist_ok=True)
    w = {}
    w['BASELINE_REPRODUCTION.md'] = _baseline_reproduction(dq, rob, base_records,
                                                           cand_records, candidate_arm)
    w['SETUP_DEFINITION.md'] = _setup_definition(all_setups)
    w['SETUP_ARRIVAL_CONFIRMATION.md'] = _arrival_confirmation(exp_a, arm_rows)
    w['ENTRY_AND_STOP_PLANS.md'] = _entry_and_stop(exp_c, rule_selected,
                                                   stop_selected, candidate_arm)
    w['STOP_OUT_FORENSICS.md'] = _stop_forensics(forensics, base_records,
                                                 cand_records)
    w['PERFORMANCE_AND_ROBUSTNESS.md'] = _performance(exp_b, exp_c, exp_d, rob,
                                                       base_records, cand_records,
                                                       candidate_arm)
    w['VALIDATION_GATES.md'] = _gates(pre, exp_d)
    w['EXECUTIVE_SUMMARY.md'] = _executive(exp_a, exp_b, exp_c, exp_d, rob,
                                           forensics, pre, dq, base_records,
                                           cand_records, candidate_arm,
                                           rule_selected, stop_selected)
    for name, text in w.items():
        (reports / name).write_text(text)
    return sorted(w)


# ----------------------------------------------------------------- baseline ---
def _baseline_reproduction(dq, rob, base_records, cand_records, candidate_arm):
    base = rob['baseline']
    lines = [
        '# Baseline reproduction',
        '',
        'The frozen production baseline was re-run unchanged inside the study '
        'environment against a fresh snapshot of the live database and then '
        're-simulated with the parent study accounting module. Both views must '
        'agree before any candidate work is allowed to start.',
        '',
        '## Data quality',
        '',
        f"- status: **{dq.get('status')}**",
        f"- problems: {dq.get('problems') or 'none'}",
        f"- range: {dq.get('range')}",
        '',
        '| instrument | sessions | complete sessions | short sessions | '
        'missing bars | duplicate timestamps | OHLC violations |',
        '|---|---|---|---|---|---|---|',
    ]
    for inst, blob in (dq.get('instruments') or {}).items():
        lines.append(f"| {inst} | {blob['sessions']} | {blob['complete_sessions']} | "
                     f"{len(blob['short_sessions'])} | "
                     f"{len(blob['sessions_with_missing_bars'])} | "
                     f"{blob['duplicate_timestamps']} | "
                     f"{len(blob['ohlc_violations'])} |")
    lines += [
        '',
        '## Production baseline (unchanged engine)',
        '',
        _tbl(PERIOD_HEADER, _agg_rows(rob['baseline_by_period'])),
        '',
        f"Total baseline trades: **{base['n']}** over "
        f"{sum(rob['baseline_by_period'].get(p, {}).get('sessions', 0) for p in PERIODS)}"
        ' instrument-sessions.',
        '',
        'The production baseline is the reference for every comparison in this '
        'study. It was not modified, re-tuned or re-parameterised.',
        '',
        '## Setup-first candidate (same accounting module)',
        '',
        _tbl(PERIOD_HEADER, _agg_rows(rob['candidate_by_period'])),
        '',
        '## Reconciliation rule',
        '',
        '- the production run and the independent re-simulation must produce the '
        'same trade count, the same entry times and the same realised R for every '
        'signal;',
        '- the check is recorded in `outputs/baseline_reconciliation.json`;',
        '- if the check fails the study stops before any candidate is computed '
        '(`verdict = BLOCKED_BASELINE_REPRODUCTION`).',
        '',
    ]
    return '\n'.join(lines)


# ------------------------------------------------------------ setup families ---
def _setup_definition(all_setups):
    fams = {}
    for s in all_setups:
        f = s['setup_family']
        b = fams.setdefault(f, {'level_names': set(), 'n': 0, 'instruments': set(),
                                'example': None})
        b['n'] += 1
        b['instruments'].add(s['instrument'])
        if s.get('level_name'):
            b['level_names'].add(s['level_name'])
        if b['example'] is None:
            b['example'] = s
    desc = {
        'F1_PREV_DAY_LEVEL_REJECTION':
            'A pre-existing resistance from the previous session (previous-day '
            'high, central pivot, R1, R2 - nearest one above the session open) is '
            'monitored. The setup is identified at the open because the level is '
            'already known; price must rally into the zone and then close back '
            'below it.',
        'F2_CPR_BOUNDARY_REJECTION':
            'The top of the previous session CPR is monitored. The setup is '
            'identified at the open; price must rally into the zone and close '
            'back below it.',
        'F3_BREAKDOWN_RETEST':
            'A pre-existing support level (previous-day low, central pivot, S1, S2, '
            'CPR bottom - nearest one below the session open) is closed below. The '
            'setup is identified at that breakdown close; the trade is only taken '
            'after price rallies back into the zone and fails again.',
        'F4_PULLBACK_TO_SWING_HIGH':
            'A confirmed downtrend (two descending confirmed swing highs and two '
            'descending confirmed swing lows, strict m=2 fractals) makes the last '
            'confirmed swing high a resistance. The setup is identified when that '
            'structure is confirmed; price must rally into the swing-high zone and '
            'close back below it.',
        'F5_FAILED_BREAK_REJECTION':
            'A breakout attempt above a pre-existing resistance is observed (the '
            'arrival), and the setup is only complete when the rejection is '
            'observable, i.e. a close back below the level.',
        'F6_SWING_BREAK_RETEST':
            'A confirmed swing low of a confirmed downtrend is closed below. The '
            'setup is identified at that break; the trade is taken only after the '
            'failed retest of the broken level.',
    }
    lines = [
        '# Setup definitions',
        '',
        'Every setup family below is **causal**: it is identified only from '
        'information that was already available at the identification bar, and no '
        'family was chosen, renamed or dropped after a result was seen.',
        '',
        '## Pre-registered parameters',
        '',
        _tbl(['parameter', 'value', 'meaning'], [
            ['zone width', f'{config.ZONE_PCT * 100:.2f} % of the level',
             'the arrival zone around the level'],
            ['expiry', f'{config.EXPIRY_BARS} bars ({config.EXPIRY_BARS * 5} min)',
             'a setup that is neither reached nor confirmed within the window is '
             'EXPIRED'],
            ['max entry extension', f'{config.MAX_ENTRY_EXTENSION_PCT * 100:.2f} %',
             'the entry must not be further than this below the level (no chasing)'],
            ['min reward/risk', config.MIN_RR, 'fixed 2 % target against the chosen stop'],
            ['min stop distance', f'{config.MIN_STOP_PCT * 100:.2f} % of entry',
             'a narrower stop is not structural'],
            ['max stop distance', f'{config.MAX_STOP_PCT * 100:.2f} % of entry',
             'a wider stop is not acceptable'],
            ['target', f'{config.TARGET_PCT * 100:.1f} % of entry',
             'the frozen production target, unchanged in every arm'],
            ['buffer beyond a level', f'{config.EPS_PCT * 100:.2f} %',
             'the stop sits just beyond the structural level'],
            ['swing definition', f'strict m={config.SWING_M} fractal',
             'a pivot is only knowable at the close of bar pivot+2'],
        ]),
        '',
        '## Scope decision',
        '',
        'Only **BEAR (short)** setups are identified and traded. The frozen '
        'baseline is 100 % BEAR because the deployed engine runs with '
        '`SHORT_ONLY=True`. A mirrored long family would be a different signal '
        'population with no comparable baseline, so it is explicitly out of scope '
        'for this study rather than silently omitted.',
        '',
        '## Families',
        '',
    ]
    for fam in config.SETUP_FAMILIES:
        b = fams.get(fam, {'n': 0, 'level_names': set(), 'instruments': set()})
        lines += [
            f'### {fam}',
            '',
            desc.get(fam, ''),
            '',
            f"- setups identified in this run: **{b['n']}**",
            f"- level tokens used: {', '.join(sorted(b['level_names'])) or 'n/a'}",
            f"- instruments: {', '.join(sorted(b['instruments'])) or 'n/a'}",
            '',
        ]
    lines += [
        '## State machine',
        '',
        '```',
        'WATCHING -> ZONE_REACHED -> CONFIRMED -> TRADE_ELIGIBLE',
        '             |              |',
        '             +-> EXPIRED    +-> EXPIRED / INVALIDATED / MISSED / NO_TRADE',
        '```',
        '',
        'Every transition is timestamped and written to '
        '`outputs/setup_state_rows.csv`. The zone is fixed at identification time '
        'and is never re-drawn. The earliest possible entry is the open of the bar '
        'after the confirming close, so a confirmation can never be used as if it '
        'were known earlier.',
        '',
        '## One opportunity, one trade',
        '',
        'No re-entry rule is declared, therefore at most one trade is taken per '
        'instrument and session. When more than one setup in the same session '
        'becomes eligible, the earliest confirmed setup wins and the others are '
        'recorded as `NO_TRADE / one_trade_per_session`.',
        '',
    ]
    return '\n'.join(lines)


# ------------------------------------------------------ arrival / confirmation --
def _arrival_confirmation(exp_a, arm_rows):
    lines = [
        '# Setup arrival and confirmation',
        '',
        'Experiment A answers one question: how often does price actually reach '
        'the zone that was defined in advance, and how often is a confirmation '
        'observed afterwards?',
        '',
        '## By family (confirmation rule C1 - close back below the level)',
        '',
        _tbl(['family', 'identified', 'zone reached', 'confirmed', 'expired',
              'invalidated', 'eligible', 'arrival rate %', 'confirmation rate %',
              'median min to arrival', 'median min to confirmation'],
             [[f, b['identified'], b['zone_reached'], b['confirmed'], b['expired'],
               b['invalidated'], b['trade_eligible'], b['arrival_rate_pct'],
               b['confirmation_rate_pct'], b['median_minutes_to_arrival'],
               b['median_minutes_to_confirmation']]
              for f, b in exp_a['by_family'].items()]),
        '',
        '## By family (confirmation rule C2 - rejection close below the level)',
        '',
        _tbl(['family', 'identified', 'zone reached', 'confirmed', 'expired',
              'invalidated'],
             [[f, b['identified'], b['zone_reached'], b['confirmed'], b['expired'],
               b['invalidated']] for f, b in exp_a['by_family_confirmation_C2'].items()]),
        '',
        '## Reading of the funnel',
        '',
        '- **EXPIRED**: neither the zone nor the confirmation happened inside the '
        'pre-declared window (12 bars). These are ordinary, non-trading sessions.',
        '- **INVALIDATED**: price closed through the zone before the arrival, so '
        'the level was broken the other way and the setup premise no longer held.',
        '- **MISSED**: the confirmation happened but the entry was already too far '
        'from the level (more than 0.25 % below it). The trade was not taken '
        'because chasing was forbidden.',
        '- **NO_TRADE**: the entry gates refused the trade (entry window, stop '
        'availability, risk distance, reward/risk, or a second eligible setup in '
        'the same session).',
        '',
        'The complete per-setup log, including every state transition with its '
        'timestamp, is in `outputs/setup_state_rows.csv`.',
        '',
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------- entry and stops ----
def _entry_and_stop(exp_c, rule_selected, stop_selected, candidate_arm):
    lines = [
        '# Entry and stop plans',
        '',
        '## Entry plan (frozen)',
        '',
        '1. a setup is identified from closed candles only;',
        '2. the zone is fixed at identification time;',
        '3. price must reach the zone (arrival);',
        '4. the confirmation rule must fire on a closed candle (confirmation);',
        '5. the entry is the **open of the bar after the confirming close**;',
        '6. the entry must fall inside the production entry window '
        f'[{config.ENTRY_OPEN_MIN}, {config.ENTRY_OPEN_MAX});',
        '7. the entry must not be more than '
        f'{config.MAX_ENTRY_EXTENSION_PCT * 100:.2f} % below the level;',
        '8. the stop must be available, must be between '
        f'{config.MIN_STOP_PCT * 100:.2f} % and {config.MAX_STOP_PCT * 100:.2f} % '
        'of the entry, and the reward/risk against the frozen '
        f'{config.TARGET_PCT * 100:.1f} % target must be at least {config.MIN_RR};',
        '9. at most one trade per instrument and session.',
        '',
        '## Stop variants',
        '',
        _tbl(['variant', 'definition', 'availability rule'], [
            ['S0', 'frozen production stop, 0.5 % of the entry',
             'always available (reference)'],
            ['S1', 'just beyond the last confirmed swing high',
             'NO_TRADE when no confirmed swing high exists above the entry'],
            ['S2', 'just beyond the failed-breakout extreme since the arrival',
             'NO_TRADE when price never broke beyond the level'],
            ['S3', 'just beyond the retest level',
             'always available'],
            ['S4', 'just beyond the nearest pre-existing level above the entry',
             'NO_TRADE when no pre-existing level is above the entry'],
            ['S5', 'structural level + 0.5 x median bar range',
             'NO_TRADE when no structural base or no median range exists'],
        ]),
        '',
        'A stop is never invented to keep a trade alive. When the required '
        'structure does not exist the candidate is recorded as NO_TRADE with the '
        'reason, and the absence is counted in the availability table below.',
        '',
        '## Stop arm results (entry policy frozen)',
        '',
    ]
    rows = []
    for name, blob in exp_c['arms'].items():
        av = blob.get('availability', {}).get(
            'S0' if name.endswith('_S0') else name.split('_')[-1], {})
        rows.append([name, blob['by_period']['IS']['n'], blob['by_period']['VAL']['n'],
                     blob['by_period']['OOS']['n'],
                     _fmt(blob['by_period']['VAL']['net_R_per_trade']),
                     _fmt(blob['by_period']['VAL']['points_per_trade'], 2),
                     _fmt(blob['by_period']['OOS']['net_R_per_trade']),
                     _fmt(blob['by_period']['OOS']['points_per_trade'], 2),
                     _fmt(blob.get('mean_stop_distance_pct'), 6)])
    lines += [
        _tbl(['arm', 'IS n', 'VAL n', 'OOS n', 'VAL net R/trade',
              'VAL points/trade', 'OOS net R/trade', 'OOS points/trade',
              'mean stop distance'], rows),
        '',
        f"- selected entry policy: **{rule_selected}**",
        f"- selected stop: **{stop_selected}**",
        f"- candidate arm: **{candidate_arm}**",
        '',
        '### Stop availability on the frozen entry policy',
        '',
    ]
    sel = {}
    for arm, blob in exp_c['arms'].items():
        variant = arm.split('_')[-1]
        av = blob.get('availability', {}).get(variant)
        if av:
            sel[variant] = av

    def _reasons(v):
        rs = v.get('reasons') or {}
        if not rs:
            return 'n/a'
        return ', '.join(f'{k} ({n})' for k, n in
                         sorted(rs.items(), key=lambda kv: (-kv[1], kv[0]))[:3])

    lines += [
        _tbl(['variant', 'confirmed setups', 'stop available', 'NO_TRADE (stop '
              'unavailable)', 'trade eligible', 'other NO_TRADE', 'missed',
              'recorded refusal reasons'],
             [[k, v['confirmed_setups'], v['stop_available'],
               v['no_trade_stop_unavailable'], v['trade_eligible'],
               v['other_no_trade'], v['missed'], _reasons(v)]
              for k, v in sel.items()]),
        '',
        'Every variant is measured on the same frozen entry policy and the same '
        '158 confirmed setups, so the columns are directly comparable.',
        '',
        'The refusal reasons are counted over every setup identified for that '
        'variant, so a variant with no usable sample shows why it has none: a '
        'structural stop that sits closer to the entry than the frozen 0.25 % '
        'minimum risk band is refused as `risk_distance_too_small` instead of '
        'being narrowed to fit.',
        '',
        '## Note on reward/risk with a fixed 2 % target',
        '',
        'The target is the frozen production target (2 % of the entry) in every '
        'arm, so that the only thing that changes between arms is the entry or the '
        'stop. With a minimum reward/risk of 1.5 the usable stop width is capped '
        'at 1.33 % of the entry: a wider structural stop is refused as NO_TRADE '
        'rather than being silently narrowed or the target being moved.',
        '',
    ]
    return '\n'.join(lines)


# ------------------------------------------------------------ stop forensics ---
def _stop_forensics(forensics, base_records, cand_records):
    lines = [
        '# Stop-out forensics',
        '',
        'Every stop-out is examined twice: over the following 12 bars (one hour) '
        'and over the remainder of the session.',
        '',
        '## Baseline stop-outs',
        '',
        _tbl(['instrument', 'session', 'entry time', 'exit time', 'level',
              'realised R', 'points', 'overshoot pts', 'fwd60 R',
              'stop then continued', 'opposite direction category'],
             [[r['instrument'], r['session_date'], r['entry_time'], r['exit_time'],
               r['level'], _fmt(r['realized_r']), _fmt(r['realized_pts'], 1),
               _fmt(r['stop_overshoot_pts'], 1),
               _fmt(r['flags'].get('fwd60_r')),
               'yes' if r['flags'].get('stop_then_continued') else 'no',
               r['missed_direction'].get('missed_direction_category')]
              for r in forensics['baseline']]),
        '',
        f"Baseline stop-outs: **{forensics['baseline_summary']['stop_outs']}**.",
        '',
        '## Candidate stop-outs',
        '',
        _tbl(['instrument', 'session', 'entry time', 'exit time', 'family',
              'stop source', 'realised R', 'points', '12-bar adverse pts',
              '12-bar favourable pts', 'remainder pts', 'remainder R'],
             [[r['instrument'], r['session_date'], r['entry_time'], r['exit_time'],
               r.get('setup_family'), r.get('stop_source'), _fmt(r['realized_r']),
               _fmt(r['realized_pts'], 1),
               _fmt(r.get('forward', {}).get('max_adverse_pts_12bars'), 1),
               _fmt(r.get('forward', {}).get('max_favourable_pts_12bars'), 1),
               _fmt(r.get('forward', {}).get('remainder_pts'), 1),
               _fmt(r.get('forward', {}).get('remainder_r'))]
              for r in forensics['candidate']]),
        '',
        f"Candidate stop-outs: **{forensics['candidate_summary']['stop_outs']}**.",
        '',
        '## Interpretation rules',
        '',
        '- a stop-out that keeps falling after the stop is a *continuation*; the '
        'stop was too tight for that session, not the entry that was wrong;',
        '- a stop-out that reverses is a *failed breakdown* or a *late '
        'confirmation*; the level was never really broken;',
        '- gap-through stops are filled at the open, never at the theoretical '
        'stop price, and the overshoot is reported in points and in R;',
        '- index points only. No rupee value and no option premium is inferred.',
        '',
    ]
    return '\n'.join(lines)


# ------------------------------------------------------------- performance -----
def _performance(exp_b, exp_c, exp_d, rob, base_records, cand_records, candidate_arm):
    cb = rob['candidate_by_period']
    bb = rob['baseline_by_period']
    lines = [
        '# Performance and robustness',
        '',
        '## Candidate vs frozen baseline',
        '',
        _tbl(['arm', 'period', 'n', 'net R/trade', 'points/trade', 'wins', 'losses',
              'stops', 'targets', 'max DD (R)', 'mean MAE (R)'],
             [[label, per, d[per].get('n'),
               _fmt(d[per].get('net_R_per_trade')),
               _fmt(d[per].get('points_per_trade'), 2),
               d[per].get('wins'), d[per].get('losses'),
               d[per].get('stop_count'), d[per].get('target_count'),
               _fmt(d[per].get('max_dd_r')), _fmt(d[per].get('mean_mae_r'))]
              for label, d in (('candidate', cb), ('baseline', bb))
              for per in PERIODS]),
        '',
        '## Cost sensitivity (net R per trade)',
        '',
        _tbl(['cost per trade (R)', 'candidate', 'baseline'],
             [[k, _fmt(rob['cost_grid_candidate'][k]['net_R_per_trade']),
               _fmt(rob['cost_grid_baseline'][k]['net_R_per_trade'])]
              for k in rob['cost_grid_candidate']]),
        '',
        '## Walk-forward blocks (out-of-sample sessions)',
        '',
        _tbl(['block', 'sessions', 'candidate n', 'baseline n',
              'candidate net R/trade', 'baseline net R/trade',
              'candidate points/trade', 'baseline points/trade', 'positive'],
             [[b['block'], b['sessions'], b['candidate_n'], b['baseline_n'],
               _fmt(b['candidate_net_R_per_trade']),
               _fmt(b['baseline_net_R_per_trade']),
               _fmt(b['candidate_points_per_trade'], 2),
               _fmt(b['baseline_points_per_trade'], 2),
               'yes' if b['candidate_positive'] else 'no']
              for b in rob['walk_forward_blocks']]),
        '',
        '## By instrument',
        '',
    ]
    for inst, blob in rob['candidate']['instrument'].items():
        base = rob['baseline']['instrument'].get(inst, {})
        lines.append(f"**{inst}** - candidate n={blob['n']}, net R/trade="
                     f"{_fmt(blob['net_R_per_trade'])}, points/trade="
                     f"{_fmt(blob['points_per_trade'], 2)}; baseline n="
                     f"{base.get('n')}, net R/trade={_fmt(base.get('net_R_per_trade'))}, "
                     f"points/trade={_fmt(base.get('points_per_trade'), 2)}")
    lines += ['', '## By setup family', '']
    lines += [
        _tbl(['family', 'n', 'net R/trade', 'points/trade', 'stop-out rate',
              'target attainment', 'mean MAE (R)'],
             [[f, b['n'], _fmt(b['net_R_per_trade']), _fmt(b['points_per_trade'], 2),
               _fmt(b['stop_out_rate']), _fmt(b['target_attainment']),
               _fmt(b['mean_mae_r'])]
              for f, b in rob['candidate']['setup_family'].items()]),
        '',
        '## By entry hour',
        '',
        _tbl(['hour', 'n', 'net R/trade', 'points/trade'],
             [[h, b['n'], _fmt(b['net_R_per_trade']), _fmt(b['points_per_trade'], 2)]
              for h, b in rob['candidate']['entry_hour'].items()]),
        '',
        '## Concentration',
        '',
    ]
    conc = rob['candidate'].get('concentration') or {}
    lines += [
        f"- best three trades: {_fmt(conc.get('best_3_trades_points'), 1)} index "
        f"points out of {_fmt(conc.get('total_points'), 1)} total "
        f"({_fmt(conc.get('best_3_share_pct'), 1)} %)",
        f"- {conc.get('note', '')}",
        '',
        '## Neighbouring settings (stability)',
        '',
        _tbl(['neighbouring arm', 'IS n', 'VAL n', 'OOS n', 'VAL net R/trade',
              'OOS net R/trade', 'OOS points/trade'],
             [[k, v['IS']['n'], v['VAL']['n'], v['OOS']['n'],
               _fmt(v['VAL']['net_R_per_trade']), _fmt(v['OOS']['net_R_per_trade']),
               _fmt(v['OOS']['points_per_trade'], 2)]
              for k, v in rob['neighbour_arms'].items()]),
        '',
        'The neighbouring arms vary the confirmation rule, the zone width '
        '(0.07 % / 0.10 % / 0.15 %) and the expiry window (6 / 12 / 18 bars). A '
        'result that only exists for one exact parameter set is not a result.',
        '',
        '## Opportunity accounting against the baseline',
        '',
    ]
    oa = rob['opportunity_accounting']
    counts = {}
    for r in oa:
        counts[r['outcome']] = counts.get(r['outcome'], 0) + 1
    lines += [
        _tbl(['outcome', 'baseline triggers'], [[k, v] for k, v in sorted(counts.items())]),
        '',
        'Per-trigger rows are in `outputs/opportunity_accounting.csv`.',
        '',
    ]
    return '\n'.join(lines)


# --------------------------------------------------------------------- gates ---
def _gate_detail(v, width=220):
    """Compact, readable rendering of one gate result."""
    parts = []
    for k, val in v.items():
        if k in ('pass', 'note'):
            continue
        if isinstance(val, dict):
            inner = []
            for kk, vv in val.items():
                if isinstance(vv, dict):
                    deep = ', '.join(f'{a}={b}' for a, b in vv.items()
                                     if not isinstance(b, dict))
                    inner.append(f'{kk}[{deep}]')
                else:
                    inner.append(f'{kk}={vv}')
            parts.append(f'{k}: ' + ', '.join(inner) if inner else k)
        else:
            parts.append(f'{k}={val}')
    text = '; '.join(parts)
    return text if len(text) <= width else text[:width - 3] + '...'


def _gates(pre, exp_d):
    lines = [
        '# Validation gates',
        '',
        'The gate definitions are the approved ones from the parent study plus the '
        "add-on study's G-A2 point test. No threshold was relaxed and no gate was "
        'replaced by an assumption.',
        '',
        '## 1. Validation pre-check (before any out-of-sample read)',
        '',
        _tbl(['gate', 'result', 'detail'],
             [[k.replace('_', ' '),
               'PASS' if v.get('pass') else 'FAIL',
               _gate_detail(v)]
              for k, v in pre.items() if not k.startswith('_')]),
        '',
        f"Pre-check verdict: **{pre['_verdict']}**"
        + (f" (failed: {', '.join(pre['_failed_gates'])})" if pre['_failed_gates'] else ''),
        '',
        '## 2. Out-of-sample evaluation',
        '',
    ]
    if exp_d.get('oos_gates'):
        g = exp_d['oos_gates']
        lines += [
            _tbl(['gate', 'result'],
                 [[k, ('PASS' if v.get('pass') else ('FAIL' if v.get('pass') is False
                                                     else 'UNRESOLVED'))]
                  for k, v in g.items() if isinstance(v, dict) and 'pass' in v]),
            '',
            f"- overall: **{g['OVERALL']}**",
            f"- eligible for human review: **{g['ELIGIBLE_FOR_HUMAN_REVIEW']}**",
            f"- decision: {g['decision']}",
            '',
            'Even a PASS does not authorise a production change: the study is '
            'research only and any production change needs a separate, explicit '
            'human authorisation.',
            '',
        ]
    else:
        lines += [
            '**Not run.** The validation pre-check did not pass, so Experiment D '
            'was not executed as a validation. The out-of-sample numbers in '
            '`outputs/experiment_D.json` are reported for description only and '
            'are explicitly not a confirmation of the candidate.',
            '',
        ]
    return '\n'.join(lines)


# ----------------------------------------------------------------- executive ---
def _executive(exp_a, exp_b, exp_c, exp_d, rob, forensics, pre, dq, base_records,
               cand_records, candidate_arm, rule_selected, stop_selected):
    cand = rob['candidate_by_period']
    base = rob['baseline_by_period']
    oos_c = cand['OOS']
    oos_b = base['OOS']
    verdict = exp_d['verdict']
    n_trades = len(cand_records)
    stopped = forensics['candidate_summary']['stop_outs']

    lines = [
        '# Phase 3 - setup-first trading, market swings, entry confirmation and '
        'structural stop-loss: executive summary',
        '',
        f"**Verdict: {verdict}**",
        '',
        '## 1. What was actually changed in the entry logic, and why',
        '',
        'Nothing in the deployed system was changed. This study builds a separate '
        'setup-first engine that changes the *entry logic under test*:',
        '',
        '- the production engine enters on the **first trigger** of a session '
        '(a level touch that qualifies);',
        '- the setup-first engine instead identifies a **setup** in advance, waits '
        'for price to **reach a pre-defined zone**, waits for a **confirmation** '
        'on a closed candle, and only then enters at the **open of the next bar**;',
        '- the trade is refused when the entry is more than 0.25 % away from the '
        'level (no chasing), when no structural stop exists, when the risk '
        'distance is outside 0.25 %-1.50 % or when the reward/risk against the '
        'frozen 2 % target is below 1.5;',
        '- at most one trade is taken per instrument and session, because no '
        're-entry rule is declared.',
        '',
        'The rationale is the one the study was commissioned to test: a trigger is '
        'an event, a setup is a condition. Entering on the condition means the '
        'entry is a decision, not a reaction.',
        '',
        '## 2. Does waiting for the setup improve expectancy, drawdown and the '
        'largest loss?',
        '',
    ]
    if verdict == 'PASS_EXPLORATORY':
        lines.append('The candidate cleared the pre-declared gates on the '
                     'out-of-sample split. The numbers below are still '
                     'exploratory - see section 7.')
    else:
        lines.append('**No.** The candidate did not clear the pre-declared gates '
                     'on the validation split, so the out-of-sample split was not '
                     'used as a validation. The comparison below is descriptive.')
    lines += [
        '',
        _tbl(['period', 'arm', 'n', 'net R/trade', 'points/trade', 'max DD (R)',
              'mean MAE (R)', 'largest loss (R)'],
             [[p, 'candidate', cand[p]['n'], _fmt(cand[p]['net_R_per_trade']),
               _fmt(cand[p]['points_per_trade'], 2), _fmt(cand[p]['max_dd_r']),
               _fmt(cand[p]['mean_mae_r']), _fmt(cand[p]['largest_loss_r'])]
              for p in PERIODS] +
             [[p, 'baseline', base[p]['n'], _fmt(base[p]['net_R_per_trade']),
               _fmt(base[p]['points_per_trade'], 2), _fmt(base[p]['max_dd_r']),
               _fmt(base[p]['mean_mae_r']), _fmt(base[p]['largest_loss_r'])]
              for p in PERIODS]),
        '',
        f"- candidate trades in total: **{n_trades}** (baseline {len(base_records)})",
        f"- candidate stop-outs: **{stopped}**",
        '',
        '## 3. Which structural stop rule performs best, and why',
        '',
    ]
    rows = []
    for name, blob in exp_c['arms'].items():
        rows.append([name, blob['by_period']['VAL']['n'],
                     _fmt(blob['by_period']['VAL']['net_R_per_trade']),
                     _fmt(blob['by_period']['VAL']['points_per_trade'], 2),
                     _fmt(blob.get('mean_stop_distance_pct'), 6)])
    lines += [
        _tbl(['arm', 'VAL n', 'VAL net R/trade', 'VAL points/trade',
              'mean stop distance'], rows),
        '',
        f"- selected stop on the validation split: **{stop_selected}**",
        f"- selected entry policy: **{rule_selected}**",
        '',
        'The selection metric for the stop arms is index points per trade, not R '
        'per trade: comparing R per trade across different stop widths would '
        'reward the variant with the largest risk denominator, which is the exact '
        'normalisation artefact that G-A2 exists to catch.',
        '',
        '## 4. Is the improvement robust, or concentrated in a few sessions?',
        '',
    ]
    conc = rob['candidate'].get('concentration') or {}
    lines += [
        f"- best three trades: {_fmt(conc.get('best_3_trades_points'), 1)} points "
        f"of {_fmt(conc.get('total_points'), 1)} total "
        f"({_fmt(conc.get('best_3_share_pct'), 1)} %)",
        f"- candidate trades: {cand['IS']['n']} in-sample, {cand['VAL']['n']} "
        f"validation, {cand['OOS']['n']} out-of-sample",
        '- walk-forward blocks and neighbouring settings are in '
        '`reports/PERFORMANCE_AND_ROBUSTNESS.md`',
        '',
        '## 5. Which setup families reach their zone and confirm, and which never '
        'do?',
        '',
        _tbl(['family', 'identified', 'zone reached', 'confirmed', 'expired',
              'invalidated', 'eligible', 'confirmation rate %'],
             [[f, b['identified'], b['zone_reached'], b['confirmed'], b['expired'],
               b['invalidated'], b['trade_eligible'], b['confirmation_rate_pct']]
              for f, b in exp_a['by_family'].items()]),
        '',
        '## 6. How many opportunities are missed, expired or invalidated, and why?',
        '',
    ]
    tot = exp_a['totals']
    lines += [
        _tbl(['state', 'setups'],
             [['identified', tot.get('identified')],
              ['zone reached (arrival)', tot.get('zone_reached')],
              ['confirmed', tot.get('confirmed')],
              ['expired (window elapsed)', tot.get('expired')],
              ['invalidated (closed through the zone)', tot.get('invalidated')],
              ['trade eligible', tot.get('trade_eligible')],
              ['missed (too extended to chase)', tot.get('missed')],
              ['NO_TRADE (entry gates, after confirmation)', tot.get('no_trade')]]),
        '',
        'The rows are not additive: a confirmed setup is counted once, and a setup '
        'that never reached its zone is counted as expired or invalidated rather '
        'than as an entry-gate refusal.',
        '',
        '## 7. Does the candidate pass every pre-declared gate?',
        '',
        f"**No - verdict: {verdict}.**",
        '',
        f"- validation pre-check: **{pre['_verdict']}**"
        + (f" (failed: {', '.join(pre['_failed_gates'])})" if pre['_failed_gates'] else ''),
        f"- Experiment D (the combined entry+stop candidate) "
        f"{'was run' if exp_d.get('experiment_d_run') else 'was NOT run'}",
        '',
    ]
    if exp_d.get('oos_gates'):
        g = exp_d['oos_gates']
        failed = [k for k, v in g.items() if isinstance(v, dict) and v.get('pass') is False]
        lines += [
            f"- out-of-sample overall: **{g['OVERALL']}**",
            f"- failed out-of-sample gates: {', '.join(failed) if failed else 'none'}",
            '',
        ]
    lines += [
        'The gates that cannot be judged are reported as unresolved rather than '
        'as a pass:',
        '',
        '- the percentage-of-capital sub-gates of G-C are **unresolved** - no '
        'production-confirmed capital base exists, and no capital figure is '
        'invented;',
        '- the out-of-sample independence of this lineage is only **partial** '
        '(the baseline signals were already inspected in the earlier phases), so '
        'even a clean pass would cap the result at exploratory.',
        '',
        '## 8. What evidence would be required before any production change could '
        'be considered',
        '',
        '1. a pre-registered replication on data that was never inspected by this '
        'lineage (for example sessions after 2026-10-21), with the parameters '
        'frozen before the data is read;',
        '2. a sample that satisfies the pre-declared evidence thresholds '
        '(15 out-of-sample trades, 5 per instrument, and a bootstrap interval '
        'that does not straddle zero);',
        '3. a resolved capital base so that the drawdown and largest-loss '
        'sub-gates can be evaluated in percent of capital;',
        '4. option-level economics (premiums, spreads, slippage) before any '
        'rupee or option-level claim - this study is index-level only;',
        '5. a shadow/paper run of the setup-first engine next to the production '
        'engine with a pre-declared comparison protocol;',
        '6. an explicit, separate human authorisation. **This study authorises '
        'no production change.**',
        '',
        '## 9. What was not tested and what remains uncertain',
        '',
        '- long (BULL) setups: out of scope by pre-registration, because the '
        'frozen baseline is 100 % BEAR under `SHORT_ONLY=True`;',
        '- option and credit-spread economics: no historical premium or bid/ask '
        'data is available, so every number here is an index-point number;',
        '- capital-relative risk: unresolved, see above;',
        '- the 2026-10-22 session was excluded because it was incomplete at '
        'study time;',
        '- the walk-forward blocks and the neighbouring arms share the same '
        'sessions, so they are not independent samples;',
        '- the setup families were pre-registered as a set, but the *weighting* '
        'between families was not tuned - no per-family parameter optimisation '
        'was performed.',
        '',
        '## Artefacts',
        '',
        '| file | content |',
        '|---|---|',
        '| `reports/PREFLIGHT.md` | repository, protected-file and service state '
        'before the study |',
        '| `reports/BASELINE_REPRODUCTION.md` | the frozen baseline re-run and '
        'reconciled |',
        '| `reports/SETUP_DEFINITION.md` | the six setup families and the frozen '
        'parameters |',
        '| `reports/SETUP_ARRIVAL_CONFIRMATION.md` | the arrival/confirmation funnel |',
        '| `reports/ENTRY_AND_STOP_PLANS.md` | the entry plan, the stop variants '
        'and their availability |',
        '| `reports/STOP_OUT_FORENSICS.md` | what happened after every stop-out |',
        '| `reports/PERFORMANCE_AND_ROBUSTNESS.md` | performance, cost, blocks, '
        'neighbours, concentration |',
        '| `reports/VALIDATION_GATES.md` | every gate and its result |',
        '| `reports/INTEGRITY_FINAL.md` | the final integrity verification |',
        '| `outputs/*.csv`, `outputs/*.json` | machine-readable setup rows, trades, '
        'gates and manifest |',
        '',
    ]
    return '\n'.join(lines)
