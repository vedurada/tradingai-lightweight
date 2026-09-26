"""Weekly/monthly vertical-spread paper engine (grid mode).

NIFTY trades weekly (Tuesday) expiry; BANKNIFTY monthly (last Tuesday).
Strikes come from the REAL exchange grid (NIFTY 50pt, BANKNIFTY 100pt);
live premiums come from app.options.nse_chain when reachable, else the
spread is structure-only (legs/width/breakeven formulas, NO invented credit).

Construction (owner spec):
- BEAR -> Bear Call Spread: SHORT first OTM call ABOVE spot, LONG +width.
- BULL -> Bull Put Spread: SHORT first OTM put BELOW spot, LONG -width.
- Widths: NIFTY 200pts, BANKNIFTY 400pts. Lots: NIFTY 65, BANKNIFTY 30.
"""
import math
from datetime import date, timedelta

STEPS = {'NIFTY': 50.0, 'BANKNIFTY': 100.0}
WIDTHS = {'NIFTY': 200.0, 'BANKNIFTY': 400.0}
LOTS = {'NIFTY': 65, 'BANKNIFTY': 30}
WEEKLY = ('NIFTY',)
MONTHLY = ('BANKNIFTY',)


def _is_holiday(d):
    try:
        from app.market.nse_calendar import holiday_name
        return bool(holiday_name(d))
    except Exception:
        return False


def _prev_trading_day(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5 or _is_holiday(d):
        d -= timedelta(days=1)
    return d


def next_expiry(instrument, from_date=None):
    """Next expiry strictly after from_date (a Tuesday expiry day itself rolls
    to the following contract). Returns ISO date string."""
    inst = (instrument or '').upper()
    today = from_date or date.today()
    if isinstance(today, str):
        from datetime import datetime as _dt
        today = _dt.strptime(today[:10], '%Y-%m-%d').date()
    if inst in WEEKLY:
        add = (1 - today.weekday()) % 7 or 7
        exp = today + timedelta(days=add)
    elif inst in MONTHLY:
        exp = _last_tuesday(today.year, today.month)
        if exp <= today:
            m = today.month + 1
            exp = _last_tuesday(today.year + (m - 1) // 12, (m - 1) % 12 + 1)
    else:
        raise ValueError('UNKNOWN_INSTRUMENT:' + str(instrument))
    while exp.weekday() >= 5 or _is_holiday(exp):
        exp = _prev_trading_day(exp)
    return exp.isoformat()


def _last_tuesday(year, month):
    from calendar import monthrange
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - 1) % 7)


def build_spread(instrument, direction, spot):
    """Legs from the real grid. No premiums here (see nse_chain for credit)."""
    inst = (instrument or '').upper()
    dr = (direction or '').upper()
    if inst not in STEPS:
        return {'error': 'UNKNOWN_INSTRUMENT'}
    if dr not in ('BULL', 'BEAR'):
        return {'error': 'UNKNOWN_DIRECTION'}
    try:
        px = float(spot)
    except (TypeError, ValueError):
        return {'error': 'BAD_SPOT'}
    if not px > 0:
        return {'error': 'BAD_SPOT'}
    step, width = STEPS[inst], WIDTHS[inst]
    atm = round(px / step) * step
    if dr == 'BEAR':
        ks = (math.floor(px / step) + 1) * step
        legs = [{'side': 'SELL', 'type': 'CE', 'strike': ks},
                {'side': 'BUY', 'type': 'CE', 'strike': ks + width}]
    else:
        ks = (math.ceil(px / step) - 1) * step
        legs = [{'side': 'SELL', 'type': 'PE', 'strike': ks},
                {'side': 'BUY', 'type': 'PE', 'strike': ks - width}]
    return {'instrument': inst, 'direction': dr, 'strategy':
            'Bear Call Spread' if dr == 'BEAR' else 'Bull Put Spread',
            'spot_ref': round(px, 2), 'atm': atm, 'step': step,
            'width': width, 'lot': LOTS[inst], 'legs': legs}


def spread_points_at_expiry(spread, expiry_price):
    """Intrinsic spread value at expiry in points, EXCLUDING credit.

    Credit (real LTPs) added by caller when available; without it this is the
    structure curve, not P&L."""
    try:
        p = float(expiry_price)
    except (TypeError, ValueError):
        return None
    total = 0.0
    for leg in spread.get('legs', []):
        k = float(leg['strike'])
        if leg['type'] == 'CE':
            v = max(p - k, 0.0)
        else:
            v = max(k - p, 0.0)
        total += -v if leg['side'] == 'SELL' else v
    return round(total, 2)


def max_outcome(spread, credit_points=None):
    """Max profit/loss/breakeven in points given net credit (None: unknown)."""
    w = spread.get('width')
    legs = spread.get('legs') or []
    if credit_points is None or w is None or not legs:
        return {'max_profit_pts': None, 'max_loss_pts': None,
                'breakeven': None, 'note': 'awaiting live credit'}
    try:
        c = float(credit_points)
        ks = float(legs[0]['strike'])
    except (TypeError, ValueError, KeyError):
        return {'max_profit_pts': None, 'max_loss_pts': None,
                'breakeven': None, 'note': 'bad credit'}
    be = ks + c if spread.get('direction') == 'BEAR' else ks - c
    return {'max_profit_pts': round(c, 2),
            'max_loss_pts': round(c - w, 2),
            'breakeven': round(be, 2), 'note': 'with live credit'}


def payoff_curve(spread, credit_points=None, n=61):
    """Expiry P&L curve (points per unit) for charting.

    Returns {spots, pnls, breakeven, ...}. pnls exclude credit when unknown
    (structure curve, flagged) — never invents a credit."""
    legs = spread.get('legs') or []
    if not legs:
        return {'error': 'NO_LEGS'}
    ks = sorted(float(l['strike']) for l in legs)
    span = max((spread.get('width') or 0), 1.0)
    lo, hi = ks[0] - span, ks[-1] + span
    spots, pnls = [], []
    for i in range(max(n, 2)):
        p = lo + (hi - lo) * i / (max(n, 2) - 1)
        v = spread_points_at_expiry(spread, p)
        if v is None:
            return {'error': 'BAD_SPREAD'}
        if credit_points is not None:
            try:
                v = round(v + float(credit_points), 2)
            except (TypeError, ValueError):
                return {'error': 'BAD_CREDIT'}
        spots.append(round(p, 2))
        pnls.append(v)
    out = max_outcome(spread, credit_points)
    out.update({'spots': spots, 'pnls': pnls,
                'live_credit': credit_points is not None})
    return out
