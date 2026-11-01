"""P0.19 atomic close-transition tests for the paper-trade engine.

No network, no Telegram, no production DB (conftest redirects
TRADINGAI_DB_PATH to a throwaway copy). Verifies that only one monitor can
transition ACTIVE/OPEN -> CLOSED and that exactly one PERF event is recorded.
"""
import json
import threading

import pytest

from app.core.db import get_conn
from app.paper_trade.engine import PaperTradeEngine

TID = "PT-P019ATOMIC"
WKEY = "scalp|NIFTY|2026-10-28|BULL|2026-10-28T09:20:00+05:30"


def _reset(tid):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM paper_trade_events WHERE trade_id=?", (tid,))
        conn.execute("DELETE FROM paper_trades WHERE trade_id=?", (tid,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def active_trade():
    _reset(TID)
    conn = get_conn()
    try:
        ev = json.dumps({"origin": "live-watch", "watch_key": WKEY,
                         "signal_time": "2026-10-28T09:20:00+05:30"})
        conn.execute(
            "INSERT INTO paper_trades (trade_id,instrument_id,scenario,strategy,"
            "direction,entry,stop,target,entry_time,status,qualification_evidence,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (TID, "NIFTY", "SCALP_HLC", "scalp", "BULL", 100.0, 99.0, 101.5,
             "2026-10-28T09:25:00+05:30", "ACTIVE", ev,
             "2026-10-28T09:30:00+05:30", "2026-10-28T09:30:00+05:30"))
        conn.commit()
    finally:
        conn.close()
    yield TID
    _reset(TID)


def _row(tid):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT status, exit_price, exit_reason FROM paper_trades WHERE trade_id=?",
            (tid,)).fetchone()
        events = conn.execute(
            "SELECT evidence FROM paper_trade_events WHERE trade_id=?", (tid,)).fetchall()
        return dict(row), [json.loads(e[0] or "{}") for e in events]
    finally:
        conn.close()


def test_second_close_is_rejected_and_does_not_overwrite(active_trade):
    engine = PaperTradeEngine()
    assert engine._exit_trade(active_trade, 99.5, "STOP", 100.0, "BULL", "NIFTY") is True
    assert engine._exit_trade(active_trade, 101.5, "TARGET", 100.0, "BULL", "NIFTY") is False

    row, events = _row(active_trade)
    assert row["status"] == "CLOSED"
    assert row["exit_price"] == 99.5
    assert row["exit_reason"] == "STOP"
    assert len(events) == 1
    assert events[0]["realized_R"] == -0.5


def test_concurrent_closes_yield_exactly_one_winner(active_trade):
    engine = PaperTradeEngine()
    barrier = threading.Barrier(2)
    results = []

    def close(px, reason):
        barrier.wait(timeout=10)
        results.append(engine._exit_trade(active_trade, px, reason, 100.0, "BULL", "NIFTY"))

    t1 = threading.Thread(target=close, args=(99.5, "STOP"))
    t2 = threading.Thread(target=close, args=(101.5, "TARGET"))
    for t in (t1, t2):
        t.start()
    for t in (t1, t2):
        t.join(timeout=20)

    assert sorted(results) == [False, True]
    row, events = _row(active_trade)
    assert row["status"] == "CLOSED"
    assert row["exit_price"] in (99.5, 101.5)
    assert len(events) == 1


def test_close_unknown_trade_returns_false():
    engine = PaperTradeEngine()
    assert engine._exit_trade("PT-P019MISSING", 100.0, "STOP", 100.0, "BULL", "NIFTY") is False
