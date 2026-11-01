#!/usr/bin/env python3
"""Read-only market-data availability probe.

This is NOT a signal engine. It watches 5-minute clock boundaries and records
whether the 5m candle, the entry-minute 1m candle and a usable quote are
available at +5/+15/+30/+60/+120 s after each boundary close. It later
correlates those observations with whatever canonical HLC signals the
production system persists. It never writes to the trading database.
"""
import argparse
import fcntl
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
DIR = "/opt/tradingai/logs/data_probe"
OBS = os.path.join(DIR, "observations.jsonl")
STATE_PATH = os.path.join(DIR, "state.json")
LOCK_PATH = os.path.join(DIR, "probe.lock")
SELFTEST_PATH = os.path.join(DIR, "selftest.json")
DB_URI = "file:/opt/tradingai/database/tradingai.db?mode=ro"
SYMBOLS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
OFFSETS = (5, 15, 30, 60, 120)
CANDLE = timedelta(minutes=5)
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
QUOTE_STALE_S = 180.0

_YF = {}


def now_ist():
    return datetime.now(IST)


def iso(dt):
    return dt.astimezone(IST).replace(microsecond=0).isoformat() if dt else None


def parse(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
    except Exception:
        return None


def ensure_dirs():
    os.makedirs(DIR, exist_ok=True)


def market_open(now):
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def floor5(now):
    return now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)


def db():
    import sqlite3
    return sqlite3.connect(DB_URI, uri=True, timeout=10)


def readonly_check():
    try:
        c = db()
        c.execute("UPDATE scalp_signals SET updated_at=updated_at WHERE 0")
        c.close()
        return False, "write_unexpectedly_allowed"
    except Exception as e:
        return True, f"{type(e).__name__}: {e}"


def append_jsonl(path, obj):
    ensure_dirs()
    with open(path, "a") as fh:
        fh.write(json.dumps(obj, default=str) + "\n")


def load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"targets": {}, "last_poll": None}


def save_state(state):
    ensure_dirs()
    cutoff = (now_ist() - timedelta(days=2)).isoformat()
    for k in list(state["targets"]):
        try:
            c = parse(k.split("|", 1)[1])
        except Exception:
            c = None
        if c is None or iso(c) < cutoff:
            state["targets"].pop(k, None)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, default=str)
    os.replace(tmp, STATE_PATH)


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def p95(vals):
    if not vals:
        return None
    s = sorted(vals)
    idx = max(0, math.ceil(0.95 * len(s)) - 1)
    return s[idx]


def med(vals):
    return statistics.median(vals) if vals else None


def _to_ist(idx):
    try:
        if getattr(idx, "tzinfo", None) is not None:
            return idx.tz_convert(IST).to_pydatetime()
        return idx.to_pydatetime().replace(tzinfo=IST)
    except Exception:
        return None


def yf_data(sym, interval, ttl=4.0):
    """Return {'rows': [(dt,o,h,l,c)], 'meta': {...}, 'fetch_ms': n, 'error': str|None}."""
    key = (sym, interval)
    cache = _YF.get(key)
    if cache and time.time() - cache["at"] <= ttl:
        return cache["data"]
    t0 = time.time()
    data = {"rows": [], "meta": {}, "fetch_ms": None, "error": None}
    try:
        import yfinance as yf
        tk = yf.Ticker(sym)
        hist = tk.history(period="2d" if interval == "5m" else "5d", interval=interval)
        rows = []
        for idx, row in hist.iterrows():
            dt = _to_ist(idx)
            if dt is None:
                continue
            try:
                o, h, l, c = (float(row["Open"]), float(row["High"]),
                              float(row["Low"]), float(row["Close"]))
            except Exception:
                continue
            if all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
                rows.append((dt, o, h, l, c))
        data["rows"] = rows
        try:
            data["meta"] = dict(getattr(tk, "history_metadata", {}) or {})
        except Exception:
            data["meta"] = {}
    except Exception as e:
        data["error"] = f"{type(e).__name__}: {str(e)[:180]}"
    data["fetch_ms"] = round((time.time() - t0) * 1000.0, 1)
    _YF[key] = {"at": time.time(), "data": data}
    return data


def _find(rows, dt):
    for r in rows:
        if r[0].replace(second=0, microsecond=0) == dt.replace(second=0, microsecond=0):
            return r
    return None


