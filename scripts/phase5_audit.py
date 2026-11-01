#!/usr/bin/env python3
"""Phase 5 read-only audit and reporting for entry-capture evidence."""
import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "tradingai.db")
EVENTS = os.path.join(BASE, "logs", "entry_shadow", "events.jsonl")
PROBE = os.path.join(BASE, "logs", "data_probe", "observations.jsonl")
SELFTEST = os.path.join(BASE, "logs", "data_probe", "selftest.json")
REPORTS = os.path.join(BASE, "reports")
REPLAY = os.path.join(BASE, "logs", "entry_shadow", "replay_20261031-145849.json")
DATES = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
SELFTEST_MAX_AGE_S = 24 * 60 * 60
SNAPSHOT_MAX_AGE_S = 7 * 24 * 60 * 60
UNITS = ["tradingai-paper-scalp-live", "tradingai-entry-shadow",
         "tradingai-data-probe", "tradingai-market-data.timer",
         "tradingai-api", "tradingai-scalp-alerts", "tradingai-live-dashboard"]


def now_ist():
    return datetime.now(IST)


def parse(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except Exception:
        return None


def iso(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat(timespec="seconds")


def secs(a, b):
    a, b = parse(a), parse(b)
    if a is None or b is None:
        return None
    return round((a - b).total_seconds(), 3)


def pctl(vals, p):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, math.ceil(p / 100.0 * len(s)) - 1))
    return round(s[k], 3)


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0, "median": None, "p95": None, "max": None}
    return {"n": len(vals), "median": round(statistics.median(vals), 3),
            "p95": pctl(vals, 95), "max": round(max(vals), 3)}


def db_counts():
    import sqlite3
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        out = {"signals": c.execute("select count(*) from scalp_signals").fetchone()[0],
               "trades": c.execute("select count(*) from paper_trades").fetchone()[0],
               "candles_5m": c.execute("select count(*) from market_candles_5m").fetchone()[0],
               "candles_1m": 0, "integrity": c.execute("pragma integrity_check").fetchone()[0],
               "dup_trade_id": c.execute(
                   "select count(*) from (select trade_id from paper_trades "
                   "group by trade_id having count(*)>1)").fetchone()[0],
               "open_positions": c.execute(
                   "select count(*) from paper_trades where upper(status) in ('OPEN','PENDING')"
               ).fetchone()[0]}
        try:
            out["candles_1m"] = c.execute("select count(*) from market_candles_1m").fetchone()[0]
        except Exception:
            pass
        return out
    finally:
        c.close()


def load_signals(day):
    import sqlite3
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "select signal_id, trade_date, instrument_id, direction, source_candle_ts, "
            "reference_price, reference_stop, reference_target, status, paper_trade_id, "
            "last_error, created_at, updated_at from scalp_signals where trade_date=? "
            "order by instrument_id, source_candle_ts", (day,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def load_trades():
    import sqlite3
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute("select trade_id, entry, entry_time, exit_time, exit_price, "
                         "status, paper_pnl from paper_trades").fetchall()
        return {r["trade_id"]: dict(r) for r in rows}
    finally:
        c.close()


def load_signals_candles(day):
    import sqlite3
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "select instrument_id, timestamp, open, close, ingested_at, is_complete "
            "from market_candles_5m where substr(timestamp,1,10)=?",
            (day,)).fetchall()
        return {(r["instrument_id"], r["timestamp"]): dict(r) for r in rows}
    finally:
        c.close()


def read_jsonl(path):
    out = []
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    out.append({"event": "parse_error", "raw": line[:200]})
    except (OSError, IOError):
        return out
    return out


def pct_text(value):
    return "N/A" if value is None else f"{value}%"


def base_source(path):
    return {"path": path, "exists": False, "readable": False, "mtime": None,
            "freshness": "UNKNOWN", "records": None, "status": "MISSING",
            "detail": "file not found"}


