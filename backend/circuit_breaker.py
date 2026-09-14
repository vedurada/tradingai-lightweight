import time
from threading import Lock


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, recovery_timeout=60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time = None
        self._state = "CLOSED"
        self._lock = Lock()

    def call(self, func, *args, **kwargs):
        with self._lock:
            if self._state == "OPEN":
                if self._last_failure_time is None or time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = "HALF_OPEN"
                else:
                    raise CircuitOpenError(f"Circuit breaker OPEN for {self.name}")

        try:
            result = func(*args, **kwargs)
            with self._lock:
                self._reset()
            return result
        except Exception:
            with self._lock:
                self._failures += 1
                self._last_failure_time = time.time()
                if self._failures >= self.failure_threshold:
                    self._state = "OPEN"
            raise

    def _reset(self):
        self._failures = 0
        self._state = "CLOSED"
        self._last_failure_time = None

    @property
    def state(self):
        with self._lock:
            if self._state == "OPEN" and self._last_failure_time is not None:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = "HALF_OPEN"
            return self._state

    def force_open(self):
        with self._lock:
            self._state = "OPEN"
            self._last_failure_time = time.time()

    def force_closed(self):
        with self._lock:
            self._reset()
