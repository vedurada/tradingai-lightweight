from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments
from app.market.provider import MarketDataProvider
from app.core.qualification import QualificationEngine
from app.paper_trade.engine import PaperTradeEngine
from app.ai.explanation import AIExplanation
from app.scenarios.engine import ScenarioEngine
from app.live.engine import LiveEngine
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.options import (
    OptionsFreshness, get_options_chain, get_option_contracts,
    init_option_tables, get_option_table_stats,
    validate_contract, validate_underlying_consistency,
    OptionsStrategyEngine)
from app.options.contract import OptionsFreshness as OF, VALID_INSTRUMENTS
from app.options.cache import recompute_age

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
market = MarketDataProvider()
qual = QualificationEngine(settings)
paper = PaperTradeEngine()
ai = AIExplanation()
scenario_engine = ScenarioEngine()
live_engine = LiveEngine()
_IST = ZoneInfo("Asia/Kolkata")

# Initialize option tables on import
try:
    init_option_tables()
except Exception:
    pass

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
    return jsonify({"status": "LIVE", "timestamp": now_ist.isoformat(),
                    "data": {"tables": len(tables), "database": DB_PATH},
                    "market": {"session_window": sess,
                               "holiday": hn,
                               "note": "application healthy; market state is informational"}})

@app.route("/api/<symbol>/summary", methods=["GET"])
@limiter.limit("30 per minute")
def summary(symbol):
    inst = (symbol or "").upper()
    if inst in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        # Read-only: dry_run performs zero DB writes (no lock side effects).
        st = live_engine.evaluate(inst, dry_run=True)
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

    Price only: no engine evaluation, no CPR, no decisions. The full
    decision/CPR cycle refreshes separately on completed 5-minute candles."""
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
    previous-session CPR research fns and read-only strategy/lock state
    into one per-instrument decision object. Zero DB writes."""
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    from app.decision.view import build_decision
    d = build_decision(inst)
    d['live_price'] = d.get('price')
    d['state'] = d.get('engine_state')
    d['now_ist'] = d.get('timestamp')
    d['reasons'] = d.get('engine_reasons')
    return jsonify({"state": d["data_status"], "timestamp": d["timestamp"], "data": d})


@app.route("/api/<symbol>/decision/claim", methods=["POST"])
@limiter.limit("5 per minute")
def decision_claim(symbol):
    """Explicit state-changing operation: run the gated live evaluation and,
    only if all gates pass and the setup qualifies, persist the one-trade-day
    lock/row. Idempotent per (instrument, trade_date): repeats return
    DAILY_TRADE_LIMIT_REACHED, never duplicates, never HTTP 500."""
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
            return jsonify({"state": "LIVE", "timestamp": now_ist.isoformat(),
                            "data": {"instrument": inst, "candles": _candles,
                                     "count": len(_candles),
                                     "completed_candle": completed.isoformat() if completed else None,
                                     "forming_excluded": True,
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


@app.route("/api/<symbol>/paper-trade", methods=["GET"])
@limiter.limit("30 per minute")
def paper_trade(symbol):
    trades = paper.monitor(symbol)
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(), "data": {"trades": trades, "active": len(trades)}})

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
    """Today's spread preview (read-only): aligned trigger state + legs from
    the real strike grid + payoff curve. Credit is live LTPs when the NSE
    feed answers, else null (structure-only, clearly flagged)."""
    from app.research.cpr_trigger_engine import today_state
    from app.options.weekly_spreads import build_spread, next_expiry, payoff_curve
    from app.options import nse_chain
    inst = (request.args.get("instrument") or "NIFTY").upper()
    if inst not in ("NIFTY", "BANKNIFTY"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    st = today_state(inst, variant="aligned")
    if not isinstance(st, dict) or st.get("state") != "SIGNAL":
        return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                        "data": {"trigger": st, "spread": None, "credit": None,
                                 "payoff": None}})
    entry = st.get("entry")
    if entry is None:
        q = market.get_quote({"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}[inst])
        entry = q.get("price")
    sp = build_spread(inst, st.get("direction"), entry)
    if sp.get("error"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": sp["error"]}}), 404
    try:
        exp = next_expiry(inst)
    except Exception:
        exp = None
    try:
        credit = nse_chain.get_credit(inst, sp["legs"])
    except Exception:
        credit = None
    sp["expiry"] = exp
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": {"trigger": st, "spread": sp, "credit": credit,
                             "payoff": payoff_curve(sp, credit)}})

# REMOVED 2026-09-28: POST /api/backtest/run (BacktestEngine simulator) had 0 callers
# (no frontend/cron). Use POST /api/backtest/cpr-triggers (opens-spec, mirrors live).
# IntradayExitEngine in app/research/backtest.py is still live-shared via replay.py.