def file_meta(rec, path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return rec
    except Exception as exc:
        rec.update(status="UNREADABLE", detail=f"stat failed: {exc}")
        return rec
    rec["exists"] = True
    rec["mtime"] = iso(datetime.fromtimestamp(st.st_mtime, IST))
    try:
        with open(path, "rb") as fh:
            fh.read(1)
        rec["readable"] = True
    except Exception as exc:
        rec.update(status="UNREADABLE", detail=f"read failed: {exc}")
    return rec


def validate_jsonl_source(path, kind, day, now, signals_count=None):
    rec = file_meta(base_source(path), path)
    if not rec["exists"]:
        return rec
    if not rec["readable"]:
        return rec
    parsed, errors = [], 0
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed.append(json.loads(line))
                except Exception:
                    errors += 1
    except Exception as exc:
        rec.update(status="UNREADABLE", detail=f"parse read failed: {exc}")
        return rec
    if kind == "events":
        day_rows = [r for r in parsed
                    if (r.get("trade_date") or (r.get("signal_ts") or "")[:10]) == day]
    else:
        day_rows = [r for r in parsed
                    if r.get("event") == "observation"
                    and (r.get("target_close") or "")[:10] == day]
    rec["records"] = len(day_rows)
    mdt = parse(rec["mtime"])
    if mdt is None:
        rec.update(status="INVALID", detail="unparseable file mtime")
        return rec
    if mdt.date().isoformat() != day:
        rec["freshness"] = "STALE"
        rec.update(status="STALE",
                   detail=f"file mtime {rec['mtime']} is not on session date {day}")
    else:
        rec["freshness"] = "FRESH"
    if errors:
        rec.update(status="INVALID", detail=f"{errors} unparseable JSONL line(s)")
        return rec
    if kind == "events" and not day_rows and signals_count:
        rec.update(status="INVALID",
                   detail=f"0 events for {signals_count} signals on {day}")
        return rec
    if kind == "probe" and not day_rows:
        rec.update(status="INVALID", detail=f"0 probe observations for {day}")
        return rec
    if rec["status"] not in ("STALE", "INVALID"):
        rec["status"] = "OK"
        rec["detail"] = ""
    return rec


def validate_selftest(path, now):
    rec = file_meta(base_source(path), path)
    if not rec["exists"] or not rec["readable"]:
        return rec
    try:
        with open(path) as fh:
            st = json.load(fh)
    except Exception as exc:
        rec.update(status="INVALID", detail=f"invalid JSON: {exc}")
        return rec
    ro = st.get("readonly")
    readonly = bool(ro[0]) if isinstance(ro, list) and ro else bool(ro)
    rec["records"] = 1
    mdt = parse(rec["mtime"])
    age = (now - mdt).total_seconds() if mdt else None
    if age is not None and 0 <= age <= SELFTEST_MAX_AGE_S:
        rec["freshness"] = "FRESH"
    else:
        rec["freshness"] = "STALE"
    if readonly is not True:
        rec.update(status="INVALID", detail="selftest readonly is not true")
    elif age is None or age > SELFTEST_MAX_AGE_S or age < 0:
        rec.update(status="STALE",
                   detail=f"selftest age {None if age is None else round(age,1)}s exceeds "
                          f"{SELFTEST_MAX_AGE_S}s")
    else:
        rec.update(status="OK", detail=f"selftest age {round(age,1)}s "
                                        f"(threshold {SELFTEST_MAX_AGE_S}s)")
    return rec


def validate_snapshot(path, day, label, now):
    rec = file_meta(base_source(path), path)
    if not rec["exists"] or not rec["readable"]:
        return rec
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:
        rec.update(status="INVALID", detail=f"invalid JSON: {exc}")
        return rec
    if not isinstance(data, dict) or data.get("date") != day:
        rec.update(status="INVALID", detail=f"snapshot date is not {day}")
        return rec
    if data.get("label") != label:
        rec.update(status="INVALID", detail=f"snapshot label is not {label}")
        return rec
    if not isinstance(data.get("counts"), dict):
        rec.update(status="INVALID", detail="snapshot counts missing")
        return rec
    rec["records"] = len(data["counts"])
    mdt = parse(rec["mtime"])
    age = (now - mdt).total_seconds() if mdt else None
    expected = (mdt.date().isoformat() <= day) if label == "pre" else (mdt.date().isoformat() >= day)
    if age is not None and 0 <= age <= SNAPSHOT_MAX_AGE_S and expected:
        rec["freshness"] = "FRESH"
        rec.update(status="OK", detail=f"snapshot age {round(age,1)}s "
                                        f"(threshold {SNAPSHOT_MAX_AGE_S}s)")
    else:
        rec["freshness"] = "STALE"
        rec.update(status="STALE",
                   detail=f"snapshot mtime {rec['mtime']} is outside expected "
                          f"{label} range for {day} or older than {SNAPSHOT_MAX_AGE_S}s")
    return rec


def validate_replay(path, now):
    rec = file_meta(base_source(path), path)
    if not rec["exists"] or not rec["readable"]:
        return rec
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:
        rec.update(status="INVALID", detail=f"invalid JSON: {exc}")
        return rec
    if not isinstance(data, dict) or not data.get("counts"):
        rec.update(status="INVALID", detail="replay counts missing")
        return rec
    rec["records"] = len(data.get("counts") or {})
    rec["freshness"] = "N/A"
    rec.update(status="OK", detail="historical replay file readable")
    return rec


def validate_sources(day, events_path, probe_path, selftest_path, pre_path, post_path,
                     counts, health, errors, signals_count, skip_system, now):
    sources = {
        "entry_shadow_events": validate_jsonl_source(
            events_path, "events", day, now, signals_count),
        "data_probe_observations": validate_jsonl_source(
            probe_path, "probe", day, now),
        "data_probe_selftest": validate_selftest(selftest_path, now),
        "snapshot_pre": validate_snapshot(pre_path, day, "pre", now),
        "snapshot_post": validate_snapshot(post_path, day, "post", now),
        "database": {"path": DB_PATH, "exists": os.path.exists(DB_PATH),
                     "readable": os.access(DB_PATH, os.R_OK),
                     "mtime": iso(datetime.fromtimestamp(os.stat(DB_PATH).st_mtime, IST))
                     if os.path.exists(DB_PATH) else None,
                     "freshness": "N/A", "records": counts.get("signals"),
                     "status": "OK" if counts.get("integrity") == "ok" else "INVALID",
                     "detail": f"integrity={counts.get('integrity')}"},
    }
    if skip_system:
        for key, label in (("systemd_state", "systemd state"),
                           ("journal_errors", "journal errors")):
            sources[key] = {"path": "systemctl/journalctl", "exists": False,
                            "readable": False, "mtime": None, "freshness": "SKIPPED",
                            "records": None, "status": "OK",
                            "detail": f"{label} skipped by operator (--skip-system); "
                                      "service gate not evaluated"}
    else:
        sources["systemd_state"] = {
            "path": "systemctl show", "exists": bool(health), "readable": bool(health),
            "mtime": iso(now), "freshness": "FRESH", "records": len(health or {}),
            "status": "OK" if health and not any("error" in s for s in health.values())
            else "INVALID",
            "detail": "all units returned state" if health else "no systemd state"}
        sources["journal_errors"] = {
            "path": "journalctl", "exists": bool(errors), "readable": bool(errors),
            "mtime": iso(now), "freshness": "FRESH",
            "records": (errors or {}).get("count"),
            "status": "OK" if errors and errors.get("count") is not None else "INVALID",
            "detail": (errors or {}).get("error") or "journal query completed"}
    reasons = [f"{key}: {s['status']} — {s['detail']}"
               for key, s in sources.items() if s["status"] != "OK"]
    return sources, reasons


def safe_write(path, text):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
    except FileExistsError:
        print(f"REFUSED: {path} exists; choose a new output directory")
        return False
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return True


def service_state():
    out = {}
    for u in UNITS:
        try:
            raw = subprocess.run(
                ["systemctl", "show", "-p", "ActiveState", "-p", "SubState",
                 "-p", "NRestarts", "-p", "MainPID", u],
                capture_output=True, text=True, timeout=10).stdout
            kv = {}
            for line in raw.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k] = v
            out[u] = {"active": kv.get("ActiveState"),
                      "sub": kv.get("SubState"),
                      "nrestarts": int(kv["NRestarts"]) if kv.get("NRestarts", "").isdigit() else None,
                      "pid": kv.get("MainPID")}
        except Exception as exc:
            out[u] = {"error": str(exc)}
    return out


