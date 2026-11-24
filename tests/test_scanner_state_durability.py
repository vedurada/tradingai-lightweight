"""C5/C6: scanner state must survive restarts and exits must be atomic.

These tests exercise the real DB helpers from every scanner source with a
temporary SQLite database (no broker, no /opt/tradingai writes).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts"

# (source path, DB env var, open-position table, trades table)
SCANNERS = [
    ("sma9_scanner/app/live_sma9_scanner.py", "SMA9_DB_PATH",
     "sma9_open_positions", "sma9_trades"),
    ("sma9_5min_scanner/app/live_sma9_5min_scanner.py", "SMA9_5MIN_DB_PATH",
     "sma9_5min_open_positions", "sma9_5min_trades"),
    ("sma9_adx_scanner/app/live_sma9_adx_scanner.py", "SMA9_ADX_DB_PATH",
     "sma9_adx_open_positions", "sma9_adx_trades"),
    ("sma9_high_scanner/app/live_sma9_high_scanner.py", "SMA9_HIGH_DB_PATH",
     "sma9_high_open_positions", "sma9_high_trades"),
    ("sma9_atr_scanner/app/live_sma9_atr_scanner.py", "SMA9_ATR_DB_PATH",
     "sma9_atr_open_positions", "sma9_atr_trades"),
    ("sma9_trail_scanner/app/live_sma9_trail_scanner.py", "SMA9_TRAIL_DB_PATH",
     "sma9_trail_open_positions", "sma9_trail_trades"),
    ("sma9_high_trail_scanner/app/live_sma9_high_trail_scanner.py",
     "SMA9_HIGH_TRAIL_DB_PATH",
     "sma9_high_trail_open_positions", "sma9_high_trail_trades"),
]


@pytest.fixture
def load_scanner(tmp_path, monkeypatch):
    """Import each scanner in isolation and initialise a throwaway DB."""
    saved_app = {
        k: v for k, v in sys.modules.items()
        if k == "app" or k.startswith("app.")
    }
    saved_path = list(sys.path)
    loaded: list = []

    def _load(rel: str, env_key: str):
        # Each scanner owns a separate `app` package. Drop stale roots/modules
        # so the current source's engine is the one that gets imported.
        sys.path[:] = [p for p in sys.path if not str(p).startswith(str(ROOT))]
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        monkeypatch.setenv(env_key, str(tmp_path / f"{env_key.lower()}.db"))
        path = ROOT / rel
        name = "scan_" + env_key.lower()
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mod.init_db()
        loaded.append(mod)
        return mod

    yield _load

    for mod in loaded:
        sys.modules.pop(mod.__name__, None)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    sys.modules.update(saved_app)
    sys.path[:] = saved_path


def _fake_position() -> SimpleNamespace:
    """One object with the union of every scanner's persisted attributes."""
    ts = datetime(2026, 1, 1, 9, 30)
    return SimpleNamespace(
        option_type="CE", trade_id="T1", strike=20000.0, expiry="2026-01-29",
        token=12345, tradingsymbol="NIFTY26JAN20000CE",
        entry_timestamp=ts, entry_candle_start=ts, entry_candle_end=ts,
        entry_price=100.0, sma9=99.0, adx=25.0, prev_sma9=98.0, sma=99.0,
        prev_close=99.0, prev_high=99.0, current_open=100.0,
        condition_a=True, condition_b=True, condition_c=False,
        ltp_at_entry=100.0, atr_at_entry=10.0, stop_price=93.0, stop_k=0.7,
        stop_distance_pct=7.0, stop_source="ATR", trail_distance=7.0,
        hwm=110.0, stop=103.0, be_locked=False, breakout=False,
    )


def _fake_trade(mod) -> dict:
    cols = [c.strip() for c in mod.TRADE_COLUMNS.split(",")]
    trade = {c: "x" for c in cols}
    trade.update(option_type="CE", trade_id="T1")
    return trade


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("rel,env_key,open_table,trade_table", SCANNERS)
def test_atomic_close_inserts_trade_and_deletes_position(
        load_scanner, rel, env_key, open_table, trade_table):
    mod = load_scanner(rel, env_key)
    mod.save_open_position(_fake_position())
    assert _count(Path(mod.DB_PATH), open_table) == 1

    mod.save_trade(_fake_trade(mod))

    assert _count(Path(mod.DB_PATH), trade_table) == 1
    assert _count(Path(mod.DB_PATH), open_table) == 0


@pytest.mark.parametrize("rel,env_key,open_table,trade_table", SCANNERS)
def test_atomic_close_rolls_back_on_failure(
        load_scanner, rel, env_key, open_table, trade_table):
    mod = load_scanner(rel, env_key)
    mod.save_open_position(_fake_position())

    # Simulate a crash during the delete half of the transaction.
    conn = sqlite3.connect(mod.DB_PATH)
    conn.execute(
        f"CREATE TRIGGER fail_close BEFORE DELETE ON {open_table} "
        "BEGIN SELECT RAISE(ABORT, 'simulated'); END"
    )
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.IntegrityError):
        mod.save_trade(_fake_trade(mod))

    # Neither half may be committed on failure.
    assert _count(Path(mod.DB_PATH), trade_table) == 0
    assert _count(Path(mod.DB_PATH), open_table) == 1


@pytest.mark.parametrize("rel,env_key,open_table,trade_table", SCANNERS)
def test_trail_state_survives_save_and_reload(
        load_scanner, rel, env_key, open_table, trade_table):
    mod = load_scanner(rel, env_key)
    mod.save_open_position(_fake_position())

    restored = mod.load_open_positions()["CE"]
    assert restored.hwm == pytest.approx(110.0)
    assert restored.stop == pytest.approx(103.0)


def test_all_scanners_persist_trail_after_update_and_close_atomically():
    """Static guard: all 8 sources carry the C5/C6 call-site patterns."""
    for rel, *_ in SCANNERS:
        src = (ROOT / rel).read_text()
        assert "prev_hwm, prev_stop = state.position.hwm, state.position.stop" in src, rel
        assert "save_open_position(trail_pos)" in src, rel
        assert "Atomic close:" in src, rel
        assert "WHERE option_type = ?" in src, rel
        assert "delete_open_position(opt)" not in src, rel
