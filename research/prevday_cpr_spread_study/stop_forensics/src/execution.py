"""Execution model used by every arm (baseline and candidates).

Mirrors `app.research.cpr_trigger_engine.exits_opens` (subsequent 5-minute OPENS
only, stop checked before target) plus the 15:20 flat, and adds the accounting the
approved audit requires: the **realized** R of the modelled fill instead of the
booked -1R / +4R label.

The modelled fill is a next-bar open model. It is never presented as a guaranteed
executable market fill.
"""
from __future__ import annotations

OPEN_EOD = '15:20'
SCAN_CUTOFF = '15:25'


def stop_target(direction: str, entry: float, stop_pct: float, target_pct: float):
    """Intended stop and target prices for a direction (production arithmetic)."""
    if direction == 'BULL':
        return entry * (1 - stop_pct), entry * (1 + target_pct)
    return entry * (1 + stop_pct), entry * (1 - target_pct)


def _signed(direction: str, entry: float, price: float) -> float:
    """Points in favour of the position."""
    return (price - entry) if direction == 'BULL' else (entry - price)


def simulate_exit(direction: str, entry: float, candles: list, entry_idx: int,
                  stop_pct: float = 0.005, target_pct: float = 0.02) -> dict:
    """Walk the candles after `entry_idx` and return the modelled exit.

    Returns None when the session has no 15:20 candle (production `missing_eod`).
    """
    stop_px, tgt_px = stop_target(direction, entry, stop_pct, target_pct)
    risk = abs(entry - stop_px)
    if not risk:
        return None
    for c in candles[entry_idx + 1:]:
        try:
            o = float(c['open'])
        except (TypeError, ValueError):
            continue
        if direction == 'BULL':
            hit_stop, hit_target = o <= stop_px, o >= tgt_px
        else:
            hit_stop, hit_target = o >= stop_px, o <= tgt_px
        if hit_stop:
            return {
                'exit_reason': 'STOP', 'exit_price': round(o, 2),
                'exit_ts': c['timestamp'], 'stop_price': round(stop_px, 4),
                'target_price': round(tgt_px, 4), 'risk_pts': risk,
                'booked_r': -1.0,
                'realized_r': round(_signed(direction, entry, o) / risk, 4),
                'stop_overshoot_pts': round(abs(o - stop_px), 4),
                'stop_overshoot_r': round(abs(o - stop_px) / risk, 4),
                'target_truncation_pts': 0.0, 'target_truncation_r': 0.0,
            }
        if hit_target:
            return {
                'exit_reason': 'TARGET', 'exit_price': round(o, 2),
                'exit_ts': c['timestamp'], 'stop_price': round(stop_px, 4),
                'target_price': round(tgt_px, 4), 'risk_pts': risk,
                'booked_r': round(target_pct / stop_pct, 3),
                'realized_r': round(_signed(direction, entry, o) / risk, 4),
                'stop_overshoot_pts': 0.0, 'stop_overshoot_r': 0.0,
                'target_truncation_pts': round(abs(o - tgt_px), 4),
                'target_truncation_r': round(abs(o - tgt_px) / risk, 4),
            }
    eod = [c for c in candles if str(c['timestamp'])[11:16] == OPEN_EOD]
    if not eod:
        return None
    last = float(eod[0]['open'])
    return {
        'exit_reason': 'EOD-1520', 'exit_price': round(last, 2),
        'exit_ts': eod[0]['timestamp'], 'stop_price': round(stop_px, 4),
        'target_price': round(tgt_px, 4), 'risk_pts': risk,
        'booked_r': round(_signed(direction, entry, last) / risk, 4),
        'realized_r': round(_signed(direction, entry, last) / risk, 4),
        'stop_overshoot_pts': 0.0, 'stop_overshoot_r': 0.0,
        'target_truncation_pts': 0.0, 'target_truncation_r': 0.0,
    }


def intrabar_bounds(direction: str, entry: float, candles: list, entry_idx: int,
                    exit_ts: str | None, stop_pct: float = 0.005,
                    target_pct: float = 0.02) -> dict:
    """Conservative bounds when a single candle touches both stop and target.

    Inside a 5-minute bar the order of the stop and the target is unknowable, so the
    study reports a lower bound (stop first) and an upper bound (target first)
    instead of inventing an execution order.
    """
    stop_px, tgt_px = stop_target(direction, entry, stop_pct, target_pct)
    ambiguous = 0
    for c in candles[entry_idx + 1:]:
        if exit_ts and str(c['timestamp'])[:16] >= str(exit_ts)[:16]:
            break
        hi, lo = float(c['high']), float(c['low'])
        if direction == 'BULL':
            both = hi >= tgt_px and lo <= stop_px
        else:
            both = hi >= stop_px and lo <= tgt_px
        if both:
            ambiguous += 1
    risk = abs(entry - stop_px)
    return {
        'intrabar_ambiguous_bars': ambiguous,
        'lower_bound_r': -1.0 if ambiguous else None,
        'upper_bound_r': round(target_pct / stop_pct, 3) if ambiguous else None,
        'risk_pts': risk,
    }