def journal_errors(day):
    since = f"{day} 00:00:00"; until = f"{day} 23:59:59"
    cmd = ["journalctl", "--since", since, "--until", until, "-p", "err",
           "--no-pager", "-o", "cat"]
    for u in UNITS:
        if u.endswith(".timer"):
            continue
        cmd += ["-u", u]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        return {"count": len(lines), "sample": lines[:10]}
    except Exception as exc:
        return {"count": None, "error": str(exc)}


def probe_index(path, day):
    idx = defaultdict(list)
    for r in read_jsonl(path):
        if r.get("event") != "observation":
            continue
        if (r.get("target_close") or "")[:10] != day:
            continue
        idx[(r.get("instrument"), r.get("target_close"))].append(r)
    for k in idx:
        idx[k].sort(key=lambda x: x.get("offset_actual_s") or 0)
    return idx


def first_probe(rows, pred):
    for r in rows:
        try:
            if pred(r):
                return r
        except Exception:
            continue
    return None


def classify(status, shadow_class):
    st = (status or "").upper()
    if st == "IGNORED":
        return "IGNORED"
    if st == "TRADED":
        return "TRADED"
    if st == "EXPIRED":
        if shadow_class == "LIVE_CAPTURE":
            return "MISSED_EXECUTION"
        if shadow_class == "LATE_PROPOSAL":
            return "LATE_PROPOSAL"
        return "EXPIRED_UNRESOLVED"
    if shadow_class == "LIVE_CAPTURE":
        return "LIVE_CAPTURE"
    if shadow_class == "LATE_PROPOSAL":
        return "LATE_PROPOSAL"
    return st or "UNKNOWN"


def build_day(day, events_path, probe_path):
    signals = load_signals(day)
    trades = load_trades()
    candles = load_signals_candles(day)
    events = [e for e in read_jsonl(events_path)
              if (e.get("trade_date") or (e.get("signal_ts") or "")[:10]) == day]
    ev = defaultdict(list)
    for e in events:
        ev[e.get("signal_id")].append(e)
    obs = probe_index_for(probe_path, day)
    rows = []
    for s in signals:
        sid = s["signal_id"]
        src = s.get("source_candle_ts")
        src_dt = parse(src)
        close_dt = src_dt + timedelta(minutes=5) if src_dt else None
        entry_dt = close_dt
        deadline_dt = entry_dt + timedelta(minutes=5) if entry_dt else None
        ce = sorted(ev.get(sid, []), key=lambda e: e.get("at") or "")
        attempts = [e for e in ce if e.get("event") == "attempt"]
        prop = next((e for e in ce if e.get("event") == "proposal"), None)
        late = next((e for e in ce if e.get("event") == "proposal_late"), None)
        outcome = next((e for e in ce if e.get("event") == "outcome"), None)
        chosen = prop or late
        shadow_class = (chosen or {}).get("classification")
        shadow_price = (chosen or {}).get("fill_price")
        shadow_source = (chosen or {}).get("source")
        shadow_fill_ts = (chosen or {}).get("fill_ts")
        trade = trades.get(s.get("paper_trade_id")) if s.get("paper_trade_id") else None
        actual_entry = trade.get("entry") if trade else None
        if actual_entry is None and outcome:
            actual_entry = outcome.get("actual_entry")
        diff = None
        diff_basis = None
        try:
            if shadow_price is not None and actual_entry is not None:
                diff = round(abs(float(shadow_price) - float(actual_entry)), 4)
                diff_basis = "engine_entry"
            elif shadow_price is not None and s.get("reference_price") is not None:
                diff = round(abs(float(shadow_price) - float(s["reference_price"])), 4)
                diff_basis = "reference_price"
        except Exception:
            diff = None
        c5 = candles.get((s["instrument_id"], src)) or {}
        ingested = c5.get("ingested_at")
        first_event = None
        for e in ce:
            if e.get("event") in ("attempt", "proposal"):
                first_event = e
                break
        attempt_at = (first_event or {}).get("at")
        retry_count = max([e.get("retry_count") or 0 for e in ce] or [0])
        o_rows = obs.get((s["instrument_id"], iso(entry_dt)), [])
        r1 = first_probe(o_rows, lambda r: (r.get("provider_1m_entry") or {}).get("present"))
        q1 = first_probe(o_rows, lambda r: (r.get("quote") or {}).get("present")
                         and (r.get("quote") or {}).get("state") == "FRESH")
        dbe = first_probe(o_rows, lambda r: (r.get("db_5m_entry") or {}).get("present"))
        min1 = (r1 or {}).get("provider_1m_entry") or {}
        quote = (q1 or {}).get("quote") or {}
        invalid = []
        if src_dt is None:
            invalid.append("source_candle_ts")
        if parse(s.get("created_at")) is None:
            invalid.append("created_at")
        if close_dt and parse(s.get("created_at")) and parse(s["created_at"]) < close_dt - timedelta(seconds=1):
            invalid.append("created_before_close")
        if close_dt and parse(ingested) and parse(ingested) < close_dt - timedelta(seconds=1):
            invalid.append("ingested_before_close")
        if prop and shadow_class == "LIVE_CAPTURE":
            if parse(shadow_fill_ts) and (parse(shadow_fill_ts) < entry_dt
                                          or parse(shadow_fill_ts) >= deadline_dt):
                invalid.append("live_capture_fill_outside_window")
        if attempt_at and entry_dt and parse(attempt_at) and parse(attempt_at) < entry_dt - timedelta(seconds=1):
            invalid.append("attempt_before_entry")
        if (r1 or {}).get("offset_actual_s") is not None and r1["offset_actual_s"] < 0:
            invalid.append("probe_negative_offset")
        row = {
            "signal_id": sid, "instrument": s["instrument_id"], "direction": s.get("direction"),
            "status": s.get("status"), "last_error": s.get("last_error"),
            "source_candle_ts": src, "source_close": iso(close_dt),
            "db_ingested_at": ingested,
            "db_ingest_latency_s": secs(ingested, close_dt),
            "signal_created_at": s.get("created_at"),
            "persistence_latency_s": secs(s.get("created_at"), close_dt),
            "entry_time": iso(entry_dt), "entry_deadline": iso(deadline_dt),
            "shadow_first_attempt_at": attempt_at,
            "shadow_attempt_latency_s": secs(attempt_at, entry_dt),
            "first_1m_ts": (min1 or {}).get("data_ts"),
            "first_1m_open": (min1 or {}).get("open"),
            "first_1m_available_s": (r1 or {}).get("offset_actual_s"),
            "first_quote_ts": (quote or {}).get("data_ts"),
            "first_quote_price": (quote or {}).get("price"),
            "first_quote_available_s": (q1 or {}).get("offset_actual_s"),
            "db_entry_ingested_at": ((dbe or {}).get("db_5m_entry") or {}).get("ingested_at"),
            "shadow_price": shadow_price, "shadow_source": shadow_source,
            "shadow_fill_ts": shadow_fill_ts,
            "shadow_classification": shadow_class,
            "shadow_latency_s": (chosen or {}).get("latency_s"),
            "actual_entry": actual_entry,
            "engine_entry_time": (trade or {}).get("entry_time"),
            "price_diff_points": diff, "price_diff_basis": diff_basis,
            "class": classify(s.get("status"), shadow_class),
            "live_capture": shadow_class == "LIVE_CAPTURE",
            "persisted_in_window": bool(parse(s.get("created_at")) and deadline_dt
                                        and parse(s["created_at"]) < deadline_dt),
            "late_proposal": shadow_class == "LATE_PROPOSAL",
            "attempt_events": len(attempts), "retry_count": retry_count,
            "probe_observations": len(o_rows),
            "duplicate_proposals": len([e for e in ce if e.get("event") in ("proposal", "proposal_late")]),
            "invalid": invalid,
        }
        rows.append(row)
    return rows, events


