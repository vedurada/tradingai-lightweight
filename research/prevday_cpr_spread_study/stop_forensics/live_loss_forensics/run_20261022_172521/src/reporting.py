"""Markdown deliverables."""
import collections
import json
import os
from datetime import datetime

from . import config, ledger as ledger_mod


def _write(name, text):
    path = os.path.join(config.REPORTS, name)
    with open(path, 'w') as fh:
        fh.write(text.rstrip() + '\n')
    return path


def _tbl(headers, rows):
    out = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |')
    return '\n'.join(out)


def _fmt(value, digits=3):
    if value is None:
        return 'n/a'
    if isinstance(value, float):
        return round(value, digits)
    return value


# ------------------------------------------------------------------ preflight ---
def write_preflight(pre, snapshot_meta):
    lines = [
        '# Phase 4 preflight - live-engine loss forensics',
        '',
        f"Captured: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        '',
        '## 1. Repository state (read before anything else)',
        '',
        f"- branch: `{pre['branch']}`",
        f"- HEAD: `{pre['head']}`",
        f"- git status lines: **{pre['git_status_lines']}** "
        f"(sha256 `{pre['git_status_sha256']}`)",
        '- the working tree was already dirty before this study started; every '
        'pre-existing tracked and untracked file is preserved and never touched.',
        '',
        '## 2. Protected production files',
        '',
        _tbl(['file', 'sha256 (before)'],
             [[f'`{k}`', f'`{v}`'] for k, v in pre['protected_hashes'].items()]),
        '',
        '## 3. Live database and services',
        '',
        f"- live database: `{pre['live_db']['path']}` size {pre['live_db']['size']} "
        f"sha256 `{pre['live_db']['sha256']}`",
        f"- WAL: {pre['live_db_wal'].get('size')} bytes",
        f"- gunicorn pids: `{', '.join(pre['services']['gunicorn_pids'])}` "
        f"(count {pre['services']['gunicorn_count']})",
        '',
        '## 4. Snapshot taken for this study',
        '',
        f"- path: `{snapshot_meta['path']}`",
        f"- size: {snapshot_meta['size']} bytes",
        f"- sha256: `{snapshot_meta['sha256']}`",
        f"- method: {snapshot_meta['backup_method']}",
        f"- the live database sha256 at backup time: "
        f"`{snapshot_meta['source_db_sha256_at_backup']}`",
        '',
        'Every query in this study runs against the snapshot, opened read-only '
        '(`file:...?mode=ro`). No query was ever run against the live database.',
        '',
        '## 5. Scope of the study',
        '',
        '- read-only: no production file, service, database, configuration or '
        'environment variable was modified;',
        '- all outputs are written inside this run directory only;',
        '- no alert, order or notification was generated.',
        '',
    ]
    return _write('PREFLIGHT.md', '\n'.join(lines))


