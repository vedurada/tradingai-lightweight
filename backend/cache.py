import time
from threading import Lock


class ResponseCache:
    def __init__(self):
        self._store = {}
        self._lock = Lock()

    @staticmethod
    def _ttl_for_endpoint(endpoint):
        if endpoint in ("/api/price", "/api/prices", "/api/indicators", "/api/vix", "/api/vix/history", "/api/vix/daily"):
            return 5
        if endpoint in ("/api/outlook", "/api/outlooks", "/api/strategy", "/api/strategies", "/api/regime", "/api/regimes", "/api/scenarios"):
            return 3600
        if endpoint in ("/api/symbols", "/api/etf", "/api/etf-holdings", "/api/fundamentals"):
            return 86400
        if endpoint in ("/api/backtest", "/api/options", "/api/pcr", "/api/maxpain", "/api/oi-top", "/api/oi-concentration"):
            return 600
        return 0

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry["timestamp"]) < entry["ttl"]:
                return entry["value"]
            return None

    def set(self, key, value, ttl):
        with self._lock:
            self._store[key] = {
                "value": value,
                "timestamp": time.time(),
                "ttl": ttl,
            }

    def invalidate(self, key):
        with self._lock:
            self._store.pop(key, None)

    @property
    def stats(self):
        with self._lock:
            total = len(self._store)
            hits = sum(1 for v in self._store.values() if True)
            return {"entries": total}
