from flask import Flask, jsonify, request
import sys
sys.path.insert(0, "/opt/tradingai")
sys.path.insert(0, "/opt/tradingai/scanners")
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments
from app.market.provider import MarketDataProvider
from app.market.zerodha_provider import ZerodhaDataProvider
from app.core.qualification import QualificationEngine
from app.ai.explanation import AIExplanation
from app.scenarios.engine import ScenarioEngine
from app.live.engine import LiveEngine
import json, os, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.options import (
    OptionsFreshness, get_options_chain, get_option_contracts,
    init_option_tables, get_option_table_stats,
    validate_contract, validate_underlying_consistency,
    OptionsStrategyEngine)
from app.options.contract import OptionsFreshness as OF, VALID_INSTRUMENTS
from app.options.cache import recompute_age
from app.api.e2_economics import bp as _e2_economics_bp
from app.api.zerodha_paper_report import bp as zerodha_paper_bp
from app.api.performance_api import bp as performance_bp
from app.api.sma9_short_api import bp as sma9_short_bp
from app.api.sma9_5min_api import bp as sma9_5min_bp
from app.api.sma9_adx_api import bp as sma9_adx_bp
from app.api.sma9_5pct_trail_api import bp as sma9_5pct_trail_bp
from app.api.sma9_live_api import bp as sma9_live_bp
from app.api.live_atm_api import bp as live_atm_bp

app = Flask(__name__)
# Trust exactly one hop (nginx on this host). Cloudflare/frontend IPs arrive
# via X-Forwarded-For set by OUR nginx; ProxyFix with x_for=1 exposes the
# nginx-verified client IP as remote_addr. Never trust client-supplied XFF
# directly (spoofable) for rate-limit keys.
# NOTE: Flask-Limiter default storage is in-memory PER-WORKER (gunicorn x2
# means 2x effective budget and no shared state). Production needs
# Redis: Limiter(..., storage_uri="redis://127.0.0.1:6379"). Documented;
# single-host fix below at least keys correctly per visitor.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)


def _client_key():
    """Per-visitor rate-limit key behind the trusted nginx proxy.

    Uses X-Real-IP (set by our nginx from the verified connection) else
    ProxyFix-resolved remote_addr. X-Forwarded-For is NOT trusted (spoofable).
    """
    try:
        real = request.headers.get('X-Real-IP', '').strip()
        if real:
            return real
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(app=app, key_func=_client_key, default_limits=["60 per minute"])

# E.2 read-only educational economics endpoint. Isolated adapter: it
# delegates to app.options.economics and touches no trade, alert,
# signal, decision or database state. Adds no behaviour to existing
# routes. Inherits the global default_limits above via before_request.
app.register_blueprint(_e2_economics_bp)
app.register_blueprint(zerodha_paper_bp, url_prefix="/api/zerodha-paper")
app.register_blueprint(performance_bp)
app.register_blueprint(sma9_short_bp)
app.register_blueprint(sma9_5min_bp)
app.register_blueprint(sma9_adx_bp)
app.register_blueprint(sma9_5pct_trail_bp)
app.register_blueprint(sma9_live_bp)
app.register_blueprint(live_atm_bp)

_market_provider = os.environ.get("MARKET_DATA_PROVIDER", "zerodha").lower()
if _market_provider == "zerodha":
    _zp = ZerodhaDataProvider()
    market = _zp

    def _zp_candles(symbol, completed_ts=None):
        """Wrap Zerodha get_5m_candles for LiveEngine: ignore completed_ts,
        return the candles list (not the full dict)."""
        res = _zp.get_5m_candles(symbol)
        if not res or res.get('state') != 'LIVE':
            return []
        return res.get('candles', [])

    live_engine = LiveEngine(quote_fn=_zp.get_quote, candles_fn=_zp_candles)
else:
    market = MarketDataProvider()
    live_engine = LiveEngine()
qual = QualificationEngine(settings)
ai = AIExplanation()
scenario_engine = ScenarioEngine()
_IST = ZoneInfo("Asia/Kolkata")

# Initialize option tables on import
try:
    init_option_tables()
except Exception:
    pass

def _feed_freshness(sess, now_ist):
    """DB-only data freshness for /api/health (no provider call).

    Market OPEN must never imply data LIVE, so the session window and the
    stored-candle freshness are reported separately.
    """
    today = now_ist.date().isoformat()
    try:
        _conn = get_conn()
        try:
            rows = _conn.execute(
                'SELECT instrument_id, MAX(timestamp) AS ts FROM market_candles_5m '
                'GROUP BY instrument_id').fetchall()
        finally:
            _conn.close()
    except Exception:
        rows = []
    by_inst = {r["instrument_id"]: r["ts"] for r in rows}
    order = {"LIVE": 0, "STALE": 1, "PREVIOUS_SESSION": 2,
             "COLLECTOR_DOWN": 3, "NO_DATA": 4}
    worst = "LIVE"
    out = {}
    for inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        ts = by_inst.get(inst)
        age = None
        if not ts:
            state = "NO_DATA"
        else:
            try:
                age = round((now_ist - datetime.fromisoformat(str(ts))).total_seconds() / 60.0, 1)
            except Exception:
                age = None
            if str(ts)[:10] < today:
                # Stale previous-session data while today's market is running
                # means ingestion stopped, not that the feed is merely delayed.
                state = "COLLECTOR_DOWN" if sess == "LIVE" else "PREVIOUS_SESSION"
            elif age is not None and age > _STALE_CANDLE_MIN:
                state = "STALE"
            else:
                state = "LIVE"
        out[inst] = {"stored_candle": str(ts) if ts else None,
                     "age_minutes": age, "data_state": state}
        if order.get(state, 0) > order.get(worst, 0):
            worst = state
    return {"overall": worst, "instruments": out}


@app.route("/api/health", methods=["GET"])
def health():
    from app.live.engine import session_state
    from app.market.nse_calendar import holiday_name
    conn = get_conn()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    now_ist = datetime.now(_IST)
    # Calendar-only window (no provider call): distinguishes application
    # health from market-data health. A closed market is not an app failure.
    sess = session_state(now_ist, has_data_today=True)
    hn = holiday_name(now_ist.date())
    feed = _feed_freshness(sess, now_ist)
    return jsonify({"status": "LIVE",
                    "app_status": "OK",
                    "status_meaning": "application_health; market session and data freshness reported separately",
                    "feed_state": feed["overall"],
                    "timestamp": now_ist.isoformat(),
                    "data": {"tables": len(tables), "database": DB_PATH},
                    "market": {"session_window": sess,
                               "holiday": hn,
                               "data": feed["instruments"],
                               "note": "application healthy; market state is informational"}})

_STALE_CANDLE_MIN = 15.0

def _stored_candle_state(inst, st):
    """Attach DB-backed freshness to a summary.

    `completed_candle` from LiveEngine is a CLOCK TARGET (the newest candle
    that *should* exist), never proof that data was stored. This adds the
    actually persisted candle and a data_state so those two cannot be
    confused, especially when the feed is AUTH_ERROR. Read-only.
    """
    stored = None
    try:
        _conn = get_conn()
        try:
            row = _conn.execute(
                'SELECT MAX(timestamp) AS ts FROM market_candles_5m '
                'WHERE instrument_id=?', (inst,)).fetchone()
            stored = row["ts"] if row and row["ts"] else None
        finally:
            _conn.close()
    except Exception:
        stored = None
    now_ist = datetime.now(_IST)
    age_min = None
    if stored:
        try:
            age_min = (now_ist - datetime.fromisoformat(str(stored))).total_seconds() / 60.0
        except Exception:
            age_min = None
    qs = st.get("quote_state")
    if qs in ("AUTH_ERROR", "RATE_LIMITED", "TIMEOUT", "API_ERROR", "UNAVAILABLE"):
        data_state = qs
    elif not stored:
        data_state = "NO_DATA"
    elif age_min is None:
        data_state = "STALE"
    elif str(stored)[:10] < now_ist.date().isoformat():
        data_state = "PREVIOUS_SESSION"
    elif age_min > _STALE_CANDLE_MIN:
        data_state = "STALE"
    else:
        data_state = "LIVE"
    return {"stored_candle": str(stored) if stored else None,
            "data_age_minutes": round(age_min, 1) if age_min is not None else None,
            "data_state": data_state}


@app.route("/api/<symbol>/summary", methods=["GET"])
@limiter.limit("30 per minute")
def summary(symbol):
    inst = (symbol or "").upper()
    if inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        # Read-only: dry_run performs zero DB writes (no lock side effects).
        st = live_engine.evaluate(inst, dry_run=True)
        st.update(_stored_candle_state(inst, st))
        return jsonify({"state": st["state"], "timestamp": st["now_ist"], "data": st})
    quote = market.get_quote(symbol)
    return jsonify({"state": quote.get("state", "UNAVAILABLE"), "timestamp": quote.get("timestamp"), "data": quote})