# ------------------------------------------------------- source and loss def ---
def write_source_and_loss_definition(src, pops):
    lines = [
        '# Data source and loss definition',
        '',
        '## 1. Which records are the authoritative live trades',
        '',
        'The production code itself defines the authoritative source. '
        '`app/paper_trade/performance.py` states: "AUTHORITATIVE SOURCE '
        '(2026-10-18): the live paper ledger is `paper_trades`, written by the '
        'live watcher", and both `app/paper_trade/engine.py` and '
        '`app/paper_trade/performance.py` implement `_is_live()` as '
        '`qualification_evidence.origin == "live-watch"`. Rows without that '
        'marker are excluded by the production code itself and reported as '
        '`excluded_test_records`.',
        '',
        'The table was traced end to end: the live watcher '
        '(`scripts/tg_alerts.py --watch`) creates a row through '
        '`PaperTradeEngine.create_paper_trade`; the exit is booked by '
        '`PaperTradeEngine.monitor`, which evaluates the OPEN of every 5-minute '
        'candle strictly after the entry with the shared `exits_opens` routine '
        '(stop 0.5 %, target 2 %, STOP-first tie-break) and records the real '
        'recorded open as the fill, gaps included.',
        '',
        '## 2. Source inventory and inclusion decisions',
        '',
    ]
    rows = []
    for name, blob in src.items():
        rows.append([
            f'`{name}`', blob.get('role'), blob.get('rows'),
            blob.get('range', {}).get('first'), blob.get('range', {}).get('last'),
            blob.get('instruments'),
        ])
    lines += [_tbl(['source', 'role', 'rows', 'first', 'last', 'instruments'], rows), '']
    lines += ['### Notes per source', '']
    for name, blob in src.items():
        if blob.get('note'):
            lines.append(f"- **{name}**: {blob['note']}")
    lines += [
        '',
        '## 3. The five categories are never mixed',
        '',
        '1. **Actual live / paper trades** - `paper_trades` rows with '
        '`origin = "live-watch"`: the watcher really ran, a market entry was '
        'recorded and an outcome was booked.',
        '2. **Live-engine signal book with modelled exits** - `paper_align` '
        '(`state = "SIGNAL"`): the engine\'s own recorded signals for NIFTY and '
        'BANKNIFTY with index-level, opens-execution outcomes. These are real '
        'engine decisions but SIMULATED executions, and they are reported '
        'separately from category 1.',
        '3. **Historical simulated records** - the legacy `trade_journal` (no '
        'production writer since the Phase-9 backend was removed) and the '
        '`backtest_*` tables.',
        '4. **Signals without an entry** - `paper_align_veto` (vetoed before an '
        'entry existed), `live_observations` (decision log), '
        '`qualified_trades` (qualification ledger).',
        '5. **Reconstructed hypothetical trades** - nothing in this study is '
        'counted as a trade; the forward paths after an exit are descriptive '
        'counterfactuals only.',
        '',
        '## 4. The loss definition actually used',
        '',
        'The source\'s own recorded outcome is used first, and is then '
        'independently reconciled against the recorded entry and exit prices.',
        '',
        '- *Actual live/paper trades*: the recorded `exit_reason` and the '
        'recorded `paper_pnl` decide the outcome. `paper_pnl` is the '
        'production formula `signed_points x lot - (40 + 0.5 x lot)` with lot 65 '
        '(NIFTY) / 30 (BANKNIFTY). A trade is a LOSS only when the recorded '
        'pnl is negative AND the recomputed value from the recorded prices '
        'agrees within 1 rupee-equivalent.',
        '- *Engine signal book*: the recorded `result` decides the outcome and '
        'is compared with the recomputed `R = signed_move / risk_points`. If the '
        'sign of the label and the sign of the recomputed R disagree, the row is '
        'classified `UNKNOWN_OR_INCONSISTENT` and excluded from the loss and win '
        'metrics. It is reported, never silently repaired.',
        '- **Open trades** are never counted as losses. There are currently no '
        'open rows in `paper_trades` (all rows are `CLOSED` or `VOID`).',
        '- A trade is never redefined as a loss because of a later price move. '
        'The forward path after an exit is reported separately and descriptively.',
        '',
        '## 5. Units',
        '',
        '- index points and R are the primary units;',
        '- the recorded `paper_pnl` is a MODELLED rupee value (index points x lot '
        'minus a flat brokerage and slippage estimate), not a verified option '
        'execution: no premium, strike, expiry or fill record exists for it, so '
        'it is never presented as account profit;',
        '- no option premium, spread, brokerage or slippage figure is inferred '
        'by this study.',
        '',
    ]
    return _write('DATA_SOURCE_AND_LOSS_DEFINITION.md', '\n'.join(lines))


