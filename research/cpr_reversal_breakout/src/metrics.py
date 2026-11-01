"""Performance metrics, uncertainty estimates and comparison tables.

All metrics are computed from normalised trade rows (baseline + candidate),
so both sides use the same denominators, the same cost model and the same
win/loss definition (production `decay_win`).

Uncertainty: win-rate intervals are Wilson score intervals; expectancy uses a
moving-block bootstrap (block = 5 consecutive sessions) so serial dependence
between consecutive days is preserved. No random shuffling of time series.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict, OrderedDict

WIN_ORDER = ('WIN', 'LOSS', 'FLAT')


def _sum(vals):
    return round(sum(vals), 4) if vals else 0.0


def wilson_ci(wins, n, z=1.96):
    if not n:
        return (None, None)
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def max_drawdown(series):
    """Peak-to-trough on a cumulative series -> (dd, peak_idx, trough_idx,
    recovery_idx|None, duration_points)."""
    if not series:
        return 0.0, None, None, None, 0
    peak = series[0]
    peak_i = 0
    dd = 0.0
    trough_i = 0
    dd_peak_i = 0
    for i, v in enumerate(series):
        if v > peak:
            peak, peak_i = v, i
        elif peak - v > dd:
            dd, trough_i, dd_peak_i = peak - v, i, peak_i
    rec_i = None
    if dd > 0:
        for i in range(trough_i + 1, len(series)):
            if series[i] >= series[dd_peak_i] + dd - 1e-9:
                rec_i = i
                break
    dur = (rec_i - dd_peak_i) if rec_i is not None else (len(series) - 1 - dd_peak_i)
    return round(dd, 2), dd_peak_i, trough_i, rec_i, int(dur)


def max_consecutive(trades, key):
    worst = cur = 0
    for t in trades:
        if key(t):
            cur += 1
            worst = max(worst, cur)
        else:
            cur = 0
    return worst


def block_bootstrap_expectancy(daily_pnl, n_boot=4000, block=5, seed=12345):
    """Moving-block bootstrap of mean DAILY pnl (₹). Returns (mean, lo, hi).

    Blocks of `block` consecutive days are sampled with replacement and
    concatenated, preserving within-block serial dependence.
    """
    x = [v for v in daily_pnl if v is not None]
    if len(x) < 2:
        return (round(sum(x), 2), None, None) if x else (0.0, None, None)
    rnd = random.Random(seed)
    n = len(x)
    starts = list(range(0, max(1, n - block + 1)))
    means = []
    for _ in range(n_boot):
        samp = []
        while len(samp) < n:
            s = rnd.choice(starts)
            samp.extend(x[s:s + block])
        means.append(sum(samp[:n]) / n)
    means.sort()
    return (round(sum(x) / n, 2),
            round(means[int(0.025 * (n_boot - 1))], 2),
            round(means[int(0.975 * (n_boot - 1))], 2))


def compute(trades, sessions=None, capital_base=None, cost_r_grid=None):
    """Full metric set for one strategy/variant over its trade rows."""
    trades = sorted(trades, key=lambda t: (t['session_date'],
                                           t.get('entry_time') or ''))
    n = len(trades)
    wins = [t for t in trades if t['win_loss'] == 'WIN']
    losses = [t for t in trades if t['win_loss'] == 'LOSS']
    flat = [t for t in trades if t['win_loss'] == 'FLAT']
    r = [float(t['r_multiple']) for t in trades]
    gross = [float(t['pnl_gross_rs']) for t in trades]
    net = [float(t['pnl_net_rs']) for t in trades]

    gross_profit = sum(v for v in net if v > 0)
    gross_loss = -sum(v for v in net if v < 0)
    cum, run = [], 0.0
    for v in net:
        run += v
        cum.append(round(run, 2))
    dd, dd_peak, dd_trough, dd_rec, dd_dur = max_drawdown(cum)
    # drawdown duration in sessions (days) rather than trades
    dd_days = None
    if dd_peak is not None and dd_trough is not None:
        d0 = trades[dd_peak]['session_date']
        d1 = trades[dd_trough]['session_date']
        dd_days = _session_span(d0, d1, trades)
    rec_days = None
    if dd > 0 and dd_rec is not None:
        rec_days = _session_span(trades[dd_peak]['session_date'],
                                 trades[dd_rec]['session_date'], trades)

    daily = OrderedDict()
    for t in trades:
        k = (t['session_date'], t['instrument'])
        daily.setdefault(k, {'trades': 0, 'gross': 0.0, 'net': 0.0, 'r': 0.0})
        daily[k]['trades'] += 1
        daily[k]['gross'] += float(t['pnl_gross_rs'])
        daily[k]['net'] += float(t['pnl_net_rs'])
        daily[k]['r'] += float(t['r_multiple'])
    daily_net = [round(v['net'], 2) for v in daily.values()]
    boot = block_bootstrap_expectancy(daily_net)

    cost_grid = {}
    for cr in (cost_r_grid or [0.0, 0.10, 0.20, 0.30]):
        cost_grid[f'{cr:.2f}R'] = round(sum(r) - cr * n, 2)

    out = {
        'total_trades': n,
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'breakeven_trades': len(flat),
        'win_rate': round(len(wins) / n, 4) if n else None,
        'win_rate_ci95': wilson_ci(len(wins), n),
        'gross_pnl_rs': round(sum(gross), 2),
        'net_pnl_rs': round(sum(net), 2),
        'total_R': round(sum(r), 3),
        'net_R_at_0.10R_cost': round(sum(r) - 0.10 * n, 3),
        'avg_net_per_trade_rs': round(sum(net) / n, 2) if n else None,
        'median_net_per_trade_rs': round(sorted(net)[n // 2], 2) if n else None,
        'avg_winner_rs': round(sum(v for v in net if v > 0) /
                               len([v for v in net if v > 0]), 2)
                              if any(v > 0 for v in net) else None,
        'avg_loser_rs': round(sum(v for v in net if v < 0) /
                              len([v for v in net if v < 0]), 2)
                             if any(v < 0 for v in net) else None,
        'avg_R_per_trade': round(sum(r) / n, 4) if n else None,
        'profit_factor': round(gross_profit / gross_loss, 3)
                         if gross_loss > 0 else None,
        'max_drawdown_rs': dd,
        'max_drawdown_sessions': dd_days,
        'max_drawdown_recovery_sessions': rec_days,
        'max_drawdown_R': round(max_drawdown([sum(r[:i + 1])
                                              for i in range(n)])[0], 3),
        'largest_win_rs': round(max(net), 2) if net else None,
        'largest_loss_rs': round(min(net), 2) if net else None,
        'largest_win_R': round(max(r), 3) if r else None,
        'largest_loss_R': round(min(r), 3) if r else None,
        'max_consecutive_losses': max_consecutive(trades,
                                                  lambda t: t['win_loss'] == 'LOSS'),
        'max_consecutive_wins': max_consecutive(trades,
                                                lambda t: t['win_loss'] == 'WIN'),
        'sessions_traded': len(daily),
        'sessions_with_position_pct': round(len(daily) / sessions, 4)
                                      if sessions else None,
        'avg_holding_minutes': round(sum(t['holding_minutes'] for t in trades
                                         if t.get('holding_minutes')) /
                                     max(1, len([t for t in trades
                                                 if t.get('holding_minutes')])), 1),
        'capital_base_rs': capital_base,
        'return_on_capital_pct': round(100 * sum(net) / capital_base, 3)
                                 if capital_base else None,
        'expectancy_daily_rs': boot[0],
        'expectancy_daily_ci95': [boot[1], boot[2]],
        'cost_sensitivity_net_R': cost_grid,
        'exit_reasons': _counts(t['exit_reason'] for t in trades),
        'by_direction': _split(trades, lambda t: t['direction']),
        'by_signal_kind': _split(trades, lambda t: t['signal_kind']),
        'by_family': _split(trades, lambda t: t['family']),
        'by_instrument': _split(trades, lambda t: t['instrument']),
        'by_weekday': _split(trades, lambda t: _weekday(t['session_date'])),
        'by_month': _split(trades, lambda t: t['session_date'][:7]),
        'by_period': _split(trades, lambda t: t.get('period') or '?'),
        'friday_trades': sum(1 for t in trades if t.get('friday')),
        'friday_net_rs': round(sum(float(t['pnl_net_rs']) for t in trades
                                   if t.get('friday')), 2),
        'daily_pnl': [{'date': k[0], 'instrument': k[1],
                       'trades': v['trades'], 'gross_rs': round(v['gross'], 2),
                       'net_rs': round(v['net'], 2),
                       'r': round(v['r'], 3)}
                      for k, v in daily.items()],
        'daily_net_series': daily_net,
    }
    out['reversal_trades'] = out['by_signal_kind'].get('REVERSAL', {}).get('n', 0)
    out['breakout_trades'] = out['by_signal_kind'].get('BREAKOUT', {}).get('n', 0)
    out['failed_reversal_rate'] = _fail_rate(trades, 'REVERSAL')
    out['false_breakout_rate'] = _fail_rate(trades, 'BREAKOUT')
    return out


def _fail_rate(trades, kind):
    sub = [t for t in trades if t['signal_kind'] == kind]
    if not sub:
        return None
    bad = [t for t in sub if t['win_loss'] == 'LOSS']
    return round(len(bad) / len(sub), 4)


def _counts(iterable):
    d = defaultdict(int)
    for v in iterable:
        d[str(v)] += 1
    return dict(sorted(d.items(), key=lambda kv: -kv[1]))


def _split(trades, key):
    g = defaultdict(list)
    for t in trades:
        g[key(t)].append(t)
    out = {}
    for k, v in g.items():
        net = [float(x['pnl_net_rs']) for x in v]
        r = [float(x['r_multiple']) for x in v]
        w = sum(1 for x in v if x['win_loss'] == 'WIN')
        out[str(k)] = {'n': len(v), 'wins': w,
                       'win_rate': round(w / len(v), 4),
                       'net_rs': round(sum(net), 2),
                       'total_R': round(sum(r), 3),
                       'avg_R': round(sum(r) / len(r), 4)}
    return dict(sorted(out.items()))


def _weekday(day_iso):
    from datetime import datetime
    try:
        return datetime.fromisoformat(day_iso).strftime('%a')
    except (TypeError, ValueError):
        return '?'


def _session_span(d0, d1, trades):
    days = sorted({t['session_date'] for t in trades})
    if d0 in days and d1 in days:
        return days.index(d1) - days.index(d0)
    return None


def compare(baseline, candidate):
    """Side-by-side deltas (absolute + percentage) on identical denominators."""
    out = {}
    keys = ['total_trades', 'win_rate', 'net_pnl_rs', 'total_R',
            'avg_net_per_trade_rs', 'avg_R_per_trade', 'profit_factor',
            'max_drawdown_rs', 'max_drawdown_R', 'largest_loss_rs',
            'max_consecutive_losses', 'return_on_capital_pct',
            'expectancy_daily_rs', 'sessions_traded',
            'friday_trades', 'reversal_trades', 'breakout_trades']
    for k in keys:
        b, c = baseline.get(k), candidate.get(k)
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            absd = round(c - b, 4)
            pct = round(100.0 * (c - b) / b, 2) if b else None
            out[k] = {'baseline': b, 'candidate': c, 'diff': absd,
                      'pct_diff': pct}
        else:
            out[k] = {'baseline': b, 'candidate': c, 'diff': None,
                      'pct_diff': None}
    return out
