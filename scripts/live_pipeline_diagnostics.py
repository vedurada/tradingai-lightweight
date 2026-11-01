#!/usr/bin/env python3
"""Read-only live pipeline diagnostic logger for TradingAI.

This process observes existing production data and logs. It does not modify
market data, signals, trades, strategy logic, dashboard rendering, or services.
"""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "tradingai.db")
LOG_DIR = os.path.join(BASE, "logs", "live_pipeline_diagnostics")
STATE_PATH = os.path.join(LOG_DIR, "state.json")
LOCK_PATH = os.path.join(LOG_DIR, "live_pipeline_diagnostics.lock")
REPORT_DIR = os.path.join(BASE, "reports")
MAX_LOG_BYTES = 50 * 1024 * 1024
RETENTION_DAYS = 30
POLL_SECONDS = 5
SERVICE_UNITS = [
    "tradingai-api.service",
    "tradingai-paper-scalp-live.service",
    "tradingai-scalp-alerts.service",
    "tradingai-entry-shadow.service",
    "tradingai-data-probe.service",
    "tradingai-live-dashboard.service",
    "tradingai-market-data.timer",
]
PAPER_LOG = os.path.join(BASE, "logs", "paper_scalp_live.log")
PAPER_ERR_LOG = os.path.join(BASE, "logs", "paper_scalp_live.err.log")
DASHBOARD_HTML = os.path.join(BASE, "app", "api", "live.dashboard.html")
DASHBOARD_HEARTBEAT = os.path.join(BASE, "logs", "live_dashboard.state.json")

REQUIRED_EVENT_KEYS = [
    "event_timestamp_ist",
    "event_timestamp_utc",
    "event_type",
    "pipeline_stage",
    "instrument",
    "symbol",
    "candle_timestamp",
    "source_candle_timestamp",
    "provider",
    "correlation_id",
    "signal_id",
    "trade_id",
    "processing_duration_ms",
    "status",
    "reason",
    "error_type",
    "error_message",
]


def now_ist():
    return datetime.now(IST)


def iso_ist(dt):
    return dt.astimezone(IST).isoformat(timespec="seconds")


def iso_utc(dt):
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def market_open(now):
    if now.weekday() >= 5:
        return False
    t = now.timetz() if now.tzinfo else now.time()
    return datetime.strptime("09:15", "%H:%M").time() <= t <= datetime.strptime("15:30", "%H:%M").time()


def safe_mkdir(path):
    os.makedirs(path, exist_ok=True)


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state):
    atomic_write_json(STATE_PATH, state)


def log_path_for(ts):
    return os.path.join(LOG_DIR, f"live_pipeline_{ts.strftime('%Y%m%d')}.jsonl")


def rotate_if_needed(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_LOG_BYTES:
            stamp = now_ist().strftime("%Y%m%d-%H%M%S")
            rotated = path.replace(".jsonl", f".{stamp}.jsonl")
            os.replace(path, rotated)
            with open(rotated, "rb") as src, gzip.open(rotated + ".gz", "wb") as dst:
                dst.write(src.read())
            os.remove(rotated)
    except Exception:
        pass


def cleanup_old_logs():
    cutoff = now_ist() - timedelta(days=RETENTION_DAYS)
    for name in os.listdir(LOG_DIR):
        p = os.path.join(LOG_DIR, name)
        if not os.path.isfile(p):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(p), IST)
            if mtime < cutoff:
                os.remove(p)
        except Exception:
            pass


def db_connect():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)


def write_event(event_type, pipeline_stage, correlation_id, **fields):
    ts = now_ist()
    event = {key: None for key in REQUIRED_EVENT_KEYS}
    event["event_timestamp_ist"] = iso_ist(ts)
    event["event_timestamp_utc"] = iso_utc(ts)
    event["event_type"] = event_type
    event["pipeline_stage"] = pipeline_stage
    event["correlation_id"] = correlation_id
    for key, value in fields.items():
        if key in event:
            event[key] = value
    path = log_path_for(ts)
    safe_mkdir(LOG_DIR)
    rotate_if_needed(path)
    cleanup_old_logs()
    with open(path, "a") as fh:
        fh.write(json.dumps(event, default=str) + "\n")
    return event


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def service_statuses():
    result = {}
    for unit in SERVICE_UNITS:
        try:
            raw = subprocess.run(
                ["systemctl", "show", "-p", "ActiveState", "-p", "SubState",
                 "-p", "NRestarts", "-p", "MainPID", unit],
                capture_output=True, text=True, timeout=10).stdout
            kv = {}
            for line in raw.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k] = v
            result[unit] = {
                "active": kv.get("ActiveState"),
                "sub": kv.get("SubState"),
                "restarts": int(kv["NRestarts"]) if kv.get("NRestarts", "").isdigit() else None,
                "pid": kv.get("MainPID"),
            }
        except Exception as exc:
            result[unit] = {"error": str(exc)}
    return result