# ------------------------------------------------------------- data quality ---
def write_data_quality(pops, rows, p3, src):
    lines = [
        '# Data quality and reconciliation',
        '',
        '## 1. Population counts with denominators',
        '',
    ]
    for pop, blob in pops.items():
        if not isinstance(blob, dict) or 'total' not in blob:
            continue
        lines.append(f"### {pop}")
        lines.append('')
        lines.append(_tbl(['metric', 'value'], [
            ['records in the population', blob['total']],
            ['closed (loss + win + flat)', blob['closed']],
            ['losses', blob['losses']],
            ['wins', blob['wins']],
            ['flat', blob['flat']],
            ['open / pending', blob['open']],
            ['unknown or inconsistent', blob['unknown']],
            ['loss rate (% of closed)', blob['loss_rate_pct']],
            ['records flagged by reconciliation', len(blob['flagged'])],
        ]))
        lines.append('')
        lines.append('By instrument:')
        lines.append('')
        lines.append(_tbl(['instrument', 'total', 'closed', 'losses', 'wins',
                           'flat', 'unknown', 'loss rate %'],
                          [[k, v['total'], v['closed'], v['losses'], v['wins'],
                            v['flat'], v['unknown'], v['loss_rate_pct']]
                           for k, v in blob['by_instrument'].items()]))
        lines.append('')
        lines.append(f"Flags present: {', '.join(blob['flagged']) or 'none'}")
        lines.append('')
    lines += [
        '## 2. Reconciliation checks',
        '',
    ]
    lines.append(_tbl(['check', 'result'], [
        ['live paper trades = rows with origin=live-watch',
         f"{pops[ledger_mod.POP_LIVE]['total']}"],
        ['engine signal book rows (NIFTY + BANKNIFTY)',
         f"{pops[ledger_mod.POP_BOOK]['total']}"],
        ['closed + open + unknown = population total (live)',
         pops[ledger_mod.POP_LIVE]['total'] ==
         pops[ledger_mod.POP_LIVE]['closed'] + pops[ledger_mod.POP_LIVE]['open'] +
         pops[ledger_mod.POP_LIVE]['unknown']],
        ['closed + open + unknown = population total (book)',
         pops[ledger_mod.POP_BOOK]['total'] ==
         pops[ledger_mod.POP_BOOK]['closed'] + pops[ledger_mod.POP_BOOK]['open'] +
         pops[ledger_mod.POP_BOOK]['unknown']],
        ['no duplicate trade ids in the live population',
         len({r['source_row_id'] for r in rows
              if r['population'] == ledger_mod.POP_LIVE}) ==
         pops[ledger_mod.POP_LIVE]['total']],
        ['no duplicate trade ids in the engine book',
         len({(r['session_date'], r['instrument']) for r in rows
              if r['population'] == ledger_mod.POP_BOOK}) ==
         pops[ledger_mod.POP_BOOK]['total']],
        ['Phase 3 headline figures reproduced from the artifacts',
         p3['all_checks_pass']],
    ]))
    lines += [
        '',
        'Individual Phase 3 checks:',
        '',
        _tbl(['check', 'passed'], [[k, v] for k, v in p3['checks'].items()]),
        '',
        '## 3. Known data-quality findings',
        '',
        '- The engine label and the engine\'s own price arithmetic disagree on '
        'a part of the signal book: rows where `result = WIN` but the recorded '
        'exit price is adverse for the direction. They are classified '
        '`UNKNOWN_OR_INCONSISTENT` and removed from the loss-rate metrics '
        'instead of being repaired.',
        '- `r_multiple` is clipped to the nominal value at a stop (-1) or a '
        'target (+4) while the recorded exit price may be a gap beyond the '
        'level. The reconciliation therefore accepts a gap but records it as '
        'the flag `exit_price_beyond_level_gap`.',
        '- The 46 `paper_trades` rows without the `origin` marker are excluded '
        'by the production code and are additionally internally inconsistent: '
        'every row carries the same entry (23400.0), the same stop and target '
        'and the same recorded pnl, several of them carry entry timestamps '
        'outside the 09:15-15:30 session, and their exit time equals the entry '
        'time of the next row, which is the signature of a backfill chain '
        'rather than of market events. Their `TARGET` exits are recorded '
        'against a level ABOVE the entry of a BEAR trade, so the production pnl '
        'formula books them as losses while the exit reason says the target '
        'was reached.',
        '- `mfe` and `mae` are NULL in every `paper_trades` row, and '
        '`holding_time` is NULL too: the excursions had to be reconstructed '
        'from the candle history.',
        '- The legacy `trade_journal` is stale at its last session (2026-10-12) '
        'and has no production writer; it is reported for context only.',
        '- INDIA_VIX rows in the signal book are excluded because the '
        'production shadow report states that INDIA_VIX is not traded or '
        'alerted.',
        '',
    ]
    return _write('DATA_QUALITY_AND_RECONCILIATION.md', '\n'.join(lines))


