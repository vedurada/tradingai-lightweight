"""P0.15 isolated runtime tests for the scalp paper/alerts paths.

No network, no production DB, no real Telegram messages. Run with:

    /usr/bin/python3 -m pytest tests/test_scalp_paper_live_runtime.py -q

Covers the previously reported NameError branches in
``scripts/paper_scalp_live.py`` and the single-owner alert dedup behaviour in
``scripts/tg_alerts.py --watch`` (provider mocked).
"""
import hashlib
import importlib.util
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = ZoneInfo("Asia/Kolkata")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


psl = _load("psl_under_test", "scripts/paper_scalp_live.py")
tga = _load("tga_under_test", "scripts/tg_alerts.py")


# ---------------------------------------------------------------------------
# Phase B: entry-time guard branches (previously undefined names)
# ---------------------------------------------------------------------------
def test_entry_time_guard_all_branches_without_nameerror(monkeypatch):
    now = datetime(2026, 10, 28, 10, 20, tzinfo=IST)
    assert psl._entry_time_guard(None, now) == ("failed", "missing_entry_time")
    assert psl._entry_time_guard("", now) == ("failed", "missing_entry_time")
    assert psl._entry_time_guard("   ", now) == ("failed", "missing_entry_time")
    assert psl._entry_time_guard("not-a-date", now) == ("failed", "bad_entry_time")
    # naive now_dt must not raise; reports tz_error
    naive_now = datetime(2026, 10, 28, 10, 20)
    assert psl._entry_time_guard((now + timedelta(minutes=5)).isoformat(), naive_now) == (
        "failed", "tz_error")
    # expired (equality and past)
    assert psl._entry_time_guard(now.isoformat(), now) == (
        "expired", "entry_candle_past_or_now")
    assert psl._entry_time_guard((now - timedelta(minutes=5)).isoformat(), now) == (
        "expired", "entry_candle_past_or_now")
    # future -> ok
    assert psl._entry_time_guard((now + timedelta(minutes=5)).isoformat(), now) == ("ok", None)
    # naive entry string is normalised to IST
    naive_et = (now + timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    assert psl._entry_time_guard(naive_et, now) == ("ok", None)

    # now_error branch: clock failure must be a clean failure, not a crash
    class _BoomClock:
        @classmethod
        def now(cls, tz=None):
            raise RuntimeError("clock unavailable")

    monkeypatch.setattr(psl, "datetime", _BoomClock)
    assert psl._entry_time_guard((now + timedelta(minutes=5)).isoformat(), None) == (
        "failed", "now_error")


# ---------------------------------------------------------------------------
# run_once harness
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self):
        self.closed = False
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if "FROM scalp_signals WHERE signal_id" in sql:
            return _Cursor(("NEW",))
        return _Cursor(None)

    def close(self):
        self.closed = True


def _install_run_once(monkeypatch, now, entry_time):
    calls = {"create": 0, "failed": [], "expired": [], "monitor": 0, "record": 0}
    conn = _Conn()
    signal = {
        "entry": 100.0, "signal_time": "2026-10-28T10:15:00+05:30",
        "direction": "BULL", "level": "H1_UP", "stop": 98.0, "target": 103.0,
        "entry_time": entry_time,
    }
    monkeypatch.setattr(psl, "latest_candle", lambda inst: {"timestamp": "2026-10-28T10:15:00+05:30"})
    monkeypatch.setattr(psl, "prev_candle", lambda inst: {"timestamp": "2026-10-28T10:10:00+05:30"})
    monkeypatch.setattr(psl, "validate_candle", lambda c, prev=None: (True, None))
    monkeypatch.setattr(psl, "is_stale", lambda ts: False)
    monkeypatch.setattr(psl, "market_open_now", lambda: True)
    monkeypatch.setattr(psl, "today_signals", lambda inst, variant="plain": [dict(signal)] if inst == "NIFTY" else [])
    monkeypatch.setattr(psl, "get_conn", lambda: conn)
    monkeypatch.setattr(psl, "init_schema", lambda c: None)

    def _record(*a, **k):
        calls["record"] += 1
        return "SS-TEST"

    monkeypatch.setattr(psl, "record_signal", _record)
    monkeypatch.setattr(psl, "mark_traded", lambda *a, **k: None)
    monkeypatch.setattr(psl, "mark_failed", lambda c, sid, why: calls["failed"].append(why))
    monkeypatch.setattr(psl, "mark_expired", lambda c, sid, why=None: calls["expired"].append(why))

    def _create(*a, **k):
        calls["create"] += 1
        return "PT-TEST"

    monkeypatch.setattr(psl, "try_create_trade", _create)

    class _Engine:
        def monitor(self, inst):
            calls["monitor"] += 1
            return []

    monkeypatch.setattr(psl, "PaperTradeEngine", _Engine)
    monkeypatch.setattr(psl, "save_state", lambda st: None)

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(psl, "datetime", _FixedDT)
    return calls, conn