def query_new_candles(state, correlation_id):
    last = state.setdefault("last_candle", {})
    conn = db_connect()
    try:
        for instrument in ("NIFTY", "BANKNIFTY"):
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, ingested_at, is_complete "
                "FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 5",
                (instrument,)).fetchall()
            if not rows:
                write_event("market_data_missing", "data_fetch", correlation_id,
                            instrument=instrument, symbol="^NSEI" if instrument == "NIFTY" else "^NSEBANK",
                            provider="yfinance", status="WARN", reason="no candles in database")
                continue
            latest = rows[0]
            latest_ts = latest[0]
            if last.get(instrument) is None:
                last[instrument] = latest_ts
                continue
            if latest_ts <= last[instrument]:
                continue
            for row in reversed(rows):
                ts = row[0]
                if ts <= last[instrument]:
                    continue
                o, h, l, c = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
                valid = (o > 0 and h > 0 and l > 0 and c > 0 and h >= l and
                         l <= o <= h and l <= c <= h)
                write_event("candle_received", "data_fetch", correlation_id,
                            instrument=instrument,
                            symbol="^NSEI" if instrument == "NIFTY" else "^NSEBANK",
                            candle_timestamp=ts, provider="yfinance",
                            status="INFO", reason="new completed candle observed")
                write_event("candle_validated", "data_validation", correlation_id,
                            instrument=instrument,
                            symbol="^NSEI" if instrument == "NIFTY" else "^NSEBANK",
                            candle_timestamp=ts, provider="yfinance",
                            status="INFO" if valid else "ERROR",
                            reason="OHLC validation passed" if valid else "OHLC validation failed")
                if valid:
                    try:
                        close_dt = datetime.fromisoformat(ts)
                        ingested_dt = datetime.fromisoformat(str(row[5]).replace("Z", "+00:00"))
                        delay_ms = round((ingested_dt - (close_dt + timedelta(minutes=5))).total_seconds() * 1000, 3)
                    except Exception:
                        delay_ms = None
                    write_event("candle_persisted", "data_persistence", correlation_id,
                                instrument=instrument,
                                symbol="^NSEI" if instrument == "NIFTY" else "^NSEBANK",
                                candle_timestamp=ts, provider="yfinance",
                                processing_duration_ms=delay_ms,
                                status="INFO", reason="candle available in market_candles_5m")
            last[instrument] = latest_ts
    finally:
        conn.close()


def query_new_signals(state, correlation_id):
    seen = state.setdefault("seen_signals", {})
    conn = db_connect()
    try:
        today = now_ist().date().isoformat()
        rows = conn.execute(
            "SELECT signal_id, instrument_id, direction, source_candle_ts, status, "
            "reference_price, reference_stop, reference_target, created_at, updated_at "
            "FROM scalp_signals WHERE trade_date=? ORDER BY created_at",
            (today,)).fetchall()
        for row in rows:
            sid = row[0]
            if sid in seen:
                continue
            seen[sid] = row[4]
            try:
                signal_dt = datetime.fromisoformat(str(row[3]).replace("Z", "+00:00"))
                created_dt = datetime.fromisoformat(str(row[8]).replace("Z", "+00:00"))
                delay_ms = round((created_dt - (signal_dt + timedelta(minutes=5))).total_seconds() * 1000, 3)
            except Exception:
                delay_ms = None
            write_event("signal_persisted", "signal_generation", correlation_id,
                        instrument=row[1],
                        symbol="^NSEI" if row[1] == "NIFTY" else "^NSEBANK",
                        candle_timestamp=row[3],
                        source_candle_timestamp=row[3],
                        provider="yfinance",
                        signal_id=sid,
                        processing_duration_ms=delay_ms,
                        status="INFO" if row[4] in ("NEW", "TRADED") else "WARN",
                        reason=f"signal status={row[4]}")
    finally:
        conn.close()