def excursion(direction: str, entry: float, candles: list, entry_idx: int,
              exit_ts: str | None) -> dict:
    """Intrabar and open-based adverse/favourable excursion over the holding window."""
    adverse = None
    favourable = None
    o_adverse = None
    o_favourable = None
    n = 0
    for c in candles[entry_idx:]:
        if exit_ts and str(c['timestamp'])[:16] > str(exit_ts)[:16]:
            break
        n += 1
        hi, lo, o = float(c['high']), float(c['low']), float(c['open'])
        if direction == 'BULL':
            a, f = lo, hi
            oa, of = min(o, lo), max(o, hi)
        else:
            a, f = hi, lo
            oa, of = max(o, hi), min(o, lo)
        adverse = a if adverse is None else (min(adverse, a) if direction == 'BULL'
                                             else max(adverse, a))
        favourable = f if favourable is None else (max(favourable, f) if direction == 'BULL'
                                                  else min(favourable, f))
        o_adverse = oa if o_adverse is None else (min(o_adverse, oa) if direction == 'BULL'
                                                 else max(o_adverse, oa))
        o_favourable = of if o_favourable is None else (max(o_favourable, of) if direction == 'BULL'
                                                        else min(o_favourable, of))
    if n == 0:
        return {'mae_hl_pts': 0.0, 'mfe_hl_pts': 0.0, 'mae_open_pts': 0.0,
                'mfe_open_pts': 0.0, 'bars_held': 0}
    mae_pts = (entry - adverse) if direction == 'BULL' else (adverse - entry)
    mfe_pts = (favourable - entry) if direction == 'BULL' else (entry - favourable)
    mae_open_pts = (entry - o_adverse) if direction == 'BULL' else (o_adverse - entry)
    mfe_open_pts = (o_favourable - entry) if direction == 'BULL' else (entry - o_favourable)
    return {'mae_hl_pts': round(mae_pts, 4), 'mfe_hl_pts': round(mfe_pts, 4),
            'mae_open_pts': round(mae_open_pts, 4), 'mfe_open_pts': round(mfe_open_pts, 4),
            'bars_held': n}


def forward_path(direction: str, exit_price: float, candles: list, exit_idx: int,
                 risk_pts: float, horizons=(15, 30, 60)) -> dict:
    """Underlying forward return after the modelled exit fill.

    `fwd_<h>_r` is the signed return from the exit fill to the close of the first
    candle at or after the horizon. A negative value means the underlying continued
    against the position (for a BEAR, a rising underlying).
    """
    out = {}
    if exit_idx is None or exit_idx >= len(candles):
        for h in horizons:
            out[f'fwd{h}_r'] = None
            out[f'fwd{h}_pts'] = None
            out[f'fwd{h}_worst_r'] = None
            out[f'fwd{h}_best_r'] = None
        return out
    base_ts = str(candles[exit_idx]['timestamp'])
    day = base_ts[:10]
    for h in horizons:
        target_min = int(base_ts[11:13]) * 60 + int(base_ts[14:16]) + h
        horizon_idx = None
        for j in range(exit_idx + 1, len(candles)):
            c = candles[j]
            if str(c['timestamp'])[:10] != day:
                break
            m = int(str(c['timestamp'])[11:13]) * 60 + int(str(c['timestamp'])[14:16])
            if m >= target_min:
                horizon_idx = j
                break
        if horizon_idx is None:
            out[f'fwd{h}_r'] = None
            out[f'fwd{h}_pts'] = None
            out[f'fwd{h}_worst_r'] = None
            out[f'fwd{h}_best_r'] = None
            continue
        close = float(candles[horizon_idx]['close'])
        pts = (close - exit_price) if direction == 'BULL' else (exit_price - close)
        worst = 0.0
        best = 0.0
        for j in range(exit_idx + 1, horizon_idx + 1):
            hi, lo = float(candles[j]['high']), float(candles[j]['low'])
            adv = (exit_price - lo) if direction == 'BULL' else (hi - exit_price)
            fav = (hi - exit_price) if direction == 'BULL' else (exit_price - lo)
            worst = max(worst, -adv)
            best = max(best, fav)
        out[f'fwd{h}_r'] = round(pts / risk_pts, 4) if risk_pts else None
        out[f'fwd{h}_pts'] = round(pts, 3)
        out[f'fwd{h}_worst_r'] = round(worst / risk_pts, 4) if risk_pts else None
        out[f'fwd{h}_best_r'] = round(best / risk_pts, 4) if risk_pts else None
    return out