def test_run_once_malformed_signal_does_not_create_trade(monkeypatch):
    now = datetime(2026, 10, 28, 10, 20, tzinfo=IST)
    calls, _ = _install_run_once(monkeypatch, now, "garbage")
    psl.run_once({})
    assert calls["create"] == 0
    assert calls["failed"] == ["bad_entry_time"]
    assert calls["monitor"] > 0  # exit monitoring still runs


def test_run_once_expired_signal_does_not_create_trade(monkeypatch):
    now = datetime(2026, 10, 28, 10, 20, tzinfo=IST)
    calls, _ = _install_run_once(monkeypatch, now, (now - timedelta(minutes=5)).isoformat())
    psl.run_once({})
    assert calls["create"] == 0
    assert calls["expired"] == ["entry_candle_past_or_now"]
    assert calls["monitor"] > 0


def test_run_once_valid_signal_creates_one_trade(monkeypatch, capsys):
    now = datetime(2026, 10, 28, 10, 20, tzinfo=IST)
    calls, conn = _install_run_once(monkeypatch, now, (now + timedelta(minutes=5)).isoformat())
    psl.run_once({})
    assert calls["create"] == 1
    assert calls["failed"] == [] and calls["expired"] == []
    assert conn.closed is True
    out = capsys.readouterr().out
    assert "[timing]" in out and "stage=cycle" in out and "stage=run_once" in out


# ---------------------------------------------------------------------------
# at-most-one trade via deterministic trade id (real function)
# ---------------------------------------------------------------------------
def test_try_create_trade_is_idempotent(monkeypatch):
    store = {}

    class _Cur:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class _C:
        def execute(self, sql, params=()):
            if "FROM paper_trades WHERE trade_id" in sql:
                return _Cur((params[0],) if params[0] in store else None)
            return _Cur(None)

    class _Engine:
        def __init__(self):
            self.calls = 0

        def create_paper_trade(self, qt, link_key=None):
            self.calls += 1
            tid = "PT-" + hashlib.sha1(str(link_key).encode()).hexdigest()[:10].upper()
            store[tid] = qt
            return tid

    engine = _Engine()
    monkeypatch.setattr(psl, "PaperTradeEngine", lambda: engine)
    monkeypatch.setattr(psl, "mark_traded", lambda *a, **k: None)
    monkeypatch.setattr(psl, "mark_failed", lambda *a, **k: None)

    st = {"direction": "BULL", "signal_time": "2026-10-28T10:15:00+05:30",
          "entry": 100.0, "stop": 98.0, "target": 103.0,
          "entry_time": "2026-10-28T10:20:00+05:30"}
    conn = _C()
    t1 = psl.try_create_trade(conn, "NIFTY", "2026-10-28", st, "SS-1")
    t2 = psl.try_create_trade(conn, "NIFTY", "2026-10-28", st, "SS-2")
    assert t1 == t2
    assert engine.calls == 1
    assert len(store) == 1