@app.route("/api/<symbol>/decision", methods=["GET"])
@limiter.limit("30 per minute")
def decision(symbol):
    inst = (symbol or "").upper()
    if inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        # READ-ONLY: dry_run performs zero DB writes, so polls/tabs/refreshes
        # across workers can never consume the daily trade slot. Explicit
        # persistence lives only in POST /decision/claim below.
        st = live_engine.evaluate(inst, dry_run=True)
        result = {"decision": st.get("qualification", st["state"]), "reasons": st.get("reasons", []),
                  "trade": st.get("trade")}
        ai_expl = ai.explain(result) if st["state"] == "QUALIFIED" else {"status": "AI_DISABLED", "agreement": "UNKNOWN"}
        st["ai"] = ai_expl
        st["read_only"] = True
        st["claim"] = f"/api/{inst}/decision/claim"
        return jsonify({"state": st["state"], "timestamp": st["now_ist"], "data": st})
    # Unknown symbols: 404, never fabricate a BULLISH market_state/qualify path.
    return jsonify({"state": "NO_DATA", "timestamp": None,
                    "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404

_QUOTE_MAP = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIA_VIX": "^INDIAVIX"}


@app.route("/api/quote/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def quote_view(instrument):
    """Lightweight 1-minute price tick (READ-ONLY, provider-cached quote).

    Price only: no engine evaluation, no decisions. The full decision cycle refreshes separately on completed 5-minute candles."""
    inst = (instrument or "").upper()
    if inst not in _QUOTE_MAP:
        return jsonify({"state": "NO_DATA", "timestamp": None, "data": None}), 404
    q = market.get_quote(_QUOTE_MAP[inst])
    return jsonify({"state": q.get("state", "UNAVAILABLE"),
                    "timestamp": q.get("timestamp"), "data": q})


@app.route("/api/decision/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def decision_view(instrument):
    """Phase 5 normalized intraday decision (READ-ONLY composer).

    Extends, never duplicates: aggregates LiveEngine dry-run evaluation,
    previous-session reference levels and read-only strategy/lock state
    into one per-instrument decision object. Zero DB writes."""
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    from app.decision.view import build_decision
    d = build_decision(inst)
    # Strategy: HLC_3BAR_REVERSED_SHORT_V1 only. No Scalp HLC overlay.
    d['live_price'] = d.get('price')
    d['state'] = d.get('engine_state')
    d['now_ist'] = d.get('timestamp')
    d['reasons'] = d.get('engine_reasons')
    return jsonify({"state": d["data_status"], "timestamp": d["timestamp"], "data": d})


@app.route("/api/<symbol>/decision/claim", methods=["POST"])
@limiter.limit("5 per minute")
def decision_claim(symbol):
    """Explicit state-changing operation: run the gated live evaluation and,
    only if all gates pass and the setup qualifies, persist (freeze) the
    one-trade-day lock/row. Idempotent per (instrument, trade_date): the first
    call freezes the live entry; repeats serve that SAME frozen trade (stable
    entry/stop/target), never duplicate, never HTTP 500."""
    inst = (symbol or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    st = live_engine.evaluate(inst)
    return jsonify({"state": st["state"], "timestamp": st["now_ist"], "data": st})


@app.route("/api/<symbol>/candles", methods=["GET"])
@limiter.limit("30 per minute")
def candles(symbol):
    """Read-only completed-5m-candle feed for the lightweight recent-candle
    display. Returns COMPLETED candles only (timestamp <= latest completed
    candle); the forming candle is excluded by construction and flagged in
    the response. Reuses the shared provider cache; zero DB writes."""
    from app.live.engine import completed_candle_ts
    inst = (symbol or "").upper()
    mapping = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIA_VIX": "^INDIAVIX"}
    if inst not in mapping:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    now_ist = datetime.now(_IST)
    completed = completed_candle_ts(now_ist)
    res = market.get_5m_candles(mapping[inst])
    if res.get("state") != "LIVE" or completed is None:
        # Fallback: most recent stored session candles (post-close / feed gap).
        try:
            _n = int(request.args.get("n", 12))
        except (TypeError, ValueError):
            _n = 12
        _n = max(1, min(80, _n))
        _conn = get_conn()
        try:
            _rows = _conn.execute(
                'SELECT timestamp, open, high, low, close, volume FROM market_candles_5m '
                'WHERE instrument_id=? ORDER BY timestamp DESC LIMIT ?', (inst, _n)).fetchall()
        finally:
            try:
                _conn.close()
            except Exception:
                pass
        _candles = [{"timestamp": str(r["timestamp"]), "open": r["open"], "high": r["high"],
                     "low": r["low"], "close": r["close"], "volume": r["volume"],
                     "is_complete": True} for r in reversed(list(_rows))]
        if _candles:
            # These candles come from the DB because the live feed is not
            # LIVE. They are never a live quote: label them CACHE_STALE.
            return jsonify({"state": "CACHE_STALE", "timestamp": now_ist.isoformat(),
                            "data": {"instrument": inst, "candles": _candles,
                                     "count": len(_candles),
                                     "completed_candle": completed.isoformat() if completed else None,
                                     "forming_excluded": True,
                                     "stale": True,
                                     "data_state": "CACHE_STALE",
                                     "data_ts": _candles[-1]["timestamp"],
                                     "reasons": ["DB_FALLBACK_LAST_SESSION"]}})
        return jsonify({"state": "NO_DATA", "timestamp": now_ist.isoformat(),
                        "data": {"instrument": inst, "candles": [],
                                 "reasons": ["NO_COMPLETED_CANDLES"],
                                 "completed_candle": completed.isoformat() if completed else None}})
    try:
        n = int(request.args.get("n", 12))
    except (TypeError, ValueError):
        n = 12
    n = max(1, min(80, n))  # bounded: 80 max (forming candle excluded below)
    done = [c for c in res.get("candles", [])
            if c.get("timestamp", "") <= completed.isoformat() and c.get("is_complete")]
    return jsonify({"state": "LIVE", "timestamp": now_ist.isoformat(),
                    "data": {"instrument": inst,
                             "candles": done[-n:],
                             "count": len(done[-n:]),
                             "completed_candle": completed.isoformat(),
                             "forming_excluded": True,
                             "data_ts": done[-1]["timestamp"] if done else None}})


@app.route("/api/<symbol>/intraday", methods=["GET"])
@limiter.limit("30 per minute")
def intraday_session(symbol):
    """Read-only full-session 5m price series with reference levels for ONE
    trading day (default: latest session with stored candles). Zero DB writes.

    Levels come from the existing pivot engine applied to the PRIOR session's
    OHLC, so the page renders backend values
    only and never estimates a level itself. ?date=YYYY-MM-DD selects a day."""

    inst = (symbol or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    now_ist = datetime.now(_IST)
    date_arg = (request.args.get("date") or "").strip()
    if date_arg:
        try:
            datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            return jsonify({"state": "NO_DATA", "timestamp": now_ist.isoformat(),
                            "data": {"reasons": ["INVALID_DATE"]}}), 400

    conn = get_conn()
    try:
        if not date_arg:
            row = conn.execute(
                "SELECT MAX(substr(timestamp,1,10)) AS d FROM market_candles_5m "
                "WHERE instrument_id=?", (inst,)).fetchone()
            date_arg = row["d"] if row and row["d"] else None
        if not date_arg:
            return jsonify({"state": "NO_DATA", "timestamp": now_ist.isoformat(),
                            "data": {"instrument": inst, "date": None, "points": [],
                                     "reasons": ["NO_STORED_SESSION"]}})
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m "
            "WHERE instrument_id=? AND substr(timestamp,1,10)=? "
            "ORDER BY timestamp", (inst, date_arg)).fetchall()
        prev_row = conn.execute(
            "SELECT MAX(substr(timestamp,1,10)) AS d FROM market_candles_5m "
            "WHERE instrument_id=? AND substr(timestamp,1,10)<?",
            (inst, date_arg)).fetchone()
        prev_date = prev_row["d"] if prev_row and prev_row["d"] else None
        prev_candles = []
        if prev_date:
            prev_candles = conn.execute(
                "SELECT high, low, close FROM market_candles_5m "
                "WHERE instrument_id=? AND substr(timestamp,1,10)=? "
                "ORDER BY timestamp", (inst, prev_date)).fetchall()
        nav = conn.execute(
            "SELECT MAX(substr(timestamp,1,10)) AS lt, "
            "MIN(CASE WHEN substr(timestamp,1,10)>? THEN substr(timestamp,1,10) END) AS nt "
            "FROM market_candles_5m WHERE instrument_id=?", (date_arg, inst)).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    points = [{"timestamp": str(r["timestamp"]), "close": float(r["close"])}
              for r in rows]
    closes = [p["close"] for p in points]
    highs = [float(r["high"]) for r in rows if r["high"] is not None]
    lows = [float(r["low"]) for r in rows if r["low"] is not None]
    return jsonify({"state": "LIVE", "timestamp": now_ist.isoformat(),
                    "data": {"instrument": inst,
                             "date": date_arg,
                             "points": points,
                             "count": len(points),
                             "first": points[0]["timestamp"] if points else None,
                             "last": points[-1]["timestamp"] if points else None,
                             "latest": closes[-1] if closes else None,
                             "day_high": max(highs) if highs else None,
                             "day_low": min(lows) if lows else None,
                             "latest_date": nav["lt"] if nav else None,
                             "prev_date": prev_date,
                             "next_date": (nav["nt"] if nav else None),
                             "session_start": "09:15",
                             "session_end": "15:30",
                             "is_latest": date_arg == (nav["lt"] if nav else date_arg),
                             "reasons": ["STORED_COMPLETED_5M_CANDLES"] if points else ["NO_CANDLES_FOR_DATE"]}})


@app.route("/api/paper/spreads", methods=["GET"])
@limiter.limit("30 per minute")
def paper_spreads():
    """Paper vertical spreads (read-only). Latest 120 rows, newest first."""
    inst = (request.args.get("instrument") or "").upper() or None
    conn = get_conn()
    try:
        if inst and inst not in ("NIFTY", "BANKNIFTY"):
            return jsonify({"state": "NO_DATA", "timestamp": None,
                            "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
        q = ("SELECT * FROM paper_spreads"
             + (" WHERE instrument_id=?" if inst else "") +
             " ORDER BY session_date DESC, instrument_id LIMIT 120")
        rows = conn.execute(q, (inst,) if inst else ()).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["legs"] = json.loads(d.get("legs") or "[]")
            except Exception:
                d["legs"] = []
            out.append(d)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": out})

@app.route("/api/paper/spread/today", methods=["GET"])
@limiter.limit("30 per minute")
def paper_spread_today():
    """Today's spread preview (read-only): Scalp HLC strategy removed.
    Only HLC_3BAR_REVERSED_SHORT_V1 is active."""
    from app.options.weekly_spreads import build_spread, next_expiry, payoff_curve
    from app.options import nse_chain
    inst = (request.args.get("instrument") or "NIFTY").upper()
    if inst not in ("NIFTY", "BANKNIFTY"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": {"trigger": None, "spread": None, "credit": None,
                             "payoff": None,
                             "note": "Scalp HLC strategy removed; use HLC_3BAR_REVERSED_SHORT_V1"}})

# REMOVED 2026-09-28: POST /api/backtest/run (BacktestEngine simulator) had 0 callers
# (no frontend/cron). Retired CPR backtest endpoint; mirrors live HLC engine.
# IntradayExitEngine in app/research/backtest.py is still live-shared via replay.py.





@app.route("/api/backtest/<run_id>", methods=["GET"])
@limiter.limit("30 per minute")
def backtest_result(run_id):
    conn = get_conn()
    run = conn.execute("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
    decisions = [dict(d) for d in conn.execute("SELECT * FROM backtest_decisions WHERE run_id=?", (run_id,)).fetchall()]
    trades = [dict(t) for t in conn.execute("SELECT * FROM backtest_trades WHERE run_id=?", (run_id,)).fetchall()]
    outcome = conn.execute("SELECT * FROM backtest_outcomes WHERE run_id=?", (run_id,)).fetchone()
    conn.close()
    return jsonify({"state": "COMPLETED", "data": {"run": dict(run) if run else None, "decisions": decisions, "trades": trades, "outcome": dict(outcome) if outcome else None}})

@app.route("/api/backtest/validation/<run_id>", methods=["GET"])
@limiter.limit("30 per minute")
def no_lookahead_validation(run_id):
    conn = get_conn()
    decisions = [dict(d) for d in conn.execute("SELECT * FROM backtest_decisions WHERE run_id=? AND lookahead_check != 'PASS'", (run_id,)).fetchall()]
    conn.close()
    return jsonify({"state": "COMPLETED", "data": {"run_id": run_id, "lookahead_violations": len(decisions), "result": "PASS" if len(decisions) == 0 else "FAILED"}})

@app.route("/api/research/scenarios", methods=["GET"])
@limiter.limit("30 per minute")
def research_scenarios():
    instrument = request.args.get("instrument")
    conn = get_conn()
    if instrument:
        rows = conn.execute("SELECT * FROM scenario_candidates WHERE instrument_id=? ORDER BY created_at DESC LIMIT 100", (instrument,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM scenario_candidates ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify({"state": "LIVE", "data": [dict(r) for r in rows]})

@app.route("/api/research/scenarios/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def research_scenarios_instrument(instrument):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM scenario_candidates WHERE instrument_id=? ORDER BY created_at DESC LIMIT 200", (instrument,)).fetchall()
    conn.close()
    return jsonify({"state": "LIVE", "data": [dict(r) for r in rows]})

@app.route("/api/research/performance", methods=["GET"])
@limiter.limit("30 per minute")
def research_performance():
    conn = get_conn()
    perf = {}
    for inst in ["NIFTY", "BANKNIFTY", "INDIA_VIX"]:
        perf[inst] = {}
        for stype in ["BULLISH_CONTINUATION", "BEARISH_CONTINUATION", "RANGE_PREMIUM_DECAY", "BREAKOUT", "BREAKOUT_FAILURE_REVERSAL"]:
            count = conn.execute("SELECT COUNT(*) FROM scenario_candidates WHERE instrument_id=? AND scenario_type=?", (inst, stype)).fetchone()[0]
            confirmed = conn.execute("SELECT COUNT(*) FROM scenario_candidates WHERE instrument_id=? AND scenario_type=? AND status='CONFIRMED'", (inst, stype)).fetchone()[0]
            invalidated = conn.execute("SELECT COUNT(*) FROM scenario_candidates WHERE instrument_id=? AND scenario_type=? AND status='INVALIDATED'", (inst, stype)).fetchone()[0]
            perf[inst][stype] = {"candidates": count, "confirmed": confirmed, "invalidated": invalidated}
    conn.close()
    return jsonify({"state": "LIVE", "data": perf})

@app.route("/api/research/baseline/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def research_baseline(instrument):
    """Serve the validated pre-computed research snapshot (FULL/30D/7D).
    Read-only file serve: no engine execution, no DB writes, bounded size."""
    import json as _json
    inst = (instrument or "").upper()
    period = (request.args.get("period") or "FULL").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX") or period not in ("FULL", "30D", "7D"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_BASELINE"]}}), 404
    try:
        with open(f"/opt/tradingai/app/research/baseline_{inst}_{period}.json") as f:
            snap = _json.load(f)
    except FileNotFoundError:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["BASELINE_NOT_GENERATED"]}}), 404
    return jsonify({"state": "RESEARCH", "timestamp": snap["dataset"]["end"],
                    "data": snap})


@app.route("/api/research/trade/<instrument>/<date>", methods=["GET"])
@limiter.limit("30 per minute")
def research_trade(instrument, date):
    """Historical trade replay inspector (read-only). Decision context uses
    ONLY information available at the entry timestamp; post-entry candles are
    returned in a SEPARATE outcome block, never mixed into the decision."""
    import json as _json
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    try:
        with open(f"/opt/tradingai/app/research/baseline_{inst}_FULL.json") as f:
            snap = _json.load(f)
    except FileNotFoundError:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["BASELINE_NOT_GENERATED"]}}), 404
    hit = [t for t in snap["trades"] if t["trade_date"] == date]
    if not hit:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["NO_TRADE_ON_DATE"]}}), 404
    trade = hit[0]
    entry_ts = trade["entry_time"]
    conn = get_conn()
    day_candles = [dict(c) for c in conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (inst, date)).fetchall()]
    scen = conn.execute(
        "SELECT candidate_id,scenario_type,status,created_at FROM scenario_candidates "
        "WHERE instrument_id=? AND created_at <= ? "
        "ORDER BY created_at DESC, candidate_id ASC LIMIT 1",
        (inst, entry_ts)).fetchone()
    match = None
    if scen:
        match = conn.execute(
            "SELECT match_state,timestamp FROM scenario_matches "
            "WHERE candidate_id=? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            (scen["candidate_id"], entry_ts)).fetchone()
    conn.close()
    decision_candles = [c for c in day_candles if c["timestamp"] <= entry_ts]
    exit_ts = trade["exit_time"]
    outcome_candles = [c for c in day_candles if entry_ts < c["timestamp"] <= exit_ts]
    return jsonify({"state": "RESEARCH", "timestamp": entry_ts, "data": {
        "trade": trade,
        "decision": {
            "timestamp": entry_ts,
            "completed_candle": decision_candles[-1] if decision_candles else None,
            "candles_available": len(decision_candles),
            "scenario": dict(scen) if scen else None,
            "scenario_match": dict(match) if match else None,
            "pit_note": "Decision made using information available at this timestamp only.",
        },
        "outcome": {
            "candles_after_entry": len(outcome_candles),
            "candles": outcome_candles,
            "separation_note": "Post-entry candles shown ONLY to explain the eventual outcome.",
        }}})


@app.route("/api/options/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def options_data(instrument):
    """Read-only options data layer. Returns validated options state,
    freshness, expiries, and contracts if available. NEVER contains
    strategy logic. No trade decisions are made here.
    Instrument-specific: NIFTY failure does not substitute BANKNIFTY."""
    inst = (instrument or "").upper()
    if inst not in VALID_INSTRUMENTS:
        return jsonify({"state": "OPTIONS_MALFORMED", "timestamp": None,
                         "data": {"error": "UNKNOWN_INSTRUMENT",
                                   "instrument": inst,
                                   "contracts": []}}), 404
    expiry = request.args.get("expiry")
    option_type = request.args.get("type")
    strike_min = request.args.get("strike_min", type=float)
    strike_max = request.args.get("strike_max", type=float)
    state, contracts, meta = get_option_contracts(inst, expiry=expiry,
                                                    option_type=option_type,
                                                    strike_min=strike_min,
                                                    strike_max=strike_max)
    # Recompute age at serve time — cached data can never look fresh
    age, freshness = recompute_age(meta)
    now = datetime.now(_IST).isoformat()
    result = {
        "state": state,
        "timestamp": now,
        "data": {
            "instrument": inst,
            "freshness": freshness.value,
            "data_age_seconds": age,
            "provider": meta.get("error", "NO_OPTIONS_DATA_FROM_PROVIDER")
                       if state != "OPTIONS_FRESH" else "yfinance",
            "underlying": meta.get("underlying"),
            "expiries": meta.get("expiries", []),
            "contracts": contracts,
            "contract_count": len(contracts),
            "validation": "CONTRACT_VALIDATED" if contracts else "NO_CONTRACTS",
            "historical_options_available": False,
            "historical_note": "HISTORICAL OPTIONS DATA IS NOT AVAILABLE FROM THIS SOURCE.",
            "options_api_note": "Data layer only. No strategy, no trade decision, no recommendation.",
        }}
    return jsonify(result)


@app.route("/api/options/strategy/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def options_strategy(instrument):
    """Read-only options strategy validation.
    Returns NO_TRADE when options data unavailable.
    Never fabricates contracts, premiums, or strategies."""
    inst = (instrument or "").upper()
    if inst not in VALID_INSTRUMENTS:
        return jsonify({"state": "NO_TRADE", "timestamp": None,
                         "data": {"reason": "UNKNOWN_INSTRUMENT",
                                   "strategy": None,
                                   "errors": ["UNKNOWN_INSTRUMENT"]}}), 404
    strategy_type = request.args.get("strategy")
    if strategy_type and strategy_type not in (
        "BULL_PUT_SPREAD", "BULL_CALL_SPREAD", "BEAR_CALL_SPREAD",
        "BEAR_PUT_SPREAD", "IRON_CONDOR"):
        return jsonify({"state": "NO_TRADE", "timestamp": None,
                         "data": {"reason": "UNKNOWN_STRATEGY",
                                   "strategy": strategy_type,
                                   "errors": ["UNKNOWN_STRATEGY"]}}), 400
    engine = OptionsStrategyEngine()
    # Attempt to qualify - will return NO_TRADE when no data
    result = engine.qualify(inst, index_state="LIVE",
                            strategy_type=strategy_type)
    now = datetime.now(_IST).isoformat()
    return jsonify({
        "state": result.status,
        "timestamp": now,
        "data": {
            "instrument": inst,
            "reason": result.reason,
            "strategy": result.strategy.value if result.strategy else None,
            "legs": result.legs,
            "economics": result.economics,
            "errors": result.errors,
            "data_gate_note": "No validated options data source is currently accessible from the Oracle VM.",
            "historical_options_available": False,
            "historical_note": "HISTORICAL OPTIONS DATA IS NOT AVAILABLE FROM THIS SOURCE.",
        }})


@app.route("/api/research/replay/<instrument>/<date>/<timestamp>", methods=["GET"])
@limiter.limit("30 per minute")
def research_replay(instrument, date, timestamp):
    import re as _re
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["INVALID_DATE"]}}), 400
    if not _re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", timestamp or ""):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["INVALID_TIMESTAMP"]}}), 400
    conn = get_conn()
    candles = conn.execute("SELECT candle_id, instrument_id, timestamp, open, high, low, close, volume FROM market_candles_5m WHERE instrument_id=? AND timestamp <= ? ORDER BY timestamp LIMIT 500", (inst, f"{date}T{timestamp}")).fetchall()
    scenarios = conn.execute("SELECT candidate_id, instrument_id, scenario_type, status, created_at FROM scenario_candidates WHERE instrument_id=? AND created_at <= ? ORDER BY created_at DESC LIMIT 100", (inst, f"{date}T{timestamp}")).fetchall()
    conn.close()
    return jsonify({
        "state": "LIVE",
        "data": {
            "instrument": inst,
            "date": date,
            "timestamp": timestamp,
            "candles_available_at_decision": [dict(c) for c in candles],
            "scenario_state": [dict(s) for s in scenarios],
            "data_known_at_decision": "All candles up to and including " + timestamp,
            "future_outcome": "Available via backtest/outcome endpoints only"
        }
    })


