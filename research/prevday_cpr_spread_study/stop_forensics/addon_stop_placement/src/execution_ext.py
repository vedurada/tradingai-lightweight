"""Execution models with an absolute stop price.

Two models are produced for every (signal, variant):

``opens``  production-exact: walk the candles AFTER the entry bar and trigger on
           candle OPENS only (stop before target), flat at 15:20. This is the model
           the accepted baseline uses, so B0 here reproduces the parent study.

``intrabar`` conservative robustness: a gap beyond the stop or target at an open
           fills at the open (gap-through), otherwise an intrabar touch fills at the
           stop/target price, and a bar that touches both is resolved as **stop
           first** (conservative) and counted as ambiguous. Includes the entry bar,
           because the position is open from that bar's open.

Booked -1R is never assumed; the realized R of the modelled fill is reported.
"""
from __future__ import annotations

OPEN_EOD = '15:20'


def _signed(direction: str, entry: float, price: float) -> float:
    return (price - entry) if direction == 'BULL' else (entry - price)


def _fill(direction, entry, stop_px, tgt_px, risk, price, reason, ts,
          stop_overshoot_pts=0.0, target_truncation_pts=0.0, ambiguous=0):
    return {
        'exit_reason': reason, 'exit_price': round(price, 2), 'exit_ts': ts,
        'stop_price': round(stop_px, 4), 'target_price': round(tgt_px, 4),
        'risk_pts': round(risk, 4),
        'booked_r': (-1.0 if reason == 'STOP' else
                     (round(abs(tgt_px - entry) / risk, 3) if reason == 'TARGET' else
                      round(_signed(direction, entry, price) / risk, 4))),
        'realized_r': round(_signed(direction, entry, price) / risk, 4),
        'realized_pts': round(_signed(direction, entry, price), 2),
        'stop_overshoot_pts': round(stop_overshoot_pts, 4),
        'stop_overshoot_r': round(stop_overshoot_pts / risk, 4) if risk else None,
        'target_truncation_pts': round(target_truncation_pts, 4),
        'target_truncation_r': round(target_truncation_pts / risk, 4) if risk else None,
        'intrabar_ambiguous_bars': ambiguous,
    }


def simulate(direction: str, entry: float, candles: list, entry_idx: int,
             stop_px: float, tgt_px: float, model: str = 'opens') -> dict | None:
    risk = abs(entry - stop_px)
    if not risk:
        return None
    if model == 'opens':
        for c in candles[entry_idx + 1:]:
            try:
                o = float(c['open'])
            except (TypeError, ValueError):
                continue
            beyond_stop = (o <= stop_px) if direction == 'BULL' else (o >= stop_px)
            beyond_tgt = (o >= tgt_px) if direction == 'BULL' else (o <= tgt_px)
            if beyond_stop:
                return _fill(direction, entry, stop_px, tgt_px, risk, o, 'STOP',
                             c['timestamp'], stop_overshoot_pts=abs(o - stop_px))
            if beyond_tgt:
                return _fill(direction, entry, stop_px, tgt_px, risk, o, 'TARGET',
                             c['timestamp'], target_truncation_pts=abs(o - tgt_px))
        eod = [c for c in candles if str(c['timestamp'])[11:16] == OPEN_EOD]
        if not eod:
            return None
        return _fill(direction, entry, stop_px, tgt_px, risk, float(eod[0]['open']),
                     'EOD-1520', eod[0]['timestamp'])
    if model == 'intrabar':
        ambiguous = 0
        for c in candles[entry_idx:]:
            if str(c['timestamp'])[11:16] >= OPEN_EOD:
                break
            o, hi, lo = float(c['open']), float(c['high']), float(c['low'])
            beyond_stop = (o <= stop_px) if direction == 'BULL' else (o >= stop_px)
            beyond_tgt = (o >= tgt_px) if direction == 'BULL' else (o <= tgt_px)
            if beyond_stop:
                return _fill(direction, entry, stop_px, tgt_px, risk, o, 'STOP',
                             c['timestamp'], stop_overshoot_pts=abs(o - stop_px),
                             ambiguous=ambiguous)
            if beyond_tgt:
                return _fill(direction, entry, stop_px, tgt_px, risk, o, 'TARGET',
                             c['timestamp'], target_truncation_pts=abs(o - tgt_px),
                             ambiguous=ambiguous)
            hit_stop = (lo <= stop_px) if direction == 'BULL' else (hi >= stop_px)
            hit_tgt = (hi >= tgt_px) if direction == 'BULL' else (lo <= tgt_px)
            if hit_stop and hit_tgt:
                ambiguous += 1
                return _fill(direction, entry, stop_px, tgt_px, risk, stop_px, 'STOP',
                             c['timestamp'], ambiguous=ambiguous)
            if hit_stop:
                return _fill(direction, entry, stop_px, tgt_px, risk, stop_px, 'STOP',
                             c['timestamp'], ambiguous=ambiguous)
            if hit_tgt:
                return _fill(direction, entry, stop_px, tgt_px, risk, tgt_px, 'TARGET',
                             c['timestamp'], ambiguous=ambiguous)
        eod = [c for c in candles if str(c['timestamp'])[11:16] == OPEN_EOD]
        if not eod:
            return None
        return _fill(direction, entry, stop_px, tgt_px, risk, float(eod[0]['open']),
                     'EOD-1520', eod[0]['timestamp'], ambiguous=ambiguous)
    raise ValueError(f'unknown model {model}')


def excursion(direction: str, entry: float, candles: list, entry_idx: int,
              exit_ts: str | None) -> dict:
    """MAE/MFE over the holding window (entry bar included)."""
    adverse = None
    favourable = None
    n = 0
    for c in candles[entry_idx:]:
        if exit_ts and str(c['timestamp'])[:16] > str(exit_ts)[:16]:
            break
        n += 1
        hi, lo = float(c['high']), float(c['low'])
        a = lo if direction == 'BULL' else hi
        f = hi if direction == 'BULL' else lo
        adverse = a if adverse is None else (min(adverse, a) if direction == 'BULL' else max(adverse, a))
        favourable = f if favourable is None else (max(favourable, f) if direction == 'BULL' else min(favourable, f))
    if n == 0:
        return {'mae_hl_pts': 0.0, 'mfe_hl_pts': 0.0, 'bars_held': 0}
    mae = (entry - adverse) if direction == 'BULL' else (adverse - entry)
    mfe = (favourable - entry) if direction == 'BULL' else (entry - favourable)
    return {'mae_hl_pts': round(mae, 4), 'mfe_hl_pts': round(mfe, 4), 'bars_held': n}


def mae_before_first_profit(direction: str, entry: float, candles: list,
                            entry_idx: int, exit_ts: str | None) -> dict:
    """Adverse excursion before the first close in profit (defined in spec §3.5)."""
    adverse = 0.0
    bars = 0
    for c in candles[entry_idx:]:
        if exit_ts and str(c['timestamp'])[:16] > str(exit_ts)[:16]:
            break
        bars += 1
        hi, lo, close = float(c['high']), float(c['low']), float(c['close'])
        a = (entry - lo) if direction == 'BULL' else (hi - entry)
        adverse = max(adverse, a)
        profitable = (close > entry) if direction == 'BULL' else (close < entry)
        if profitable:
            return {'mae_before_first_profit_pts': round(adverse, 4),
                    'bars_to_first_profit': bars}
    return {'mae_before_first_profit_pts': round(adverse, 4),
            'bars_to_first_profit': None}