def probe_index_for(path, day):
    return probe_index(path, day)


def summarize(rows):
    eligible = [r for r in rows if (r["status"] or "").upper() != "IGNORED"]
    live = [r for r in eligible if r["live_capture"]]
    traded = [r for r in rows if (r["status"] or "").upper() == "TRADED"]
    expired = [r for r in rows if (r["status"] or "").upper() == "EXPIRED"]
    ignored = [r for r in rows if (r["status"] or "").upper() == "IGNORED"]
    diffs = [r["price_diff_points"] for r in traded if r["price_diff_points"] is not None]
    diffs_all = [r["price_diff_points"] for r in rows if r["price_diff_points"] is not None]
    classes = defaultdict(int)
    for r in rows:
        classes[r["class"]] += 1
    return {
        "signals": len(rows), "eligible": len(eligible),
        "live_capture": len(live),
        "live_capture_pct": round(100.0 * len(live) / len(eligible), 2) if eligible else None,
        "persisted_in_window": sum(1 for r in eligible if r["persisted_in_window"]),
        "persisted_in_window_pct": round(100.0 * sum(1 for r in eligible if r["persisted_in_window"]) / len(eligible), 2) if eligible else None,
        "probe_coverage_pct": round(100.0 * sum(1 for r in eligible if r["probe_observations"] > 0) / len(eligible), 2) if eligible else None,
        "late_proposals": sum(1 for r in eligible if r["late_proposal"]),
        "missed_execution": sum(1 for r in rows if r["class"] == "MISSED_EXECUTION"),
        "traded": len(traded), "ignored": len(ignored), "expired": len(expired),
        "classification_counts": dict(sorted(classes.items())),
        "price_diff_traded": stats(diffs),
        "price_diff_all": stats(diffs_all),
        "ingest_latency": stats([r["db_ingest_latency_s"] for r in rows]),
        "persistence_latency": stats([r["persistence_latency_s"] for r in rows]),
        "attempt_latency": stats([r["shadow_attempt_latency_s"] for r in rows]),
        "first_1m_latency": stats([r["first_1m_available_s"] for r in rows]),
        "first_quote_latency": stats([r["first_quote_available_s"] for r in rows]),
        "duplicate_proposals": sum(max(0, r["duplicate_proposals"] - 1) for r in rows),
        "invalid_timestamps": sum(len(r["invalid"]) for r in rows),
        "invalid_signals": [r["signal_id"] for r in rows if r["invalid"]],
        "by_instrument": {i: summarize_group(rows, i) for i in ("NIFTY", "BANKNIFTY")},
    }


def summarize_group(rows, inst):
    g = [r for r in rows if r["instrument"] == inst]
    e = [r for r in g if (r["status"] or "").upper() != "IGNORED"]
    return {"signals": len(g), "eligible": len(e),
            "live_capture": sum(1 for r in e if r["live_capture"]),
            "live_capture_pct": round(100.0 * sum(1 for r in e if r["live_capture"]) / len(e), 2) if e else None,
            "late_proposals": sum(1 for r in e if r["late_proposal"]),
            "traded": sum(1 for r in g if (r["status"] or "").upper() == "TRADED"),
            "ignored": sum(1 for r in g if (r["status"] or "").upper() == "IGNORED")}


def gate(name, value, target, passed):
    return {"gate": name, "value": value, "target": target,
            "result": "PASS" if passed else ("NOT_EVALUATED" if passed is None else "FAIL")}


def readonly_audit(selftest_path=SELFTEST):
    details = {"selftest_readonly": None, "write_sql": [], "mode_ro": {}, "ok": False}
    try:
        with open(selftest_path) as fh:
            st = json.load(fh)
        ro = st.get("readonly")
        details["selftest_readonly"] = bool(ro[0]) if isinstance(ro, list) and ro else bool(ro)
    except Exception as exc:
        details["selftest_error"] = str(exc)
    sql_patterns = ("insert into", "update ", "delete from", "replace into", "drop table")
    allowed = "UPDATE scalp_signals SET updated_at=updated_at WHERE 0".lower()
    for name in ("entry_shadow.py", "entry_capture.py", "data_probe.py"):
        try:
            with open(os.path.join(BASE, "scripts", name)) as fh:
                txt = fh.read()
            low = txt.lower().replace(allowed, "")
            details["mode_ro"][name] = ("mode=ro" in txt) or ("ec.db_connect()" in txt)
            for kw in sql_patterns:
                if kw in low:
                    details["write_sql"].append(f"{name}:{kw.strip()}")
        except Exception as exc:
            details["mode_ro"][name] = f"error:{exc}"
    details["ok"] = (details.get("selftest_readonly") is True
                     and not details["write_sql"]
                     and all(v is True for v in details["mode_ro"].values()))
    return details


