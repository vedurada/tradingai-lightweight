#!/usr/bin/env python3
"""Out-of-process entry-capture shadow monitor.

Runs ALONGSIDE the live paper trader. It never places, modifies or records
trades, never imports the trading engine, and opens the database read-only.
Its only output is append-only JSONL plus a small state file.
"""
import argparse
import fcntl
import re
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entry_capture as ec  # noqa: E402

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def market_open(now):
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def load_state():
    try:
        with open(ec.STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"signals": {}, "last_poll": None}


def save_state(state):
    ec.ensure_dirs()
    tmp = ec.STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, default=str)
    os.replace(tmp, ec.STATE_PATH)


def load_signals(day):
    conn = ec.db_connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            "SELECT signal_id, instrument_id, trade_date, direction, source_candle_ts, "
            "status, reference_price, reference_stop, reference_target, paper_trade_id, "
            "last_error, updated_at FROM scalp_signals "
            "WHERE trade_date = ? "
            "ORDER BY trade_date, instrument_id, source_candle_ts",
            (day,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_trade(trade_id):
    if not trade_id:
        return None
    conn = ec.db_connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        r = conn.execute(
            "SELECT trade_id, entry, stop, target, entry_time, exit_time, exit_price, "
            "exit_reason, paper_pnl, status FROM paper_trades WHERE trade_id=? LIMIT 1",
            (trade_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def availability(attempts):
    return {
        "db_5m": next((a for a in attempts if a["source"] == "5m_db"), {}).get("present"),
        "provider_5m": next((a for a in attempts if a["source"] == "5m_provider"), {}).get("present"),
        "one_min": next((a for a in attempts if a["source"] == "1m_open"), {}).get("present"),
        "quote": next((a for a in attempts if a["source"] == "quote"), {}).get("present"),
    }


def reject_reasons(attempts):
    return {a["source"]: a.get("reject") for a in attempts if a.get("reject")}


def process(now, force=False, day=None):
    if not market_open(now) and not force:
        return 0
    day = day or now.date().isoformat()
    hist = day != now.date().isoformat()
    state = load_state()
    sig_state = state.setdefault("signals", {})
    signals = load_signals(day)
    emitted = 0

    for s in signals:
        sid = s["signal_id"]
        st = sig_state.setdefault(sid, {"retries": 0, "events": {}})
        events = st["events"]
        sig_dt = ec.parse_ts(s["source_candle_ts"])
        if sig_dt is None:
            continue
        entry_time = sig_dt + timedelta(minutes=ec.CANDLE_MINUTES)
        deadline = entry_time + timedelta(minutes=ec.ENTRY_WINDOW_MINUTES)
        status = (s["status"] or "").upper()

        # Live probing only while the entry window is open.
        if now < entry_time:
            continue
        if now < deadline and status == "NEW":
            st["retries"] += 1
            if "proposal" not in events:
                res = ec.resolve(s["instrument_id"], entry_time, deadline, now=now,
                                 historical=hist)
                av = availability(res["attempts"])
                if st["retries"] == 1 or st["retries"] % 6 == 0:
                    ec.append_jsonl(ec.EVENTS_PATH, {
                        "event": "attempt", "at": ec.iso(now), "signal_id": sid,
                        "instrument": s["instrument_id"], "direction": s["direction"],
                        "signal_ts": s["source_candle_ts"], "entry_time": ec.iso(entry_time),
                        "deadline": ec.iso(deadline), "retry_count": st["retries"],
                        "availability": av, "reject": reject_reasons(res["attempts"]),
                        "since_entry_s": round((now - entry_time).total_seconds(), 1),
                    })
                    emitted += 1
                if res["resolved"]:
                    events["proposal"] = True
                    st["proposal"] = {
                        "source": res["source"], "price": res["price"],
                        "fill_ts": res["fill_ts"], "latency_s": res["latency_s"],
                        "classification": "LIVE_CAPTURE", "late": False,
                    }
                    ec.append_jsonl(ec.EVENTS_PATH, {
                        "event": "proposal", "classification": "LIVE_CAPTURE", "at": ec.iso(now), "signal_id": sid,
                        "instrument": s["instrument_id"], "direction": s["direction"],
                        "signal_ts": s["source_candle_ts"], "entry_time": ec.iso(entry_time),
                        "deadline": ec.iso(deadline), "retry_count": st["retries"],
                        "availability": av, "source": res["source"],
                        "fill_price": res["price"], "fill_ts": res["fill_ts"],
                        "price_ts": res.get("price_ts"), "latency_s": res["latency_s"],
                        "reject": reject_reasons(res["attempts"]),
                    })
                    emitted += 1

        if (now >= deadline and status in ("NEW", "EXPIRED")
                and "unresolved" not in events and "proposal" not in events):
            res = ec.resolve(s["instrument_id"], entry_time, deadline, now=now,
                             historical=hist)
            av = availability(res["attempts"])
            provider_failure = not (av.get("provider_5m") or av.get("one_min") or av.get("quote"))
            if res["resolved"]:
                events["proposal"] = True
                st["proposal"] = {
                    "source": res["source"], "price": res["price"],
                    "fill_ts": res["fill_ts"], "latency_s": res["latency_s"],
                    "classification": "LATE_PROPOSAL", "late": True,
                }
                ec.append_jsonl(ec.EVENTS_PATH, {
                    "event": "proposal_late", "classification": "LATE_PROPOSAL", "at": ec.iso(now), "signal_id": sid,
                    "instrument": s["instrument_id"], "direction": s["direction"],
                    "signal_ts": s["source_candle_ts"], "entry_time": ec.iso(entry_time),
                    "deadline": ec.iso(deadline), "retry_count": st["retries"],
                    "availability": av, "source": res["source"],
                    "fill_price": res["price"], "fill_ts": res["fill_ts"],
                    "price_ts": res.get("price_ts"), "latency_s": res["latency_s"],
                    "reject": reject_reasons(res["attempts"]),
                })
            else:
                events["unresolved"] = True
                st["unresolved"] = {"retries": st["retries"], "availability": av,
                                    "provider_failure": provider_failure}
                ec.append_jsonl(ec.EVENTS_PATH, {
                    "event": "unresolved", "at": ec.iso(now), "signal_id": sid,
                    "instrument": s["instrument_id"], "direction": s["direction"],
                    "signal_ts": s["source_candle_ts"], "entry_time": ec.iso(entry_time),
                    "deadline": ec.iso(deadline), "retry_count": st["retries"],
                    "availability": av, "provider_failure": provider_failure,
                    "expiry_reason": s.get("last_error"),
                    "reject": reject_reasons(res["attempts"]),
                })
            emitted += 1

        # Final outcome once production has decided.
        if status in ("TRADED", "EXPIRED", "IGNORED") and "outcome" not in events:
            trade = load_trade(s["paper_trade_id"]) if status == "TRADED" else None
            actual_entry = None
            actual_entry_ts = None
            source = None
            if trade:
                try:
                    actual_entry = float(trade["entry"])
                except Exception:
                    actual_entry = None
                actual_entry_ts = trade.get("entry_time")
                db5 = ec.db_candle_5m(s["instrument_id"], entry_time)
                if db5 and actual_entry is not None:
                    try:
                        if abs(actual_entry - float(db5["open"])) < 0.01:
                            source = "5m_open"
                    except Exception:
                        pass
            proposal = st.get("proposal")
            delta = None
            recovered = False
            if proposal and status == "EXPIRED":
                recovered = True
                try:
                    delta = round(proposal["price"] - float(s["reference_price"]), 4)
                except Exception:
                    delta = None
            elif proposal and actual_entry is not None:
                delta = round(proposal["price"] - actual_entry, 4)
                recovered = abs(delta) < 5.0
            events["outcome"] = True
            ec.append_jsonl(ec.EVENTS_PATH, {
                "event": "outcome", "at": ec.iso(now), "signal_id": sid,
                "instrument": s["instrument_id"], "direction": s["direction"],
                "signal_ts": s["source_candle_ts"], "trade_date": s["trade_date"],
                "status": status, "expiry_reason": s.get("last_error"),
                "actual_entry": actual_entry, "actual_entry_time": actual_entry_ts,
                "actual_price_source": source,
                "shadow_classification": (proposal or {}).get("classification"),
                "shadow_source": (proposal or {}).get("source"),
                "shadow_price": (proposal or {}).get("price"),
                "shadow_fill_ts": (proposal or {}).get("fill_ts"),
                "shadow_latency_s": (proposal or {}).get("latency_s"),
                "delta_points": delta, "recovered": recovered,
                "retry_count": st.get("retries", 0),
            })
            emitted += 1

    state["last_poll"] = ec.iso(now)
    save_state(state)
    return emitted


def session_stats():
    conn = ec.db_connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            "SELECT trade_date, status, COALESCE(last_error,'') err, COUNT(*) n "
            "FROM scalp_signals GROUP BY trade_date, status, err ORDER BY trade_date"
        ).fetchall()
    finally:
        conn.close()

    sessions = {}
    for r in rows:
        d = sessions.setdefault(r["trade_date"], {
            "date": r["trade_date"], "total": 0, "traded": 0, "expired": 0,
            "ignored": 0, "new": 0, "entry_candle_closed": 0, "provider_failures": 0,
            "stale_rejections": 0, "service_interruptions": None,
            "shadow_proposals": 0, "shadow_live_captures": 0,
            "late_proposals": 0, "shadow_recovered_missed": 0,
        })
        n = r["n"]
        d["total"] += n
        st = (r["status"] or "").upper()
        if st == "TRADED":
            d["traded"] += n
        elif st == "EXPIRED":
            d["expired"] += n
            if r["err"] == "entry_candle_closed":
                d["entry_candle_closed"] += n
        elif st == "IGNORED":
            d["ignored"] += n
        elif st == "NEW":
            d["new"] += n

    # Event-derived counts.
    stale_sigs = {}
    if os.path.exists(ec.EVENTS_PATH):
        with open(ec.EVENTS_PATH) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                day = (e.get("trade_date") or (e.get("signal_ts") or "")[:10])
                if day not in sessions:
                    continue
                if e.get("event") == "proposal":
                    sessions[day]["shadow_proposals"] += 1
                    sessions[day]["shadow_live_captures"] += 1
                if e.get("event") == "proposal_late":
                    sessions[day]["late_proposals"] += 1
                if e.get("event") == "unresolved" and e.get("provider_failure"):
                    sessions[day]["provider_failures"] += 1
                if (e.get("event") == "outcome" and e.get("status") == "EXPIRED"
                        and e.get("shadow_classification") == "LIVE_CAPTURE"):
                    sessions[day]["shadow_recovered_missed"] += 1
                reject = e.get("reject") or {}
                if isinstance(reject, dict) and any("stale" in str(v) for v in reject.values()):
                    stale_sigs.setdefault(day, set()).add(e.get("signal_id"))

    for day, sigs in stale_sigs.items():
        if day in sessions:
            sessions[day]["stale_rejections"] = len(sigs)

    # Service interruptions from journal (best effort).
    for day, d in sessions.items():
        try:
            out = subprocess.run(
                ["journalctl", "-u", "tradingai-paper-scalp-live", "--since",
                 f"{day} 09:00:00", "--until", f"{day} 15:40:00", "--no-pager"],
                capture_output=True, text=True, timeout=20).stdout
            d["service_interruptions"] = max(0, len(re.findall(r"systemd\[\d+\]: Started ", out)) - 1)
        except Exception:
            d["service_interruptions"] = None

    ec.ensure_dirs()
    out_path = os.path.join(ec.SHADOW_DIR, "session_stats.json")
    with open(out_path, "w") as fh:
        json.dump(list(sessions.values()), fh, indent=2)
    print(json.dumps(list(sessions.values()), indent=2))
    print("WROTE", out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entry-capture shadow monitor")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--force", action="store_true", help="process even if market closed")
    ap.add_argument("--report", action="store_true", help="print per-session statistics")
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD session override")
    args = ap.parse_args(argv)

    if args.report:
        session_stats()
        return 0

    ec.ensure_dirs()
    lock = open(ec.LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another entry_shadow instance holds the lock; exiting")
        return 0

    print("entry_shadow started", flush=True)
    while True:
        now = ec.now_ist()
        try:
            n = process(now, force=args.force, day=args.date)
            if n:
                print(f"{ec.iso(now)} shadow events={n}", flush=True)
        except Exception as exc:  # noqa: BLE001 - never crash the monitor
            print(f"{ec.iso(now)} shadow error: {exc}", flush=True)
        if args.once:
            return 0
        interval = args.interval or (5 if market_open(now) else 60)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