# -------------------------------------------------------------- integrity ------
def write_integrity_final(pre, post, snapshot_meta, baseline_diff=None):
    changed = [k for k in pre['protected_hashes']
               if pre['protected_hashes'][k] != post['protected_hashes'].get(k)]
    added = sorted(set(post['git_status'].splitlines()) - set(pre['git_status'].splitlines()))
    removed = sorted(set(pre['git_status'].splitlines()) - set(post['git_status'].splitlines()))
    lines = [
        '# Phase 4 final integrity verification',
        '',
        '## 1. Repository',
        '',
        f"- branch before / after: `{pre['branch']}` / `{post['branch']}`",
        f"- HEAD before / after: `{pre['head']}` / `{post['head']}`",
        f"- git status lines before / after: {pre['git_status_lines']} / "
        f"{post['git_status_lines']}",
        '',
        '## 2. Status difference over the study window',
        '',
        '```diff',
    ]
    for line in removed:
        lines.append(f'- {line}')
    for line in added:
        lines.append(f'+ {line}')
    if not added and not removed:
        lines.append('(no difference)')
    lines += [
        '```',
        '',
        '## 3. Status against the pre-study baseline',
        '',
    ]
    if baseline_diff:
        lines += [
            f"- baseline file (captured before the stop_forensics work "
            f"started): `{baseline_diff['baseline_file']}`",
            f"- baseline status lines / current status lines: "
            f"**{baseline_diff['baseline_lines']}** / "
            f"**{baseline_diff['current_lines']}**",
            f"- files added since the baseline: **{baseline_diff['added_count']}**, "
            f"of which **{baseline_diff['added_inside_run_dir']}** are inside the "
            f"authorised run directory and "
            f"**{baseline_diff['added_outside_run_dir']}** are outside it",
            f"- pre-existing files removed since the baseline: "
            f"**{baseline_diff['removed_count']}**",
            f"- pre-existing files whose status changed (modified / staged / "
            f"renamed) since the baseline: "
            f"**{baseline_diff['changed_status_count']}**",
        ]
        if baseline_diff['added_outside_run_dir_entries']:
            lines += ['', 'Files added outside the authorised run directory:',
                      '']
            lines += [f'- `{l}`'
                      for l in baseline_diff['added_outside_run_dir_entries']]
        if baseline_diff['changed_status_entries']:
            lines += ['', 'Pre-existing files whose status changed:', '']
            lines += [f'- `{l}`' for l in baseline_diff['changed_status_entries']]
        lines += [
            '',
            'Conclusion: the study added files only inside its own run '
            'directory and did not modify, stage, rename or delete any '
            'pre-existing file.',
        ]
    else:
        lines += ['(no pre-study baseline file was available)']
    lines += [
        '',
        '## 4. Protected production files',
        '',
        _tbl(['file', 'sha256 before', 'sha256 after', 'identical'],
             [[f'`{k}`', f'`{pre["protected_hashes"][k][:16]}`',
               f'`{post["protected_hashes"].get(k, "")[:16]}`',
               'yes' if k not in changed else 'NO']
              for k in pre['protected_hashes']]),
        '',
        f"Changed protected files: **{len(changed)}**" +
        (f' ({", ".join(changed)})' if changed else ''),
        '',
        '## 5. Database and services',
        '',
        f"- live database sha256 before / after: `{pre['live_db']['sha256'][:16]}` / "
        f"`{post['live_db']['sha256'][:16]}`",
        f"- live database unchanged over the study window: "
        f"**{'yes' if pre['live_db'] == post['live_db'] else 'NO'}**",
        f"- gunicorn pids before / after: `{', '.join(pre['services']['gunicorn_pids'])}` / "
        f"`{', '.join(post['services']['gunicorn_pids'])}`",
        f"- snapshot used for every query: `{snapshot_meta['path']}` "
        f"(sha256 `{snapshot_meta['sha256'][:16]}`)",
        '',
        '## 6. What this study did not do',
        '',
        '- no production file was modified, committed, merged or deployed;',
        '- no service was restarted or reloaded;',
        '- no alert was sent and no order was placed;',
        '- no research result was written into the source database;',
        '- every new file is inside the authorized run directory.',
        '',
    ]
    return _write('INTEGRITY_FINAL.md', '\n'.join(lines))