def evaluate(rows, summary, counts, pre, post, health, errors,
             status="COMPLETE", reasons=None, selftest_path=SELFTEST):
    gates = []
    gates.append(gate("Required evidence complete",
                      "all sources OK" if status == "COMPLETE" else "; ".join(reasons or []),
                      "all sources OK", status == "COMPLETE"))
    gates.append(gate("LIVE_CAPTURE rate >= 95% of eligible",
                      summary["live_capture_pct"], ">=95%",
                      None if not summary["eligible"] else summary["live_capture_pct"] >= 95.0))
    md = summary["price_diff_traded"]["median"]
    p95 = summary["price_diff_traded"]["p95"]
    gates.append(gate("Median entry-price difference <= 2 points",
                      md, "<=2", None if md is None else md <= 2.0))
    gates.append(gate("95th percentile entry-price difference <= 5 points",
                      p95, "<=5", None if p95 is None else p95 <= 5.0))
    gates.append(gate("Zero duplicate proposals", summary["duplicate_proposals"], "0",
                      summary["duplicate_proposals"] == 0))
    gates.append(gate("Zero invalid timestamps", summary["invalid_timestamps"], "0",
                      summary["invalid_timestamps"] == 0))
    ro = readonly_audit(selftest_path)
    gates.append(gate("Zero shadow database writes (read-only verified)", ro, "read-only", ro["ok"]))
    restart_delta = None
    if pre and pre.get("services") and health:
        try:
            restart_delta = sum(
                (health.get(u, {}).get("nrestarts") or 0)
                - (pre["services"].get(u, {}).get("nrestarts") or 0)
                for u in health)
        except Exception:
            restart_delta = None
    unexplained = (errors.get("count") or 0) > 0 if errors else False
    if restart_delta:
        unexplained = True
    if not errors and restart_delta is None:
        g = gate("Zero unexplained service interruptions", None, "0", None)
    else:
        g = gate("Zero unexplained service interruptions",
                 {"journal_errors": (errors or {}).get("count"),
                  "restart_delta": restart_delta}, "0", not unexplained)
    gates.append(g)
    if status == "INCOMPLETE":
        gates[0]["result"] = "FAIL"
        for g in gates[1:]:
            g["result"] = "NOT_EVALUATED"
            g["value"] = f"NOT EVALUATED — incomplete evidence: {g['value']}"
    return gates


def md_table(rows):
    out = ["| signal | inst | dir | source close | db ingest | created | deadline | shadow attempt | 1m ts/open | quote ts/price | shadow price/source | engine entry | diff | class | status | notes |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| {sid} | {inst} | {dir} | {sc} | {db} | {ca} | {dl} | {at} | {m1} | {q} | {sp} | {ae} | {df} | {cl} | {st} | {nt} |".format(
            sid=r["signal_id"], inst=r["instrument"], dir=r["direction"],
            sc=r["source_close"], db=r["db_ingested_at"], ca=r["signal_created_at"],
            dl=r["entry_deadline"], at=r["shadow_first_attempt_at"],
            m1=f"{r['first_1m_ts']} / {r['first_1m_open']}",
            q=f"{r['first_quote_ts']} / {r['first_quote_price']}",
            sp=f"{r['shadow_price']} / {r['shadow_source']}",
            ae=r["actual_entry"], df=r["price_diff_points"], cl=r["class"],
            st=r["status"], nt="; ".join(r["invalid"]) or (r["last_error"] or "")))
    return "\n".join(out)


