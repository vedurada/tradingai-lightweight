import time
import threading
import uuid
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone


class RequestMonitor:
    """In-memory request monitoring. Process-local, thread-safe."""

    def __init__(self):
        self._lock = threading.RLock()
        self._latencies = defaultdict(list)
        self._counts = defaultdict(lambda: {
            "total_requests": 0,
            "total_errors": 0,
            "by_status": defaultdict(int),
            "by_error_code": defaultdict(int),
            "last_error_at": None,
        })
        self._external_failures = defaultdict(lambda: defaultdict(int))
        self._circuit_breaker_state = {}
        self._uptime_start = time.monotonic()
        self._alerted = {}

    def record_request(self, endpoint, duration_ms, status_code, error_code=None):
        with self._lock:
            ep = self._counts[endpoint]
            ep["total_requests"] += 1
            if status_code >= 400:
                ep["total_errors"] += 1
                ep["by_status"][f"{status_code // 100}xx"] += 1
                if error_code:
                    ep["by_error_code"][error_code] += 1
                    ep["last_error_at"] = datetime.now(timezone.utc).isoformat()
            self._latencies[endpoint].append(duration_ms)
            if len(self._latencies[endpoint]) > 1000:
                self._latencies[endpoint] = self._latencies[endpoint][-1000:]

    def record_external_failure(self, source, error_type):
        with self._lock:
            self._external_failures[source][error_type] += 1

    def record_circuit_breaker_state(self, source, state, failures=0, last_failure=None):
        with self._lock:
            self._circuit_breaker_state[source] = {
                "state": state,
                "failures": failures,
                "last_failure": last_failure,
            }

    def get_latency(self, endpoint, window=1000):
        with self._lock:
            samples = self._latencies.get(endpoint, [])[-window:]
            if not samples:
                return {"count": 0, "avg_ms": 0, "min_ms": 0, "max_ms": 0, "p95_ms": 0}
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            return {
                "count": n,
                "avg_ms": round(sum(samples) / n, 2),
                "min_ms": round(min(samples), 2),
                "max_ms": round(max(samples), 2),
                "p95_ms": round(sorted_samples[int(n * 0.95)], 2),
            }

    def get_counts(self, endpoint=None):
        with self._lock:
            if endpoint:
                return dict(self._counts.get(endpoint, {}))
            return {ep: dict(data) for ep, data in self._counts.items()}

    def get_summary(self):
        with self._lock:
            return {
                "endpoints": {ep: self.get_latency(ep) for ep in self._latencies},
                "counts": self.get_counts(),
                "circuit_breakers": dict(self._circuit_breaker_state),
                "external_api_failures": {s: dict(d) for s, d in self._external_failures.items()},
            }

    def get_uptime_seconds(self):
        return round(time.monotonic() - self._uptime_start, 2)

    def reset(self):
        with self._lock:
            self._latencies.clear()
            self._counts.clear()
            self._external_failures.clear()
            self._circuit_breaker_state.clear()
            self._alerted.clear()

    def check_alerts(self, alert_rules=None):
        with self._lock:
            if alert_rules is None:
                alert_rules = {
                    "sustained_api_failures": {"threshold": 10, "window_seconds": 60, "severity": "WARNING"},
                    "abnormal_latency": {"p95_threshold_ms": 5000, "window_seconds": 300, "severity": "WARNING"},
                }
            now = datetime.now(timezone.utc)
            alerts = []
            for endpoint, data in self._counts.items():
                rule = alert_rules.get("sustained_api_failures", {})
                if data["total_errors"] >= rule.get("threshold", 10):
                    alert_key = f"sustained_api_failures:{endpoint}"
                    last = self._alerted.get(alert_key)
                    if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= 300:
                        alerts.append({
                            "alert_type": "sustained_api_failures",
                            "endpoint": endpoint,
                            "severity": rule.get("severity", "WARNING"),
                            "threshold": rule.get("threshold", 10),
                            "actual": data["total_errors"],
                            "timestamp": now.isoformat(),
                        })
                        self._alerted[alert_key] = now.isoformat()
            for source, state in self._circuit_breaker_state.items():
                if state.get("state") == "OPEN":
                    alert_key = f"circuit_breaker_open:{source}"
                    last = self._alerted.get(alert_key)
                    if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= 300:
                        alerts.append({
                            "alert_type": "circuit_breaker_open",
                            "source": source,
                            "severity": "CRITICAL",
                            "timestamp": now.isoformat(),
                        })
                        self._alerted[alert_key] = now.isoformat()
            for endpoint, latency_info in self._latencies.items():
                if not latency_info:
                    continue
                p95 = sorted(latency_info)[-1] if len(latency_info) == 1 else sorted(latency_info)[int(len(latency_info) * 0.95)]
                rule = alert_rules.get("abnormal_latency", {})
                if p95 > rule.get("p95_threshold_ms", 5000):
                    alert_key = f"abnormal_latency:{endpoint}"
                    last = self._alerted.get(alert_key)
                    if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= 300:
                        alerts.append({
                            "alert_type": "abnormal_latency",
                            "endpoint": endpoint,
                            "severity": rule.get("severity", "WARNING"),
                            "p95_ms": round(p95, 2),
                            "threshold_ms": rule.get("p95_threshold_ms", 5000),
                            "timestamp": now.isoformat(),
                        })
                        self._alerted[alert_key] = now.isoformat()
            return alerts