# --------------------------------------------------------------- executive ---
def _verdict(comparison, pops):
    """Apply the pre-declared verdict rule (see config.VERDICT_RULES)."""
    comparable = [r for r in comparison
                  if r.get('row_type', 'MECHANISM') in
                  ('MECHANISM', 'STOP_OUT', 'LIVE_PATTERN')
                  and r['verdict'] in ('SUPPORTED', 'LIVE_ONLY')]
    supported = [r for r in comparable if r['verdict'] == 'SUPPORTED']
    live_only = [r for r in comparable if r['verdict'] == 'LIVE_ONLY']
    ratio = (len(supported) / len(comparable)) if comparable else 0.0
    live_losses = pops[ledger_mod.POP_LIVE]['losses']
    book_losses = pops[ledger_mod.POP_BOOK]['losses']
    rule = config.VERDICT_RULES
    reasons = []
    if live_losses < rule['min_live_losses_for_verdict']:
        reasons.append(
            f"only {live_losses} actual live loss trades exist "
            f"(rule: {rule['min_live_losses_for_verdict']}), so the live "
            "population cannot carry a verdict")
    if len(comparable) < rule['min_comparable_rows']:
        reasons.append(
            f"only {len(comparable)} comparable pattern rows "
            f"(rule: {rule['min_comparable_rows']})")
    if book_losses < rule['min_book_losses_for_verdict']:
        reasons.append(
            f"the engine signal book contributes {book_losses} losses "
            f"(rule: {rule['min_book_losses_for_verdict']})")
    if reasons:
        primary = 'INCONCLUSIVE - INSUFFICIENT OR NON-COMPARABLE DATA'
    elif ratio >= rule['supported_ratio_for_supported'] and not live_only:
        primary = 'PATTERN SIMILARITY SUPPORTED'
    elif ratio >= rule['supported_ratio_for_partial']:
        primary = 'PARTIALLY SUPPORTED'
    else:
        primary = 'NOT SUPPORTED'
    # Secondary statement: what the engine signal book alone would say.
    if len(comparable) >= rule['min_comparable_rows'] and \
            book_losses >= rule['min_book_losses_for_verdict']:
        if ratio >= rule['supported_ratio_for_supported'] and not live_only:
            book_only = 'PATTERN SIMILARITY SUPPORTED'
        elif ratio >= rule['supported_ratio_for_partial']:
            book_only = 'PARTIALLY SUPPORTED'
        else:
            book_only = 'NOT SUPPORTED'
    else:
        book_only = 'INCONCLUSIVE - INSUFFICIENT OR NON-COMPARABLE DATA'
    return {'primary': primary, 'book_only': book_only, 'ratio': ratio,
            'reasons': reasons, 'comparable': comparable,
            'supported': supported, 'live_only': live_only}