def write_md(day, rows, summary, gates, counts, pre, post, health, errors, out_dir,
             dry, status, sources, reasons, selftest_path=SELFTEST):
    os.makedirs(out_dir, exist_ok=True)
    suffix = "_DRYRUN" if dry else ""
    path = os.path.join(out_dir, f"phase5_daily_{day.replace('-','')}{suffix}.md")
    tag = ("DRY RUN — historical/backfill only; NOT live evidence." if dry
           else "LIVE SESSION EVIDENCE.")
    lines = [f"# Phase 5 Entry Capture — {day}", "", f"**{tag}**", "",
             f"**Daily status: {status}**", "",
             f"Generated: {iso(now_ist())}", "",
             "## Summary", "",
             f"- Eligible signals: **{summary['eligible']}** of {summary['signals']}",
             f"- LIVE_CAPTURE: **{summary['live_capture']}** ({pct_text(summary['live_capture_pct'])})",
             f"- Signals persisted before deadline: {summary['persisted_in_window']} ({pct_text(summary['persisted_in_window_pct'])})",
             f"- Probe coverage of eligible signals: {pct_text(summary['probe_coverage_pct'])}",
             f"- LATE_PROPOSAL: {summary['late_proposals']}",
             f"- MISSED_EXECUTION: {summary['missed_execution']}",
             f"- TRADED: {summary['traded']}  |  IGNORED: {summary['ignored']}  |  EXPIRED: {summary['expired']}",
             f"- Classification counts: `{json.dumps(summary['classification_counts'])}`",
             "", "## Evidence completeness", "",
             f"- Daily status: **{status}**",
             f"- selftest freshness threshold: **{SELFTEST_MAX_AGE_S}s "
             f"({SELFTEST_MAX_AGE_S // 3600}h)** from file mtime.",
             f"- Snapshot freshness threshold: **{SNAPSHOT_MAX_AGE_S}s "
             f"({SNAPSHOT_MAX_AGE_S // 86400}d)**; pre mtime must be on/before "
             f"the session date, post mtime on/after it.",
             "- Events and probe files must be modified on the session date.",
             "- Any required source not `OK` makes the daily result `INCOMPLETE`; "
             "capture rate is then N/A and gates are not evaluated.", ""]
    if reasons:
        lines += ["Missing/invalid evidence:", ""] + [f"- {r}" for r in reasons] + [""]
    lines += ["| source | path | exists | readable | mtime | freshness | records | status | detail |",
              "|---|---|---|---|---|---|---|---|---|"]
    for key, s in sources.items():
        lines.append(f"| {key} | `{s['path']}` | {s['exists']} | {s['readable']} | "
                     f"{s['mtime']} | {s['freshness']} | {s['records']} | "
                     f"**{s['status']}** | {s['detail']} |")
    lines += ["", "## Acceptance gates", "",
              "| gate | measured | target | result |", "|---|---|---|---|"]
    for g in gates:
        lines.append(f"| {g['gate']} | {g['value']} | {g['target']} | **{g['result']}** |")
    lines += ["", "## Latency (seconds)", "",
              "| metric | n | median | p95 | max |", "|---|---|---|---|---|"]
    for name, key in [("Candle ingestion", "ingest_latency"),
                      ("Signal persistence", "persistence_latency"),
                      ("Shadow first attempt", "attempt_latency"),
                      ("First 1m candle availability", "first_1m_latency"),
                      ("First fresh quote availability", "first_quote_latency")]:
        s = summary[key]
        lines.append(f"| {name} | {s['n']} | {s['median']} | {s['p95']} | {s['max']} |")
    lines += ["", "## Entry-price difference (points)", "",
              f"- TRADED vs engine entry: `{json.dumps(summary['price_diff_traded'])}`",
              f"- All available pairs: `{json.dumps(summary['price_diff_all'])}`", "",
              "## By instrument", ""]
    for inst, s in summary["by_instrument"].items():
        lines.append(f"- **{inst}**: signals {s['signals']}, eligible {s['eligible']}, live {s['live_capture']} ({pct_text(s['live_capture_pct'])}), late {s['late_proposals']}, traded {s['traded']}, ignored {s['ignored']}")
    lines += ["", "## Per-signal evidence", "", md_table(rows), "",
              "## Integrity and service health", "",
              f"- SQLite integrity: **{counts['integrity']}**",
              f"- Rows at report: signals {counts['signals']}, trades {counts['trades']}, 5m {counts['candles_5m']}, 1m {counts['candles_1m']}",
              f"- Duplicate trade IDs: {counts['dup_trade_id']}; open positions: {counts['open_positions']}",
              f"- Pre-session snapshot: `{json.dumps(pre)}`",
              f"- Post-session snapshot: `{json.dumps(post)}`",
              f"- Read-only audit: `{json.dumps(readonly_audit(selftest_path))}`",
              f"- Journal errors: `{json.dumps(errors)}`", "",
              "| unit | active | sub | restarts | restart delta | pid |", "|---|---|---|---|---|---|"]
    pre_units = (pre or {}).get("services") or {}
    for u, s in health.items():
        delta = None
        if u in pre_units and s.get("nrestarts") is not None and pre_units[u].get("nrestarts") is not None:
            delta = s["nrestarts"] - pre_units[u]["nrestarts"]
        lines.append(f"| {u} | {s.get('active')} | {s.get('sub')} | {s.get('nrestarts')} | {delta} | {s.get('pid')} |")
    lines += ["", "## Raw evidence", "",
              f"- Shadow events: `{EVENTS}`",
              f"- Probe observations: `{PROBE}`",
              f"- Probe selftest: `{selftest_path}`",
              f"- Shadow state: `{os.path.join(BASE,'logs','entry_shadow','shadow_state.json')}`",
              f"- Probe state: `{os.path.join(BASE,'logs','data_probe','state.json')}`",
              f"- Database (read-only): `{DB_PATH}`", "",
              "## Limitations", "",
              "- A required source that is missing, unreadable, stale, or invalid makes the day INCOMPLETE; no capture rate is calculated.",
              "- Production execution-attempt timestamp is not logged with a signal ID; shadow attempt time is shown separately.",
              "- yfinance is unofficial and may be delayed, rate-limited, or stale.",
              "- Paper fills assume the first 1-minute open; slippage is not modelled.",
              "- Historical replay is not live evidence and is excluded from this report.",
              "- The shadow can only act after the signal is persisted; late persistence necessarily yields LATE_PROPOSAL regardless of data availability.",
              "- Shadow probes only while production status is NEW; a fast TRADED transition can hide an otherwise valid live capture.",
              "- Pre/post count snapshots and daily reports are invoked manually; no new timer or service was added.",
              "- `paper_trades` has no `signal_id`; linkage is via `paper_trade_id` on the signal.", ""]
    if not safe_write(path, "\n".join(lines)):
        return None
    return path


def cmd_snapshot(day, label, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"phase5_counts_{day.replace('-','')}_{label}.json")
    if os.path.exists(path):
        print(f"REFUSED: {path} exists; choose a new output directory")
        return 3
    data = {"date": day, "label": label, "captured_at": iso(now_ist()),
            "counts": db_counts(), "services": service_state()}
    if not safe_write(path, json.dumps(data, indent=2) + "\n"):
        return 3
    print(path)
    return 0


