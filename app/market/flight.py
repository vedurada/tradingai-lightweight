"""PERF single-flight (no logic change).

Concurrent cache-miss requests for one (kind, symbol) share ONE upstream
fetch instead of each firing its own yfinance storm + serialized SQLite
writes. Per-process (one copy per gunicorn worker); cross-worker worst
case is still max 2 fetches. Followers re-read the cache after the
leader finishes; if still a miss they fetch themselves.
"""
import threading

_FLIGHT = {}
_FLIGHT_LOCK = threading.Lock()
_FLIGHT_WAIT_S = 30  # leader fetch bounded by 2 attempts x 12s + put


def begin(key):
    """Return (is_leader, event) for a (kind, symbol) fetch."""
    with _FLIGHT_LOCK:
        ev = _FLIGHT.get(key)
        if ev is None:
            ev = threading.Event()
            _FLIGHT[key] = ev
            return True, ev
    ev.wait(timeout=_FLIGHT_WAIT_S)
    return False, ev


def end(key, ev):
    with _FLIGHT_LOCK:
        if _FLIGHT.get(key) is ev:
            del _FLIGHT[key]
    ev.set()