@app.route("/api/performance/live", methods=["GET"])
@limiter.limit("30 per minute")
def live_performance():
    """Live paper-trade performance aggregated across all instruments.

    Source: the live paper ledger (`paper_trades`, written by the watcher).
    Returns an explicit empty result when no eligible live trades exist, and
    an explicit error (never a silent 200 with data:null) when the calculation
    cannot be completed."""
    from app.paper_trade.performance import get_performance
    try:
        perf = get_performance(start=request.args.get("start"),
                               end=request.args.get("end"))
    except Exception as e:
        return jsonify({"state": "ERROR", "timestamp": datetime.now(_IST).isoformat(),
                        "data": {"error": "PERFORMANCE_UNAVAILABLE",
                                 "detail": str(e)[:200]}}), 500
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(), "data": perf})


@app.route("/api/performance/live/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def live_performance_instrument(instrument):
    """Live paper-trade performance for one instrument (see live_performance)."""
    from app.paper_trade.performance import get_performance
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    try:
        perf = get_performance(inst, start=request.args.get("start"),
                               end=request.args.get("end"))
    except Exception as e:
        return jsonify({"state": "ERROR", "timestamp": datetime.now(_IST).isoformat(),
                        "data": {"error": "PERFORMANCE_UNAVAILABLE",
                                 "detail": str(e)[:200]}}), 500
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(), "data": perf})




