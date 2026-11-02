#!/usr/bin/env python3
"""Live intraday paper trader for the scalp (HLC 3-bar) engine (Phase 4)."""
import fcntl, hashlib, json, os, sys, time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_IST = ZoneInfo('Asia/Kolkata')

from app.research.scalp_engine import today_signals
from app.research.scalp_validation import validate_candle
from app.research.scalp_signal_store import (record_signal, mark_traded, mark_failed, mark_expired, init_schema, recover_new_signals)
from app.paper_trade.engine import PaperTradeEngine
from app.core.db import get_conn
from app.market.provider import MarketDataProvider

sys.path.insert(0, os.path.join(BASE, "scripts"))
from options_trading_engine import OptionsEngine

INSTRUMENTS = ("NIFTY", "BANKNIFTY")
OPTIONS_ENGINE = OptionsEngine()
POLL_SECONDS = 5
LOCK_PATH = os.path.join(BASE, "logs", "paper_scalp_live.lock")
STATE_PATH = os.path.join(BASE, "logs", "paper_scalp_live.state.json")
STALE_MIN = 20
LAST_ENTRY_CUTOFF = dtime(15, 25)


def scalp_link(inst, trade_date, direction, signal_time):
    return f"scalp|{inst}|{trade_date}|{direction}|{signal_time}"


def scalp_trade_id(link_key):
    return 'PT-' + hashlib.sha1(str(link_key).encode()).hexdigest()[:10].upper()


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
        # recover NEW signals that may already have trades (per-signal link)
        for sig in recover_new_signals(conn):
            sid, inst, td, direction, _px, _sl, _tg, source_ts = sig[:8]
            tid = scalp_trade_id(scalp_link(inst, td, direction, source_ts))
            row = conn.execute("SELECT trade_id FROM paper_trades WHERE trade_id=?", (tid,)).fetchone()
            if row:
                mark_traded(conn, sid, row[0])
                print(f"recovered signal {sid} -> trade {row[0]}", flush=True)
        conn.close()
    except Exception as e:
        print(f"recovery failed: {e}", flush=True)


def has_open_position(conn, inst):
    """Mode C: return the open trade_id for an instrument, or None.

    Maximum one open paper position per instrument (NIFTY and BANKNIFTY
    tracked independently). Prevents concurrent positions for the same
    instrument, including across restarts and race conditions.
    """
    row = conn.execute(
        "SELECT trade_id FROM paper_trades WHERE instrument_id=? "
        "AND scenario='SCALP_HLC' AND status IN ('ACTIVE','OPEN')",
        (inst,)).fetchone()
    return row[0] if row else None


def try_create_trade(conn, inst, today, st, sid):
    # One trade per qualifying signal (canonical research: every alignment).
    link = scalp_link(inst, today, st.get("direction"), st.get("signal_time"))
    tid = scalp_trade_id(link)
    row = conn.execute("SELECT trade_id FROM paper_trades WHERE trade_id=?", (tid,)).fetchone()
    if row:
        mark_traded(conn, sid, row[0])
        print(f"{inst} scalp paper trade {row[0]} already exists (signal {st.get('signal_time')})", flush=True)
        return row[0]
    # Mode C: one open position per instrument — block if already open.
    open_pos = has_open_position(conn, inst)
    if open_pos:
        mark_failed(conn, sid, f"POSITION_OPEN_{inst}")
        print(f"{inst} scalp paper trade skipped: existing open position {open_pos} (signal {st.get('signal_time')})", flush=True)
        return None
    qt = {
        "instrument_id": inst,
        "scenario": "SCALP_HLC",
        "strategy": "Scalp HLC 3-bar",
        "objective": "SCALP",
        "direction": st.get("direction"),
        "level": st.get("level"),
        "signal_time": st.get("signal_time"),
        "entry": st.get("entry"),
        "stop": st.get("stop"),
        "target": st.get("target"),
        "max_risk": None,
        "expected_reward": None,
        "entry_time": st.get("entry_time") or st.get("signal_time"),
        "legs": [],
    }
    try:
        tid = PaperTradeEngine().create_paper_trade(qt, link_key=link)
        if tid:
            mark_traded(conn, sid, tid)
            print(f"{inst} scalp paper trade {tid} active (signal {st.get('signal_time')})", flush=True)
            return tid
        else:
            mark_failed(conn, sid, f"SCALP_TRADE_BLOCKED_{inst}")
            print(f"{inst} scalp paper trade create skipped (signal {st.get('signal_time')})", flush=True)
            return None
    except Exception as e:
        mark_failed(conn, sid, str(e))
        print(f"{inst} scalp paper-trade create failed: {e}", flush=True)
        return None