def load_snapshot(day, label, out_dir):
    p = os.path.join(out_dir, f"phase5_counts_{day.replace('-','')}_{label}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as fh:
            return json.load(fh).get("counts")
    except Exception:
        return None


def mask_capture_rates(summary):
    summary["live_capture_pct"] = None
    for group in summary.get("by_instrument", {}).values():
        group["live_capture_pct"] = None
    return summary


def cmd_day(day, events, probe, out_dir, dry, skip_system, selftest=SELFTEST):
    global EVENTS, PROBE
    EVENTS, PROBE = events, probe
    out_dir = out_dir or ("/tmp/phase5_dryrun" if dry else REPORTS)
    suffix = "_DRYRUN" if dry else ""
    base = os.path.join(out_dir, f"phase5_daily_{day.replace('-','')}{suffix}")
    targets = [base + ".md", base + ".json"]
    for target in targets:
        if os.path.exists(target):
            print(f"REFUSED: {target} exists; choose a new output directory")
            return 3
    rows, _ = build_day(day, events, probe)
    counts = db_counts()
    pre = load_snapshot(day, "pre", out_dir)
    post = load_snapshot(day, "post", out_dir)
    pre_path = os.path.join(out_dir, f"phase5_counts_{day.replace('-','')}_pre.json")
    post_path = os.path.join(out_dir, f"phase5_counts_{day.replace('-','')}_post.json")
    health = {} if skip_system else service_state()
    errors = {} if skip_system else journal_errors(day)
    now = now_ist()
    sources, reasons = validate_sources(
        day, events, probe, selftest, pre_path, post_path, counts, health, errors,
        len([r for r in rows if (r["status"] or "").upper() != "IGNORED"]),
        skip_system, now)
    status = "DRY_RUN" if dry else ("INCOMPLETE" if reasons else "COMPLETE")
    summary = summarize(rows)
    if status == "INCOMPLETE":
        mask_capture_rates(summary)
    gates = evaluate(rows, summary, counts, pre, post, health, errors,
                     status=status, reasons=reasons, selftest_path=selftest)
    if dry:
        for g in gates:
            g["result"] = "NOT_EVALUATED"
            g["value"] = f"DRY RUN: {g['value']}"
    path = write_md(day, rows, summary, gates, counts, pre, post, health, errors,
                    out_dir, dry, status, sources, reasons, selftest)
    if path is None:
        return 3
    jpath = path.replace(".md", ".json")
    payload = {"date": day, "mode": "DRY_RUN" if dry else "LIVE",
               "status": status, "incomplete_reasons": reasons,
               "selftest_max_age_s": SELFTEST_MAX_AGE_S,
               "snapshot_max_age_s": SNAPSHOT_MAX_AGE_S,
               "generated_at": iso(now), "summary": summary,
               "sources": sources, "gates": gates, "counts": counts,
               "pre": pre, "post": post, "services": health,
               "journal_errors": errors, "signals": rows}
    if not safe_write(jpath, json.dumps(payload, indent=2) + "\n"):
        return 3
    print(path)
    print(jpath)
    return 0


def cmd_final(out_dir):
    today = now_ist().date()
    if today < datetime.fromisoformat(DATES[-1]).date() + timedelta(days=1):
        print("REFUSED: final report may only be generated after the 2026-11-06 session")
        return 2
    missing = [d for d in DATES if not os.path.exists(os.path.join(
        out_dir, f"phase5_daily_{d.replace('-','')}.json"))]
    if missing:
        print("REFUSED: missing live daily JSON for " + ", ".join(missing))
        return 2
    target = os.path.join(out_dir, "phase5_live_entry_capture_20261102_20261106.md")
    if os.path.exists(target):
        print(f"REFUSED: {target} exists; choose a new output directory")
        return 3
    days = []
    for d in DATES:
        try:
            with open(os.path.join(out_dir, f"phase5_daily_{d.replace('-','')}.json")) as fh:
                days.append(json.load(fh))
        except Exception as exc:
            print(f"REFUSED: unreadable daily JSON for {d}: {exc}")
            return 2
    bad = [d.get("date", "?") for d in days if d.get("status") != "COMPLETE"]
    if bad:
        print("REFUSED: daily evidence is not COMPLETE for " + ", ".join(bad))
        return 2
    replay_src = validate_replay(REPLAY, now_ist())
    if replay_src["status"] != "OK":
        print(f"REFUSED: replay evidence {replay_src['status']}: {replay_src['detail']}")
        return 2
    all_rows = [r for d in days for r in d["signals"]]
    summary = summarize(all_rows)
    counts = db_counts()
    pre = load_snapshot(DATES[0], "pre", out_dir)
    post = load_snapshot(DATES[-1], "post", out_dir)
    health = days[-1].get("services") or {}
    jcount = sum((d.get("journal_errors") or {}).get("count") or 0 for d in days)
    errors = {"count": jcount,
              "sample": [x for d in days for x in ((d.get("journal_errors") or {}).get("sample") or [])][:10]}
    gates = evaluate(all_rows, summary, counts, pre, post, health, errors,
                     status="COMPLETE", reasons=[])
    try:
        with open(REPLAY) as fh:
            replay = json.load(fh)
    except Exception:
        replay = {}
    rc = replay.get("counts") or {}
    ro = replay.get("outcomes") or {}
    rd = replay.get("entry_price_diff_points") or {}
    rec = ro.get("combined") or {}
    lines = ["# Phase 5 Live Entry Capture — 2026-11-02 to 2026-11-06", "",
             "**Daily status: COMPLETE**", "",
             f"Generated: {iso(now_ist())}", "",
             "## Combined metrics", "",
             f"- Eligible signals: **{summary['eligible']}** of {summary['signals']}",
             f"- LIVE_CAPTURE: **{summary['live_capture']}** ({pct_text(summary['live_capture_pct'])})",
             f"- Signals persisted before deadline: {summary['persisted_in_window']} ({pct_text(summary['persisted_in_window_pct'])})",
             f"- Probe coverage of eligible signals: {pct_text(summary['probe_coverage_pct'])}",
             f"- LATE_PROPOSAL: {summary['late_proposals']}",
             f"- MISSED_EXECUTION: {summary['missed_execution']}",
             f"- TRADED: {summary['traded']} | IGNORED: {summary['ignored']} | EXPIRED: {summary['expired']}",
             f"- Classification counts: `{json.dumps(summary['classification_counts'])}`",
             "", "## Daily status", "",
             "| date | status | signals | eligible | live | live % | late | missed | traded | ignored | expired |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in days:
        ds = summarize(d["signals"])
        lines.append(f"| {d['date']} | {d.get('status')} | {ds['signals']} | {ds['eligible']} | "
                     f"{ds['live_capture']} | {pct_text(ds['live_capture_pct'])} | "
                     f"{ds['late_proposals']} | {ds['missed_execution']} | {ds['traded']} | "
                     f"{ds['ignored']} | {ds['expired']} |")
    lines += ["", "## Combined latency (seconds)", "",
              "| metric | n | median | p95 | max |", "|---|---|---|---|---|"]
    for name, key in [("Candle ingestion", "ingest_latency"),
                      ("Signal persistence", "persistence_latency"),
                      ("Shadow first attempt", "attempt_latency"),
                      ("First 1m candle availability", "first_1m_latency"),
                      ("First fresh quote availability", "first_quote_latency")]:
        st = summary[key]
        lines.append(f"| {name} | {st['n']} | {st['median']} | {st['p95']} | {st['max']} |")
    lines += ["", "## Combined entry-price difference (points)", "",
              f"- TRADED vs engine entry: `{json.dumps(summary['price_diff_traded'])}`",
              f"- All available pairs: `{json.dumps(summary['price_diff_all'])}`", "",
              "## Acceptance gates", "", "| gate | measured | target | result |", "|---|---|---|---|"]
    for g in gates:
        lines.append(f"| {g['gate']} | {g['value']} | {g['target']} | **{g['result']}** |")
    lines += ["", "## Historical replay comparison", "",
              f"- Source: `{REPLAY}` (historical replay, not live evidence).",
              f"- Replay source status: **{replay_src['status']}** ({replay_src['detail']}).",
              f"- Replay totals: {rc.get('total')} signals, {rc.get('traded')} traded, {rc.get('expired')} expired, "
              f"{rc.get('recovered')}/{rc.get('expired')} recovered ({rc.get('recovery_rate_pct')}%).",
              f"- Replay combined outcomes: n={rec.get('n')}, win rate={rec.get('win_rate_pct')}%, "
              f"{rec.get('total_points')} points, {rec.get('sum_R')}R.",
              f"- Replay entry-price difference: n={rd.get('n')}, mean |diff|={rd.get('mean_abs')}, max={rd.get('max_abs')}.",
              f"- Live capture rate: {pct_text(summary['live_capture_pct'])} of eligible; live median entry diff "
              f"{summary['price_diff_traded']['median']} points.",
              "", "## Service health and database integrity", "",
              f"- SQLite integrity: **{counts['integrity']}**",
              f"- Rows at final report: signals {counts['signals']}, trades {counts['trades']}, "
              f"5m {counts['candles_5m']}, 1m {counts['candles_1m']}",
              f"- Duplicate trade IDs: {counts['dup_trade_id']}; open positions: {counts['open_positions']}",
              f"- Read-only audit: `{json.dumps(readonly_audit())}`",
              f"- Pre-session snapshot: `{json.dumps(pre)}`",
              f"- Post-session snapshot: `{json.dumps(post)}`", "",
              "| unit | active | sub | restarts | restart delta | pid |", "|---|---|---|---|---|---|"]
    pre_units = (pre or {}).get("services") or {}
    for u, sv in health.items():
        delta = None
        if u in pre_units and sv.get("nrestarts") is not None and pre_units[u].get("nrestarts") is not None:
            delta = sv["nrestarts"] - pre_units[u]["nrestarts"]
        lines.append(f"| {u} | {sv.get('active')} | {sv.get('sub')} | {sv.get('nrestarts')} | {delta} | {sv.get('pid')} |")
    lines += ["", "## Raw evidence", "",
              f"- Daily JSON: {out_dir}/phase5_daily_YYYYMMDD.json",
              f"- Daily reports: {out_dir}/phase5_daily_YYYYMMDD.md",
              f"- Shadow events: `{EVENTS}`", f"- Probe observations: `{PROBE}`",
              f"- Database (read-only): `{DB_PATH}`", "",
              "## Known limitations", "",
              "- A daily result is only combined when its status is COMPLETE; incomplete evidence is refused.",
              "- selftest freshness threshold is 86400s (24h); snapshot threshold is 604800s (7d).",
              "- yfinance is unofficial and may be delayed, rate-limited, or stale; weekend/after-hours quotes are not representative.",
              "- Paper fills assume the first 1-minute open; slippage and depth are not modelled.",
              "- Production execution-attempt timestamps are not signal-linked in logs; shadow attempt time is reported separately.",
              "- `paper_trades` has no `signal_id`; signal-to-trade linkage uses `paper_trade_id`.",
              "- Historical replay proves data existence, not real-time availability, and is excluded from live gates.",
              "- The shadow cannot capture a signal before it is persisted; late persistence creates LATE_PROPOSAL independently of data availability.",
              "- Shadow probes only while production status is NEW; a fast TRADED transition can hide an otherwise valid live capture.",
              "- Pre/post count snapshots and daily reports are invoked manually; no new timer or service was added.",
              "", "## Recommendation", ""]
    failed = [g["gate"] for g in gates if g["result"] == "FAIL"]
    unknown = [g["gate"] for g in gates if g["result"] == "NOT_EVALUATED"]
    if failed:
        lines.append(f"Investigate the failed gates ({'; '.join(failed)}). Continue shadow monitoring; "
                     "do not enable fallback without a separately approved implementation phase.")
    elif unknown:
        lines.append(f"Continue shadow monitoring; gates not evaluated ({'; '.join(unknown)}). "
                     "Do not enable fallback without a separately approved implementation phase.")
    else:
        lines.append("All acceptance gates passed on live evidence. Continue shadow monitoring; "
                     "any production fallback requires a separately approved implementation phase.")
    lines.append("")
    if not safe_write(target, "\n".join(lines)):
        return 3
    print(target)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 5 read-only audit")
    ap.add_argument("--date", help="session date YYYY-MM-DD")
    ap.add_argument("--events", default=EVENTS)
    ap.add_argument("--probe", default=PROBE)
    ap.add_argument("--selftest", default=SELFTEST,
                    help="selftest.json path (freshness threshold 86400s)")
    ap.add_argument("--out-dir", default=REPORTS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-system", action="store_true")
    ap.add_argument("--snapshot", choices=["pre", "post"])
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args(argv)
    if args.final:
        return cmd_final(args.out_dir)
    if not args.date:
        ap.error("--date is required unless --final")
    if args.snapshot:
        return cmd_snapshot(args.date, args.snapshot, args.out_dir)
    return cmd_day(args.date, args.events, args.probe, args.out_dir,
                   args.dry_run, args.skip_system, args.selftest)


if __name__ == "__main__":
    sys.exit(main())