@app.route("/api/alerts/rss", methods=["GET"])
@limiter.limit("30 per minute")
def alerts_rss():
    """RSS 2.0 feed of model alerts for automation (Make/Zapier/Buffer -> FB Page).

    Read-only: serves the latest 30 records from data/tg_alerts_archive.jsonl
    (same source as frontend/rss.xml). No DB writes, no trading logic.
    Content-Type application/rss+xml so RSS readers accept it directly."""
    import json as _json
    import os as _os
    from email.utils import format_datetime as _fmt_dt
    from xml.sax.saxutils import escape as _esc
    from flask import Response as _Resp
    base = _os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
    arch = _os.path.join(base, 'data', 'tg_alerts_archive.jsonl')
    recs = []
    try:
        with open(arch) as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    recs.append(_json.loads(_line))
                except Exception:
                    continue
    except FileNotFoundError:
        recs = []
    recs.sort(key=lambda r: str(r.get('ts_ist') or r.get('date') or ''), reverse=True)
    recs = recs[:30]
    _SITE = 'https://tradingai.in'
    _DISC = ('Automated model output. Not investment advice. Educational research only.')
    _items = []
    for _r in recs:
        _t = _r.get('type', '')
        _inst = _r.get('inst') or 'Model'
        _dir = (_r.get('direction') or '').upper()
        _date = _r.get('date') or ''
        if _t == 'signal':
            _trig = ((_r.get('ctx') or {}).get('trigger')) or ''
            _title = f'{_inst} {_dir} model signal {_trig} | {_date}'.strip()
        elif _t == 'update':
            _o = _r.get('outcome') or {}
            _title = f"{_inst} model update: {_o.get('reason')} ({_o.get('points_text')}) | {_date}".strip()
        elif _t == 'eod':
            _title = f'TradingAI EOD recap | {_date}'
        elif _t == 'morning':
            _title = f'TradingAI model levels | {_date}'
        else:
            _title = f'TradingAI model alert ({_inst}) | {_date}'
        _tg = (_r.get('tg_text') or '').strip()
        if _tg:
            _desc = _tg
        else:
            _bits = []
            _ctx = _r.get('ctx') or {}
            if _t == 'signal':
                _bits.append(f'Direction: {_dir}')
                for _k in ('trigger', 'invalidation', 'target', 'strategy', 'signal_time'):
                    if _ctx.get(_k):
                        _bits.append(f'{_k}: {_ctx[_k]}')
            if _t == 'update':
                _o = _r.get('outcome') or {}
                _bits.append(f"Result: {_o.get('reason')} ({_o.get('points_text')})")
            _ex = (_r.get('explanation') or '').strip()
            if _ex:
                _bits.append(_ex)
            _bits.append(_DISC)
            _desc = ' \u2014 '.join(_b for _b in _bits if _b)
        _sym = (_r.get('sym') or '').lower()
        _link = {'nifty': _SITE + '/indices/nifty.html',
                 'banknifty': _SITE + '/indices/banknifty.html'}.get(_sym, _SITE + '/alerts.html')
        try:
            _dt = datetime.fromisoformat(_r.get('ts_ist') or _r.get('date'))
            if _dt.tzinfo is None:
                _dt = _dt.replace(tzinfo=_IST)
        except Exception:
            _dt = datetime.now(_IST)
        _items.append(
            '<item><title>' + _esc(_title) + '</title><link>' + _esc(_link) + '</link>'
            '<guid isPermaLink="false">' + _esc(f"{_SITE}/alerts.html#{_r.get('key') or _r.get('ts_ist') or _title}") + '</guid>'
            '<pubDate>' + _fmt_dt(_dt) + '</pubDate><description>' + _esc(_desc) + '</description></item>')
    _now = _fmt_dt(datetime.now(_IST))
    _xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        '<title>TradingAI.in Model Alerts</title><link>' + _SITE + '/alerts.html</link>'
        '<description>Automated NIFTY/BANKNIFTY model signals, updates and EOD recaps. '
        'Educational research only, not investment advice.</description>'
        '<language>en-in</language>'
        '<lastBuildDate>' + _now + '</lastBuildDate>'
        '<pubDate>' + _now + '</pubDate><ttl>5</ttl>'
        + ''.join(_items) + '</channel></rss>\n')
    return _Resp(_xml, mimetype='application/rss+xml')


