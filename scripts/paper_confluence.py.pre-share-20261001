#!/usr/bin/env python3
"""Paper-traded pivot-bounce feed (EXPERIMENTAL, informational only).

Single strategy: LONG on the S1 touch, SHORT on the R1 touch, anytime during
the day, targeting PP. Stops past S2/R2, flat by 3:15 PM, NSE lots (NIFTY 65 / BANKNIFTY 30; VIX research default 50).

Daily: tops up recent 5m candles, runs the production backtest, logs one row
per session per instrument into paper_pivot, regenerates paper.html and
refreshes backtest.html. Idempotent via INSERT OR IGNORE -- safe for cron.

  python3 paper_confluence.py --topup     # cron: ingest last 3d + log + pages
  python3 paper_confluence.py --backfill  # one-off: log all history, no guard
"""
import sys, os, argparse, sqlite3, importlib.util, json
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/opt/tradingai")
_IST = ZoneInfo("Asia/Kolkata")

spec = importlib.util.spec_from_file_location(
    "ing", "/opt/tradingai/scripts/ingest_historical.py")
ing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ing)
from app.core.db import get_conn
from app.research.cpr_strategy_engine import run_multi_session_backtest
import pandas as pd

PAGE = "/opt/tradingai/frontend/paper.html"

FILTER_HTML = r"""<div class="card" id="dateFilter"><label for="dateSel"><b>Filter by session date:</b></label> <select id="dateSel" style="padding:.4rem .6rem;border-radius:8px;border:1px solid #cbd5e1;font-size:.9rem;max-width:100%"><option value="">All dates</option></select> <span class="meta" id="dateCount"></span></div>"""
FILTER_JS = r"""<script>(function(){var sel=document.getElementById('dateSel');if(!sel)return;var dates=[];var rows=document.querySelectorAll('table tbody tr');rows.forEach(function(tr){var c=tr.cells[0];var d=c?c.textContent.trim():'';if(/^\d{4}-\d{2}-\d{2}$/.test(d)&&dates.indexOf(d)<0)dates.push(d);});dates.sort().reverse();dates.forEach(function(d){var o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o);});function apply(){var v=sel.value,n=0;rows.forEach(function(tr){var c=tr.cells[0];var d=c?c.textContent.trim():'';var show=!v||d===v;tr.style.display=show?'':'none';if(show)n++;});var el=document.getElementById('dateCount');if(el)el.textContent=v?('Showing '+n+' of '+rows.length+' rows'):(''+rows.length+' rows');}sel.addEventListener('change',apply);apply();})();</script>"""

BT_PAGE = "/opt/tradingai/frontend/backtest.html"
RDIR = "/opt/tradingai/research"


def ensure_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_pivot (
        session_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
        state TEXT NOT NULL, direction TEXT,
        entry_price REAL, stop_price REAL, target_price REAL,
        exit_price REAL, exit_reason TEXT, net_pnl REAL, result TEXT,
        gap_direction TEXT, note TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (session_date, instrument_id))""")
    conn.commit()
    conn.close()


def topup(days=3):
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        try:
            candles = ing.fetch_candles_yfinance(inst, days=days)
        except Exception as e:
            print(f"topup {inst} fetch failed: {e}", flush=True)
            continue
        seen, valid = set(), []
        for c in candles:
            ts = ing.normalize_timestamp(c["timestamp"])
            c["timestamp"] = ts
            if ing.validate_candle(c) or ts in seen:
                continue
            seen.add(ts)
            valid.append(c)
        conn = get_conn()
        conn.executemany(
            """INSERT OR IGNORE INTO market_candles_5m
            (candle_id, instrument_id, timestamp, open, high, low, close, volume,
             source, data_state, ingested_at, is_complete)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(f"C-{inst}-{c['timestamp']}", inst, c["timestamp"], c["open"], c["high"],
              c["low"], c["close"], c["volume"], c["source"], c["data_state"],
              datetime.now(_IST).isoformat(), 1) for c in valid])
        conn.commit()
        conn.close()
        print(f"topup {inst}: fetched={len(candles)} valid={len(valid)}", flush=True)


def session_complete(df, date_str, today_str):
    if date_str < today_str:
        return True
    day = df[df["timestamp"].dt.tz_localize(None).dt.strftime("%Y-%m-%d") == date_str]
    if day.empty:
        return False
    last = pd.to_datetime(day["timestamp"].max())
    try:
        last_ist = last.tz_convert(_IST) if last.tzinfo else last.tz_localize("UTC").tz_convert(_IST)
    except Exception:
        return False
    return last_ist.hour * 60 + last_ist.minute >= 15 * 60 + 15