def _entry_time_guard(entry_time_s, now_dt=None):
    """Validate the entry timestamp without raising.

    Returns (state, reason) where state is 'ok', 'expired' or 'failed'.
    'failed' and 'expired' MUST prevent any trade creation. Using explicit
    string reasons keeps every branch free of undefined-name (NameError) bugs.
    """
    if not entry_time_s or str(entry_time_s).strip() == '':
        return 'failed', 'missing_entry_time'
    try:
        from datetime import datetime as _dt
        et = _dt.fromisoformat(str(entry_time_s).replace('Z', '+00:00'))
    except Exception:
        return 'failed', 'bad_entry_time'
    if et.tzinfo is None:
        et = et.replace(tzinfo=_IST)
    if now_dt is None:
        try:
            now_dt = datetime.now(_IST)
        except Exception:
            return 'failed', 'now_error'
    if et.tzinfo is None or now_dt.tzinfo is None:
        return 'failed', 'tz_error'
    # Entry candle interval is [entry_time, entry_time + 5min). We can enter
    # at the open price any time during this interval. Reject only if the
    # entry candle has already closed (now > entry_time + 5min).
    entry_close = et + timedelta(minutes=5)
    if now_dt > entry_close:
        return 'expired', 'entry_candle_closed'
    return 'ok', None


def _get_entry_price_from_provider(inst, entry_time):
    """Get the entry candle's open price from the live provider.

    The entry candle's OPEN is available at candle-open time via yfinance
    5-minute data (the forming candle's Open field is populated as soon as
    the first tick of the interval arrives). This avoids waiting ~5 minutes
    for the candle to be ingested into market_candles_5m as completed data.

    Returns the entry price as a float, or None if not yet available.
    """
    try:
        provider = MarketDataProvider()
        yf_symbol = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(inst, inst)
        candles_data = provider.get_5m_candles(yf_symbol)
        for c in candles_data.get('candles', []):
            if c.get('timestamp') == entry_time:
                return float(c['open'])
    except Exception as e:
        print(f"{inst} provider entry price lookup failed: {e}", flush=True)
    return None