def db_candle(inst, start):
    try:
        c = db()
        row = c.execute(
            "SELECT timestamp, open, is_complete, ingested_at FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp=?", (inst, iso(start))).fetchone()
        c.close()
    except Exception as e:
        return {"present": False, "error": f"{type(e).__name__}: {e}"}
    if not row:
        return {"present": False}
    ing = parse(row[3])
    close_at = start + CANDLE
    return {
        "present": True,
        "open": row[1],
        "is_complete": bool(row[2]),
        "ingested_at": iso(ing),
        "ingest_after_close_s": round((ing - close_at).total_seconds(), 1) if ing else None,
    }


def quote_from_meta(meta, observed_at):
    price = meta.get("regularMarketPrice")
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    ts = meta.get("regularMarketTime")
    data_ts = None
    if ts:
        try:
            data_ts = datetime.fromtimestamp(float(ts), IST)
        except Exception:
            data_ts = None
    age = round((observed_at - data_ts).total_seconds(), 1) if data_ts else None
    if price is None or price <= 0:
        state = "UNAVAILABLE"
    elif age is not None and age > QUOTE_STALE_S:
        state = "STALE"
    else:
        state = "FRESH"
    return {"present": price is not None and price > 0, "price": price,
            "data_ts": iso(data_ts), "age_s": age, "state": state}


def snapshot(inst, close_at):
    sig_start = close_at - CANDLE
    sym = SYMBOLS[inst]
    d5 = yf_data(sym, "5m")
    d1 = yf_data(sym, "1m")
    observed = now_ist()
    ps = _find(d5["rows"], sig_start)
    pe = _find(d5["rows"], close_at)
    p1 = _find(d1["rows"], close_at)
    snap = {
        "target_close": iso(close_at),
        "signal_candle_start": iso(sig_start),
        "db_5m_signal": db_candle(inst, sig_start),
        "db_5m_entry": db_candle(inst, close_at),
        "provider_5m_signal": {
            "present": ps is not None,
            "open": ps[1] if ps else None,
            "data_ts": iso(ps[0]) if ps else None,
        },
        "provider_5m_entry": {
            "present": pe is not None,
            "open": pe[1] if pe else None,
            "data_ts": iso(pe[0]) if pe else None,
        },
        "provider_1m_entry": {
            "present": p1 is not None,
            "open": p1[1] if p1 else None,
            "data_ts": iso(p1[0]) if p1 else None,
        },
        "quote": quote_from_meta(d5.get("meta") or {}, observed),
        "fetch_ms": {"5m": d5.get("fetch_ms"), "1m": d1.get("fetch_ms")},
        "errors": {"5m": d5.get("error"), "1m": d1.get("error")},
    }
    any_provider = (ps or pe or p1 or snap["quote"]["present"])
    snap["provider_outage"] = not any_provider
    return snap


def correlate(state, now):
    """Attach canonical signals persisted later to the matching target."""
    today = now.date().isoformat()
    try:
        c = db()
        c.row_factory = __import__("sqlite3").Row
        rows = c.execute(
            "SELECT signal_id, instrument_id, source_candle_ts, status, created_at, "
            "paper_trade_id, last_error FROM scalp_signals WHERE trade_date=?",
            (today,)).fetchall()
        c.close()
    except Exception:
        return 0
    emitted = 0
    sigs = {}
    for r in rows:
        sigs.setdefault((r["instrument_id"], r["source_candle_ts"]), []).append(dict(r))
    for key, tgt in list(state["targets"].items()):
        inst, c_iso = key.split("|", 1)
        close_at = parse(c_iso)
        if close_at is None:
            continue
        sig_start = iso(close_at - CANDLE)
        found = sigs.get((inst, sig_start), [])
        if not found:
            continue
        done = set(tgt.get("correlated", []))
        for s in found:
            if s["signal_id"] in done:
                continue
            created = parse(s["created_at"])
            compact = {m: {
                "db_5m_signal": v.get("db_5m_signal", {}).get("present"),
                "provider_5m_signal": v.get("provider_5m_signal", {}).get("present"),
                "provider_5m_entry": v.get("provider_5m_entry", {}).get("present"),
                "provider_1m_entry": v.get("provider_1m_entry", {}).get("present"),
                "quote": v.get("quote", {}).get("present"),
            } for m, v in (tgt.get("observations") or {}).items()}
            append_jsonl(OBS, {
                "event": "correlated", "at": iso(now), "instrument": inst,
                "signal_id": s["signal_id"], "status": s["status"],
                "source_candle_ts": s["source_candle_ts"],
                "target_close": c_iso,
                "created_at": s["created_at"],
                "created_after_close_s": round((created - close_at).total_seconds(), 1) if created else None,
                "paper_trade_id": s["paper_trade_id"], "last_error": s["last_error"],
                "observed_offsets": compact,
            })
            done.add(s["signal_id"])
            emitted += 1
        tgt["correlated"] = sorted(done)
    return emitted