def day_complete_ts(max_ts):
    """True if a session's last candle is at/after 15:15 IST (day closed).

    Lets the EOD cron log a completed today instead of waiting one extra day,
    while still skipping genuinely incomplete sessions (pre-market/mid-day)."""
    if not max_ts:
        return False
    try:
        t = datetime.fromisoformat(str(max_ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=ZoneInfo("UTC"))
        t = t.astimezone(_IST)
        return t.hour * 60 + t.minute >= 15 * 60 + 15
    except Exception:
        try:
            return int(str(max_ts)[11:13]) * 60 + int(str(max_ts)[14:16]) >= 15 * 60 + 15
        except (ValueError, IndexError):
            return False


def log_pivot(backfill=False):
    from datetime import datetime as dt
    today = dt.now(_IST).strftime("%Y-%m-%d")
    now = dt.now(_IST).isoformat()
    conn = get_conn()
    total = 0
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        rows = conn.execute(
            'SELECT open,high,low,close,timestamp FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp',
            (inst,)).fetchall()
        df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        result = run_multi_session_backtest(df, inst)
        by_date = {t["session_date"]: t for t in result.get("trades", [])}
        for s in result.get("signals", []):
            d = s["date"]
            if not backfill and not session_complete(df, d, today):
                continue
            t = by_date.get(d)
            if t and t.get("strategy") == "PIVOT_BOUNCE":
                row = (d, inst, "SIGNAL", t["direction"], t["entry_price"],
                       t["stop_price"], t["target_price"], t["exit_price"],
                       t["exit_reason"], t["net_pnl"], t["result"],
                       t.get("gap_direction"), "pivot-bounce paper trade", now)
            else:
                reason = f"no signal: {s.get('state')}" if not t else "no fill"
                row = (d, inst, "NO_TRADE", None, None, None, None, None, None,
                       0.0, "SKIP", None, reason, now)
            conn.execute(
                """INSERT OR IGNORE INTO paper_pivot
                (session_date, instrument_id, state, direction, entry_price, stop_price,
                 target_price, exit_price, exit_reason, net_pnl, result, gap_direction, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            total += 1
    conn.commit()
    conn.close()
    print(f"pivot rows processed={total} (new inserts only; history frozen)", flush=True)


def money(x):
    x = float(x or 0)
    return ("+" if x > 0 else "-" if x < 0 else "") + f"{abs(x):,.2f}"


def ensure_spread_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_spreads (
        session_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
        direction TEXT, strategy TEXT, expiry TEXT, atm REAL, spot_ref REAL,
        legs TEXT, width REAL, lot INTEGER, credit REAL,
        state TEXT NOT NULL DEFAULT 'OPEN',
        entry_time TEXT, exit_time TEXT, exit_reason TEXT, exit_spot REAL,
        r_spot REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (session_date, instrument_id))""")
    conn.commit()
    conn.close()


def log_spreads():
    """Create today's paper spread per instrument on aligned SIGNAL.

    One row/session/instrument (INSERT OR IGNORE). Legs from the real strike
    grid; credit attempted live (NULL while NSE unreachable -> structure-only).
    NIFTY/BANKNIFTY only (VIX non-tradable, no options)."""
    from app.research.cpr_trigger_engine import today_state
    from app.options.weekly_spreads import build_spread, next_expiry
    from app.options import nse_chain
    from datetime import datetime as dt
    ensure_spread_table()
    today = dt.now(_IST).strftime("%Y-%m-%d")
    now = dt.now(_IST).isoformat()
    conn = get_conn()
    for inst in ("NIFTY", "BANKNIFTY"):
        try:
            st = today_state(inst, variant="aligned")
        except Exception as e:
            print(f"spreads {inst} state failed: {e}", flush=True)
            continue
        if not isinstance(st, dict) or st.get("state") != "SIGNAL":
            continue
        entry = st.get("entry")
        if entry is None:
            continue
        sp = build_spread(inst, st.get("direction"), entry)
        if sp.get("error"):
            continue
        try:
            exp = next_expiry(inst, today)
        except Exception:
            exp = None
        try:
            credit = nse_chain.get_credit(inst, sp["legs"])
        except Exception:
            credit = None
        conn.execute(
            """INSERT OR IGNORE INTO paper_spreads
            (session_date, instrument_id, direction, strategy, expiry, atm, spot_ref,
             legs, width, lot, credit, state, entry_time, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (today, inst, sp["direction"], sp["strategy"], exp, sp["atm"], entry,
             json.dumps(sp["legs"]), sp["width"], sp["lot"], credit,
             "OPEN", now, now, now))
    conn.commit()
    conn.close()
    print("spreads logged (new inserts only)", flush=True)


def mark_spreads():
    """Close OPEN spreads on spot stop/target (opens execution) or 15:20 EOD.

    Premiums unknown while NSE unreachable, so exits follow the approved
    spot trigger levels; r_spot is informational until live revaluation."""
    from app.research.cpr_trigger_engine import OPEN_STOP_PCT, OPEN_TARGET_PCT
    from datetime import datetime as dt
    today = dt.now(_IST).strftime("%Y-%m-%d")
    now = dt.now(_IST).isoformat()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM paper_spreads WHERE state='OPEN'").fetchall()
    for r in rows:
        inst, day = r["instrument_id"], r["session_date"]
        try:
            entry = float(r["spot_ref"])
        except (TypeError, ValueError):
            continue
        dr = r["direction"]
        sp, tp = OPEN_STOP_PCT, OPEN_TARGET_PCT
        stop = entry * (1 - sp) if dr == "BULL" else entry * (1 + sp)
        tgt = entry * (1 + tp) if dr == "BULL" else entry * (1 - tp)
        candles = conn.execute(
            "SELECT timestamp, open FROM market_candles_5m WHERE instrument_id=? "
            "AND substr(timestamp,1,10)=? AND substr(timestamp,12,5)>=substr(?,12,5) "
            "ORDER BY timestamp", (inst, day, r["entry_time"] or "")).fetchall()
        closed = None
        for c in candles:
            try:
                o = float(c["open"])
            except (TypeError, ValueError):
                continue
            if o == entry:
                continue
            if dr == "BULL":
                s, t = o <= stop, o >= tgt
            else:
                s, t = o >= stop, o <= tgt
            if s:
                closed = (c["timestamp"], o, "STOP")
                break
            if t:
                closed = (c["timestamp"], o, "TARGET")
                break
        if closed is None:
            eod = [c for c in candles if c["timestamp"][11:16] == "15:20"]
            if not eod:
                continue
            last = float(eod[0]["open"])
            closed = (eod[0]["timestamp"], last, "EOD-1520")
        xt, xp, how = closed
        risk = abs(entry * sp)
        move = (xp - entry) if dr == "BULL" else (entry - xp)
        conn.execute(
            "UPDATE paper_spreads SET state='CLOSED', exit_time=?, exit_reason=?, "
            "exit_spot=?, r_spot=?, updated_at=? "
            "WHERE session_date=? AND instrument_id=? AND state='OPEN'",
            (xt, how, xp, round(move / risk, 3) if risk else 0.0, now,
             day, inst))
    conn.commit()
    conn.close()
    print("spreads marked", flush=True)


def ensure_align_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_align (
        session_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
        variant TEXT NOT NULL DEFAULT 'aligned',
        state TEXT NOT NULL, direction TEXT, level TEXT,
        entry_time TEXT, entry_price REAL, stop_price REAL, target_price REAL,
        exit_time TEXT, exit_price REAL, exit_reason TEXT,
        r_multiple REAL, result TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY (session_date, instrument_id, variant))""")
    conn.commit()
    conn.close()


def log_align(backfill=False):
    """Log approved-spec (opens execution) trigger results per variant.

    One row/session/instrument/variant. Idempotent via INSERT OR IGNORE.
    Incomplete today skipped unless backfill. Covers plain + aligned.
    result stores the shared decay_win() label (not raw sign), so paper.html
    and the API agree by construction."""
    from app.research.cpr_trigger_engine import run_opens_range, decay_win
    from datetime import datetime as dt
    ensure_align_table()
    today = dt.now(_IST).strftime("%Y-%m-%d")
    now = dt.now(_IST).isoformat()
    conn = get_conn()
    total = 0
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        day_max = {d: m for d, m in conn.execute(
            "SELECT substr(timestamp,1,10), max(timestamp) FROM market_candles_5m "
            "WHERE instrument_id=? GROUP BY substr(timestamp,1,10)", (inst,))}
        for variant in ("plain", "aligned"):
            try:
                res = run_opens_range(inst, "2000-01-01", "2100-01-01", variant)
            except Exception as e:
                print(f"align {inst}/{variant} failed: {e}", flush=True)
                continue
            for t in res.get("trades", []):
                if not backfill and (t["trade_date"] > today or (
                        t["trade_date"] == today and not day_complete_ts(day_max.get(today)))):
                    continue
                dr = t["direction"]
                entry = t["entry"]
                stop = entry * (0.995 if dr == "BULL" else 1.005)
                tgt = entry * (1.02 if dr == "BULL" else 0.98)
                r = t["r_multiple"]
                row = (t["trade_date"], inst, variant, "SIGNAL", dr, t["level"],
                       t.get("entry_time"), entry, round(stop, 2), round(tgt, 2),
                       t.get("exit_time"), t["exit"], t["exit_reason"], r,
                       decay_win(dr, entry, t["exit"], r, inst), now)
                conn.execute(
                    """INSERT OR IGNORE INTO paper_align
                    (session_date, instrument_id, variant, state, direction, level,
                     entry_time, entry_price, stop_price, target_price, exit_time,
                     exit_price, exit_reason, r_multiple, result, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
                total += 1
    conn.commit()
    conn.close()
    print(f"align rows processed={total} (new inserts only; history frozen)", flush=True)


def ensure_trigger_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_trigger (
        session_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
        state TEXT NOT NULL, direction TEXT, level TEXT,
        entry_price REAL, stop_price REAL, target_price REAL,
        exit_price REAL, exit_reason TEXT, r_multiple REAL, result TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (session_date, instrument_id))""")
    conn.commit()
    conn.close()


def log_trigger(backfill=False):
    """Log no-filter CPR trigger results (one row/session/instrument, R units).

    Same triggers as /api/backtest/cpr-triggers. Idempotent via
    INSERT OR IGNORE -- safe for cron. Incomplete today skipped unless backfill."""
    from app.research.cpr_trigger_engine import day_levels, first_trigger, exit_trade
    from datetime import datetime as dt
    ensure_trigger_table()
    today = dt.now(_IST).strftime("%Y-%m-%d")
    now = dt.now(_IST).isoformat()
    conn = get_conn()
    total = 0
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        rows = conn.execute(
            'SELECT open,high,low,close,timestamp FROM market_candles_5m WHERE instrument_id=? ORDER BY timestamp',
            (inst,)).fetchall()
        by_day = {}
        for r in rows:
            by_day.setdefault(r['timestamp'][:10], []).append(dict(r))
        for d in sorted(by_day):
            if not backfill and (d > today or (
                    d == today and not day_complete_ts(max(c["timestamp"] for c in by_day[d])))):
                continue
            prev_days = sorted(x for x in by_day if x < d)
            if not prev_days:
                continue
            pc = by_day[prev_days[-1]]
            lv = day_levels(max(c['high'] for c in pc), min(c['low'] for c in pc), pc[-1]['close'])
            day = by_day[d]
            if not lv or not day:
                continue
            sig = first_trigger(day, lv)
            if not sig:
                row = (d, inst, "NO_TRADE", None, None, None, None, None,
                       None, None, 0.0, "SKIP", now)
            else:
                entry = float(day[sig['index']]['close'])
                stop = entry * (0.99 if sig['direction'] == 'BULL' else 1.01)
                tgt = entry * (1.02 if sig['direction'] == 'BULL' else 0.98)
                r, xp, how = exit_trade(sig['direction'], entry, day[sig['index'] + 1:])
                res = 'WIN' if r > 0 else ('LOSS' if r < 0 else 'FLAT')
                row = (d, inst, "SIGNAL", sig['direction'], sig['level'], entry,
                       stop, tgt, xp, how, r, res, now)
            conn.execute(
                """INSERT OR IGNORE INTO paper_trigger
                (session_date, instrument_id, state, direction, level, entry_price, stop_price,
                 target_price, exit_price, exit_reason, r_multiple, result, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            total += 1
    conn.commit()
    conn.close()
    print(f"trigger rows processed={total} (new inserts only; history frozen)", flush=True)


def maxdd(pnls):
    peak, dd, cum = 0.0, 0.0, 0.0
    for p in pnls:
        cum += float(p)
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return dd


def render_page():
    conn = get_conn()
    cur = conn.execute("SELECT * FROM paper_pivot ORDER BY session_date, instrument_id")
    cols = [d[0] for d in cur.description]
    recs = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur2 = conn.execute("SELECT * FROM paper_trigger ORDER BY session_date, instrument_id")
    cols2 = [d[0] for d in cur2.description]
    trigs = [dict(zip(cols2, r)) for r in cur2.fetchall()]
    try:
        cur3 = conn.execute("SELECT * FROM paper_align ORDER BY session_date, instrument_id, variant")
        cols3 = [d[0] for d in cur3.description]
        aligns = [dict(zip(cols3, r)) for r in cur3.fetchall()]
    except Exception:
        aligns = []
    try:
        cur4 = conn.execute("SELECT * FROM paper_spreads ORDER BY session_date DESC, instrument_id")
        cols4 = [d[0] for d in cur4.description]
        spreads = [dict(zip(cols4, r)) for r in cur4.fetchall()]
    except Exception:
        spreads = []
    conn.close()
    sigs = [r for r in recs if r["state"] == "SIGNAL"]

    def card(title, ts):
        n = len(ts)
        w = sum(1 for t in ts if (t["net_pnl"] or 0) > 0)
        l = sum(1 for t in ts if (t["net_pnl"] or 0) < 0)
        pnl = sum(t["net_pnl"] or 0 for t in ts)
        wr = w / n * 100 if n else 0
        exp = pnl / n if n else 0
        return (f'<div class="card"><h3>{title}</h3><div class="kv">'
                f'<dt>Paper trades</dt><dd>{n}</dd>'
                f'<dt>Above / below reference</dt><dd>{w} / {l}</dd>'
                f'<dt>Share above reference (hypothetical)</dt><dd >{wr:.1f}%</dd>'
                f'<dt>Net P&amp;L</dt><dd class="{("win" if pnl > 0 else "loss" if pnl < 0 else "")}">{money(pnl)}</dd>'
                f'<dt>Expectancy</dt><dd>{money(exp)}</dd></div></div>')

    cum, pts = 0.0, []
    for r in sorted(sigs, key=lambda x: (x["session_date"], x["instrument_id"])):
        cum += r["net_pnl"] or 0
        pts.append(cum)
    if pts:
        wpx, hpx = 600, 160
        mn, mx = min(0, min(pts)), max(0, max(pts))
        span = (mx - mn) or 1.0
        step = wpx / max(len(pts) - 1, 1)
        path = " ".join(f"{i * step:.1f},{hpx - 10 - (v - mn) / span * (hpx - 20):.1f}"
                        for i, v in enumerate(pts))
        curve = (f'<svg viewBox="0 0 {wpx} {hpx}" style="width:100%;background:#fff;border:1px solid #e2e8f0;border-radius:8px">'
                 f'<polyline points="{path}" fill="none" stroke="#2563eb" stroke-width="2"/></svg>')
    else:
        curve = "<p>No paper signals logged yet.</p>"

    def trig_card(title, ts):
        ts = [t for t in ts if t["state"] == "SIGNAL"]
        n = len(ts)
        w = sum(1 for t in ts if (t["r_multiple"] or 0) > 0)
        l = sum(1 for t in ts if (t["r_multiple"] or 0) < 0)
        tot = sum(t["r_multiple"] or 0 for t in ts)
        wr = w / n * 100 if n else 0
        return (f'<div class="card"><h3>{title} (trigger)</h3><div class="kv">'
                f'<dt>Classified sessions</dt><dd>{n}</dd>'
                f'<dt>Above / below reference</dt><dd>{w} / {l}</dd>'
                f'<dt>Share above reference (hypothetical)</dt><dd >{wr:.1f}%</dd>'
                f'<dt>Total R</dt><dd class="{("win" if tot > 0 else "loss" if tot < 0 else "")}">{tot:+.2f}R</dd>'
                f'<dt>Avg R</dt><dd>{(tot / n if n else 0):+.3f}R</dd></div></div>')

    def trig_ledger():
        out = []
        for r in sorted(trigs, key=lambda x: (x["session_date"], x["instrument_id"]), reverse=True):
            if r["state"] == "SIGNAL":
                d = ""
                out.append(
                    f'<tr><td>{r["session_date"]}</td><td>{r["instrument_id"]}</td><td>SIGNAL</td>'
                    f'<td>{"Upward" if r["direction"] in ("BULL","LONG") else "Downward"}</td><td>{r["level"] or ""}</td>'
                    f'<td>{r["entry_price"]:.2f}</td><td>{r["exit_price"]:.2f}</td>'
                    f'<td class="{("win" if (r["r_multiple"] or 0) > 0 else "loss")}">{(r["r_multiple"] or 0):+.2f}R</td>'
                    f'<td>{r["exit_reason"]}</td></tr>')
            else:
                out.append(
                    f'<tr><td>{r["session_date"]}</td><td>{r["instrument_id"]}</td>'
                    f'<td class="bear">NO TRADE</td><td colspan="5">no trigger</td><td>-</td></tr>')
        return "\n".join(out)

    def align_card(title, ts):
        ts = [t for t in ts if t["state"] == "SIGNAL"]
        n = len(ts)
        w = sum(1 for t in ts if (t.get("result") or '') == 'WIN')
        l = sum(1 for t in ts if (t.get("result") or '') == 'LOSS')
        tot = sum(t["r_multiple"] or 0 for t in ts)
        wr = w / n * 100 if n else 0
        return (f'<div class="card"><h3>{title} (align)</h3><div class="kv">'
                f'<dt>Classified sessions</dt><dd>{n}</dd>'
                f'<dt>Above / below reference</dt><dd>{w} / {l}</dd>'
                f'<dt>Share above reference (hypothetical)</dt><dd >{wr:.1f}%</dd></div></div>')

    def align_ledger(inst=None):
        out = []
        # One truth on display: aligned variant, tradable instruments only.
        # (plain rows stay in paper_align table; VIX rows stay in DB.)
        shown = [x for x in aligns if x["instrument_id"] != "INDIA_VIX"
                 and x.get("variant", "aligned") == "aligned"
                 and (inst is None or x["instrument_id"] == inst)]
        for r in sorted(shown, key=lambda x: (x["session_date"], x["instrument_id"]), reverse=True):
            if r["state"] == "SIGNAL":
                d = ""
                wl = (r.get("result") or "")
                out.append(
                    f'<tr><td>{r["session_date"]}</td><td>{r["instrument_id"]}</td>'
                    f'<td>{"Upward" if r["direction"] in ("BULL","LONG") else "Downward"}</td><td>{r["level"] or ""}</td>'
                    f'<td>{(r["entry_time"] or "")[11:16]}</td><td>{r["entry_price"]:.2f}</td>'
                    f'<td>{(r["exit_time"] or "")[11:16]}</td><td>{r["exit_price"]:.2f}</td>'
                    f'<td>{"Above reference" if wl == "WIN" else ("Below reference" if wl == "LOSS" else "—")}</td>'
                    f'<td>{(r["exit_reason"] or "").replace("EOD-1520", "EOD").replace("EOD-1510", "EOD")}</td></tr>')
            else:
                out.append(
                    f'<tr><td>{r["session_date"]}</td><td>{r["instrument_id"]}</td>'
                    f'<td>No classified session</td><td colspan="6">no classified observation</td><td>-</td></tr>')
        return "\n".join(out)

    def ledger(inst):
        out = []
        rows = sorted([r for r in recs if r["instrument_id"] == inst],
                      key=lambda x: x["session_date"], reverse=True)
        for r in rows:
            if r["state"] == "SIGNAL":
                d = "bull" if r["direction"] == "LONG" else "bear"
                out.append(
                    f'<tr><td>{r["session_date"]}</td><td>SIGNAL</td>'
                    f'<td class="{d}">{r["direction"]}</td>'
                    f'<td>{r["entry_price"]:.2f}</td><td>{r["exit_price"]:.2f}</td>'
                    f'<td class="{("win" if (r["net_pnl"] or 0) > 0 else "loss")}">{money(r["net_pnl"])}</td>'
                    f'<td>{r["exit_reason"]}</td></tr>')
            else:
                out.append(
                    f'<tr><td>{r["session_date"]}</td>'
                    f'<td class="bear">NO TRADE</td><td colspan="4">{r["note"]}</td><td>-</td></tr>')
        return "\n".join(out)

    def _strike(x):
        try:
            return ('%g' % float(x))
        except (TypeError, ValueError):
            return '?'

    def legs_text(row):
        try:
            legs = json.loads(row.get("legs") or "[]")
        except Exception:
            legs = []
        return "<br>".join(f'{l.get("side")} {l.get("type")} {_strike(l.get("strike"))}'
                           for l in legs) or "—"

    def spread_card(inst):
        rows = [r for r in spreads if r["instrument_id"] == inst]
        if not rows:
            return (f'<div class="card"><h3>{inst} spread</h3><div class="kv">'
                    f'<dt>Status</dt><dd>No paper spread yet</dd></div></div>')
        r = rows[0]
        return (f'<div class="card"><h3>{inst} spread</h3><div class="kv">'
                f'<dt>Strategy</dt><dd>{r.get("strategy") or "—"}</dd>'
                f'<dt>Expiry</dt><dd>{r.get("expiry") or "—"}</dd>'
                f'<dt>Legs</dt><dd>{legs_text(r)}</dd>'
                f'<dt>Status</dt><dd>{r.get("state")} · {r.get("session_date")}</dd></div></div>')

    def spread_ledger():
        out = []
        for r in spreads:
            try:
                legs = json.loads(r.get("legs") or "[]")
                ltxt = " / ".join(f'{l.get("side")} {l.get("type")}{_strike(l.get("strike"))}'
                                  for l in legs) or "—"
            except Exception:
                ltxt = "—"
            out.append(
                f'<tr><td>{r["session_date"]}</td><td>{r["instrument_id"]}</td>'
                f'<td>{r.get("strategy") or ""}</td><td>{r.get("expiry") or ""}</td>'
                f'<td>{ltxt}</td><td>{r.get("state")}</td>'
                f'<td>{(r.get("exit_reason") or "").replace("EOD-1520", "EOD").replace("EOD-1510", "EOD")}</td></tr>')
        return "\n".join(out)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-MJ3X88QYEL"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());

  gtag('config', 'G-MJ3X88QYEL');
</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historical Model Observations (Hypothetical) | TradingAI.in</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="apple-touch-icon" href="/favicon-180.png">
<meta name="description" content="A dated journal of hypothetical rule-based market observations for NIFTY and BANKNIFTY, recorded for study. Historical and hypothetical — not investment advice.">
<link rel="canonical" href="https://tradingai.in/paper.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="TradingAI.in">
<meta property="og:url" content="https://tradingai.in/paper.html">
<meta property="og:title" content="Historical Model Observations (Hypothetical) | TradingAI.in">
<meta property="og:description" content="A dated journal of hypothetical rule-based market observations for NIFTY and BANKNIFTY, recorded for study. Historical and hypothetical — not investment advice.">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="Historical Model Observations (Hypothetical) | TradingAI.in">
<meta name="twitter:description" content="A dated journal of hypothetical rule-based market observations for NIFTY and BANKNIFTY, recorded for study. Historical and hypothetical — not investment advice.">
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "WebPage", "name": "Historical Model Observations (Hypothetical) | TradingAI.in", "url": "https://tradingai.in/paper.html", "description": "A dated journal of hypothetical rule-based market observations for NIFTY and BANKNIFTY, recorded for study. Historical and hypothetical — not investment advice.", "isPartOf": {{"@type": "WebSite", "name": "TradingAI.in", "url": "https://tradingai.in/"}}}}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f1f5f9;color:#0f172a;line-height:1.5}}
.topbar{{background:#0b1e3a;color:#fff;padding:.6rem 1.2rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem}}
.brand{{font-size:1.4rem;font-weight:800}}.brand .dot{{color:#22d3ee}}
.tagline{{font-size:.85rem;color:#cbd5e1;margin-left:.8rem}}
nav.main{{background:#0b1e3a;color:#cbd5e1;border-top:1px solid #1e3a5f;padding:.5rem 1.2rem;display:flex;gap:1.5rem;justify-content:flex-end;font-size:.9rem;flex-wrap:wrap}}
nav.main a{{color:#cbd5e1;text-decoration:none}}nav.main a.active,nav.main a:hover{{color:#fff;border-bottom:2px solid #38bdf8;padding-bottom:2px}}
.wrap{{max-width:1400px;margin:0 auto;padding:1rem}}
h1{{font-size:1.6rem;color:#0f172a;margin-bottom:.4rem}}
h1 .exp{{font-size:1rem;color:#a78bfa}}
h2{{color:#0b1e3a;margin:1.2rem 0 .6rem;font-size:1.15rem}}
h3{{font-size:1rem;color:#0f172a}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem;margin:1rem 0}}
.card{{background:#fff;padding:1.2rem;border-radius:12px;border:1px solid #e2e8f0}}
.kv{{display:grid;grid-template-columns:auto 1fr;gap:.3rem 1rem}}.kv dt{{color:#64748b}}.kv dd{{text-align:right;font-variant-numeric:tabular-nums}}
table{{width:100%;border-collapse:collapse;font-size:.82rem;margin:.5rem 0}}
th{{color:#64748b;font-weight:700;text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e2e8f0}}
td{{padding:.35rem .5rem;border-bottom:1px solid #e2e8f0;font-variant-numeric:tabular-nums}}
.win{{color:#15803d;font-weight:700}}.loss{{color:#b91c1c;font-weight:700}}.bear{{color:#b91c1c}}.bull{{color:#15803d}}
.ok{{background:#f0fdf4;border:1px solid #bbf7d0;padding:1rem;border-radius:8px;margin:1rem 0}}
.note{{font-size:.8rem;color:#475569;margin-top:.5rem}}
.ok h3,.ok p{{color:#334155}}
.pill{{font-size:.72rem;font-weight:700;padding:.1rem .5rem;border-radius:999px;background:#eff6ff;color:#2563eb}}
.pill.normal{{background:#f8fafc;color:#334155;border:1px solid #e2e8f0}}
footer{{background:#0b1e3a;color:#94a3b8;text-align:center;font-size:.75rem;padding:1rem;margin-top:1.2rem}}
</style>
</head>
<body>
<div class="topbar"><div><img src="/favicon.svg" alt="TradingAI logo" style="width:26px;height:26px;vertical-align:-6px;margin-right:.45rem"><span class="brand">TradingAI<span class="dot">.in</span></span><span class="tagline">Model Observations</span></div></div>
<nav class="main" aria-label="Primary"><a href="/">Home</a><a href="/indices/nifty.html">NIFTY Outlook</a><a href="/indices/banknifty.html">BANKNIFTY Outlook</a><a href="/backtest.html">Historical Analysis</a><a href="/tools.html">Tools</a><a href="/learn.html">Learn</a><a href="/methodology.html">Methodology</a></nav>
<div class="wrap">
<h1>Historical Model Observations <span class="exp">HYPOTHETICAL</span></h1>
<p class="note">Snapshot rendered {datetime.now(_IST).strftime('%Y-%m-%d %H:%M')} IST — rows below are frozen historical records for study.</p>
<div class="ok"><h3>What this is</h3><p>One hypothetical observation per day per instrument from the CPR classification system (same rules as the <a href="/backtest.html">historical scenario analysis</a>): first classified observation per session, reference observation at the next open in [09:20,15:20), assumed reference bounds 0.5% / 2% evaluated at subsequent opens, session reference close at the 15:20 open. Rows are frozen once recorded. No real money, no positions, no instructions — study material only.</p><p class="note">Rules: <a href="/methodology.html">methodology</a> · <a href="/learn.html">learn</a></p></div><div class="notice" style="background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;border-radius:8px;padding:.55rem .9rem;font-size:.78rem;margin:.7rem 0">TradingAI.in provides general educational market information based on predefined rules and public data. This content does not consider your financial circumstances, objectives, or risk profile. It is not investment advice, a research recommendation, or an instruction to buy, sell, or hold any security or derivative.</div>
<h2>Spread structures studied (educational reference)</h2>
<div class="card"><p class="note">Structures below were studied hypothetically in past sessions. Legs and expiries reference the strike grid at the time; no profit or loss is shown or implied, and nothing suggests using any structure on any day.</p></div>
<h2>Recorded observations by session (hypothetical)</h2>
<div class="grid">
{align_card("NIFTY", [t for t in aligns if t["instrument_id"] == "NIFTY" and t["variant"] == "aligned"])}
{align_card("BANKNIFTY", [t for t in aligns if t["instrument_id"] == "BANKNIFTY" and t["variant"] == "aligned"])}
</div>
{FILTER_HTML}
<h2>NIFTY observations journal</h2>
<table><thead><tr><th>Date</th><th>Instrument</th><th>Classified direction</th><th>Context level</th><th>Observation time</th><th>Reference price</th><th>Session-close time</th><th>Close price</th><th>Reference outcome</th><th>Session-close basis</th></tr></thead>
<tbody>
{align_ledger("NIFTY")}
</tbody></table>
<h2>BANKNIFTY observations journal</h2>
<table><thead><tr><th>Date</th><th>Instrument</th><th>Classified direction</th><th>Context level</th><th>Observation time</th><th>Reference price</th><th>Session-close time</th><th>Close price</th><th>Reference outcome</th><th>Session-close basis</th></tr></thead>
<tbody>
{align_ledger("BANKNIFTY")}
</tbody></table>
<h2>Structures journal (hypothetical reference)</h2>
<table><thead><tr><th>Date</th><th>Instrument</th><th>Structure studied</th><th>Reference expiry</th><th>Legs recorded</th><th>Record state</th><th>Session-close basis</th></tr></thead>
<tbody>
{spread_ledger()}
</tbody></table>
</div>
<footer style="background:#0b1e3a;color:#94a3b8;text-align:center;font-size:.78rem;padding:1.2rem;margin-top:1.5rem"><nav aria-label="Footer"><a href="/contact.html" style="color:#cbd5e1">About</a><a href="/methodology.html" style="color:#cbd5e1">Methodology</a><a href="/learn.html" style="color:#cbd5e1">Learn</a><a href="/tools.html" style="color:#cbd5e1">Tools</a><a href="/disclaimer.html" style="color:#cbd5e1">Risk Disclosure</a><a href="/terms.html" style="color:#cbd5e1">Terms of Use</a><a href="/privacy.html" style="color:#cbd5e1">Privacy Policy</a><a href="/refund-policy.html" style="color:#cbd5e1">Refund Policy</a><a href="/affiliate-disclosure.html" style="color:#cbd5e1">Affiliate Disclosure</a><a href="/contact.html" style="color:#cbd5e1">Contact</a></nav><div>TradingAI.in · Educational market analytics · Not investment advice</div></footer>
{FILTER_JS}
</body>
</html>"""
    with open(PAGE, "w") as f:
        f.write(html)
    print(f"page written: {len(sigs)} signals, {len(recs)} rows", flush=True)


def swap_tbody(html, heading, rows):
    h = html.find("<h2>" + heading + "</h2>")
    if h < 0:
        return html
    tb = html.find("<tbody>", h) + len("<tbody>")
    te = html.find("</tbody>", tb)
    return html[:tb] + "\n" + "\n".join(rows) + "\n" + html[te:]


def bt_row(t):
    d = "bull" if t["direction"] == "LONG" else "bear"
    cp = (t.get("cpr_classification") or "").lower()
    cp = cp if cp in ("narrow", "wide") else "normal"
    lad = {"ASCENDING": "ASC", "DESCENDING": "DESC"}.get(t.get("ladder") or "", "NEU")
    return (f'<tr><td>{t["session_date"]}</td><td>{t["strategy"]}</td><td class="{d}">{t["direction"]}</td>'
            f'<td><span class="pill {cp}">{t.get("cpr_classification") or "NORMAL"}</span></td><td>{lad}</td>'
            f'<td>{float(t["entry_price"]):.2f}</td><td>{float(t["exit_price"]):.2f}</td>'
            f'<td class="{("win" if float(t["net_pnl"] or 0) > 0 else "loss")}">{money(t["net_pnl"])}</td>'
            f'<td>{t.get("exit_reason") or ""}</td></tr>')


def refresh_backtest():
    """Rebuild backtest.html from research CSVs + appended live paper SIGNAL days."""
    import csv as _csv
    led, raw = {}, {}
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        try:
            with open(f"{RDIR}/cpr_trade_ledger_{inst}.csv") as f:
                for r in _csv.DictReader(f):
                    led.setdefault(inst, {})[r["session_date"]] = r
            with open(f"{RDIR}/cpr_daily_signals_{inst}.csv") as f:
                for r in _csv.DictReader(f):
                    raw[r.get("selected_strategy") or "UNKNOWN"] = \
                        raw.get(r.get("selected_strategy") or "UNKNOWN", 0) + 1
        except FileNotFoundError:
            continue
    conn = get_conn()
    paper = conn.execute(
        "SELECT session_date, instrument_id, direction, entry_price, stop_price, target_price,"
        " exit_price, exit_reason, net_pnl, result, gap_direction FROM paper_pivot WHERE state='SIGNAL'"
        " ORDER BY session_date").fetchall()
    conn.close()
    n_appended = 0
    csv_max = max((d for ts in led.values() for d in ts), default="")
    for d, inst, direc, ep, sp, tp, xp, xr, pnl, res, gap in paper:
        if d in led.get(inst, {}) or d <= csv_max:
            continue
        led.setdefault(inst, {})[d] = {
            "session_date": d, "strategy": "PIVOT_BOUNCE", "direction": direc,
            "cpr_classification": "", "ladder": "", "entry_price": str(ep),
            "exit_price": str(xp), "net_pnl": str(pnl), "exit_reason": xr or "",
            "result": res}
        n_appended += 1

    all_tr = [t for ts in led.values() for t in ts.values()]
    strats = sorted({t["strategy"] for t in all_tr})
    research = []
    for st in strats:
        tr = [t for t in all_tr if t["strategy"] == st]
        n = len(tr)
        w = sum(1 for t in tr if float(t["net_pnl"]) > 0)
        l = sum(1 for t in tr if float(t["net_pnl"]) < 0)
        wr = w / n * 100 if n else 0
        pnl = sum(float(t["net_pnl"]) for t in tr)
        avg = pnl / n if n else 0
        gp = sum(float(t["net_pnl"]) for t in tr if float(t["net_pnl"]) > 0)
        gl = abs(sum(float(t["net_pnl"]) for t in tr if float(t["net_pnl"]) < 0))
        pf = f"{gp / gl:.2f}" if gl > 0 else ("inf" if gp > 0 else "N/A")
        dd = maxdd([float(t["net_pnl"]) for t in sorted(tr, key=lambda x: x["session_date"])])
        research.append(
            f'<tr><td><span class="pill normal">{st}</span></td><td>{raw.get(st, n)}</td><td>{n}</td><td>{w}</td><td>{l}</td>'
            f'<td >{wr:.1f}%</td><td>{money(avg)}</td><td>{money(avg)}</td>'
            f'<td>{pf}</td><td>{dd:,.0f}</td><td class="{("win" if pnl > 0 else "loss" if pnl < 0 else "")}">{money(pnl)}</td></tr>')

    mon = {}
    for inst, ts in led.items():
        for t in ts.values():
            mon.setdefault((inst, t["session_date"][:7]), []).append(t)
    monthly = []
    for (inst, ym) in sorted(mon):
        ts = mon[(inst, ym)]
        n = len(ts)
        w = sum(1 for t in ts if float(t["net_pnl"]) > 0)
        l = sum(1 for t in ts if float(t["net_pnl"]) < 0)
        wr = w / n * 100 if n else 0
        pnl = sum(float(t["net_pnl"]) for t in ts)
        dd = maxdd([float(t["net_pnl"]) for t in sorted(ts, key=lambda x: x["session_date"])])
        monthly.append(
            f'<tr><td>{inst}</td><td>{ym}</td><td>{n}</td><td class="win">{w}</td><td class="loss">{l}</td>'
            f'<td >{wr:.2f}%</td>'
            f'<td class="{("win" if pnl > 0 else "loss" if pnl < 0 else "")}">{money(pnl)}</td><td>{dd:,.0f}</td></tr>')

    with open(BT_PAGE) as f:
        html = f.read()
    html = swap_tbody(html, "CPR Strategy Research", research)
    html = swap_tbody(html, "Monthly Breakdown", monthly)
    html = swap_tbody(html, "NIFTY Full Trade Ledger",
                      [bt_row(t) for t in sorted(led.get("NIFTY", {}).values(), key=lambda x: x["session_date"])])
    html = swap_tbody(html, "BANKNIFTY Full Trade Ledger",
                      [bt_row(t) for t in sorted(led.get("BANKNIFTY", {}).values(), key=lambda x: x["session_date"])])
    if "INDIA_VIX Full Trade Ledger" in html:
        html = swap_tbody(html, "INDIA_VIX Full Trade Ledger",
                          [bt_row(t) for t in sorted(led.get("INDIA_VIX", {}).values(), key=lambda x: x["session_date"])])
    note = ("<p>Backtest record includes live paper-traded days from the pivot-bounce feed "
            "(same execution rules); new paper days append automatically.</p>")
    if "live paper-traded days" not in html:
        anchor = "<h2>Integrity Report</h2>"
        html = html.replace(anchor, note + "\n" + anchor, 1)
    with open(BT_PAGE, "w") as f:
        f.write(html)
    print(f"backtest page refreshed: {len(all_tr)} trades ({n_appended} appended live)", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topup", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    a = ap.parse_args()
    _failures = []

    def stage(name, fn):
        try:
            fn()
        except Exception as e:
            print(f"STAGE-FAILED {name}: {type(e).__name__}: {str(e)[:160]}", flush=True)
            _failures.append(name)

    stage("ensure_table", ensure_table)
    if a.topup:
        stage("topup", topup)
    stage("log_pivot", lambda: log_pivot(backfill=a.backfill))
    stage("log_trigger", lambda: log_trigger(backfill=a.backfill))
    stage("log_align", lambda: log_align(backfill=a.backfill))
    stage("log_spreads", log_spreads)
    stage("mark_spreads", mark_spreads)
    stage("render_page", render_page)
    stage("refresh_backtest", refresh_backtest)
    if _failures:
        print(f"completed WITH stage failures: {','.join(_failures)}", flush=True)
    else:
        print("completed all stages", flush=True)
