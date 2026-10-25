#!/usr/bin/env python3
"""Live intraday paper trader for the scalp (HLC 3-bar) engine (Phase 4)."""
import fcntl, json, os, sys, time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_IST = ZoneInfo('Asia/Kolkata')

from app.research.scalp_engine import today_state
from app.research.scalp_validation import validate_candle
from app.research.scalp_signal_store import (record_signal, mark_traded, mark_failed, init_schema, recover_new_signals, find_existing_trade)
from app.paper_trade.engine import PaperTradeEngine
from app.core.db import get_conn

INSTRUMENTS = ("NIFTY", "BANKNIFTY")
POLL_SECONDS = 60
LOCK_PATH = os.path.join(BASE, "logs", "paper_scalp_live.lock")
STATE_PATH = os.path.join(BASE, "logs", "paper_scalp_live.state.json")
STALE_MIN = 15


def market_open_now():
    now = datetime.now(_IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 15) <= t <= dtime(15, 30)


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(st, f)
    except Exception as e:
        print(f"state save failed: {e}", flush=True)


def latest_candle(inst):
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1",
            (inst,)).fetchone()
        conn.close()
        if not row:
            return None
        keys = ['timestamp', 'open', 'high', 'low', 'close']
        return dict(zip(keys, row))
    except Exception:
        return None


def prev_candle(inst):
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 2",
            (inst,)).fetchall()
        conn.close()
        if len(rows) < 2:
            return None
        keys = ['timestamp', 'open', 'high', 'low', 'close']
        return dict(zip(keys, rows[1]))
    except Exception:
        return None


def is_stale(ts):
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return (datetime.now(_IST) - dt.astimezone(_IST)).total_seconds() > STALE_MIN * 60
    except Exception:
        return True


def recover_open_positions():
    try:
        conn = get_conn()
        init_schema(conn)
        rows = conn.execute(
            "SELECT trade_id, instrument_id, status FROM paper_trades "
            "WHERE scenario='SCALP_HLC' AND status IN ('ACTIVE','OPEN')").fetchall()
        print(f"recovery: {len(rows)} open scalp paper trade(s)", flush=True)
        # recover NEW signals that may already have trades
        for sig in recover_new_signals(conn):
            sid = sig[0]; inst = sig[1]; td = sig[2]
            tid = find_existing_trade(conn, inst, td)
            if tid:
                mark_traded(conn, sid, tid)
                print(f"recovered signal {sid} -> trade {tid}", flush=True)
        conn.close()
    except Exception as e:
        print(f"recovery failed: {e}", flush=True)


def try_create_trade(conn, inst, today, st, sid):
    # if a trade already exists for this day, link and skip
    tid = find_existing_trade(conn, inst, today)
    if tid:
        mark_traded(conn, sid, tid)
        print(f"{inst} scalp paper trade {tid} already exists (signal {st.get('signal_time')})", flush=True)
        return
    qt = {
        "instrument_id": inst,
        "scenario": "SCALP_HLC",
        "strategy": "Scalp HLC 3-bar",
        "objective": "SCALP",
        "direction": st.get("direction"),
        "entry": st.get("entry"),
        "stop": st.get("stop"),
        "target": st.get("target"),
        "max_risk": None,
        "expected_reward": None,
        "entry_time": st.get("entry_time") or st.get("signal_time"),
        "legs": [],
    }
    try:
        tid = PaperTradeEngine().create_paper_trade(qt, link_key=f"scalp|{inst}|{today}")
        mark_traded(conn, sid, tid)
        print(f"{inst} scalp paper trade {tid} active (signal {st.get('signal_time')})", flush=True)
    except Exception as e:
        mark_failed(conn, sid, str(e))
        print(f"{inst} scalp paper-trade create failed: {e}", flush=True)


def run_once(state):
    today = datetime.now(_IST).date().isoformat()
    for inst in INSTRUMENTS:
        c = latest_candle(inst)
        pc = prev_candle(inst)
        ok, reason = validate_candle(c, prev=pc)
        if not ok:
            print(f"{inst}: invalid/stale candle ({reason}); skipping entries", flush=True)
            try:
                PaperTradeEngine().monitor(inst)
            except Exception as e:
                print(f"{inst} monitor failed: {e}", flush=True)
            continue
        if state.get(inst) == c['timestamp']:
            try:
                PaperTradeEngine().monitor(inst)
            except Exception as e:
                print(f"{inst} monitor failed: {e}", flush=True)
            continue
        try:
            st = today_state(inst, variant="plain")
        except Exception as e:
            print(f"{inst} state failed: {e}", flush=True)
            continue
        if isinstance(st, dict) and st.get("state") == "SIGNAL":
            entry = st.get("entry")
            signal_ts = st.get("signal_time")
            if signal_ts:
                conn = get_conn()
                init_schema(conn)
                sid = record_signal(conn, inst, today, st.get("direction"), st.get("level"),
                                   signal_ts, entry, st.get("stop"), st.get("target"))
                if entry is not None:
                    try_create_trade(conn, inst, today, st, sid)
                conn.close()
        try:
            PaperTradeEngine().monitor(inst)
        except Exception as e:
            print(f"{inst} monitor failed: {e}", flush=True)
        state[inst] = c['timestamp']
    save_state(state)


def main():
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print("another paper_scalp_live instance is already running; exiting", flush=True)
        sys.exit(0)
    print("paper_scalp_live started", flush=True)
    recover_open_positions()
    state = load_state()
    while True:
        if market_open_now():
            run_once(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
