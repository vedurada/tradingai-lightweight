import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def clear_cache():
    try:
        from backend.cache import ResponseCache
        from backend.api_server import response_cache
        response_cache._store.clear()
    except Exception:
        pass
    yield
    try:
        from backend.api_server import response_cache
        response_cache._store.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clear_backtest_jobs():
    try:
        from backend.api_server import _backtest_jobs, _jobs_lock
        with _jobs_lock:
            _backtest_jobs.clear()
    except Exception:
        pass
    yield
    try:
        from backend.api_server import _backtest_jobs, _jobs_lock
        with _jobs_lock:
            _backtest_jobs.clear()
    except Exception:
        pass
