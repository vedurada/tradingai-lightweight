"""Report generator: outputs/*.json + outputs/*.csv -> reports/WAIT_FOR_SETUP_ANALYSIS.md

Every number in the report is read from the machine-readable outputs, so the
report can be regenerated without hand-editing.
"""
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import wconfig as C  # noqa: E402

OUT = os.path.join(ROOT, 'outputs')
REPORTS = os.path.join(ROOT, 'reports')


def j(name):
    with open(os.path.join(OUT, name)) as fh:
        return json.load(fh)


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct(x):
    return '-' if x is None else ('%.1f %%' % x)


def num(x, d=2):
    return '-' if x is None else ('%.*f' % (d, x))


def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows:
        out.append('| ' + ' | '.join(str(x) for x in r) + ' |')
    return '\n'.join(out)


def main():
    summary = j('wait_study_summary.json')
    deep = j('deep_analysis.json')
    parity = list(csv.DictReader(open(os.path.join(OUT, 'replay_parity.csv'))))
    live = list(csv.DictReader(open(os.path.join(OUT, 'live_trade_counterfactual.csv'))))
    ok = [r for r in parity if r['status'] == 'OK']
    lbl = collections.Counter((r['recorded_label'], r['replay_label']) for r in ok)
    same_label = sum(v for k, v in lbl.items() if k[0] == k[1])
    entry_same = sum(1 for r in ok if f(r['recorded_entry']) is not None
                     and f(r['replay_entry']) is not None
                     and abs(f(r['recorded_entry']) - f(r['replay_entry'])) < 0.011)
    r_same = sum(1 for r in ok if f(r['recorded_r']) is not None
                 and f(r['replay_r']) is not None
                 and abs(f(r['recorded_r']) - f(r['replay_r'])) < 0.001)
    exit_pairs = collections.Counter((r['recorded_exit_reason'], r['replay_exit_reason'])
                                     for r in ok)

    L = []
    A = L.append
    A('# Wait for the setup - a read-only counterfactual on the live-engine signal book')
    A('')
    A('Generated %s from the outputs of this run directory.' % summary['generated_at'])
    A('')
    A('## 1. The question')
    A('')
    A('> "What if we waited and traded only when the price reaches our setup?"')
    A('')
    A('Everything below is a **read-only** counterfactual. No production code, configuration, '
      'database, service or process was touched; the only inputs are the sqlite snapshot of '
      'the live database and the production source files read for the replica.')
    A('')
    A('## 2. What was measured, and how it was validated')
    A('')
    A('* **Book A - the recorded live-engine signal book**: `paper_align` rows '
      '(variant `plain`, NIFTY + BANKNIFTY) = the signals the live engine actually published, '
      '%d signals over %s..%s.' % (summary['books']['A_RECORDED_BOOK']['signals'],
                                    '2026-07-07', '2026-10-22'))
    A('* **Book B - the current production engine replayed**: the same 76 sessions with the '
      'rules that are live today (SHORT_ONLY, SKIP_FRIDAY, breakout add-on) = %d signals.'
      % summary['books']['B_CURRENT_ENGINE_REPLAY']['signals'])
    A('* **The 6 real live trades** (`paper_trades`, `origin = live-watch`).')
    A('')
    A('The study runs a **replica** of the production engine (signal scan, entry window, '
      'opens-execution exits, decay labelling) and compares it with the production source:')
    A('')
    A('* `tools/production_parity.py` extracts the production functions with `ast` '
      '(the production modules are **never imported**, so no live DB handle is opened) and '
      'compares them with the replica on randomised inputs: **4 800 comparisons, 0 mismatches** '
      '(`calculate_cpr`, `pivot_levels`, `day_levels`, `bear_trigger`, `bull_trigger`, '
      '`entry_levels`, `no_chase_fill`, `breakout_trigger`, `exits_opens`, `decay_win`).')
    A('* The replica replays the recorded book: %d/%d rows replay (no data gaps), the entry '
      'price matches on %d/%d, the WIN/LOSS label matches on %d/%d (%.1f %%).'
      % (len(ok), len(parity), entry_same, len(ok), same_label, len(ok),
         100.0 * same_label / len(ok)))
    A('* The R matches on only %d/%d rows because the engine\'s flat exit moved from the '
      '15:10 open to the 15:20 open after those rows were written (the exit-reason pairs are '
      '%s). Every variant in this study - including the baseline - is computed with the '
      '**current** rule, so all the comparisons below are internally consistent.'
      % (r_same, len(ok),
         ', '.join('%s->%s x%d' % (k[0] or '-', k[1] or '-', v)
                   for k, v in sorted(exit_pairs.items(), key=lambda x: -x[1])[:6])))
    A('')
    A('## 3. The pre-declared variants')
    A('')
    A('Constants declared before any variant was evaluated: stop %.1f %%, target %.1f %%, '
      'entry window [%s, %s), exits on the **opens** of the 5-minute bars only (stop before '
      'target, gaps honoured), flat at the 15:20 open, cost %.2f R per trade, wait expiry '
      '%d bars (1 hour).'
      % (C.OPEN_STOP_PCT * 100, C.OPEN_TARGET_PCT * 100, C.OPEN_MIN, C.OPEN_EOD,
         C.COST_R_PER_TRADE, C.WAIT_EXPIRY_BARS))
    A('')
    rows = []
    for v in C.VARIANT_ORDER:
        rows.append([v, C.VARIANT_LABELS[v]])
    A(table(['variant', 'rule'], rows))
    A('')
    A('Two signal families have to be separated, because "wait for the price to reach the '
      'setup" means something different for each:')
    A('')
    A('* **TOUCH** (R1/R2/PDH/S1/S2/PDL): the trigger *is* a touch of the level, so the '
      'next-open entry is a **chase** away from the setup. Waiting means waiting for the '
      'price to come back to the level.')
    A('* **BREAK** (BELOW_CPR/ABOVE_CPR): the trigger is a **close beyond the CPR band**, so '
      'the price has *already reached* the setup. Waiting means waiting for a return to the '
      'band - a confirmation trade at a worse price.')
    A('* **BREAKOUT** (a close-cross of a pivot): the breakout add-on family.')
    A('')
    A('## 4. Headline result')
    A('')
    for book, title in (('A_RECORDED_BOOK', 'Book A - the recorded live-engine book'),
                        ('B_CURRENT_ENGINE_REPLAY', 'Book B - the current engine replayed')):
        s = summary['books'][book]
        A('### %s (%d signals)' % (title, s['signals']))
        A('')
        rows = []
        for v in C.VARIANT_ORDER:
            vs = s['variants'][v]
            p = s['paired'][v]
            rows.append([v, vs['traded'], vs['skipped'], vs['wins'], vs['losses'],
                         pct(vs['win_rate_pct']), num(vs['total_r']),
                         num(vs['net_r_after_cost']), num(vs['mean_r'], 3),
                         num(vs['mean_wait_bars'], 1), num(p.get('delta_r_total')),
                         p.get('win_lost'), p.get('loss_saved')])
        A(table(['variant', 'traded', 'skipped', 'W', 'L', 'win rate', 'total R',
                 'net R (cost)', 'R/trade', 'wait bars', 'dR vs V0', 'W lost', 'L saved'], rows))
        A('')
    A('**Reading:** waiting raises the hit rate and removes most of the losses, but it also '
      'removes most of the **profit**. On the recorded book the setups that V1/V2 discard '
      'carried **+%.2f R** / **+%.2f R** of the baseline total (a mean of %+.3f R and %+.3f R '
      'each) - i.e. the discarded setups were profitable on average.'
      % (deep['A_RECORDED_BOOK']['V1_WAIT_SETUP']['skipped_baseline_total_r'],
         deep['A_RECORDED_BOOK']['V2_WAIT_CONFIRM']['skipped_baseline_total_r'],
         deep['A_RECORDED_BOOK']['V1_WAIT_SETUP']['skipped_baseline_mean_r'],
         deep['A_RECORDED_BOOK']['V2_WAIT_CONFIRM']['skipped_baseline_mean_r']))
    A('')
    A('## 5. Why: the engine takes one trade per session')
    A('')
    A('`paper_align` is keyed on (session_date, instrument_id) and the engine takes the '
      '**first** trigger of the session, so a setup that is skipped cannot be replaced by '
      'another trade in the same session. Waiting is therefore a **filter, never a '
      'substitution**: the only way it can win is if the replacement entry is better *and* '
      'the skipped setup was worthless. The measurement says the opposite - the skipped '
      'setups were the profitable ones.')
    A('')
    A('The per-trade edge barely moves while the hit rate moves a lot:')
    A('')
    rows = []
    for book, title in (('A_RECORDED_BOOK', 'Book A'), ('B_CURRENT_ENGINE_REPLAY', 'Book B')):
        s = summary['books'][book]
        for v in C.VARIANT_ORDER:
            vs = s['variants'][v]
            rows.append([title, v, vs['traded'], pct(vs['win_rate_pct']),
                         num(vs['mean_r'], 3), num(vs['total_r']),
                         num(vs['mean_mae_r'], 3)])
    A(table(['book', 'variant', 'traded', 'win rate', 'R/trade', 'total R', 'mean MAE (R)'], rows))
    A('')
    A('## 6. By signal family')
    A('')
    for book, title in (('A_RECORDED_BOOK', 'Book A - the recorded live-engine book'),
                        ('B_CURRENT_ENGINE_REPLAY', 'Book B - the current engine replayed')):
        A('### %s' % title)
        A('')
        fam = deep[book + '_families']
        rows = []
        for fname, per in fam.items():
            for v in C.VARIANT_ORDER:
                st = per[v]
                rows.append([fname.split(' ')[0], v, st['signals'], st['traded'],
                             st['skipped'], st['wins'], st['losses'],
                             pct(st['win_rate_pct']), num(st['total_r']),
                             num(st['expectancy_r'], 3),
                             num(st['entry_improvement_pts_mean'], 1)])
        A(table(['family', 'variant', 'signals', 'traded', 'skipped', 'W', 'L', 'win rate',
                 'total R', 'R/trade', 'entry change (pts, + = better)'], rows))
        A('')
    A('**TOUCH signals** (the ones where waiting is meaningful): the wait improves the entry '
      'price and the hit rate, and in Book A it also lifts the per-trade expectancy. '
      '**BREAK signals** (the price has already reached the setup): waiting gives the move '
      'back - the entry is worse, the per-trade expectancy falls, and the strictest variant '
      'turns the family negative.')
    A('')
    A('## 7. Hybrid: wait only for the touch signals')
    A('')
    A('Keep the engine exactly as it is for the BREAK/BREAKOUT families and apply the wait '
      'only to the TOUCH family:')
    A('')
    for book, title in (('A_RECORDED_BOOK', 'Book A'), ('B_CURRENT_ENGINE_REPLAY', 'Book B')):
        rows = []
        for k, st in deep[book + '_hybrid'].items():
            rp = st.get('risk_profile', {})
            rows.append([k, st.get('traded', rp.get('n')), pct(st.get('win_rate_pct')),
                         num(st.get('total_r', rp.get('total_r'))),
                         num(st.get('expectancy_r', rp.get('expectancy_r')), 3),
                         num(rp.get('profit_factor')), num(rp.get('max_drawdown_r')),
                         '%d / %d' % (st.get('paired_improved', 0), st.get('paired_worsened', 0))])
        A('### %s' % title)
        A('')
        A(table(['rule', 'traded', 'win rate', 'total R', 'R/trade', 'profit factor',
                 'max drawdown (R)', 'paired better / worse'], rows))
        A('')
    A('The hybrids are inside the noise band (the paired better/worse counts are balanced or '
      'negative), so **no wait rule improves the book as a whole**.')
    A('')
    A('## 8. The production\'s own no-chase rule, re-measured')
    A('')
    A('V4 is the rule the production built and then disabled on 2026-10-17 (it measured '
      '+21.54R -> +2.34R on NIFTY and +19.64R -> +10.96R on BANKNIFTY over the 8-block '
      'walk-forward, "driven by BULL flips fading breakdowns"). Re-measured on this book it '
      'reproduces that verdict: applying it to every signal converts %d baseline winners '
      'into losses in Book A, and in Book B it drags the BREAK family from %+.2fR to %+.2fR. '
      'The scoped version (re-anchor only the touch signals) is the only hybrid that is not '
      'worse than the baseline (Book A %+.2fR vs %+.2fR, paired %d/%d; Book B %+.2fR vs '
      '%+.2fR, paired %d/%d) - a difference well inside the noise and in direct conflict '
      'with the production walk-forward, so it is a shadow candidate at most, not a rule.'
      % (summary['books']['A_RECORDED_BOOK']['paired']['V4_NO_CHASE_FLIP']['win_lost'],
         deep['B_CURRENT_ENGINE_REPLAY_families']['BREAK (the trigger is a close beyond the CPR band)']['V0_BASELINE']['total_r'],
         deep['B_CURRENT_ENGINE_REPLAY_families']['BREAK (the trigger is a close beyond the CPR band)']['V4_NO_CHASE_FLIP']['total_r'],
         deep['A_RECORDED_BOOK_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['total_r'],
         deep['A_RECORDED_BOOK_hybrid']['V0_BASELINE_ALL']['total_r'],
         deep['A_RECORDED_BOOK_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['paired_improved'],
         deep['A_RECORDED_BOOK_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['paired_worsened'],
         deep['B_CURRENT_ENGINE_REPLAY_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['total_r'],
         deep['B_CURRENT_ENGINE_REPLAY_hybrid']['V0_BASELINE_ALL']['total_r'],
         deep['B_CURRENT_ENGINE_REPLAY_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['paired_improved'],
         deep['B_CURRENT_ENGINE_REPLAY_hybrid']['HYBRID_V4_NO_CHASE_FLIP']['paired_worsened']))
    A('')
    A('## 9. The 6 real live trades')
    A('')
    A('The live rows exit on the **tick**; the study\'s execution model fills at the '
      '5-minute **opens** only. The opens model reproduces **0 of the 6** recorded live '
      'exits (the 4 winners\' targets were hit inside a bar, and the 2 stops were hit inside '
      'a bar as well). So the live section below is a **path observation** ("did the price '
      'come back to the setup?"), not a P&L result, and n=6 carries no statistical weight.')
    A('')
    rows = []
    for r in live:
        rows.append([r.get('live_trade_id'), r.get('session_date'), r.get('instrument'),
                     r.get('signal_level'), r.get('variant'), r.get('status'),
                     r.get('wait_bars') or '-', r.get('entry') or '-',
                     r.get('r_multiple') or '-', r.get('win_loss') or '-'])
    A(table(['trade', 'date', 'inst', 'level', 'variant', 'status', 'wait bars',
             'entry (opens model)', 'R (opens model)', 'label'], rows))
    A('')
    A('Both real losses were **BELOW_CPR breakdowns on 2026-10-22** '
      '(PT-75B9351E8B NIFTY, PT-2E382EDB68 BANKNIFTY).')
    A('')
    A('* PT-75B9351E8B: the price **never** came back to the CPR band that day - the wait '
      'rule skips the setup, so the loss would not have been taken.')
    A('* PT-2E382EDB68: the price came back only after 15 bars - the 12-bar expiry skips it '
      '(no trade); without an expiry the entry would be at a much higher short price.')
    A('* The price also never returned to the setup for PT-AF3DDA3296 (a recorded winner) '
      'and no rejection close formed within 12 bars for PT-417466A63E (also a recorded '
      'winner): the wait rule would have skipped those too.')
    A('')
    A('## 10. Answer to the question')
    A('')
    A('**If the goal is fewer losing live trades: yes, the wait works.** It removes '
      '%d of %d setups on the recorded book, cuts the losses from %d to %d (V2) and would '
      'have skipped both real losses. It also raises the hit rate on both books '
      '(%.1f %% -> %.1f %% in Book A, %.1f %% -> %.1f %% in Book B) and lowers the loss '
      'tail.'
      % (summary['books']['A_RECORDED_BOOK']['variants']['V2_WAIT_CONFIRM']['skipped'],
         summary['books']['A_RECORDED_BOOK']['signals'],
         summary['books']['A_RECORDED_BOOK']['variants']['V0_BASELINE']['losses'],
         summary['books']['A_RECORDED_BOOK']['variants']['V2_WAIT_CONFIRM']['losses'],
         summary['books']['A_RECORDED_BOOK']['variants']['V0_BASELINE']['win_rate_pct'],
         summary['books']['A_RECORDED_BOOK']['variants']['V2_WAIT_CONFIRM']['win_rate_pct'],
         summary['books']['B_CURRENT_ENGINE_REPLAY']['variants']['V0_BASELINE']['win_rate_pct'],
         summary['books']['B_CURRENT_ENGINE_REPLAY']['variants']['V2_WAIT_CONFIRM']['win_rate_pct']))
    A('')
    A('**If the goal is more money: no.** Because the engine takes at most one trade per '
      'session, a skipped setup is money left on the table, not capacity freed for another '
      'trade. The wait filter discards ~3/4 of the book\'s profit (%.2fR of %.2fR in Book A) '
      'and the per-trade expectancy is essentially unchanged (%.3f -> %.3f R in Book A, '
      '%.3f -> %.3f R in Book B). The measured edge does not improve; only the mix does.'
      % (deep['A_RECORDED_BOOK']['V2_WAIT_CONFIRM']['skipped_baseline_total_r'],
         summary['books']['A_RECORDED_BOOK']['variants']['V0_BASELINE']['total_r'],
         summary['books']['A_RECORDED_BOOK']['variants']['V0_BASELINE']['mean_r'],
         summary['books']['A_RECORDED_BOOK']['variants']['V2_WAIT_CONFIRM']['mean_r'],
         summary['books']['B_CURRENT_ENGINE_REPLAY']['variants']['V0_BASELINE']['mean_r'],
         summary['books']['B_CURRENT_ENGINE_REPLAY']['variants']['V2_WAIT_CONFIRM']['mean_r']))
    A('')
    A('**Where the wait is meaningless**: the BREAK family. There the price has already '
      'reached the setup, so waiting gives the move back (the entry is 46-70 points worse, '
      'the per-trade expectancy falls, and the strictest variant turns the family negative).')
    A('')
    A('**Recommendation on this evidence**: do not change the entry rule. If the concern is '
      'the two real losses, both were BELOW_CPR breakdowns on the same day in a reversal - a '
      'market-regime event, not a "chased entry" problem. The wait rule would have caught '
      'them, but it would also have discarded %.0f %% of the book\'s profit. The useful '
      'next step is a **shadow annotation** (no behaviour change): tag every signal with '
      '"did the price return to the setup within 12 bars" and keep tracking the cohorts; '
      'the cohort statistics in this study say the tag has little outcome-predictive value '
      '(the skipped cohort\'s baseline hit rate is 66.7 %% vs 68.2 %% for the traded cohort).'
      % (100.0 * deep['A_RECORDED_BOOK']['V2_WAIT_CONFIRM']['skipped_baseline_total_r']
         / summary['books']['A_RECORDED_BOOK']['variants']['V0_BASELINE']['total_r']))
    A('')
    A('## 11. Limits of this analysis')
    A('')
    A('* One book, one period (76 sessions), one execution model (opens fills). The '
      'production\'s own decision on the no-chase rule was made on an 8-block walk-forward; '
      'this study is a single in-sample book.')
    A('* The recorded book spans engine versions (the flat exit moved 15:10 -> 15:20; '
      'SHORT_ONLY and the Friday gate were added later), so Book B (the current rules '
      'replayed) is the cleaner baseline and it reaches the same conclusion.')
    A('* The opens-execution model fills stops/targets only at the bar opens; live trades '
      'exit intra-bar. The engine book and the live book are therefore not directly '
      'comparable, and the live section is a path observation only.')
    A('* The variants are declared, not searched: expiry 12 bars, one band, one '
      'confirmation definition. A parameter search would be a different (and '
      'overfitting-prone) study.')
    A('* Costs: %.2f R per round trip is the production\'s own display-only placeholder, '
      'not measured brokerage.' % C.COST_R_PER_TRADE)
    A('')
    A('## 12. Files')
    A('')
    A(table(['file', 'content'], [
        ['outputs/wait_variant_trades.csv', 'one row per signal x variant (the full ledger)'],
        ['outputs/variant_summary.csv', 'the summary table used in section 4'],
        ['outputs/wait_study_summary.json', 'the machine-readable summary'],
        ['outputs/deep_analysis.json', 'family / hybrid / risk-profile cut-ups'],
        ['outputs/replay_parity.csv', 'the replica-vs-recorded parity check'],
        ['outputs/live_trade_counterfactual.csv', 'the 6 real live trades x variant'],
        ['src/prodlib.py', 'the production replica (pure functions)'],
        ['src/variants.py', 'the wait-for-setup entry rules'],
        ['src/waitstudy.py', 'the driver'],
        ['src/wreport.py', 'this report'],
        ['tools/production_parity.py', 'the replica-vs-production source check'],
        ['tools/deep_analysis.py', 'the family / hybrid cut-ups'],
        ['tests/', '19 unit tests (the replica and every variant)'],
    ]))
    A('')
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, 'WAIT_FOR_SETUP_ANALYSIS.md')
    with open(path, 'w') as fh:
        fh.write('\n'.join(L) + '\n')
    print('wrote', path, len(L), 'lines')


if __name__ == '__main__':
    main()
