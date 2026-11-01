#!/usr/bin/env python3
"""TradingAI live HLC 3-Bar dashboard generator.

Reads persisted output of the existing live engine (tradingai-paper-scalp-live)
and renders a static HTML page that nginx serves at /live/dashboard.

Design guarantees:
- Python stdlib + sqlite3 only.
- SQLite opened read-only (mode=ro). Never writes to the database.
- Never invokes the signal engine and never creates/updates signals or trades.
- Renders only public signal data; never reads/emits credentials or secrets.
- Atomic publish (temp file + os.replace); keeps last-good page on failure.
- Single-instance flock; append-only logging; heartbeat JSON.
"""

import argparse
import fcntl
import html
import json
import os
import sqlite3
import sys
import tempfile
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

BASE = "/opt/tradingai"
DEFAULT_DB = os.path.join(BASE, "database", "tradingai.db")
DEFAULT_HTML = os.path.join(BASE, "app", "api", "live.dashboard.html")
LOG_PATH = os.path.join(BASE, "logs", "live_dashboard.log")
ERR_PATH = os.path.join(BASE, "logs", "live_dashboard.err.log")
HEARTBEAT_PATH = os.path.join(BASE, "logs", "live_dashboard.state.json")
LOCK_PATH = os.path.join(BASE, "logs", "live_dashboard.lock")

INSTRUMENTS = ("NIFTY", "BANKNIFTY")
MAX_ROWS = 15
STALE_SECONDS = 15 * 60
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
BURST_INTERVAL = 5
NORMAL_INTERVAL = 60
CANDLE_MINUTES = 5

# Refuse to publish if any of these appear in the rendered document.
FORBIDDEN_MARKERS = (
    "KITE_ACCESS_TOKEN",
    "KITE_API_SECRET",
    "KITE_API_KEY",
    "access_token",
    "api_secret",
    "BEGIN RSA",
    "BEGIN PRIVATE KEY",
    ".env",
    "password",
)