def query_trade_changes(state, correlation_id):
    seen = state.setdefault("seen_trades", {})
    conn = db_connect()
    try:
        today = now_ist().date().isoformat()
        rows = conn.execute(
            "SELECT trade_id, instrument_id, status, entry, stop, target, entry_time, "
            "exit_time, exit_price, exit_reason, created_at, updated_at "
            "FROM paper_trades WHERE scenario='SCALP_HLC' AND substr(COALESCE(entry_time,''),1,10)=? "
            "ORDER BY created_at",
            (today,)).fetchall()
        for row in rows:
            tid = row[0]
            status = row[2]
            if tid not in seen:
                seen[tid] = status
                try:
                    entry_dt = datetime.fromisoformat(str(row[6]).replace("Z", "+00:00"))
                    created_dt = datetime.fromisoformat(str(row[10]).replace("Z", "+00:00"))
                    delay_ms = round((created_dt - entry_dt).total_seconds() * 1000, 3)
                except Exception:
                    delay_ms = None
                write_event("paper_trade_created", "trade_execution", correlation_id,
                            instrument=row[1],
                            symbol="^NSEI" if row[1] == "NIFTY" else "^NSEBANK",
                            candle_timestamp=row[6],
                            source_candle_timestamp=None,
                            trade_id=tid,
                            processing_duration_ms=delay_ms,
                            status="INFO",
                            reason=f"entry={row[3]} stop={row[4]} target={row[5]}")
            elif seen[tid] != status:
                seen[tid] = status
                write_event("trade_status_changed", "trade_lifecycle", correlation_id,
                            instrument=row[1],
                            symbol="^NSEI" if row[1] == "NIFTY" else "^NSEBANK",
                            candle_timestamp=row[6],
                            trade_id=tid,
                            status="INFO" if status in ("CLOSED", "TRADED") else "WARN",
                            reason=f"status {status}, exit_reason={row[9]}, exit_price={row[8]}")
    finally:
        conn.close()


def query_dashboard(correlation_id):
    state = load_state()
    last_mtime = state.get("dashboard_mtime")
    last_hash = state.get("dashboard_hash")
    try:
        st = os.stat(DASHBOARD_HTML)
        mtime = st.st_mtime
        digest = sha256_file(DASHBOARD_HTML)
        if last_mtime != mtime or last_hash != digest:
            write_event("dashboard_publication", "dashboard_publication", correlation_id,
                        instrument=None, symbol=None, candle_timestamp=None,
                        source_candle_timestamp=None, provider="local_file",
                        processing_duration_ms=None, status="INFO",
                        reason=f"dashboard rendered, bytes={st.st_size}")
            state["dashboard_mtime"] = mtime
            state["dashboard_hash"] = digest
            save_state(state)
    except Exception as exc:
        write_event("dashboard_publication_failed", "dashboard_publication", correlation_id,
                    instrument=None, symbol=None, candle_timestamp=None,
                    source_candle_timestamp=None, provider="local_file",
                    processing_duration_ms=None, status="ERROR",
                    error_type=type(exc).__name__, error_message=str(exc))


def tail_log_file(path, state_key, correlation_id, stage, default_status="INFO"):
    state = load_state()
    offsets = state.setdefault("log_offsets", {})
    try:
        if not os.path.exists(path):
            return
        size = os.path.getsize(path)
        offset = offsets.get(state_key, size)
        if offset > size:
            offset = 0
        with open(path) as fh:
            fh.seek(offset)
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                low = line.lower()
                if "error" in low or "traceback" in low or "failed" in low:
                    status = "ERROR"
                elif "invalid" in low or "stale" in low or "rejected" in low or "expired" in low or "missing" in low:
                    status = "WARN"
                else:
                    status = default_status
                write_event("production_log", stage, correlation_id,
                            instrument=None, symbol=None, candle_timestamp=None,
                            source_candle_timestamp=None, provider="local_log",
                            processing_duration_ms=None, status=status,
                            reason=line[:500], error_type=None, error_message=None)
            offsets[state_key] = fh.tell()
            state["log_offsets"] = offsets
            save_state(state)
    except Exception as exc:
        write_event("log_tail_failed", stage, correlation_id,
                    instrument=None, symbol=None, candle_timestamp=None,
                    source_candle_timestamp=None, provider="local_log",
                    processing_duration_ms=None, status="ERROR",
                    error_type=type(exc).__name__, error_message=str(exc))


