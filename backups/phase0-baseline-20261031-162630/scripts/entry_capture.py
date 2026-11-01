#!/usr/bin/env python3
"""Entry-capture research, replay and shadow-resolution helpers.

STRICT SAFETY:
- Read-only access to the trading database (mode=ro). Never writes trades/signals.
- Does not import or execute the signal engine or paper-trade engine.
- External market data goes through yfinance directly (no provider_cache writes).
- All monitoring output is append-only JSONL under logs/entry_shadow/.
"""
import fcntl
import json
import math
import os
import sqlite3
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "tradingai.db")
SHADOW_DIR = os.path.join(BASE, "logs", "entry_shadow")
CACHE_DIR = os.path.join(SHADOW_DIR, "cache")
EVENTS_PATH = os.path.join(SHADOW_DIR, "events.jsonl")
STATE_PATH = os.path.join(SHADOW_DIR, "shadow_state.json")
LOCK_PATH = os.path.join(SHADOW_DIR, "shadow.lock")

SYMBOLS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
CANDLE_MINUTES = 5
ENTRY_WINDOW_MINUTES = 5
EOD = dtime(15, 25)
STALE_QUOTE_SECONDS = 300

# Resolution priority (highest first).
SOURCE_PRIORITY = ("5m_db", "5m_provider", "1m_open", "quote")


def now_ist():
    return datetime.now(IST)


def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)


def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def iso(dt):
    return dt.astimezone(IST).isoformat()


def symbol_for(inst):
    return SYMBOLS.get((inst or "").upper(), inst)


def db_connect():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)


def db_candle_5m(inst, entry_time):
    """Exact 5-minute candle at entry_time from market_candles_5m (read-only)."""
    day = entry_time.strftime("%Y-%m-%d")
    conn = db_connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp LIKE ? ORDER BY timestamp",
            (inst, day + "%"),
        ).fetchall()
    finally:
        conn.close()
    for r in rows:
        if parse_ts(r["timestamp"]) == entry_time:
            return {
                "ts": r["timestamp"],
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
            }
    return None


def db_5m_day(inst, day):
    conn = db_connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp LIKE ? ORDER BY timestamp",
            (inst, day + "%"),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        ts = parse_ts(r["timestamp"])
        if ts is None:
            continue
        out.append({
            "ts": ts,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        })
    return out


def _cache_path(symbol, interval, day=None, period=None):
    tag = symbol.replace("^", "") + "_" + interval
    if period:
        tag += "_" + str(period).replace("/", "-")
    if day:
        tag += "_" + day
    return os.path.join(CACHE_DIR, tag + ".json")