def run_once(state):
    now = now_ist()
    if not market_open(now):
        return 0, False
    close_at = floor5(now)
    emitted = 0
    changed = False
    for inst in SYMBOLS:
        if close_at - CANDLE < now.replace(hour=9, minute=15, second=0, microsecond=0):
            continue
        if close_at.time() > dtime(15, 25):
            continue
        key = f"{inst}|{iso(close_at)}"
        tgt = state["targets"].get(key)
        if tgt is None:
            if (now - close_at).total_seconds() > 10:
                continue
            tgt = {"created_at": iso(now), "observations": {}, "missed": [],
                   "correlated": []}
            state["targets"][key] = tgt
            changed = True
        elapsed = (now - close_at).total_seconds()
        pending = []
        for m in OFFSETS:
            if m in tgt["observations"] or m in tgt["missed"]:
                continue
            if elapsed >= m + 8:
                tgt["missed"].append(m)
                changed = True
            elif elapsed >= m:
                pending.append(m)
        if pending:
            snap = snapshot(inst, close_at)
            for m in pending:
                actual = round((now_ist() - close_at).total_seconds(), 1)
                rec = {"event": "observation", "observed_at": iso(now_ist()),
                       "instrument": inst, "offset_target": m,
                       "offset_actual_s": actual}
                rec.update(snap)
                append_jsonl(OBS, rec)
                tgt["observations"][str(m)] = rec
                emitted += 1
            changed = True
    state["last_poll"] = iso(now)
    if correlate(state, now):
        emitted += 1
        changed = True
    return emitted, changed