def run_cycle(state):
    ts = now_ist()
    correlation_id = f"LPD-{ts.strftime('%Y%m%d')}-{ts.strftime('%H%M%S')}"
    try:
        statuses = service_statuses()
        previous = state.get("service_statuses")
        if previous != statuses:
            write_event("service_health", "service_health", correlation_id,
                        instrument=None, symbol=None, candle_timestamp=None,
                        source_candle_timestamp=None, provider="systemd",
                        processing_duration_ms=None, status="INFO",
                        reason=json.dumps(statuses, sort_keys=True))
            state["service_statuses"] = statuses
            save_state(state)
    except Exception as exc:
        write_event("service_health_failed", "service_health", correlation_id,
                    instrument=None, symbol=None, candle_timestamp=None,
                    source_candle_timestamp=None, provider="systemd",
                    processing_duration_ms=None, status="ERROR",
                    error_type=type(exc).__name__, error_message=str(exc))

    query_new_candles(state, correlation_id)
    query_new_signals(state, correlation_id)
    query_trade_changes(state, correlation_id)
    query_dashboard(correlation_id)
    tail_log_file(PAPER_LOG, "paper_log", correlation_id, "trade_execution")
    tail_log_file(PAPER_ERR_LOG, "paper_err_log", correlation_id, "trade_execution")
    save_state(state)


