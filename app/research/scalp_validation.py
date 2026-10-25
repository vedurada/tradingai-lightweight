"""Candle validation helpers for ScanLP (scalp) engine."""
import math
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')
INTERVAL_MIN = 5
STALE_MIN = 15


def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return dt.astimezone(_IST)
    except (TypeError, ValueError):
        return None


def _is_finite(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v)


def validate_candle(c, prev=None, now=None):
    """Return (ok, reason). ok=False means do not use this candle."""
    if not isinstance(c, dict):
        return False, 'NOT_DICT'
    ts = c.get('timestamp')
    dt = _parse_ts(ts)
    if dt is None:
        return False, 'BAD_TIMESTAMP'
    now = now or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)
    if dt > now + timedelta(minutes=1):
        return False, 'FUTURE_CANDLE'
    if (now - dt).total_seconds() > STALE_MIN * 60:
        return False, 'STALE_CANDLE'
    for k in ('open', 'high', 'low', 'close'):
        if not _is_finite(c.get(k)):
            return False, 'NON_FINITE_OHLC'
    o, h, l, cl = float(c['open']), float(c['high']), float(c['low']), float(c['close'])
    if h < l:
        return False, 'HIGH_LT_LOW'
    if h < max(o, cl) or l > min(o, cl):
        return False, 'OHLC_INCONSISTENT'
    if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
        return False, 'NON_POSITIVE_PRICE'
    # interval / gap checks
    if prev is not None:
        pdt = _parse_ts(prev.get('timestamp'))
        if pdt is not None:
            if dt.date() == pdt.date():
                delta = (dt - pdt).total_seconds()
                if delta <= 0:
                    return False, 'OUT_OF_ORDER_OR_DUPLICATE'
                if delta != INTERVAL_MIN * 60:
                    # allow session boundary? same day expected 5m
                    if delta > INTERVAL_MIN * 60:
                        return False, 'UNEXPECTED_GAP'
    # session hours (informational; do not reject pre/post market candles outright)
    return True, 'OK'


def latest_candle_ok(candles):
    """Validate the last candle against the previous one."""
    if not candles:
        return False, 'NO_CANDLES'
    if len(candles) == 1:
        return validate_candle(candles[-1])
    return validate_candle(candles[-1], prev=candles[-2])