@app.route("/api/backtest/cpr-triggers", methods=["POST"])
@limiter.limit("5 per minute")
def run_cpr_trigger_backtest():
    """No-filter CPR trigger backtest over stored 5m candles (opens execution).

    variant plain: bull on S2/S1/PDL touch or close above TC; bear on
      R2/R1/PDH touch or close below BC.
    variant aligned: same triggers gated by weekly CPR (bull needs close
      above weekly TC, bear below weekly BC).
    First trigger/session, entry at next open in [09:20,15:20), 0.5% stop /
    2% target evaluated at subsequent opens (stop first), flat 15:20 open.
    Read-only. Paper rows newer than date_end are appended (source='paper')
    so the table grows day by day with live paper trading."""
    from app.research.cpr_trigger_engine import run_opens_range, VARIANTS
    body = request.get_json() or {}
    inst = (body.get("instrument") or "NIFTY").upper()
    variant = (body.get("variant") or "aligned").lower()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_INSTRUMENT"]}}), 404
    if variant not in VARIANTS:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": ["UNKNOWN_VARIANT"]}}), 404
    ds = body.get("date_start", "2026-07-29")
    de = body.get("date_end", "2026-09-25")
    result = run_opens_range(inst, ds, de, variant)
    if isinstance(result, dict) and result.get('error'):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"reasons": [result['error']]}}), 404
    paper = []
    conn = None
    try:
        from app.research.cpr_trigger_engine import decay_win
        conn = get_conn()
        rows = conn.execute(
            "SELECT session_date AS trade_date, direction, level, entry_time, "
            "entry_price AS entry, exit_time, exit_price AS exit, exit_reason, "
            "r_multiple, result FROM paper_align "
            "WHERE instrument_id=? AND variant=? AND session_date>? "
            "ORDER BY session_date", (inst, variant, de)).fetchall()
        for r in rows:
            d = dict(r)
            d['source'] = 'paper'
            d['exit_reason'] = 'PAPER · ' + (d.get('exit_reason') or '')
            d['win_loss'] = decay_win(d.get('direction'), d.get('entry'),
                                      d.get('exit'), d.get('r_multiple'), inst)
            try:
                en, ex = float(d['entry']), float(d['exit'])
                d['points'] = round((ex - en) if d.get('direction') == 'BULL'
                                    else (en - ex), 1)
            except (TypeError, ValueError):
                d['points'] = None
            paper.append(d)
    except Exception as e:
        import logging as _log
        _log.getLogger('tradingai.api').warning('paper merge failed: %s', str(e)[:120])
        paper = []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    result['paper_trades'] = paper
    result['paper_appended'] = len(paper)
    if paper:
        pw = sum(1 for t in paper if t.get('win_loss') == 'WIN')
        pl = sum(1 for t in paper if t.get('win_loss') == 'LOSS')
        pr = [t['r_multiple'] for t in paper
              if isinstance(t.get('r_multiple'), (int, float))]
        result['wins'] = result.get('wins', 0) + pw
        result['losses'] = result.get('losses', 0) + pl
        result['signals'] = result.get('signals', 0) + len(paper)
        n = result['signals']
        result['win_rate'] = round(100 * result['wins'] / n, 1) if n else 0
        result['total_R'] = round(result.get('total_R', 0) + sum(pr), 2)
        result['paper_included'] = True
    return jsonify({"state": "COMPLETED", "data": result})

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
    """Live paper-trade performance aggregated across all instruments."""
    from app.paper_trade.performance import get_performance
    perf = get_performance()
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(), "data": perf})


@app.route("/api/performance/live/<instrument>", methods=["GET"])
@limiter.limit("30 per minute")
def live_performance_instrument(instrument):
    """Live paper-trade performance for one instrument."""
    from app.paper_trade.performance import get_performance
    inst = (instrument or "").upper()
    if inst not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    perf = get_performance(inst)
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(), "data": perf})



@app.route("/api/strategy/cpr-triggers", methods=["GET"])
@limiter.limit("30 per minute")
def cpr_trigger_signal():
    """Today's CPR trigger state (opens execution). Read-only: today's stored
    candles so far vs previous-session CPR. ?variant=plain|aligned (default
    aligned, matching POST). SIGNAL (direction/level/entry/stop/target),
    WATCH, or NO_DATA. Never writes, never trades."""
    from app.research.cpr_trigger_engine import today_state, VALID, VARIANTS
    instrument = (request.args.get("instrument") or "NIFTY").upper()
    variant = (request.args.get("variant") or "aligned").lower()
    if instrument not in VALID:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    if variant not in VARIANTS:
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": "UNKNOWN_VARIANT"}}), 404
    st = today_state(instrument, variant=variant)
    if isinstance(st, dict) and st.get('error'):
        return jsonify({"state": "NO_DATA", "timestamp": None,
                        "data": {"error": st['error']}}), 404
    return jsonify({"state": "LIVE", "timestamp": datetime.now(_IST).isoformat(),
                    "data": st})