def selftest(close_iso):
    ensure_dirs()
    close_at = parse(close_iso) or floor5(now_ist())
    out = {"at": iso(now_ist()), "close": iso(close_at),
           "readonly": readonly_check(), "instruments": {}}
    for inst in SYMBOLS:
        out["instruments"][inst] = snapshot(inst, close_at)
    with open(SELFTEST_PATH, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(json.dumps(out, indent=2, default=str))
    return 0


def report(date_str):
    ensure_dirs()
    obs = []
    if os.path.exists(OBS):
        with open(OBS) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event") == "observation" and (e.get("target_close") or "").startswith(date_str):
                    obs.append(e)
    corr = []
    if os.path.exists(OBS):
        with open(OBS) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event") == "correlated" and (e.get("target_close") or "").startswith(date_str):
                    corr.append(e)

    insts = list(SYMBOLS)
    by = {i: {"offsets": {m: [] for m in OFFSETS}, "fetch": {"5m": [], "1m": []},
              "ingest": [], "outages": 0, "stale": 0, "errors": 0,
              "targets": set()} for i in insts}
    for e in obs:
        d = by.get(e.get("instrument"))
        if d is None:
            continue
        d["targets"].add(e.get("target_close"))
        m = e.get("offset_target")
        if m in d["offsets"]:
            d["offsets"][m].append(e)
        for k in ("5m", "1m"):
            v = (e.get("fetch_ms") or {}).get(k)
            if v is not None:
                d["fetch"][k].append(v)
        ing = (e.get("db_5m_signal") or {}).get("ingest_after_close_s")
        if ing is not None:
            d["ingest"].append(ing)
        if e.get("provider_outage"):
            d["outages"] += 1
        if (e.get("quote") or {}).get("state") == "STALE":
            d["stale"] += 1
        if any((e.get("errors") or {}).values()):
            d["errors"] += 1

    def pct_true(rows, getter):
        return pct(sum(1 for r in rows if getter(r)), len(rows))

    result = {"date": date_str, "observations": len(obs), "instruments": {},
              "correlations": len(corr)}
    for i in insts:
        d = by[i]
        res = {"targets": len(d["targets"]), "offsets": {},
               "fetch_ms": {k: {"median": med(v), "p95": p95(v), "max": max(v) if v else None}
                            for k, v in d["fetch"].items()},
               "db_ingest_after_close_s": {"n": len(d["ingest"]), "median": med(d["ingest"]),
                                            "p95": p95(d["ingest"]),
                                            "max": max(d["ingest"]) if d["ingest"] else None},
               "provider_outage_observations": d["outages"],
               "stale_quotes": d["stale"], "provider_errors": d["errors"]}
        for m in OFFSETS:
            rows = d["offsets"][m]
            if not rows:
                res["offsets"][m] = {"n": 0}
                continue
            res["offsets"][m] = {
                "n": len(rows),
                "db_5m_signal_pct": pct_true(rows, lambda r: (r.get("db_5m_signal") or {}).get("present")),
                "db_5m_entry_pct": pct_true(rows, lambda r: (r.get("db_5m_entry") or {}).get("present")),
                "provider_5m_signal_pct": pct_true(rows, lambda r: (r.get("provider_5m_signal") or {}).get("present")),
                "provider_5m_entry_pct": pct_true(rows, lambda r: (r.get("provider_5m_entry") or {}).get("present")),
                "provider_1m_entry_pct": pct_true(rows, lambda r: (r.get("provider_1m_entry") or {}).get("present")),
                "quote_pct": pct_true(rows, lambda r: (r.get("quote") or {}).get("present")),
                "quote_age_median": med([(r.get("quote") or {}).get("age_s") for r in rows
                                         if (r.get("quote") or {}).get("age_s") is not None]),
            }
        result["instruments"][i] = res

    # Correlation summary.
    created = [c.get("created_after_close_s") for c in corr if c.get("created_after_close_s") is not None]
    result["correlation_summary"] = {
        "signals": len(corr),
        "created_after_close_s": {"median": med(created), "p95": p95(created),
                                  "max": max(created) if created else None},
        "by_instrument": {i: sum(1 for c in corr if c.get("instrument") == i) for i in insts},
    }

    out_json = os.path.join(DIR, f"report_{date_str}.json")
    out_md = os.path.join(DIR, f"report_{date_str}.md")
    with open(out_json, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    lines = [f"# Data availability probe — {date_str}", ""]
    lines.append(f"Observations: {len(obs)}  Correlated signals: {len(corr)}")
    for i in insts:
        r = result["instruments"][i]
        lines += ["", f"## {i}  (targets observed: {r['targets']})", "",
                  f"DB 5m ingestion after close: n={r['db_ingest_after_close_s']['n']} "
                  f"median={r['db_ingest_after_close_s']['median']}s "
                  f"p95={r['db_ingest_after_close_s']['p95']}s "
                  f"max={r['db_ingest_after_close_s']['max']}s", "",
                  "| +s | n | 5m db | 5m prov | entry 5m prov | 1m prov | quote |",
                  "|---:|---:|---:|---:|---:|---:|---:|"]
        for m in OFFSETS:
            o = r["offsets"][m]
            if not o.get("n"):
                lines.append(f"| {m} | 0 | - | - | - | - | - |")
                continue
            lines.append(f"| {m} | {o['n']} | {o['db_5m_signal_pct']}% | "
                         f"{o['provider_5m_signal_pct']}% | {o['provider_5m_entry_pct']}% | "
                         f"{o['provider_1m_entry_pct']}% | {o['quote_pct']}% |")
        lines += ["", f"Provider fetch ms: {r['fetch_ms']}",
                  f"Provider outage observations: {r['provider_outage_observations']}  "
                  f"stale quotes: {r['stale_quotes']}  provider errors: {r['provider_errors']}"]
    with open(out_md, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nWROTE", out_json, out_md)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--close", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--date", default=now_ist().date().isoformat())
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args(argv)
    if args.report:
        return report(args.date)
    if args.selftest:
        return selftest(args.close)
    ensure_dirs()
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another data_probe instance holds the lock; exiting")
        return 0
    ro_ok, ro_msg = readonly_check()
    print(f"data_probe started readonly_ok={ro_ok} detail={ro_msg}", flush=True)
    append_jsonl(OBS, {"event": "probe_start", "at": iso(now_ist()),
                       "readonly_ok": ro_ok, "detail": ro_msg})
    state = load_state()
    for _ in range(1):
        try:
            n, changed = run_once(state)
            if n:
                print(f"{iso(now_ist())} events={n}", flush=True)
            if changed:
                save_state(state)
        except Exception as e:
            print(f"{iso(now_ist())} probe error: {e}", flush=True)
        if args.once:
            return 0
    while True:
        try:
            n, changed = run_once(state)
            if n:
                print(f"{iso(now_ist())} events={n}", flush=True)
            if changed:
                save_state(state)
        except Exception as e:
            print(f"{iso(now_ist())} probe error: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