@app.route("/api/alerts/status", methods=["GET"])
@limiter.limit("30 per minute")
def alerts_status():
    """Read-only Telegram alert lifecycle for today (fired / still open / closed).

    Homepage cards use this to show a record only while its alert is live:
    visible once fired, hidden after STOP or EOD exit. Zero DB writes."""
    import json as _json
    import os as _os
    base = _os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
    try:
        with open(_os.path.join(base, 'data', 'tg_state.json')) as _f:
            st = _json.load(_f)
    except Exception:
        st = {}
    today = datetime.now(_IST).date().isoformat()
    try:
        open_all = (st.get('open') or {})
        open_today = {k: v for k, v in open_all.items() if str(k).startswith(today + '|')}
    except Exception:
        open_today = {}
    try:
        closed_today = [c for c in (st.get('closed') or []) if str((c or {}).get('date')) == today]
    except Exception:
        closed_today = []
    try:
        fired_today = [k for k in (st.get('fired') or []) if str(k).startswith(today + '|')]
    except Exception:
        fired_today = []
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": {"date": today, "open": open_today,
                             "closed": closed_today, "fired": fired_today}})


@app.route("/api/market/holidays", methods=["GET"])
@limiter.limit("30 per minute")
def market_holidays():
    """Read-only NSE session info: today open/closed, timings, 2026 holidays.

    Powers the 'is the market open today' page. Weekends/holidays/after-close
    reported factually from the encoded calendar; no trading content."""
    from app.market import nse_calendar as _cal
    from datetime import date as _date
    today = datetime.now(_IST).date()
    hn = _cal.holiday_name(today)
    wknd = _cal.is_weekend(today)
    now_t = datetime.now(_IST).time()
    past_close = now_t >= datetime.strptime("15:30", "%H:%M").time()
    pre_open = now_t < datetime.strptime("09:15", "%H:%M").time()
    if wknd:
        status, reason = "CLOSED", "Weekend (Saturday/Sunday are never NSE sessions)"
    elif hn:
        status, reason = "CLOSED", f"NSE holiday: {hn}"
    elif past_close:
        status, reason = "CLOSED", "Regular session ended at 15:30 IST"
    elif pre_open:
        status, reason = "PREMARKET", "Regular session opens at 09:15 IST"
    else:
        status, reason = "OPEN", "Regular session 09:15-15:30 IST is underway"
    upcoming = []
    try:
        names = _cal._HOLIDAY_NAMES_2026
        for ds in sorted(_cal.NSE_HOLIDAYS_2026):
            if ds >= today.isoformat():
                upcoming.append({"date": ds, "name": names.get(ds, "NSE holiday")})
    except Exception:
        upcoming = []
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": {"date": today.isoformat(), "status": status, "reason": reason,
                             "session": "09:15-15:30 IST (Mon-Fri)",
                             "premarket": "09:00-09:15 IST call auction",
                             "upcoming_holidays": upcoming,
                             "calendar_coverage": "2026 (NSE circular CMTR71775)"}})