@app.route("/api/strategy/cpr", methods=["GET"])
@limiter.limit("30 per minute")
def cpr_strategy():
    """Live CPR directional signal."""
    instrument = (request.args.get("instrument") or "NIFTY").upper()
    if instrument not in ("NIFTY", "BANKNIFTY", "INDIA_VIX"):
        return jsonify({"state": "NO_DATA", "timestamp": None, "data": {"error": "UNKNOWN_INSTRUMENT"}}), 404
    from app.live.engine import completed_candle_ts
    from app.market.provider import MarketDataProvider
    from app.research.cpr_strategy_engine import calculate_cpr as calc_cpr, classify_cpr as cls_cpr, classify_gap as cls_gap, classify_ladder as cls_ladder, is_virgin_cpr as is_virgin, live_signal
    import sqlite3
    from app.core.db import get_conn

    now = datetime.now(_IST)
    cutoff = completed_candle_ts(now)
    provider = MarketDataProvider()

    # Fetch previous session data for CPR calculation
    conn = get_conn()
    prev = conn.execute(
        "SELECT MAX(timestamp) as ts FROM market_candles_5m WHERE instrument_id=? AND timestamp < ?",
        (instrument, now.isoformat())).fetchone()
    conn.close()

    if not prev or not prev["ts"]:
        return jsonify({"state": "NO_DATA", "timestamp": now.isoformat(),
                         "data": {"error": "NO_PREVIOUS_SESSION", "instrument": instrument}})

    # Get previous session OHLC
    prev_date = prev["ts"][:10]
    conn = get_conn()
    prev_candles = conn.execute(
        "SELECT open, high, low, close FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp",
        (instrument, prev_date)).fetchall()
    conn.close()

    if len(prev_candles) < 2:
        return jsonify({"state": "NO_DATA", "timestamp": now.isoformat(),
                         "data": {"error": "INSUFFICIENT_HISTORY", "instrument": instrument}})

    prev_h = max(c["high"] for c in prev_candles)
    prev_l = min(c["low"] for c in prev_candles)
    prev_c = prev_candles[-1]["close"]

    cpr = calc_cpr(prev_h, prev_l, prev_c)
    cpr["r1"] = 2 * cpr["pp"] - prev_l
    cpr["s1"] = 2 * cpr["pp"] - prev_h
    cpr["r2"] = cpr["pp"] + (prev_h - prev_l)
    cpr["s2"] = cpr["pp"] - (prev_h - prev_l)
    classification = cls_cpr(cpr["width_pct"])

    # Gap from previous close vs CACHED quote close only (45s TTL shared cache).
    # Never bypasses cache (no use_cache=False) and never uses a forming-tick:
    # today_candles below are filtered to completed candles (<= completed cutoff).
    live_quote = provider.get_quote({"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIA_VIX": "^INDIAVIX"}[instrument])
    gift_change = (live_quote.get("price", 0) - prev_c) if live_quote.get("price") else 0
    gap = cls_gap(gift_change)

    # Get current session candles for ladder/virgin check
    conn = get_conn()
    today_candles = conn.execute(
        "SELECT open, high, low, close, timestamp FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10)=? AND timestamp<=? ORDER BY timestamp",
        (instrument, now.strftime("%Y-%m-%d"), (completed_candle_ts(now) or now).isoformat())).fetchall()
    conn.close()

    if len(today_candles) >= 2:
        today_h = max(c["high"] for c in today_candles)
        today_l = min(c["low"] for c in today_candles)
        ladder = cls_ladder(cpr, calc_cpr(today_h, today_l, today_candles[-1]["close"]))
        virgin = is_virgin(today_h, today_l, cpr["tc"], cpr["bc"])
    else:
        ladder = "NEUTRAL"
        virgin = False

    # Real 9:15-9:45 confirmation (when formed) enables full signal
    # evaluation incl. gap-fade; otherwise the endpoint reports state only.
    conf_arg, open_arg = None, None
    try:
        oc = [c for c in today_candles
              if "09:15" <= str(c["timestamp"])[11:16] <= "09:45"]
        if oc:
            conf_arg = {"open": float(oc[0]["open"]), "high": max(float(c["high"]) for c in oc),
                        "low": min(float(c["low"]) for c in oc), "close": float(oc[-1]["close"]),
                        "green": bool(float(oc[-1]["close"]) > float(oc[0]["open"])),
                        "red": bool(float(oc[-1]["close"]) < float(oc[0]["open"])),
                        "timestamp": str(oc[-1]["timestamp"])}
            open_arg = float(today_candles[0]["open"])
    except Exception:
        conf_arg, open_arg = None, None
    day_candles = [{"open": float(c["open"]), "high": float(c["high"]),
                    "low": float(c["low"]), "close": float(c["close"]),
                    "timestamp": str(c["timestamp"])} for c in today_candles] or None
    signal = live_signal(instrument, cpr, gift_change, ladder, virgin,
                         confirmation=conf_arg, opening_price=open_arg,
                         day_candles=day_candles)
    return jsonify({"state": "LIVE", "timestamp": now.isoformat(), "data": signal})



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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)


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