def run_once(state):
    t_start = time.perf_counter()
    now = datetime.now(_IST)
    today = now.date().isoformat()
    # Never create a trade outside the session or from a stale signal. Monitor
    # existing positions regardless, so a restart still books settled exits.
    allow_new = market_open_now() and now.time() <= LAST_ENTRY_CUTOFF
    for inst in INSTRUMENTS:
        t_inst = time.perf_counter()
        n_signals = 0
        n_created = 0
        ms_signals = 0.0
        c = None
        try:
            c = latest_candle(inst)
            pc = prev_candle(inst)
            ok, reason = validate_candle(c, prev=pc)
            if ok and allow_new:
                t0 = time.perf_counter()
                try:
                    signals = today_signals(inst, variant="plain")
                except Exception as e:
                    print(f"{inst} state failed: {e}", flush=True)
                    signals = []
                ms_signals = (time.perf_counter() - t0) * 1000
                n_signals = len(signals)
                for st in signals:
                    try:
                        entry = st.get("entry")
                        signal_ts = st.get("signal_time")
                        if not signal_ts:
                            continue
                        # Entry price may be None if the entry candle is not yet
                        # ingested into market_candles_5m. Resolve it from the
                        # live provider (forming candle's open is available at
                        # candle-open time, before the candle is ingested).
                        if entry is None:
                            entry = _get_entry_price_from_provider(inst, st.get("entry_time"))
                            if entry is None:
                                # Entry price not yet available from provider;
                                # try again on the next poll cycle.
                                continue
                            st["entry"] = round(entry, 2)
                            stop = st.get("stop")
                            if stop is not None and entry is not None:
                                risk = abs(entry - float(stop))
                                if direction := st.get("direction"):
                                    if direction == "BULL":
                                        st["target"] = round(entry + risk * 1.5, 2)
                                    else:
                                        st["target"] = round(entry - risk * 1.5, 2)
                        conn = get_conn()
                        try:
                            init_schema(conn)
                            sid = record_signal(conn, inst, today, st.get("direction"), st.get("level"),
                                               signal_ts, st.get("entry"), st.get("stop"), st.get("target"))
                            status = conn.execute("SELECT status FROM scalp_signals WHERE signal_id=?", (sid,)).fetchone()
                            if status and status[0] != "NEW":
                                continue
                            entry_time_s = st.get("entry_time")
                            if entry_time_s is None:
                                # Entry candle not yet ingested; compute as
                                # signal_time + 5min so the entry window is
                                # 5 minutes after the entry candle, not 5
                                # minutes after the signal candle.
                                from datetime import datetime as _dt, timedelta as _td
                                signal_dt = _dt.fromisoformat(
                                    str(st.get("signal_time")).replace("Z", "+00:00")
                                )
                                entry_dt = signal_dt + _td(minutes=5)
                                entry_time_s = entry_dt.isoformat()
                            guard, why = _entry_time_guard(entry_time_s, now)
                            if guard == "failed":
                                mark_failed(conn, sid, why)
                                print(f"{inst} signal {signal_ts} rejected: {why}", flush=True)
                                continue
                            if guard == "expired":
                                mark_expired(conn, sid, why)
                                print(f"{inst} signal {signal_ts} expired: {why}", flush=True)
                                continue
                            t1 = time.perf_counter()
                            tid = try_create_trade(conn, inst, today, st, sid)
                            ms_create = (time.perf_counter() - t1) * 1000
                            if tid:
                                n_created += 1
                                # Create matching option trade (ATM CE for BULL, ATM PE for BEAR)
                                try:
                                    opt_res = OPTIONS_ENGINE.on_signal(
                                        instrument=inst,
                                        direction=st.get("direction"),
                                        signal_time=signal_ts,
                                        entry_spot=st.get("entry"),
                                        stop_spot=st.get("stop"),
                                        target_spot=st.get("target"),
                                        signal_id=sid,
                                    )
                                    if opt_res.get("status") == "TRADE_CREATED":
                                        print(f"{inst} option trade {opt_res.get('trade_id')} "
                                              f"{opt_res.get('option_type')} {opt_res.get('strike')} "
                                              f"premium={opt_res.get('premium_entry')} "
                                              f"(signal {signal_ts})", flush=True)
                                    elif opt_res.get("status") == "NO_TRADE":
                                        print(f"{inst} option trade skipped: {opt_res.get('reason')} "
                                              f"(signal {signal_ts})", flush=True)
                                except Exception as e:
                                    print(f"{inst} option trade create failed: {e}", flush=True)
                            print(f"[timing] inst={inst} stage=create ms={ms_create:.1f} "
                                  f"signal={signal_ts} created={bool(tid)}", flush=True)
                        finally:
                            conn.close()
                    except Exception as e:
                        print(f"{inst} signal processing failed: {e}", flush=True)
            elif not ok:
                print(f"{inst}: invalid/stale candle ({reason}); skipping entries", flush=True)
        except Exception as e:
            print(f"{inst} cycle failed: {e}", flush=True)
        t_mon = time.perf_counter()
        try:
            PaperTradeEngine().monitor(inst)
        except Exception as e:
            print(f"{inst} monitor failed: {e}", flush=True)
        # Check option position exits (stop/target/EOD)
        try:
            spot = latest_candle(inst)
            spot_price = float(c["close"]) if c and c.get("close") else None
            if spot_price:
                opt_exits = OPTIONS_ENGINE.check_exits(current_spot=spot_price)
                for ex in opt_exits:
                    print(f"{inst} option exit {ex['trade_id']} {ex['exit_reason']} "
                          f"pnl={ex.get('pnl_points')} pts / {ex.get('pnl_rupees')} "
                          f"rupees (exit_spot={ex.get('exit_spot')})", flush=True)
        except Exception as e:
            print(f"{inst} option exit check failed: {e}", flush=True)
        ms_monitor = (time.perf_counter() - t_mon) * 1000
        if c:
            state[inst] = c['timestamp']
        print(f"[timing] inst={inst} stage=cycle signals={n_signals} created={n_created} "
              f"ms_signals={ms_signals:.1f} ms_monitor={ms_monitor:.1f} "
              f"ms_total={(time.perf_counter() - t_inst) * 1000:.1f}", flush=True)
    save_state(state)
    print(f"[timing] stage=run_once ms_total={(time.perf_counter() - t_start) * 1000:.1f}", flush=True)



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
