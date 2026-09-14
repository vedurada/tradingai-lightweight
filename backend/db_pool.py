import sqlite3
from threading import Lock


class PooledConnection:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        # B6.4: idempotent — explicit close() plus teardown-reclaim must never
        # double-return a slot (that would corrupt the active count).
        if self._closed:
            return
        self._closed = True
        self._pool.put(self._conn)


class ConnectionPool:
    def __init__(self, db_path, max_connections=10):
        self._get_db_path = db_path if callable(db_path) else lambda: db_path
        self.max_connections = max_connections
        self._pool = []
        self._lock = Lock()
        self._active = 0

    @property
    def db_path(self):
        return self._get_db_path()

    def get(self):
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                self._active += 1
                return conn
            if self._active < self.max_connections:
                conn = self._connect()
                self._active += 1
                return conn
            raise sqlite3.OperationalError("Connection pool exhausted")

    def put(self, conn):
        with self._lock:
            self._active -= 1
            if len(self._pool) < self.max_connections:
                self._pool.append(conn)
            else:
                conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def close_all(self):
        with self._lock:
            for conn in self._pool:
                conn.close()
            self._pool.clear()

    @property
    def status(self):
        with self._lock:
            return {
                "active": self._active,
                "available": len(self._pool),
                "max": self.max_connections,
                "exhausted": self._active >= self.max_connections and not self._pool,
            }