def log(msg, err=False):
    line = f"{datetime.now(_IST).isoformat(timespec='seconds')} {msg}"
    path = ERR_PATH if err else LOG_PATH
    try:
        with open(path, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def market_is_open(now):
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return MARKET_OPEN <= hm <= MARKET_CLOSE


def refresh_interval(now, market_open, entry_pending=False):
    """5s from signal-candle close through trade entry, else 60s.

    Fast polling is active while a NEW signal is still awaiting entry, and
    during the first minute after each 5-min candle close (when a signal and
    its next-candle entry are produced).
    """
    if market_open and (entry_pending or now.minute % CANDLE_MINUTES == 0):
        return BURST_INTERVAL
    return NORMAL_INTERVAL


def connect_ro(db_path):
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def query(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except Exception as exc:  # noqa: BLE001 - surface but do not crash render
        log(f"WARN query failed: {exc}")
        return []


def parse_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return dt.astimezone(_IST)
    except Exception:
        return None


def fmt_num(value, nd=2):
    if value is None:
        return "\u2014"
    try:
        return f"{float(value):.{nd}f}"
    except Exception:
        return html.escape(str(value))


def human_age(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def latest_candle(conn, inst):
    rows = query(
        conn,
        "SELECT timestamp, close FROM market_candles_5m "
        "WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1",
        (inst,),
    )
    if not rows:
        return None, None
    row = rows[0]
    price = None
    try:
        price = float(row["close"]) if row["close"] is not None else None
    except Exception:
        price = None
    return row["timestamp"], price


def signals_for_latest_session(conn, inst):
    return query(
        conn,
        "SELECT signal_id, trade_date, direction, source_candle_ts, status, "
        "reference_price, reference_stop, reference_target, paper_trade_id, updated_at "
        "FROM scalp_signals "
        "WHERE instrument_id=? AND trade_date=("
        "  SELECT MAX(trade_date) FROM scalp_signals WHERE instrument_id=?"
        ") ORDER BY source_candle_ts DESC LIMIT ?",
        (inst, inst, MAX_ROWS),
    )


def trade_for(conn, trade_id):
    if not trade_id:
        return None
    rows = query(
        conn,
        "SELECT trade_id, status, entry, stop, target, entry_time, exit_time, "
        "exit_price, exit_reason, paper_pnl, max_risk, direction "
        "FROM paper_trades WHERE trade_id=? AND scenario='SCALP_HLC' LIMIT 1",
        (trade_id,),
    )
    return rows[0] if rows else None


def r_multiple(trade):
    if not trade:
        return None
    try:
        pnl = trade["paper_pnl"]
        risk = trade["max_risk"]
        if pnl is not None and risk not in (None, 0):
            return float(pnl) / abs(float(risk))
    except Exception:
        pass
    try:
        entry = float(trade["entry"])
        exitp = float(trade["exit_price"])
        stop = float(trade["stop"])
        if abs(entry - stop) > 0:
            sign = 1.0 if (trade["direction"] or "").upper() == "BULL" else -1.0
            return sign * (exitp - entry) / abs(entry - stop)
    except Exception:
        pass
    return None


def pnl_points(trade, price, data_fresh):
    """Realised points for closed trades, unrealised for open trades (fresh data only)."""
    if not trade:
        return None
    try:
        entry = float(trade["entry"]) if trade["entry"] is not None else None
    except Exception:
        return None
    if entry is None:
        return None
    sign = 1.0 if (trade["direction"] or "").upper() == "BULL" else -1.0
    exitp = trade["exit_price"]
    if exitp is not None:
        try:
            return sign * (float(exitp) - entry)
        except Exception:
            return None
    tst = (trade["status"] or "").upper()
    if tst in ("OPEN", "ACTIVE") and data_fresh and price is not None:
        try:
            return sign * (float(price) - entry)
        except Exception:
            return None
    return None


def base_status(signal, trade):
    st = (signal["status"] or "").upper()
    tst = (trade["status"] or "").upper() if trade else ""
    if st == "NEW":
        return "NEW"
    if st == "EXPIRED":
        return "EXPIRED"
    if st == "IGNORED":
        return "IGNORED"
    if st == "TRADED":
        if tst in ("OPEN", "ACTIVE"):
            return "OPEN"
        if tst == "CLOSED":
            return "CLOSED"
        return "TRADED"
    return st or "UNKNOWN"


def status_cell(status, data_stale, sig_age):
    active = status in ("NEW", "OPEN", "TRADED")
    stale = active and (data_stale or (sig_age is not None and sig_age > STALE_SECONDS))
    label = status + (" \u00b7 STALE" if stale else "")
    css = status.lower()
    if stale:
        css += " stale"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def build_rows(conn, inst, now, data_stale, price):
    rows_html = []
    seen = set()
    latest = None
    for sig in signals_for_latest_session(conn, inst):
        sid = sig["signal_id"]
        if sid in seen:
            continue
        seen.add(sid)
        trade = trade_for(conn, sig["paper_trade_id"])
        status = base_status(sig, trade)
        sig_dt = parse_ts(sig["source_candle_ts"])
        sig_age = int((now - sig_dt).total_seconds()) if sig_dt else None
        when = sig_dt.strftime("%Y-%m-%d %H:%M") if sig_dt else "\u2014"
        direction = (sig["direction"] or "\u2014").upper()
        entry = trade["entry"] if trade else sig["reference_price"]
        stop = trade["stop"] if trade else sig["reference_stop"]
        target = trade["target"] if trade else sig["reference_target"]
        exit_price = trade["exit_price"] if trade else None
        exit_reason = (trade["exit_reason"] if trade else None) or "\u2014"
        rm = r_multiple(trade)
        rm_txt = "\u2014" if rm is None else f"{rm:+.2f}R"
        et_dt = parse_ts(trade["entry_time"]) if trade else None
        entry_when = et_dt.strftime("%Y-%m-%d %H:%M") if et_dt else "\u2014"
        pts = pnl_points(trade, price, not data_stale)
        if pts is None:
            pts_txt, pts_css = "\u2014", ""
        else:
            pts_txt = f"{pts:+.2f}"
            pts_css = "pos" if pts > 0 else ("neg" if pts < 0 else "")
        dir_css = "bull" if direction == "BULL" else ("bear" if direction == "BEAR" else "")
        row = (
            "<tr>"
            f'<td class="mono">{when}</td>'
            f'<td class="mono">{entry_when}</td>'
            f'<td class="{dir_css}">{html.escape(direction)}</td>'
            f'<td class="mono">{fmt_num(entry)}</td>'
            f'<td class="mono">{fmt_num(stop)}</td>'
            f'<td class="mono">{fmt_num(target)}</td>'
            f'<td class="mono">{fmt_num(exit_price)}</td>'
            f'<td>{html.escape(str(exit_reason))}</td>'
            f'<td class="mono">{rm_txt}</td>'
            f'<td class="mono {pts_css}">{pts_txt}</td>'
            f'<td>{status_cell(status, data_stale, sig_age)}</td>'
            "</tr>"
        )
        rows_html.append(row)
        if latest is None:
            latest = (when, direction, status)
    return rows_html, latest


def build_section(conn, inst, now, market_open):
    candle_ts, price = latest_candle(conn, inst)
    candle_dt = parse_ts(candle_ts)
    data_age = int((now - candle_dt).total_seconds()) if candle_dt else None
    if candle_dt is None:
        data_state, data_css = "UNAVAILABLE", "unavailable"
    elif data_age > STALE_SECONDS:
        data_state, data_css = "STALE", "stale"
    else:
        data_state, data_css = "FRESH", "fresh"
    data_stale = data_state != "FRESH"
    # Current price only when the underlying candle is fresh.
    price_txt = fmt_num(price) if (price is not None and data_state == "FRESH") else "\u2014"
    candle_txt = candle_ts or "\u2014"
    age_txt = human_age(data_age)

    rows_html, latest = build_rows(conn, inst, now, data_stale, price)
    if rows_html:
        body = (
            "<table><thead><tr>"
            "<th>Signal time (IST)</th><th>Entry time (IST)</th><th>Dir</th>"
            "<th>Entry</th><th>Stop</th><th>Target</th><th>Exit</th>"
            "<th>Exit reason</th><th>R</th><th>P&amp;L (pts)</th><th>Status</th>"
            "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
        )
    else:
        body = '<p class="empty">No persisted signals for the latest session.</p>'

    if latest:
        latest_txt = (
            f'<div class="latest">Latest signal: <b>{html.escape(latest[1])}</b> '
            f'@ {html.escape(latest[0])} &nbsp;'
            f'{status_cell(latest[2], data_stale, None)}</div>'
        )
    else:
        latest_txt = '<div class="latest">Latest signal: \u2014</div>'

    return f"""
    <section>
      <h2>{inst} <span class="badge data {data_css}">DATA {data_state}</span></h2>
      <div class="sub">
        Latest candle: <span class="mono">{html.escape(candle_txt)}</span>
        &nbsp;|&nbsp; Age: <span class="mono">{age_txt}</span>
        &nbsp;|&nbsp; Price: <span class="mono">{price_txt}</span>
      </div>
      {latest_txt}
      {body}
    </section>
    """


def render(db_path, now):
    conn = connect_ro(db_path)
    try:
        market_open = market_is_open(now)
        sections = [build_section(conn, inst, now, market_open) for inst in INSTRUMENTS]
        session = "\u2014"
        entry_pending = False
        for inst in INSTRUMENTS:
            rows = signals_for_latest_session(conn, inst)
            if rows and rows[0]["trade_date"] and session == "\u2014":
                session = rows[0]["trade_date"]
            if any(
                (r["status"] or "").upper() == "NEW" and not r["paper_trade_id"]
                for r in rows
            ):
                entry_pending = True
    finally:
        conn.close()

    generated = now.strftime("%Y-%m-%d %H:%M:%S")
    refresh_note = (
        f"Refreshed every {BURST_INTERVAL}s from signal candle close until trade "
        f"entry, otherwise {NORMAL_INTERVAL}s"
    )
    market_label = "OPEN" if market_open else "CLOSED"
    market_css = "open" if market_open else "closed"
    stale_banner = ""
    if not market_open:
        stale_banner = (
            '<div class="banner closed">MARKET CLOSED \u2014 showing the most recent '
            "persisted session. Live generation resumes on the next trading session.</div>"
        )
    if any("DATA STALE" in s or 'data stale' in s for s in sections):
        stale_banner += (
            '<div class="banner stale">MARKET DATA STALE \u2014 latest candle is older '
            f"than {STALE_SECONDS // 60} minutes; current price is withheld rather than shown stale.</div>"
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TradingAI \u2014 Live HLC 3-Bar Dashboard</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 1.5rem; background: #0b0c15; color: #e8eaf0;
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
h1 {{ color: #00e5ff; font-size: 1.4rem; margin: 0 0 .4rem; }}
h2 {{ color: #9ad7ff; font-size: 1.05rem; margin: 1.6rem 0 .4rem; display: flex;
      align-items: center; gap: .6rem; }}
.meta, .sub {{ color: #9aa4bf; font-size: .82rem; margin: .2rem 0; }}
.latest {{ font-size: .9rem; margin: .5rem 0 .7rem; color: #cdd6ef; }}
.mono {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }}
section {{ border-top: 1px solid #1e2438; padding-top: .3rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
th {{ background: #141a2c; color: #00e5ff; text-align: left; padding: .5rem .45rem;
      position: sticky; top: 0; }}
td {{ padding: .42rem .45rem; border-bottom: 1px solid #1c2236; white-space: nowrap; }}
tbody tr:hover {{ background: #121827; }}
.bull, .pos {{ color: #36d399; font-weight: 600; }}
.bear, .neg {{ color: #fb7185; font-weight: 600; }}
.badge {{ display: inline-block; padding: .12rem .45rem; border-radius: 999px;
         font-size: .7rem; font-weight: 700; letter-spacing: .02em; }}
.badge.new {{ background: #3a3208; color: #fbbf24; }}
.badge.open, .badge.traded {{ background: #06301f; color: #34d399; }}
.badge.closed {{ background: #0b2440; color: #60a5fa; }}
.badge.expired, .badge.ignored {{ background: #232838; color: #94a3b8; }}
.badge.unknown {{ background: #2a2233; color: #c4b5fd; }}
.badge.stale {{ outline: 1px solid #f59e0b; }}
.badge.data.fresh {{ background: #06301f; color: #34d399; }}
.badge.data.stale {{ background: #3a2a06; color: #f59e0b; }}
.badge.data.unavailable {{ background: #3a0f14; color: #fb7185; }}
.banner {{ padding: .55rem .8rem; border-radius: 8px; font-size: .82rem; margin: .6rem 0; }}
.banner.closed {{ background: #1a1f30; color: #cbd5e1; border-left: 3px solid #64748b; }}
.banner.stale {{ background: #3a2a06; color: #fbbf24; border-left: 3px solid #f59e0b; }}
.empty {{ color: #9aa4bf; }}
footer {{ margin-top: 2rem; color: #6b7590; font-size: .76rem; line-height: 1.5; }}
</style>
</head>
<body>
<h1>TradingAI \u2014 Live HLC 3-Bar Dashboard</h1>
<div class="meta">
  Generated: <span class="mono">{generated} IST</span>
  &nbsp;|&nbsp; Market: <span class="badge data {market_css}">{market_label}</span>
  &nbsp;|&nbsp; Session: <span class="mono">{html.escape(str(session))}</span>
  &nbsp;|&nbsp; {refresh_note}
</div>
{stale_banner}
{''.join(sections)}
<footer>
  Read-only view of signals persisted by the existing HLC 3-Bar paper engine.
  This page never creates signals and never writes to the database.
  Rule: 3-bar H/L/C alignment \u2192 entry at next candle open; stop = signal low/high \u00b11pt;
  target = 1.5R; exit on stop/target or EOD 15:25 IST.
  Values shown as \u201c\u2014\u201d are genuinely unavailable (never fabricated).
</footer>
</body>
</html>
"""
    meta = {
        "generated_at": now.isoformat(),
        "market": market_label,
        "session": str(session),
        "entry_pending": bool(entry_pending),
    }
    return doc, meta


def publish(doc, html_path):
    lowered = doc.lower()
    for marker in FORBIDDEN_MARKERS:
        if marker.lower() in lowered:
            raise RuntimeError(f"refusing to publish: forbidden marker detected ({marker})")
    directory = os.path.dirname(html_path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".live.dashboard.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(doc)
        os.chmod(tmp, 0o644)
        os.replace(tmp, html_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_heartbeat(meta):
    try:
        tmp = HEARTBEAT_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(meta, fh)
        os.replace(tmp, HEARTBEAT_PATH)
    except Exception as exc:  # noqa: BLE001
        log(f"WARN heartbeat write failed: {exc}")


def acquire_lock():
    handle = open(LOCK_PATH, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another instance holds the lock; exiting")
        return None
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(description="TradingAI live dashboard renderer")
    parser.add_argument("--once", action="store_true", help="render once then exit")
    parser.add_argument("--db", default=DEFAULT_DB, help="sqlite database path (read-only)")
    parser.add_argument("--html", default=DEFAULT_HTML, help="output html path")
    parser.add_argument("--interval", type=int, default=None, help="override refresh seconds")
    args = parser.parse_args(argv)

    lock = acquire_lock()
    if lock is None:
        return 0

    log(f"worker start pid={os.getpid()} db={args.db} out={args.html}")
    try:
        while True:
            now = datetime.now(_IST)
            market_open = market_is_open(now)
            meta = {}
            ok = True
            try:
                doc, meta = render(args.db, now)
                publish(doc, args.html)
                write_heartbeat(meta)
            except Exception as exc:  # noqa: BLE001
                ok = False
                log(f"ERROR render failed; keeping last-good page: {exc}", err=True)
                log(traceback.format_exc().replace("\n", " | ")[:900], err=True)

            if args.interval:
                interval = args.interval
            else:
                interval = refresh_interval(
                    now, market_open, bool(meta.get("entry_pending"))
                )

            if ok:
                log(
                    f"render ok market={'OPEN' if market_open else 'CLOSED'} "
                    f"session={meta.get('session')} "
                    f"entry_pending={bool(meta.get('entry_pending'))} "
                    f"next_in={interval}s bytes={len(doc)}"
                )
            else:
                log(f"render retry scheduled in {interval}s")
            if args.once:
                return 0
            time.sleep(interval)
    finally:
        try:
            lock.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