def generate_daily_report(date_str):
    state = load_state()
    if state.get("report_generated") == date_str:
        return
    path = os.path.join(REPORT_DIR, f"live_pipeline_daily_{date_str}.md")
    if os.path.exists(path):
        state["report_generated"] = date_str
        save_state(state)
        return

    day_events = []
    log_file = os.path.join(LOG_DIR, f"live_pipeline_{date_str}.jsonl")
    if os.path.exists(log_file):
        with open(log_file) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        day_events.append(json.loads(line))
                    except Exception:
                        pass

    conn = db_connect()
    try:
        candles = {}
        ingestion_delays = []
        for instrument in ("NIFTY", "BANKNIFTY"):
            rows = conn.execute(
                "SELECT timestamp, ingested_at FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
                (instrument, date_str)).fetchall()
            candles[instrument] = len(rows)
            for ts, ingested in rows:
                try:
                    close_dt = datetime.fromisoformat(ts) + timedelta(minutes=5)
                    ingested_dt = datetime.fromisoformat(str(ingested).replace("Z", "+00:00"))
                    ingestion_delays.append((ingested_dt - close_dt).total_seconds())
                except Exception:
                    pass
        signals = {}
        for status, count in conn.execute(
                "SELECT status, count(*) FROM scalp_signals WHERE trade_date=? GROUP BY status", (date_str,)):
            signals[status] = count
        trades = {}
        for status, count in conn.execute(
                "SELECT status, count(*) FROM paper_trades WHERE scenario='SCALP_HLC' AND substr(COALESCE(entry_time,''),1,10)=? GROUP BY status", (date_str,)):
            trades[status] = count
        open_after_close = conn.execute(
            "SELECT count(*) FROM paper_trades WHERE scenario='SCALP_HLC' AND substr(COALESCE(entry_time,''),1,10)=? AND status IN ('OPEN','ACTIVE') AND substr(COALESCE(entry_time,''),12,5) >= '15:25'",
            (date_str,)).fetchone()[0]
        signal_persistence_delays = []
        for source_ts, created in conn.execute(
                "SELECT source_candle_ts, created_at FROM scalp_signals WHERE trade_date=?", (date_str,)):
            try:
                signal_dt = datetime.fromisoformat(str(source_ts).replace("Z", "+00:00"))
                created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                signal_persistence_delays.append((created_dt - (signal_dt + timedelta(minutes=5))).total_seconds())
            except Exception:
                pass
    finally:
        conn.close()

    expected_candles = 75
    event_counts = {}
    for event in day_events:
        event_counts[event.get("event_type", "unknown")] = event_counts.get(event.get("event_type", "unknown"), 0) + 1
    error_events = [e for e in day_events if e.get("status") in ("ERROR", "CRITICAL")]
    warn_events = [e for e in day_events if e.get("status") == "WARN"]
    dashboard_failures = [e for e in day_events if e.get("event_type") == "dashboard_publication_failed"]
    production_errors = [e for e in day_events if e.get("event_type") == "production_log" and e.get("status") == "ERROR"]

    lines = [
        f"# Live Pipeline Daily Diagnostic — {date_str}",
        "",
        f"Generated: {iso_ist(now_ist())}",
        "",
        "## Market data",
        "",
    ]
    for instrument in ("NIFTY", "BANKNIFTY"):
        count = candles.get(instrument, 0)
        missing = max(0, expected_candles - count)
        lines.append(f"- {instrument}: {count}/{expected_candles} completed 5m candles observed; missing={missing}")
    if ingestion_delays:
        lines.append(f"- Ingestion delay seconds: min={min(ingestion_delays):.3f}, max={max(ingestion_delays):.3f}, median={sorted(ingestion_delays)[len(ingestion_delays)//2]:.3f}")
    lines += [
        "",
        "## Signals",
        "",
        f"- Signal statuses: {json.dumps(signals, sort_keys=True)}",
    ]
    if signal_persistence_delays:
        lines.append(f"- Signal persistence delay seconds: min={min(signal_persistence_delays):.3f}, max={max(signal_persistence_delays):.3f}, median={sorted(signal_persistence_delays)[len(signal_persistence_delays)//2]:.3f}")
    lines += [
        "",
        "## Paper trades",
        "",
        f"- Trade statuses: {json.dumps(trades, sort_keys=True)}",
        f"- Open trades entered at/after 15:25: {open_after_close}",
        "",
        "## Diagnostic events",
        "",
        f"- Event counts: {json.dumps(event_counts, sort_keys=True)}",
        f"- ERROR/CRITICAL events: {len(error_events)}",
        f"- WARN events: {len(warn_events)}",
        f"- Production log ERROR lines: {len(production_errors)}",
        f"- Dashboard publication failures: {len(dashboard_failures)}",
        "",
        "## Potential issues",
        "",
    ]
    issues = []
    for instrument in ("NIFTY", "BANKNIFTY"):
        if candles.get(instrument, 0) < expected_candles:
            issues.append(f"{instrument} missing {expected_candles - candles.get(instrument, 0)} expected 5m candles.")
    if ingestion_delays and max(ingestion_delays) > 30:
        issues.append(f"Ingestion delay exceeded 30 seconds (max {max(ingestion_delays):.3f}s).")
    if signal_persistence_delays and max(signal_persistence_delays) > 30:
        issues.append(f"Signal persistence delay exceeded 30 seconds (max {max(signal_persistence_delays):.3f}s).")
    if open_after_close:
        issues.append(f"{open_after_close} scalp trade(s) remained open after 15:25.")
    if error_events:
        issues.append(f"{len(error_events)} ERROR/CRITICAL diagnostic event(s) require review.")
    if dashboard_failures:
        issues.append(f"{len(dashboard_failures)} dashboard publication failure(s).")
    if not issues:
        issues.append("No automated issue detected from available diagnostic events.")
    for issue in issues:
        lines.append(f"- {issue}")
    lines += [
        "",
        "## Pattern detection note",
        "",
        "Pattern-level detection is not separately instrumented by this read-only diagnostic process. "
        "Persisted signals are reported above; pattern confirmation details are only available where "
        "existing production logs include them.",
        "",
        "## Evidence",
        "",
        f"- Diagnostic JSONL: `/opt/tradingai/logs/live_pipeline_diagnostics/live_pipeline_{date_str}.jsonl`",
        f"- Database: `/opt/tradingai/database/tradingai.db` (read-only)",
        "",
    ]
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    state["report_generated"] = date_str
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="TradingAI live pipeline diagnostic logger")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--test-seconds", type=int, default=0, help="run for N seconds and exit")
    parser.add_argument("--generate-report", default=None, help="generate report for YYYYMMDD and exit")
    args = parser.parse_args()

    safe_mkdir(LOG_DIR)
    safe_mkdir(REPORT_DIR)

    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print("another diagnostic logger instance is running; exiting", flush=True)
        sys.exit(0)

    state = load_state()
    if state.get("last_candle") is None:
        # Baseline current candles without emitting events.
        conn = db_connect()
        try:
            for instrument in ("NIFTY", "BANKNIFTY"):
                row = conn.execute(
                    "SELECT timestamp FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1",
                    (instrument,)).fetchone()
                if row:
                    state.setdefault("last_candle", {})[instrument] = row[0]
        finally:
            conn.close()
        state.setdefault("seen_signals", {})
        state.setdefault("seen_trades", {})
        state.setdefault("log_offsets", {})
        # Start at EOF for existing logs to avoid flooding.
        for key, path in (("paper_log", PAPER_LOG), ("paper_err_log", PAPER_ERR_LOG)):
            try:
                if os.path.exists(path):
                    state["log_offsets"][key] = os.path.getsize(path)
            except Exception:
                pass
        save_state(state)

    if args.generate_report:
        generate_daily_report(args.generate_report)
        print(f"generated {args.generate_report}")
        return

    start = time.time()
    while True:
        ts = now_ist()
        if market_open(ts):
            run_cycle(state)
        else:
            if ts.timetuple().tm_hour == 15 and ts.timetuple().tm_min >= 35:
                generate_daily_report(ts.date().isoformat())
            time.sleep(10)
            if args.once or (args.test_seconds and time.time() - start >= args.test_seconds):
                break
            continue
        if args.once:
            break
        if args.test_seconds and time.time() - start >= args.test_seconds:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