@app.route("/api/market/events", methods=["GET"])
@limiter.limit("30 per minute")
def market_events():
    """Read-only scheduled market-event calendar + advisory event-risk overlay.

    Powers the /events.html page and the decision view's event_risk field.
    Curated events only (no network): RBI MPC, US FOMC, Union Budget, monthly
    F&O expiry, CPI/WPI/GDP and US payrolls/CPI. Advisory reference layer —
    never changes a trade, entry/stop/target or any gate.

    Query: instrument (NIFTY|BANKNIFTY|INDIA_VIX, optional), days (default 90,
    capped 365). Unknown instrument -> 400 UNKNOWN_INSTRUMENT (never guess)."""
    from app.market.events_calendar import (
        upcoming_events, event_risk, COVERAGE_START, COVERAGE_END,
        HAND_ENCODED_END, RECURRING_END, CALENDAR_LAST_VERIFIED)
    inst = (request.args.get("instrument") or "").upper() or None
    if inst is not None and inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 400
    try:
        days = int(request.args.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 365))
    events = upcoming_events(days=days, instrument=inst)
    # Advisory risk for each traded instrument (INDIA_VIX is not traded but
    # shown for context on the events page).
    risks = {i: event_risk(i) for i in ("NIFTY", "BANKNIFTY", "INDIA_VIX")}
    return jsonify({
        "state": "LIVE",
        "timestamp": datetime.now(_IST).isoformat(),
        "data": {
            "instrument": inst,
            "days": days,
            "events": events,
            "risk": {k: {"risk_level": v.get("risk_level"),
                         "risk_label": v.get("risk_label"),
                         "confirmation_required": v.get("confirmation_required"),
                         "bias_overlay": v.get("bias_overlay"),
                         "today_impact": v.get("today_impact"),
                         "pending": v.get("pending"),
                         "next_event": v.get("next_event")}
                     for k, v in risks.items()},
            "coverage": {"start": COVERAGE_START, "end": COVERAGE_END,
                         "hand_encoded_end": HAND_ENCODED_END,
                         "recurring_end": RECURRING_END,
                         "last_verified": CALENDAR_LAST_VERIFIED},
        },
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)


@app.route("/api/backtest/prevday-pa", methods=["POST"])
@limiter.limit("5 per minute")
def run_prevday_pa_backtest():
    """Previous-day price action strategy backtest (isolated second strategy)."""
    body = request.get_json() or {}
    inst = (body.get("instrument") or "NIFTY").upper()
    ds = body.get("date_start", "2026-07-06")
    de = body.get("date_end", "2026-10-23")
    from app.research.prevday_price_action_engine import run_prevday_pa_range
    result = run_prevday_pa_range(inst, ds, de)
    if isinstance(result, dict) and result.get("error"):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        return jsonify({"state": "NO_DATA", "timestamp": _dt.now(_ZI("Asia/Kolkata")).isoformat(),
                        "data": {"reasons": [result["error"]]}}), 404
    return jsonify({"state": "OK", "timestamp": None, "data": result})


@app.route("/api/backtest/price-action-target", methods=["POST"])
@limiter.limit("5 per minute")
def run_price_action_target_backtest():
    body = request.get_json() or {}
    inst = (body.get("instrument") or "NIFTY").upper()
    ds = body.get("date_start", "2026-07-06")
    de = body.get("date_end", "2026-10-23")
    from app.research.prevday_price_action_engine import run_price_action_target_range
    result = run_price_action_target_range(inst, ds, de)
    if isinstance(result, dict) and result.get("error"):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        return jsonify({"state": "NO_DATA", "timestamp": _dt.now(_ZI("Asia/Kolkata")).isoformat(),
                        "data": {"reasons": [result["error"]]}}), 404
    return jsonify({"state": "OK", "timestamp": None, "data": result})


from app.api.nifty_spot_paper_api import bp as nifty_spot_paper_api_bp
from app.api.live_api import bp as live_api_bp, init_services as init_live_api_services
app.register_blueprint(nifty_spot_paper_api_bp, url_prefix="/api/nifty-spot-paper")
app.register_blueprint(live_api_bp, url_prefix="/api/live")


@app.errorhandler(404)
def _json_404(e):
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        ts = _dt.now(_ZI('Asia/Kolkata')).isoformat()
    except Exception:
        ts = None
    return jsonify({"state": "NO_DATA", "timestamp": ts,
                    "data": {"reasons": ["UNKNOWN_ROUTE"]}}), 404


@app.errorhandler(500)
def _json_500(e):
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        ts = _dt.now(_ZI('Asia/Kolkata')).isoformat()
    except Exception:
        ts = None
    import logging as _log
    _log.getLogger('tradingai.api').exception('unhandled API error')
    return jsonify({"state": "UNAVAILABLE", "timestamp": ts,
                    "data": {"reasons": ["ENGINE_ERROR"]}}), 500


# ============================================================================
# Live API Service Initialization
# Initializes the scanner registry, repository, and service layer.
# ============================================================================
def init_live_services():
    """Initialize all live API services."""
    import sys
    import os
    # Ensure scanners package is importable
    base = "/opt/tradingai"
    if base not in sys.path:
        sys.path.insert(0, base)
    if f"{base}/scanners" not in sys.path:
        sys.path.insert(0, f"{base}/scanners")

    from scanners.registry import ScannerRegistry
    from scanners.reverse_short_only.scanner import ReverseShortScanner
    from database.connection import get_connection
    from database.repositories import ScannerRepository
    from services.scanner_service import ScannerService
    from services.signal_service import SignalService
    from services.trade_service import TradeService
    from services.dashboard_service import DashboardService
    from services.scanner_selector import ScannerSelector

    # Initialize database connection
    db_conn = get_connection(DB_PATH, read_only=False)

    # Initialize repository
    repo = ScannerRepository(db_conn)

    # Initialize scanner registry
    registry = ScannerRegistry()
    registry.discover()

    # Initialize services
    scanner_service = ScannerService(registry, repo)
    signal_service = SignalService(repo)
    trade_service = TradeService(repo)
    dashboard_service = DashboardService(repo, signal_service, trade_service, scanner_service)
    scanner_selector = ScannerSelector(scanner_service)

    # Initialize live API with services
    init_live_api_services(
        scanner_service, signal_service, trade_service,
        dashboard_service, scanner_selector, repo
    )

    # Register Reversed Short scanner and set as active
    registry.register(ReverseShortScanner())
    scanner_service.start_scanner("reverse_short_only")

    # Record service health
    repo.record_health("scanner", "OK", "Reversed Short scanner active")
    repo.record_health("database", "OK", "Database connected")
    repo.record_health("api", "OK", "API initialized")

    return registry, scanner_service, signal_service, trade_service, dashboard_service, scanner_selector, repo

# Initialize services on module load
try:
    init_live_services()
except Exception as e:
    import logging
    logging.getLogger('tradingai.api').warning(f"Live service initialization deferred: {e}")
# ============================================================================
# SMA9 Scanner API Endpoints (dedicated database: database/sma9.db)
# ============================================================================
SMA9_DB_PATH = os.environ.get(
    "SMA9_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "sma9.db")
)


def get_sma9_conn():
    """Per-request connection to the dedicated SMA9 database."""
    conn = sqlite3.connect(SMA9_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _sma9_live_state():
    """Read the scanner heartbeat/state row (empty dict when unavailable)."""
    try:
        conn = get_sma9_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM sma9_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _sma9_scanner_health(state):
    """Classify scanner health without pretending stale data is live."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


def _dataset_filter(request, query, params, default=None):
    dataset = request.args.get("dataset", default)
    if dataset:
        query += " AND dataset = ?"
        params.append(dataset)
    return query, params


@app.route("/api/sma9/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_signals():
    """Get SMA9 signals/trades with pagination and filters."""
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        conn = get_sma9_conn()
        query = "SELECT * FROM sma9_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        signals = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "signals": signals,
            "trades": signals,
            "count": len(signals),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trades():
    """Alias for /api/sma9/signals."""
    return api_sma9_signals()


@app.route("/api/sma9/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_daily_summary():
    """Daily summary, optionally scoped by dataset."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) as datasets
            FROM sma9_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_scanner_status():
    """Scanner status + lifetime stats + current live evaluation."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0

        state = _sma9_live_state()
        status, age = _sma9_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "sma9_only",
            "scanner_name": "SMA9 Only - ATM Option Strike (BUY ONLY)",
            "scanner_version": "2.7.0",
            "strategy_type": "SMA9_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_live_status():
    """Raw live scanner heartbeat/evaluation for the 5-second dashboard."""
    state = _sma9_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _sma9_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/sma9/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_recent_trades():
    """Recent trades, optionally scoped by dataset and trade date."""
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_sma9_conn()
        query = "SELECT * FROM sma9_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({"success": True, "trades": trades, "count": len(trades),
                        "total": total, "dataset": dataset or "ALL",
                        "trade_date": trade_date})
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/sma9/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_open_positions():
    """Open (unclosed) live paper positions, independent of the current ATM strike."""
    try:
        conn = get_sma9_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        positions = [dict(r) for r in rows]
        return jsonify({"success": True, "positions": positions,
                        "count": len(positions)})
    except Exception as e:
        return jsonify({"success": False, "positions": [], "error": str(e)}), 500


@app.route("/api/sma9/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_today():
    """ONLY today's LIVE paper trades (never stale historical rows)."""
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_sma9_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/sma9/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_sma9_legacy_audit():
    """Summary + optional rows for the 339 preserved legacy trades."""
    try:
        include_rows = request.args.get("rows", "0") == "1"
        conn = get_sma9_conn()
        total = conn.execute("SELECT COUNT(*) FROM sma9_audit").fetchone()[0]
        compliant = conn.execute("SELECT COUNT(*) FROM sma9_audit WHERE compliant=1").fetchone()[0]
        by_opt = [dict(r) for r in conn.execute(
            "SELECT option_type, COUNT(*) total, SUM(compliant) compliant "
            "FROM sma9_audit GROUP BY option_type"
        ).fetchall()]
        reasons = [dict(r) for r in conn.execute(
            "SELECT discrepancy_reasons, COUNT(*) n FROM sma9_audit "
            "WHERE compliant=0 GROUP BY discrepancy_reasons ORDER BY n DESC"
        ).fetchall()]
        rows = []
        if include_rows:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM sma9_audit ORDER BY entry_timestamp DESC LIMIT 1000"
            ).fetchall()]
        conn.close()
        return jsonify({
            "success": True,
            "total_audited": total,
            "compliant": compliant,
            "discrepant": total - compliant,
            "compliance_rate_pct": round(compliant / total * 100, 2) if total else 0,
            "by_option_type": by_opt,
            "discrepancy_reason_groups": reasons,
            "rows": rows,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
# ============================================================================
# SMA9 ATR Scanner API Endpoints (dedicated database: database/sma9_atr.db)
# Standalone volatility-scaled-stop scanner; read-only access to its own DB.
# ============================================================================
SMA9_ATR_DB_PATH = os.environ.get(
    "SMA9_ATR_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "sma9_atr.db")
)


def get_sma9_atr_conn():
    """Per-request read-only connection to the dedicated SMA9 ATR database."""
    conn = sqlite3.connect(
        "file:" + SMA9_ATR_DB_PATH + "?mode=ro", uri=True, timeout=10
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _sma9_atr_live_state():
    """Read the scanner heartbeat/state row (empty dict when unavailable)."""
    try:
        conn = get_sma9_atr_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM sma9_atr_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _sma9_atr_scanner_health(state):
    """Classify scanner health without pretending stale data is live."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    heartbeat = state.get("_state_updated_at")
    beat_age = None
    if heartbeat:
        try:
            beat_age = (now - datetime.fromisoformat(heartbeat)).total_seconds()
        except Exception:
            beat_age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        # Fresh install: no completed scan yet.  A recent heartbeat with the
        # market closed means the process is alive and idle, not dead.
        if not market_open and beat_age is not None and beat_age <= 120:
            status = "IDLE_MARKET_CLOSED"
        else:
            status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/sma9-atr/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_atr_signals():
    """Get SMA9 ATR signals/trades with pagination and filters."""
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        conn = get_sma9_atr_conn()
        query = "SELECT * FROM sma9_atr_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        signals = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "signals": signals,
            "trades": signals,
            "count": len(signals),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-atr/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_atr_trades():
    """Alias for /api/sma9-atr/signals."""
    return api_sma9_atr_signals()


@app.route("/api/sma9-atr/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_atr_daily_summary():
    """Daily summary, optionally scoped by dataset."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_atr_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) as datasets
            FROM sma9_atr_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-atr/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_atr_scanner_status():
    """Scanner status + lifetime stats + current live evaluation."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_atr_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_atr_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0

        state = _sma9_atr_live_state()
        status, age = _sma9_atr_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "sma9_atr",
            "scanner_name": "SMA9 ATR Stop - ATM Option Strike (BUY ONLY)",
            "scanner_version": state.get("scanner_version", "1.1.0"),
            "strategy_type": "SMA9_ATR_STOP_BUY_ONLY",
            "regime": state.get("regime", {}),
            "instrument": "NIFTY",
            "timeframe": "5m",
            "stop_model": {
                "type": "premium_atr",
                "k": 0.70,
                "atr_period": 14,
                "floor_pct": 0.05,
                "cap_pct": 0.30,
                "fallback_pct": 0.10,
                "fill": "actual_ltp",
            },
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-atr/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_atr_live_status():
    """Raw live scanner heartbeat/evaluation for the 5-second dashboard."""
    state = _sma9_atr_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _sma9_atr_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/sma9-atr/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_atr_recent_trades():
    """Recent trades, optionally scoped by dataset and trade date."""
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_sma9_atr_conn()
        query = "SELECT * FROM sma9_atr_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({"success": True, "trades": trades, "count": len(trades),
                        "total": total, "dataset": dataset or "ALL",
                        "trade_date": trade_date})
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/sma9-atr/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_atr_open_positions():
    """Open (unclosed) live paper positions, independent of the current ATM strike."""
    try:
        conn = get_sma9_atr_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_atr_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        positions = [dict(r) for r in rows]
        return jsonify({"success": True, "positions": positions,
                        "count": len(positions)})
    except Exception as e:
        return jsonify({"success": False, "positions": [], "error": str(e)}), 500


@app.route("/api/sma9-atr/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_atr_today():
    """ONLY today's LIVE paper trades (never stale historical rows)."""
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_sma9_atr_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_atr_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


# ============================================================================
# SMA9 HIGH Scanner API Endpoints (dedicated database: database/sma9_high.db)
# ============================================================================
SMA9_HIGH_DB_PATH = os.environ.get(
    "SMA9_HIGH_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "sma9_high.db")
)


def get_sma9_high_conn():
    """Per-request connection to the dedicated SMA9 HIGH database."""
    conn = sqlite3.connect(SMA9_HIGH_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _sma9_high_live_state():
    """Read the scanner heartbeat/state row (empty dict when unavailable)."""
    try:
        conn = get_sma9_high_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM sma9_high_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _sma9_high_scanner_health(state):
    """Classify scanner health without pretending stale data is live."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/sma9-high/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_signals():
    """Get SMA9 HIGH signals/trades with pagination and filters."""
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        conn = get_sma9_high_conn()
        query = "SELECT * FROM sma9_high_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        signals = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "signals": signals,
            "trades": signals,
            "count": len(signals),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trades():
    """Alias for /api/sma9-high/signals."""
    return api_sma9_high_signals()


@app.route("/api/sma9-high/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_daily_summary():
    """Daily summary, optionally scoped by dataset."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_high_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) as datasets
            FROM sma9_high_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_scanner_status():
    """Scanner status + lifetime stats + current live evaluation."""
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_high_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_high_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0

        state = _sma9_high_live_state()
        status, age = _sma9_high_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "sma9_high",
            "scanner_name": "SMA9 HIGH Only - ATM Option Strike + Prev-High Breakout (BUY ONLY)",
            "scanner_version": "1.8.0",
            "strategy_type": "SMA9_HIGH_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_live_status():
    """Raw live scanner heartbeat/evaluation for the 5-second dashboard."""
    state = _sma9_high_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _sma9_high_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/sma9-high/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_recent_trades():
    """Recent trades, optionally scoped by dataset and trade date."""
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_sma9_high_conn()
        query = "SELECT * FROM sma9_high_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({"success": True, "trades": trades, "count": len(trades),
                        "total": total, "dataset": dataset or "ALL",
                        "trade_date": trade_date})
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/sma9-high/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_today():
    """ONLY today's LIVE paper trades (never stale historical rows)."""
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_sma9_high_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_high_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/sma9-high/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_sma9_high_legacy_audit():
    """Stub: no legacy audit table for SMA9 HIGH."""
    return jsonify({
        "success": True,
        "total_audited": 0,
        "compliant": 0,
        "discrepant": 0,
        "compliance_rate_pct": 0,
        "by_option_type": [],
        "discrepancy_reason_groups": [],
        "rows": [],
    })


@app.route("/api/sma9-high/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_open_positions():
    """Open (unclosed) live paper positions, independent of the current ATM strike."""
    try:
        conn = get_sma9_high_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_high_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        positions = [dict(r) for r in rows]
        return jsonify({"success": True, "positions": positions,
                        "count": len(positions)})
    except Exception as e:
        return jsonify({"success": False, "positions": [], "error": str(e)}), 500


# ============================================================================
# NO-SMA Scanner API Endpoints (dedicated database: database/no_sma.db)
# ============================================================================
NO_SMA_DB_PATH = os.environ.get(
    "NO_SMA_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "no_sma.db")
)


def get_no_sma_conn():
    """Per-request connection to the dedicated NO-SMA database."""
    conn = sqlite3.connect(NO_SMA_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _no_sma_live_state():
    """Read the scanner heartbeat/state row (empty dict when unavailable)."""
    try:
        conn = get_no_sma_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM no_sma_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _no_sma_scanner_health(state):
    """Classify scanner health without pretending stale data is live."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/no-sma/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_signals():
    """Get NO-SMA signals/trades with pagination and filters."""
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")

        conn = get_no_sma_conn()
        query = "SELECT * FROM no_sma_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        signals = [dict(r) for r in rows]
        return jsonify({
            "success": True,
            "signals": signals,
            "trades": signals,
            "count": len(signals),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trades():
    """Alias for /api/no-sma/signals."""
    return api_no_sma_signals()


@app.route("/api/no-sma/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_daily_summary():
    """Daily summary, optionally scoped by dataset."""
    try:
        dataset = request.args.get("dataset")
        conn = get_no_sma_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl,
                   GROUP_CONCAT(DISTINCT dataset) as datasets
            FROM no_sma_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_scanner_status():
    """Scanner status + lifetime stats + current live evaluation."""
    try:
        dataset = request.args.get("dataset")
        conn = get_no_sma_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM no_sma_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0

        state = _no_sma_live_state()
        status, age = _no_sma_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "no_sma",
            "scanner_name": "NO-SMA Only - ATM Option Strike + Prev-High Breakout (BUY ONLY)",
            "scanner_version": "1.6.0",
            "strategy_type": "NO_SMA_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_live_status():
    """Raw live scanner heartbeat/evaluation for the 5-second dashboard."""
    state = _no_sma_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _no_sma_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/no-sma/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_recent_trades():
    """Recent trades, optionally scoped by dataset and trade date."""
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_no_sma_conn()
        query = "SELECT * FROM no_sma_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({"success": True, "trades": trades, "count": len(trades),
                        "total": total, "dataset": dataset or "ALL",
                        "trade_date": trade_date})
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/no-sma/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_today():
    """ONLY today's LIVE paper trades (never stale historical rows)."""
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_no_sma_conn()
        rows = conn.execute(
            "SELECT * FROM no_sma_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/no-sma/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_no_sma_legacy_audit():
    """Stub: no legacy audit table for NO-SMA."""
    return jsonify({
        "success": True,
        "total_audited": 0,
        "compliant": 0,
        "discrepant": 0,
        "compliance_rate_pct": 0,
        "by_option_type": [],
        "discrepancy_reason_groups": [],
        "rows": [],
    })


@app.route("/api/no-sma/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_open_positions():
    """Open (unclosed) live paper positions, independent of the current ATM strike."""
    try:
        conn = get_no_sma_conn()
        rows = conn.execute(
            "SELECT * FROM no_sma_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        positions = [dict(r) for r in rows]
        return jsonify({"success": True, "positions": positions,
                        "count": len(positions)})
    except Exception as e:
        return jsonify({"success": False, "positions": [], "error": str(e)}), 500
# ============================================================================
# SMA9_TRAIL trail API
# ============================================================================

SMA9_TRAIL_DB_PATH = os.environ.get(
    "SMA9_TRAIL_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "sma9_trail.db")
)


def get_sma9_trail_conn():
    """Per-request connection to the dedicated sma9_trail trail database."""
    conn = sqlite3.connect(SMA9_TRAIL_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _sma9_trail_live_state():
    try:
        conn = get_sma9_trail_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM sma9_trail_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _sma9_trail_scanner_health(state):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/sma9-trail/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trail_signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")
        conn = get_sma9_trail_conn()
        query = "SELECT * FROM sma9_trail_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "signals": [dict(r) for r in rows],
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-trail/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trail_trades():
    return api_sma9_trail_signals()


@app.route("/api/sma9-trail/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trail_daily_summary():
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_trail_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl
            FROM sma9_trail_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-trail/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trail_scanner_status():
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_trail_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_trail_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0
        state = _sma9_trail_live_state()
        status, age = _sma9_trail_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "sma9_trail",
            "scanner_name": "SMA9 Trail - ATM Option Strike + Trail Exit (BUY ONLY)",
            "scanner_version": "2.1.0",
            "strategy_type": "SMA_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-trail/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_trail_live_status():
    state = _sma9_trail_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _sma9_trail_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/sma9-trail/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_trail_recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_sma9_trail_conn()
        query = "SELECT * FROM sma9_trail_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
            "dataset": dataset or "ALL",
            "trade_date": trade_date,
        })
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/sma9-trail/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_trail_today():
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_sma9_trail_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_trail_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/sma9-trail/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_sma9_trail_legacy_audit():
    return jsonify({
        "success": True,
        "total_audited": 0,
        "compliant": 0,
        "discrepant": 0,
        "compliance_rate_pct": 0,
        "by_option_type": [],
        "discrepancy_reason_groups": [],
        "rows": [],
    })


@app.route("/api/sma9-trail/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_trail_open_positions():
    try:
        conn = get_sma9_trail_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_trail_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "positions": [dict(r) for r in rows],
            "count": len(rows),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "positions": []}), 500


# ============================================================================
# SMA9_HIGH_TRAIL trail API
# ============================================================================

SMA9_HIGH_TRAIL_DB_PATH = os.environ.get(
    "SMA9_HIGH_TRAIL_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "sma9_high_trail.db")
)


def get_sma9_high_trail_conn():
    """Per-request connection to the dedicated sma9_high_trail trail database."""
    conn = sqlite3.connect(SMA9_HIGH_TRAIL_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn


def _sma9_high_trail_live_state():
    try:
        conn = get_sma9_high_trail_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM sma9_high_trail_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _sma9_high_trail_scanner_health(state):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/sma9-high-trail/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trail_signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")
        conn = get_sma9_high_trail_conn()
        query = "SELECT * FROM sma9_high_trail_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "signals": [dict(r) for r in rows],
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high-trail/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trail_trades():
    return api_sma9_high_trail_signals()


@app.route("/api/sma9-high-trail/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trail_daily_summary():
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_high_trail_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl
            FROM sma9_high_trail_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high-trail/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trail_scanner_status():
    try:
        dataset = request.args.get("dataset")
        conn = get_sma9_high_trail_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM sma9_high_trail_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0
        state = _sma9_high_trail_live_state()
        status, age = _sma9_high_trail_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "sma9_high_trail",
            "scanner_name": "SMA9 HIGH Trail - ATM Option Strike + Trail Exit (BUY ONLY)",
            "scanner_version": "2.1.0",
            "strategy_type": "SMA_HIGH_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sma9-high-trail/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_trail_live_status():
    state = _sma9_high_trail_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _sma9_high_trail_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/sma9-high-trail/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_sma9_high_trail_recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_sma9_high_trail_conn()
        query = "SELECT * FROM sma9_high_trail_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
            "dataset": dataset or "ALL",
            "trade_date": trade_date,
        })
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/sma9-high-trail/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_trail_today():
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_sma9_high_trail_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_high_trail_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/sma9-high-trail/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_sma9_high_trail_legacy_audit():
    return jsonify({
        "success": True,
        "total_audited": 0,
        "compliant": 0,
        "discrepant": 0,
        "compliance_rate_pct": 0,
        "by_option_type": [],
        "discrepancy_reason_groups": [],
        "rows": [],
    })


@app.route("/api/sma9-high-trail/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_sma9_high_trail_open_positions():
    try:
        conn = get_sma9_high_trail_conn()
        rows = conn.execute(
            "SELECT * FROM sma9_high_trail_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "positions": [dict(r) for r in rows],
            "count": len(rows),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "positions": []}), 500


# ============================================================================
# NO_SMA_TRAIL trail API
# ============================================================================

NO_SMA_TRAIL_DB_PATH = os.environ.get(
    "NO_SMA_TRAIL_DB_PATH", os.path.join(os.path.dirname(DB_PATH), "no_sma_trail.db")
)


def get_no_sma_trail_conn():
    """Per-request connection to the dedicated no_sma_trail trail database."""
    conn = sqlite3.connect(NO_SMA_TRAIL_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    return conn

def _no_sma_trail_live_state():
    try:
        conn = get_no_sma_trail_conn()
        row = conn.execute(
            "SELECT value, updated_at FROM no_sma_trail_scan_state WHERE key='live_status'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        state = json.loads(row["value"])
        state["_state_updated_at"] = row["updated_at"]
        return state
    except Exception:
        return {}


def _no_sma_trail_scanner_health(state):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    last = state.get("last_scan_at")
    age = None
    if last:
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            age = None
    market_open = bool(state.get("market_open"))
    if last is None:
        status = "NOT_RUNNING"
    elif market_open and age is not None and age <= 15:
        status = "ACTIVE"
    elif market_open and age is not None and age > 15:
        status = "STALE"
    elif not market_open and age is not None and age <= 120:
        status = "IDLE_MARKET_CLOSED"
    else:
        status = "STOPPED"
    return status, age


@app.route("/api/no-sma-trail/signals", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trail_signals():
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        option_type = request.args.get("option_type")
        trade_date = request.args.get("trade_date")
        dataset = request.args.get("dataset")
        conn = get_no_sma_trail_conn()
        query = "SELECT * FROM no_sma_trail_trades WHERE 1=1"
        params = []
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type.upper())
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "signals": [dict(r) for r in rows],
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma-trail/trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trail_trades():
    return api_no_sma_trail_signals()


@app.route("/api/no-sma-trail/daily-summary", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trail_daily_summary():
    try:
        dataset = request.args.get("dataset")
        conn = get_no_sma_trail_conn()
        query = """
            SELECT trade_date as date,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_points) as total_pnl_points,
                   ROUND(AVG(pnl_points), 2) as avg_pnl
            FROM no_sma_trail_trades
        """
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " GROUP BY trade_date ORDER BY trade_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        daily = [dict(r) for r in rows]
        for d in daily:
            d["win_rate"] = round(d["wins"] / d["total_trades"] * 100, 2) if d["total_trades"] > 0 else 0
        return jsonify({"success": True, "daily": daily, "dataset": dataset or "ALL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma-trail/scanner-status", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trail_scanner_status():
    try:
        dataset = request.args.get("dataset")
        conn = get_no_sma_trail_conn()
        query = (
            "SELECT COUNT(*) as total_trades, SUM(pnl_points) as total_pnl, "
            "SUM(CASE WHEN pnl_points > 0 THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN pnl_points < 0 THEN 1 ELSE 0 END) as losses "
            "FROM no_sma_trail_trades"
        )
        params = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        row = conn.execute(query, params).fetchone()
        conn.close()
        total = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0
        win_rate = round(wins / total * 100, 2) if total > 0 else 0
        state = _no_sma_trail_live_state()
        status, age = _no_sma_trail_scanner_health(state)
        return jsonify({
            "success": True,
            "scanner_id": "no_sma_trail",
            "scanner_name": "NO-SMA Trail - ATM Option Strike + Trail Exit (BUY ONLY)",
            "scanner_version": "2.1.0",
            "strategy_type": "PREV_HIGH_BUY_ONLY",
            "instrument": "NIFTY",
            "timeframe": "5m",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "status": status,
            "last_scan_at": state.get("last_scan_at"),
            "last_scan_age_seconds": round(age, 1) if age is not None else None,
            "poll_seconds": state.get("poll_seconds", 5),
            "actual_interval_seconds": state.get("actual_interval_seconds"),
            "market_open": state.get("market_open"),
            "spot": state.get("spot"),
            "spot_source": state.get("spot_source"),
            "atm_strike": state.get("atm_strike"),
            "last_closed_spot": state.get("last_closed_spot"),
            "last_closed_atm_strike": state.get("last_closed_atm_strike"),
            "last_closed_candle_start": state.get("last_closed_candle_start"),
            "last_closed_ce_close": state.get("last_closed_ce_close"),
            "last_closed_pe_close": state.get("last_closed_pe_close"),
            "last_closed_spot_source": state.get("last_closed_spot_source"),
            "expiry": state.get("expiry"),
            "options": state.get("options", {}),
            "today": state.get("today", {}),
            "errors": state.get("errors", []),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/no-sma-trail/live-status", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_trail_live_status():
    state = _no_sma_trail_live_state()
    if not state:
        return jsonify({
            "success": False,
            "status": "NOT_RUNNING",
            "error": "No scanner heartbeat found",
            "poll_seconds": 5,
        }), 200
    status, age = _no_sma_trail_scanner_health(state)
    state["status"] = status
    state["last_scan_age_seconds"] = round(age, 1) if age is not None else None
    state["server_time"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return jsonify({"success": True, "data": state})


@app.route("/api/no-sma-trail/recent-trades", methods=["GET"])
@limiter.limit("120 per minute")
def api_no_sma_trail_recent_trades():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        dataset = request.args.get("dataset")
        trade_date = request.args.get("trade_date")
        conn = get_no_sma_trail_conn()
        query = "SELECT * FROM no_sma_trail_trades WHERE 1=1"
        params = []
        if dataset:
            query += " AND dataset = ?"
            params.append(dataset)
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY signal_timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "trades": [dict(r) for r in rows],
            "count": len(rows),
            "total": total,
            "dataset": dataset or "ALL",
            "trade_date": trade_date,
        })
    except Exception as e:
        return jsonify({"success": False, "trades": [], "error": str(e)}), 500


@app.route("/api/no-sma-trail/today", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_trail_today():
    try:
        today = request.args.get("trade_date") or datetime.now(
            ZoneInfo("Asia/Kolkata")).date().isoformat()
        conn = get_no_sma_trail_conn()
        rows = conn.execute(
            "SELECT * FROM no_sma_trail_trades WHERE dataset='LIVE' AND trade_date=? "
            "ORDER BY signal_timestamp DESC",
            (today,),
        ).fetchall()
        conn.close()
        trades = [dict(r) for r in rows]
        pnl = round(sum(t["pnl_points"] or 0 for t in trades), 2)
        wins = sum(1 for t in trades if (t["pnl_points"] or 0) > 0)
        losses = sum(1 for t in trades if (t["pnl_points"] or 0) < 0)
        return jsonify({
            "success": True,
            "trade_date": today,
            "trades": trades,
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "pnl_points": pnl,
            "is_today": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trades": []}), 500


@app.route("/api/no-sma-trail/legacy-audit", methods=["GET"])
@limiter.limit("60 per minute")
def api_no_sma_trail_legacy_audit():
    return jsonify({
        "success": True,
        "total_audited": 0,
        "compliant": 0,
        "discrepant": 0,
        "compliance_rate_pct": 0,
        "by_option_type": [],
        "discrepancy_reason_groups": [],
        "rows": [],
    })


@app.route("/api/no-sma-trail/open-positions", methods=["GET"])
@limiter.limit("180 per minute")
def api_no_sma_trail_open_positions():
    try:
        conn = get_no_sma_trail_conn()
        rows = conn.execute(
            "SELECT * FROM no_sma_trail_open_positions ORDER BY entry_timestamp"
        ).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "positions": [dict(r) for r in rows],
            "count": len(rows),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "positions": []}), 500