def yf_candles(inst, interval, period, ttl_seconds=15, day=None):
    """Fetch candles via yfinance with an on-disk cache. No DB writes."""
    ensure_dirs()
    symbol = symbol_for(inst)
    path = _cache_path(symbol, interval, day, period)
    ensure_dirs()
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        age = 1e9
    if age <= ttl_seconds and os.path.exists(path):
        try:
            with open(path) as fh:
                payload = json.load(fh)
            return payload.get("rows", [])
        except Exception:
            pass
    lock = open(path + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            age = time.time() - os.path.getmtime(path)
        except OSError:
            age = 1e9
        if age <= ttl_seconds and os.path.exists(path):
            with open(path) as fh:
                return json.load(fh).get("rows", [])
        import yfinance as yf  # imported lazily

        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        rows = []
        for ts, row in hist.iterrows():
            ts_ist = ts.astimezone(IST) if getattr(ts, "tzinfo", None) else ts.replace(tzinfo=IST)
            if day and ts_ist.strftime("%Y-%m-%d") != day:
                continue
            try:
                o = float(row["Open"]); h = float(row["High"])
                l = float(row["Low"]); c = float(row["Close"])
            except Exception:
                continue
            if not all(math.isfinite(x) for x in (o, h, l, c)):
                continue
            rows.append({"ts": iso(ts_ist), "open": o, "high": h, "low": l, "close": c})
        payload = {"fetched_at": iso(now_ist()), "symbol": symbol,
                   "interval": interval, "rows": rows}
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
        return rows
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass


def fast_quote(inst):
    """Best-effort latest quote via yfinance fast_info. Timestamp = observation time."""
    ensure_dirs()
    symbol = symbol_for(inst)
    path = _cache_path(symbol, "quote")
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        age = 1e9
    if age <= 5:
        try:
            with open(path) as fh:
                return json.load(fh).get("quote")
        except Exception:
            pass
    quote = None
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        price = None
        try:
            price = float(t.fast_info["last_price"])
        except Exception:
            price = None
        if price is None or not math.isfinite(price) or price <= 0:
            hist = t.history(period="1d", interval="1m")
            if len(hist):
                price = float(hist["Close"].iloc[-1])
        if price is not None and math.isfinite(price) and price > 0:
            quote = {"price": price, "ts": iso(now_ist()), "state": "FRESH",
                     "source": "yfinance_fast_info"}
    except Exception:
        quote = None
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump({"quote": quote}, fh)
        os.replace(tmp, path)
    except Exception:
        pass
    return quote


def _valid_candidate(c, entry_time, deadline, now, tolerance_seconds=5):
    """Apply the authorized rejection rules."""
    try:
        price = float(c.get("price"))
    except Exception:
        return False, "missing_price"
    if not math.isfinite(price) or price <= 0:
        return False, "invalid_price"
    ts = parse_ts(c.get("ts"))
    if ts is None:
        return False, "bad_timestamp"
    if ts < entry_time:
        return False, "before_entry_time"
    if ts >= deadline:
        return False, "at_or_after_deadline"
    if ts > now + timedelta(seconds=tolerance_seconds):
        return False, "future_dated"
    available_at = parse_ts(c.get("available_at")) or ts
    if available_at >= deadline:
        return False, "available_after_deadline"
    if available_at > now + timedelta(seconds=tolerance_seconds):
        return False, "not_yet_available"
    if c.get("source") == "quote" and str(c.get("state", "")).upper() == "STALE":
        return False, "stale_quote"
    return True, None


def probe_sources(inst, entry_time, deadline, now=None, historical=False):
    """Probe the 5m DB, 5m provider, 1m, and quote sources in priority order."""
    now = now or now_ist()
    day = entry_time.strftime("%Y-%m-%d")
    out = []

    db5 = db_candle_5m(inst, entry_time)
    out.append({
        "source": "5m_db",
        "ts": iso(entry_time),
        "price": db5["open"] if db5 else None,
        # Completed candles are only ingested after the candle closes.
        "available_at": iso(entry_time + timedelta(minutes=CANDLE_MINUTES)),
        "present": bool(db5),
    })

    prov5 = None
    if not historical:
        try:
            rows = yf_candles(inst, "5m", "1d", ttl_seconds=15)
            for r in rows:
                if parse_ts(r["ts"]) == entry_time:
                    prov5 = r
                    break
        except Exception:
            prov5 = None
    out.append({
        "source": "5m_provider",
        "ts": iso(entry_time),
        "price": prov5["open"] if prov5 else None,
        "available_at": iso(now),
        "present": bool(prov5),
    })

    one = None
    try:
        rows = yf_candles(inst, "1m", "7d" if historical else "1d",
                          ttl_seconds=3600 if historical else 15, day=day)
        for r in rows:
            ts = parse_ts(r["ts"])
            if ts is None:
                continue
            if ts >= entry_time and ts < deadline:
                one = r
                break
    except Exception:
        one = None
    one_ts = parse_ts(one["ts"]) if one else None
    out.append({
        "source": "1m_open",
        "ts": one["ts"] if one else None,
        "price": one["open"] if one else None,
        "available_at": iso(one_ts + timedelta(minutes=1)) if one_ts else None,
        "present": bool(one),
    })

    qt = None if historical else fast_quote(inst)
    out.append({
        "source": "quote",
        "ts": qt["ts"] if qt else None,
        "price": qt["price"] if qt else None,
        "available_at": iso(now),
        "state": qt.get("state") if qt else None,
        "present": bool(qt),
    })
    return out


def resolve(inst, entry_time, deadline, now=None, historical=False):
    """Return the highest-priority valid entry within [entry_time, deadline)."""
    now = now or now_ist()
    attempts = []
    chosen = None
    for cand in probe_sources(inst, entry_time, deadline, now=now, historical=historical):
        ok, reason = _valid_candidate(cand, entry_time, deadline, now)
        attempts.append({**cand, "valid": ok, "reject": reason})
        if ok and chosen is None:
            chosen = cand
    if chosen is None:
        return {"resolved": False, "attempts": attempts, "price": None,
                "source": None, "fill_ts": None, "latency_s": None}
    fill_ts = parse_ts(chosen.get("available_at")) or parse_ts(chosen["ts"])
    latency = (fill_ts - entry_time).total_seconds() if fill_ts else None
    return {
        "resolved": True,
        "attempts": attempts,
        "price": float(chosen["price"]),
        "source": chosen["source"],
        "fill_ts": iso(fill_ts) if fill_ts else None,
        "price_ts": chosen["ts"],
        "latency_s": latency,
    }


def simulate(direction, entry, stop, fill_ts, bars, eod=EOD):
    """Simulate stop/target/EOD on 1-minute bars from fill_ts. Stop-first."""
    direction = (direction or "").upper()
    if direction not in ("BULL", "BEAR"):
        return None
    fill_ts = fill_ts if isinstance(fill_ts, datetime) else parse_ts(fill_ts)
    if fill_ts is None:
        return None
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return None
    target = entry + 1.5 * risk if direction == "BULL" else entry - 1.5 * risk
    mae = 0.0
    mfe = 0.0
    last_close = float(entry)
    visited = 0
    for bar in bars:
        ts = bar["ts"] if isinstance(bar["ts"], datetime) else parse_ts(bar["ts"])
        if ts is None:
            continue
        if ts < fill_ts:
            continue
        if ts.time() > eod:
            break
        visited += 1
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if direction == "BULL":
            if low <= stop:
                mae = max(mae, entry - stop)
                return {"exit_ts": iso(ts), "exit": stop, "reason": "STOP",
                        "points": stop - entry, "R": -1.0, "mae": mae, "mfe": mfe,
                        "bars": visited, "target": target}
            if high >= target:
                mfe = max(mfe, target - entry)
                return {"exit_ts": iso(ts), "exit": target, "reason": "TARGET",
                        "points": target - entry, "R": 1.5, "mae": mae, "mfe": mfe,
                        "bars": visited, "target": target}
            mae = max(mae, entry - low)
            mfe = max(mfe, high - entry)
        else:
            if high >= stop:
                mae = max(mae, stop - entry)
                return {"exit_ts": iso(ts), "exit": stop, "reason": "STOP",
                        "points": entry - stop, "R": -1.0, "mae": mae, "mfe": mfe,
                        "bars": visited, "target": target}
            if low <= target:
                mfe = max(mfe, entry - target)
                return {"exit_ts": iso(ts), "exit": target, "reason": "TARGET",
                        "points": entry - target, "R": 1.5, "mae": mae, "mfe": mfe,
                        "bars": visited, "target": target}
            mae = max(mae, high - entry)
            mfe = max(mfe, entry - low)
        last_close = close
    points = last_close - entry if direction == "BULL" else entry - last_close
    last_ts = bars[-1]["ts"] if bars else None
    if last_ts is not None and not isinstance(last_ts, datetime):
        last_ts = parse_ts(last_ts)
    return {"exit_ts": iso(last_ts) if last_ts else None, "exit": last_close,
            "reason": "EOD", "points": points, "R": points / risk,
            "mae": mae, "mfe": mfe, "bars": visited, "target": target}


def summarize(name, rows):
    if not rows:
        return {"name": name, "n": 0}
    n = len(rows)
    targets = sum(1 for r in rows if r.get("reason") == "TARGET")
    stops = sum(1 for r in rows if r.get("reason") == "STOP")
    eod = sum(1 for r in rows if r.get("reason") == "EOD")
    wins = sum(1 for r in rows if (r.get("points") or 0) > 0)
    pts = sum(r.get("points") or 0 for r in rows)
    rsum = sum(r.get("R") or 0 for r in rows)
    maes = [r.get("mae") or 0 for r in rows]
    mfes = [r.get("mfe") or 0 for r in rows]
    return {
        "name": name, "n": n, "target": targets, "stop": stops, "eod": eod,
        "wins": wins, "win_rate_pct": round(100.0 * wins / n, 1),
        "total_points": round(pts, 2), "sum_R": round(rsum, 2),
        "avg_R": round(rsum / n, 3),
        "avg_mae": round(sum(maes) / n, 2), "max_mae": round(max(maes), 2),
        "avg_mfe": round(sum(mfes) / n, 2), "max_mfe": round(max(mfes), 2),
    }


def append_jsonl(path, record):
    ensure_dirs()
    line = json.dumps(record, default=str) + "\n"
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