# ---------------------------------------------------------------------------
# Phase D/E: signal & trade id correlation across the two paths
# ---------------------------------------------------------------------------
def test_ids_correlate_across_paths():
    today, inst = "2026-10-28", "NIFTY"
    sig = {"direction": "BULL", "signal_time": "2026-10-28T10:15:00+05:30",
           "entry_time": "2026-10-28T10:20:00+05:30"}
    link_live = psl.scalp_link(inst, today, "BULL", sig["signal_time"])
    link_alert = tga._scalp_link(today, inst, sig)
    assert link_live == link_alert
    expected = "PT-" + hashlib.sha1(link_live.encode()).hexdigest()[:10].upper()
    assert psl.scalp_trade_id(link_live) == expected
    assert tga._scalp_key(today, inst, sig) == tga._scalp_key(today, inst, dict(sig))


def test_poll_seconds_is_five():
    assert psl.POLL_SECONDS == 5


# ---------------------------------------------------------------------------
# Phase D/E: do_watch single-owner alert dedup, delivery provenance
# ---------------------------------------------------------------------------
def _install_do_watch(monkeypatch, tmp_path, tg_result):
    now = datetime(2026, 10, 28, 10, 20, tzinfo=IST)

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(tga, "datetime", _FixedDT)
    monkeypatch.setattr(tga, "ARCHIVE", str(tmp_path / "archive.jsonl"))
    holder = {}
    monkeypatch.setattr(tga, "state", lambda: holder)
    monkeypatch.setattr(tga, "save_state", lambda s: holder.update(s))
    monkeypatch.setattr(tga, "rebuild_page", lambda: None)
    monkeypatch.setattr(tga, "fb_post", lambda *a, **k: None)
    monkeypatch.setattr(tga, "closed_trade_by_id", lambda xid: None)

    et = (now - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    sig = {"state": "SIGNAL", "direction": "BULL", "level": "H1_UP",
           "signal_time": et, "entry_time": et,
           "entry": 100.0, "stop": 98.0, "target": 103.0}

    def _api(path, tries=3, sleep_s=5):
        if "/api/strategy/scalp" in path and "instrument=NIFTY" in path:
            return {"state": "SIGNAL", "signals": [dict(sig)]}
        if "/api/strategy/scalp" in path:
            return {"state": "WATCH", "signals": []}
        return {}

    monkeypatch.setattr(tga, "api_retry", _api)

    import app.paper_trade.engine as engine_mod

    class _Engine:
        def create_paper_trade(self, t, link_key=None):
            return "PT-WATCH"

        def monitor(self, inst):
            return []

    monkeypatch.setattr(engine_mod, "PaperTradeEngine", _Engine)

    calls = {"tg": 0, "texts": []}

    def _tg(method, payload, photo=None, timeout=30):
        calls["tg"] += 1
        calls["texts"].append(payload.get("text"))
        return tg_result

    monkeypatch.setattr(tga, "tg", _tg)
    return now, sig, holder, calls


def test_do_watch_replay_does_not_duplicate_logical_alert(monkeypatch, tmp_path):
    _, sig, holder, calls = _install_do_watch(
        monkeypatch, tmp_path, {"ok": True, "result": {"message_id": 7}})
    lock1 = str(tmp_path / "lock1")
    lock2 = str(tmp_path / "lock2")
    tga.do_watch(lock_path=lock1)  # first cron tick
    first_count = calls["tg"]
    assert first_count == 1
    key = tga._scalp_key("2026-10-28", "NIFTY", sig)
    assert key in holder.get("fired", [])
    tga.do_watch(lock_path=lock2)  # replay / next tick, same state
    assert calls["tg"] == first_count  # no duplicate alert
    lines = (tmp_path / "archive.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert '"delivered": true' in lines[0]


def test_do_watch_provider_failure_not_recorded_as_success(monkeypatch, tmp_path):
    _, sig, holder, calls = _install_do_watch(
        monkeypatch, tmp_path, {"ok": False, "description": "simulated down"})
    tga.do_watch(lock_path=str(tmp_path / "lock1"))
    assert calls["tg"] == 1
    key = tga._scalp_key("2026-10-28", "NIFTY", sig)
    assert key not in holder.get("fired", [])
    archive = tmp_path / "archive.jsonl"
    assert not archive.exists() or archive.read_text().strip() == ""
    # failure retries next tick rather than silently marking success
    tga.do_watch(lock_path=str(tmp_path / "lock2"))
    assert calls["tg"] == 2