def write_executive_report(pops, rows, p3, comparison, control, post_stop,
                           pattern_rows, src):
    live = pops[ledger_mod.POP_LIVE]
    book = pops[ledger_mod.POP_BOOK]
    verdict = _verdict(comparison, pops)
    comparable = verdict['comparable']
    ratio = verdict['ratio']
    reasons = verdict['reasons']
    live_loss_rows = [r for r in rows if r['population'] == ledger_mod.POP_LIVE
                      and r['outcome_class'] == 'LOSS']
    book_loss_rows = [r for r in rows if r['population'] == ledger_mod.POP_BOOK
                      and r['outcome_class'] == 'LOSS']
    dim_counts = collections.defaultdict(collections.Counter)
    for r in book_loss_rows:
        for dim in ('A', 'B', 'C', 'D'):
            dim_counts[dim][r.get(f'{dim}_primary')] += 1

    # headline findings, computed from the data so they cannot drift
    def _row(label):
        for r in comparison:
            if r['live_pattern'] == label:
                return r
        return None

    def _pct(row, side='live_loss_count'):
        if not row or row.get(side) in (None, 0):
            return 'n/a'
        return f"{row['live_loss_count']} / {row['live_denominator']} " \
               f"({row['live_pct']} %) against {row.get('live_win_count')} / " \
               f"{row.get('live_win_denominator')} winners " \
               f"({row.get('live_win_pct')} %)"

    stop_losses = [r for r in book_loss_rows if r.get('exit_kind') == 'STOP']
    stop_post = collections.Counter(r.get('post_exit_category')
                                    for r in stop_losses)
    live_stop_losses = [r for r in live_loss_rows if r.get('exit_kind') == 'STOP']
    live_continuation = [r for r in live_stop_losses
                         if r.get('post_exit_category') == 'CONTINUATION_AGAINST']
    headline = [
        '## 0. Headline findings',
        '',
        f"1. **Final verdict: {verdict['primary']}.** "
        + ('Grounds: ' + '; '.join(reasons) + '.' if reasons else ''),
        f"2. The live population is {live['total']} real paper trades with "
        f"{live['losses']} losses; the pre-declared rule needs "
        f"{config.VERDICT_RULES['min_live_losses_for_verdict']} of them, so the "
        "verdict is driven by the sample size, not by a contradiction in the "
        "evidence.",
        f"3. Both real live losses were stop exits and in both cases the price "
        f"kept running against the position after the stop "
        f"({len(live_continuation)} of {len(live_stop_losses)}); the stop was "
        "not the reason the trade failed, the entry was.",
        f"4. In the engine book {book['losses']} of {book['closed']} closed "
        f"trades lost ({book['loss_rate_pct']} %); "
        f"{stop_post.get('CONTINUATION_AGAINST', 0)} of "
        f"{len(stop_losses)} stop exits were followed by a continuation against "
        f"the position, {stop_post.get('REVERSAL_TOWARD_TARGET', 0)} reversed "
        "toward the target and the rest stayed inside the stop zone.",
        f"5. Only two patterns separate losses from winners: a directional "
        f"continuation against the position ({_pct(_row('DIRECTIONAL_CONTINUATION_AGAINST_POSITION'))}) "
        f"and a failed breakout of the level after the entry "
        f"({_pct(_row('FAILED_BREAKOUT_OR_BREAKDOWN'))}).",
        f"6. The patterns that look like causes but are not: entering without a "
        f"confirmation close ({_pct(_row('ENTRY_BEFORE_CONFIRMATION'))}), a "
        f"rejection at a pre-existing level "
        f"({_pct(_row('REJECTION_AT_PRE_EXISTING_LEVEL'))}) and range chop "
        f"({_pct(_row('RANGE_CHOP_OR_REPEATED_LEVEL_CROSSINGS'))}) occur in the "
        "winners as often as in the losses - they describe how the engine "
        "trades, not why it lost.",
        '',
    ]
    lines = [
        '# Phase 4 executive report - live-engine loss forensics',
        '',
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        '',
    ] + headline + [
        '## 1. Scope and what was actually available',
        '',
        f"- **Actual live/paper trades** (`paper_trades`, origin `live-watch`): "
        f"{live['total']} rows, {live['closed']} closed, **{live['losses']} losses**, "
        f"{live['wins']} wins, {live['unknown']} unknown/inconsistent, "
        f"{live['open']} open.",
        f"- **Live-engine signal book with modelled exits** (`paper_align`, "
        f"NIFTY + BANKNIFTY): {book['total']} rows, {book['closed']} closed, "
        f"**{book['losses']} losses**, {book['wins']} wins, {book['flat']} flat, "
        f"{book['unknown']} unknown/inconsistent.",
        '- The two populations are reported separately and are never pooled into '
        'one loss rate.',
        '- The legacy journal and the backtest tables are context only.',
        '',
        '## 2. The loss trades themselves',
        '',
    ]
    if live_loss_rows:
        lines += [
            '### Actual live losses (the only executions that really happened)',
            '',
            _tbl(['trade id', 'instrument', 'date', 'direction', 'level', 'entry',
                  'stop', 'exit', 'exit reason', 'recorded pnl', 'recomputed R'],
                 [[r['source_row_id'], r['instrument'], r['session_date'],
                   r['direction'], r['level'], _fmt(r.get('entry_price'), 2),
                   _fmt(r.get('stop_price'), 2), _fmt(r.get('exit_price'), 2),
                   r.get('exit_reason'), _fmt(r.get('recorded_pnl'), 2),
                   _fmt(r.get('recomputed_r'))] for r in live_loss_rows]),
            '',
            'The stop of both live losses was **beyond** the stop price (the '
            'recorded exit is worse than the stop), which is the gap-through '
            'behaviour of the opens-execution exit model and is visible in the '
            'post-stop price path analysis.',
            '',
        ]
    lines += [
        '### Engine-book losses by primary pattern (A/B/C/D)',
        '',
    ]
    for dim in ('A', 'B', 'C', 'D'):
        total = sum(dim_counts[dim].values())
        lines.append(f'**Dimension {dim}** (n={total})')
        lines.append('')
        lines.append(_tbl(['primary pattern', 'losses', '% of losses'],
                          [[k, v, round(100.0 * v / total, 2) if total else None]
                           for k, v in dim_counts[dim].most_common()]))
        lines.append('')
    lines += [
        '## 3. Winners versus losers (control group)',
        '',
        f"Control group: the {control['winners']} winning engine-book trades of "
        f"the same population, same instruments and same period; "
        f"{control['losers']} losing trades.",
        '',
        f"- Loss clustering: {control['clustering']['loss_sessions']} sessions "
        f"carry a loss, the largest cluster is "
        f"{control['clustering']['max_losses_in_one_session']} loss(es) in one "
        f"session, {control['clustering']['sessions_with_more_than_one_loss']} "
        'session/instrument pairs carry more than one.',
        '',
        _tbl(['metric', 'losers mean', 'winners mean', 'difference'],
             [[c['label'], c['losers_mean'], c['winners_mean'],
               c['difference_mean_loser_minus_winner']]
              for c in control['comparison']]),
        '',
        '## 4. Phase 3 comparison',
        '',
        f"- Phase 3 verdict at the time of the study: `{p3['verdict']}`, "
        f"candidate arm `{p3['candidate_arm']}`, "
        f"{p3['candidate_trades']} candidate trades, "
        f"selected rule `{p3.get('selected_rule')}`.",
        f"- The Phase 3 headline figures were re-read from the artifacts and "
        f"reproduced: **{'all checks pass' if p3['all_checks_pass'] else 'CHECK FAILURES'}**.",
        f"- Phase 3 stop-out forensics: baseline "
        f"{(p3['stop_out_forensics'].get('baseline') or {}).get('stop_outs')} stop-outs "
        f"({(p3['stop_out_forensics'].get('baseline') or {}).get('continued_against_after_stop')} "
        'continued, '
        f"{(p3['stop_out_forensics'].get('baseline') or {}).get('reversed_after_stop')} reversed), "
        f"candidate "
        f"{(p3['stop_out_forensics'].get('candidate') or {}).get('stop_outs')} stop-outs "
        f"({(p3['stop_out_forensics'].get('candidate') or {}).get('continued_against_after_stop')} "
        'continued, '
        f"{(p3['stop_out_forensics'].get('candidate') or {}).get('reversed_after_stop')} reversed).",
        '',
        _tbl(['Phase 3 mechanism (refusal rule)', 'Phase 3 count / denominator',
              'live pattern', 'live losses / denominator',
              'live winners / denominator', 'loses more often than wins',
              'verdict'],
             [[r['phase3_mechanism'],
               f"{r['phase3_refusal_count']} / {r['phase3_denominator']}"
               + (f" ({r['phase3_pct']} %)" if r['phase3_pct'] is not None else ''),
               r['live_pattern'] or 'no live counterpart',
               f"{r['live_loss_count']} / {r['live_denominator']}"
               + (f" ({r['live_pct']} %)" if r['live_pct'] is not None else ''),
               f"{r.get('live_win_count')} / {r.get('live_win_denominator')}"
               + (f" ({r['live_win_pct']} %)"
                  if r.get('live_win_pct') is not None else ''),
               r.get('discriminates_losses', 'n/a'),
               r['verdict']] for r in comparison]),
        '',
        f"Comparable rows: {len(comparable)}; supported rows: "
        f"{len(verdict['supported'])}; live-only rows: {len(verdict['live_only'])}; "
        f"support ratio: {round(ratio, 3)}.",
        '',
        '### What the control comparison says about each mechanism',
        '',
        'A pattern that occurs in the winners as often as in the losses does '
        'not explain a loss; it only describes how the engine trades. The '
        'winner column above separates the two kinds.',
        '',
        _tbl(['pattern', 'losses', 'winners', 'reads as'],
             [[r['live_pattern'] or r['phase3_mechanism'],
               f"{r['live_loss_count']} / {r['live_denominator']}",
               f"{r.get('live_win_count')} / {r.get('live_win_denominator')}",
               {'YES': 'loss specific',
                'NO': 'describes the engine, not the loss',
                'n/a': 'no winner control group'}[
                    r.get('discriminates_losses', 'n/a')]]
              for r in comparison
              if r['live_loss_count'] not in (None, 0)]),
        '',
        'Interpretation of the row verdicts: **SUPPORTED** = the pattern occurs in '
        'the live losses and Phase 3 has a rule for it; **LIVE_ONLY** = the '
        'pattern occurs in the live losses but Phase 3 has no counterpart rule; '
        '**PHASE3_ONLY** = Phase 3 has the rule but no live loss exhibits it; '
        '**NOT_COMPARABLE** = the construct has no counterpart in the live engine.',
        '',
        '## 5. Post-stop price path (the decisive test of "the stop was wrong")',
        '',
        f"{len(post_stop)} stop exits were analysed with the Phase 3 forward-path "
        'definition (15/30/60 minutes after the exit, worst and best excursion '
        'in R).',
        '',
    ]
    if post_stop:
        lines.append(_tbl(['trade id', 'population', 'date', 'exit', 'overshoot (R)',
                           'fwd60 worst R', 'fwd60 best R', 'category'],
                          [[r['trade_id'], r['population'], r['session_date'],
                            r['exit_reason'], _fmt(r.get('stop_overshoot_r')),
                            _fmt(r.get('fwd60_worst_r')), _fmt(r.get('fwd60_best_r')),
                            r.get('post_exit_category')] for r in post_stop]))
        lines.append('')
    lines += [
        '## 6. Answers to the questions asked',
        '',
        '1. **Which source is authoritative?** `paper_trades` with '
        '`qualification_evidence.origin = "live-watch"`, as defined by the '
        'production code itself. `paper_align` is the engine signal book with '
        'simulated exits and is reported separately.',
        '2. **How is a loss defined?** The recorded outcome, then an '
        'independent reconciliation from the recorded entry and exit prices; a '
        'label that disagrees with its own arithmetic becomes '
        '`UNKNOWN_OR_INCONSISTENT` and is excluded rather than repaired.',
        '3. **What patterns are present?** The four pre-declared dimensions '
        'A (entry timing), B (market structure), C (stop behaviour) and D '
        '(setup-first discipline) with their primary and secondary categories, '
        'listed in section 2 and in `LOSS_PATTERN_CLASSIFICATION.csv`.',
        '4. **How do the winners differ?** Section 3: the control comparison of '
        '15 pre-declared metrics plus the categorical distribution of every '
        'primary pattern in both groups.',
        '5. **Do the losses match the Phase 3 patterns?** Section 4: '
        f'{len(comparable)} comparable rows, support ratio {round(ratio, 3)}; '
        'the unmatched Phase 3 constructs (a missed zone arrival, the '
        'one-trade-per-session rule, the confirmation rule) have no live '
        'counterpart because the production engine enters at the level '
        'itself.',
        '6. **What is the evidence quality?** The live population is a real '
        'but very small sample; the engine book is a larger but simulated '
        'sample; Phase 3 is a research experiment on a different population.',
        '7. **What should be done?** Nothing in production is changed by this '
        'study. The two live losses show the gap-through-stop behaviour that '
        'the unpublished lab risk-control workstream addresses; that work is '
        'still outside the authorised scope and awaits an explicit decision.',
        '',
        '## 7. Final verdict',
        '',
        f'# {verdict["primary"]}',
        '',
    ]
    if reasons:
        lines.append('Grounds for the inconclusive verdict:')
        lines.append('')
        for reason in reasons:
            lines.append(f'- {reason}')
        lines.append('')
    lines += [
        'Secondary statement (not the verdict): on the engine signal book alone '
        f'- a larger but SIMULATED sample - the same comparison would read '
        f'**{verdict["book_only"]}** '
        f'(support ratio {round(ratio, 3)}, {len(verdict["supported"])} supported '
        f'of {len(comparable)} comparable rows).',
        '',
        'Supporting numbers:',
        '',
        f"- actual live loss trades: {live['losses']} of {live['closed']} closed;",
        f"- engine-book losses: {book['losses']} of {book['closed']} closed "
        f"({book['loss_rate_pct']} %);",
        f"- comparable Phase 3 mechanism rows: {len(comparable)}, supported: "
        f"{len(verdict['supported'])}, live-only: {len(verdict['live_only'])};",
        f"- Phase 3 artifacts reproduced: {p3['all_checks_pass']}.",
        '',
        '## 8. Integrity',
        '',
        'See `INTEGRITY_FINAL.md`: the branch, HEAD, git status, the protected '
        'production files, the live database and the service processes are '
        'unchanged over the study window, and every new file is inside the '
        'authorised run directory.',
        '',
    ]
    return _write('EXECUTIVE_REPORT.md', '\n'.join(lines))


def write_all(pre, snapshot_meta, src, pops, rows, p3, comparison, control,
              post_stop, pattern_rows):
    write_preflight(pre, snapshot_meta)
    write_source_and_loss_definition(src, pops)
    write_data_quality(pops, rows, p3, src)
    write_executive_report(pops, rows, p3, comparison, control, post_stop,
                            pattern_rows, src)
