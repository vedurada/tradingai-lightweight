from __future__ import annotations

import json
import os
import sys
import sqlite3
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def serialize_val(v):
    if isinstance(v, float):
        return round(v, 4)
    return v

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})

@app.route("/api/symbols")
def symbols():
    conn = get_db()
    rows = conn.execute("SELECT * FROM symbols WHERE active=1 ORDER BY type, symbol").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/price/<symbol>")
def latest_price(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no data"}), 404

@app.route("/api/prices/<symbol>")
def prices(symbol):
    limit = request.args.get("limit", 100, type=int)
    interval = request.args.get("interval", "1m")
    table = f"price_{interval}" if interval in ("1m", "5m", "15m", "1d") else "price_1m"
    conn = get_db()
    rows = conn.execute(f"SELECT * FROM {table} WHERE symbol=? ORDER BY timestamp DESC LIMIT ?", (symbol, limit)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in reversed(rows)])

@app.route("/api/prices")
def all_prices():
    limit = request.args.get("limit", 50, type=int)
    symbols_param = request.args.get("symbols", "")
    conn = get_db()
    if symbols_param:
        syms = symbols_param.split(",")
        placeholders = ",".join("?" for _ in syms)
        rows = conn.execute(f"SELECT * FROM price_1m WHERE symbol IN ({placeholders}) ORDER BY timestamp DESC LIMIT ?", (*syms, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM price_1m ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/vix")
def vix():
    conn = get_db()
    row = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        d = row_to_dict(row)
        # Legacy frontend expects {price, change, change_pct}.
        d["price"] = d.get("close", 0)
        return jsonify(d)
    return jsonify({"error": "no VIX data"}), 404

@app.route("/api/vix/history")
def vix_history():
    limit = request.args.get("limit", 100, type=int)
    conn = get_db()
    rows = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in reversed(rows)])

@app.route("/api/indicators/<symbol>")
def indicators(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no indicators"}), 404

@app.route("/api/indicators")
def indicators_default():
    symbol = request.args.get("symbol", "NIFTY")
    conn = get_db()
    row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no indicators"}), 404

@app.route("/api/nifty")
def nifty():
    return _symbol_data("NIFTY")

@app.route("/api/banknifty")
def banknifty():
    return _symbol_data("BANKNIFTY")

@app.route("/api/sensex")
def sensex():
    return _symbol_data("SENSEX")

@app.route("/api/finnifty")
def finnifty():
    return _symbol_data("FINNIFTY")

@app.route("/api/<symbol>")
def symbol_generic(symbol):
    s = (symbol or "").upper()
    if s in ("MARKET", "HEALTH", "HISTORY", "VIX", "SNAPSHOT", "SNAPSHOTS", "BREADTH", "SYMBOLS", "STRATEGIES", "OUTLOOKS", "REGIMES", "PRICES", "ETF", "NEWS"):
        return jsonify({"error": "use dedicated endpoint"}), 404
    conn = get_db()
    row = conn.execute("SELECT symbol FROM symbols WHERE UPPER(symbol)=? LIMIT 1", (s,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": f"unknown symbol {symbol}"}), 404
    return _symbol_data(s)

def _parse_json_field(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _build_quote(symbol, price_row):
    """price_1m row -> legacy quote shape {price, change, change_pct, ...}."""
    if not price_row:
        return None
    d = row_to_dict(price_row)
    close = d.get("close", 0) or 0
    prev = d.get("previous_close", 0) or 0
    if not prev:
        try:
            conn = get_db()
            prow = conn.execute("SELECT close FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 2", (symbol,)).fetchall()
            conn.close()
            if len(prow) > 1:
                prev = prow[1]["close"] or 0
        except Exception:
            pass
    change = (close - prev) if prev else 0
    return {
        "symbol": symbol, "price": close, "change": round(change, 2),
        "change_pct": round(change / prev * 100, 2) if prev else 0,
        "open": d.get("open", 0), "high": d.get("high", 0), "low": d.get("low", 0),
        "previous_close": prev, "volume": d.get("volume", 0),
        "timestamp": d.get("timestamp"), "stale": False,
    }


def _build_indicators(ind_row):
    if not ind_row:
        return None
    d = row_to_dict(ind_row)
    sr = _parse_json_field(d.get("support_resistance"), {}) or {}
    if isinstance(sr, str):
        sr = {}
    d["support_resistance"] = {"support": sr.get("support", []), "resistance": sr.get("resistance", [])} if isinstance(sr, dict) else {"support": [], "resistance": []}
    return d


def _build_strategy(strat_row):
    """DB single row -> legacy {strategies: [...]} shape (options for indexes, BUY/HOLD/EXIT for stocks)."""
    if not strat_row:
        return None
    d = row_to_dict(strat_row)
    legs_parsed = _parse_json_field(d.get("legs"), None)
    if isinstance(legs_parsed, dict) and "all_strategies" in legs_parsed:
        strategies = legs_parsed.get("all_strategies", []) or []
        legs = legs_parsed.get("legs", [])
        if strategies:
            strategies[0]["legs"] = strategies[0].get("legs", legs)
            return {"strategies": strategies, "timestamp": d.get("timestamp")}
    single = {k: d.get(k) for k in ("strategy", "market_condition", "expiry", "entry_trigger", "maximum_profit", "maximum_loss", "breakeven", "stop_loss", "target", "adjustment", "exit", "strategy_environment", "invalidation", "position_size")}
    single["legs"] = legs_parsed if isinstance(legs_parsed, list) else []
    return {"strategies": [single], "timestamp": d.get("timestamp")}


def _build_scenarios(scen_row):
    """DB flattened row -> legacy list [{scenario_type, description, target, stop_loss, trigger}]."""
    if not scen_row:
        return []
    d = row_to_dict(scen_row)
    out = []
    if d.get("bullish_trigger") or d.get("bullish_target"):
        out.append({"scenario_type": "BULLISH", "description": d.get("bullish_confirmation", ""), "trigger": d.get("bullish_trigger", ""), "target": d.get("bullish_target", ""), "stop_loss": d.get("bullish_invalidation", "")})
    if d.get("bearish_trigger") or d.get("bearish_target"):
        out.append({"scenario_type": "BEARISH", "description": d.get("bearish_confirmation", ""), "trigger": d.get("bearish_trigger", ""), "target": d.get("bearish_target", ""), "stop_loss": d.get("bearish_invalidation", "")})
    if d.get("range_condition"):
        out.append({"scenario_type": "RANGE", "description": d.get("range_strategy", ""), "trigger": d.get("range_condition", ""), "target": d.get("range_strategy", ""), "stop_loss": d.get("range_invalidation", "")})
    return out


def _build_outlook(outlook_row):
    if not outlook_row:
        return None
    d = row_to_dict(outlook_row)
    full = _parse_json_field(d.get("outlook"), None)
    if isinstance(full, dict) and full:
        return full
    return {"market_summary": d.get("outlook", ""), "data_quality": d.get("data_quality", "")}


def _symbol_data(symbol):
    symbol = (symbol or "").upper()
    conn = get_db()
    result = {}
    price_row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    quote = _build_quote(symbol, price_row)
    if quote:
        result["quote"] = quote
    ind_row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    ind = _build_indicators(ind_row)
    if ind:
        result["indicators"] = ind
    regime_row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if regime_row:
        result["regime"] = row_to_dict(regime_row)
    strat_row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    strat = _build_strategy(strat_row)
    if strat:
        result["strategy"] = strat
    scen_row = conn.execute("SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    result["scenarios"] = _build_scenarios(scen_row)
    outlook_row = conn.execute("SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    outlook = _build_outlook(outlook_row)
    if outlook:
        result["ai_outlook"] = outlook
    try:
        from expiry import get_current_expiry
        if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            result["expiry"] = get_current_expiry() if callable(get_current_expiry) else {}
    except Exception:
        pass
    last_ts = None
    for key in ("quote", "indicators", "regime", "strategy"):
        ts = (result.get(key) or {}).get("timestamp")
        if ts and (not last_ts or ts > last_ts):
            last_ts = ts
    result["last_updated"] = last_ts
    result["data_quality"] = (result.get("ai_outlook") or {}).get("data_quality", "GOOD")
    conn.close()
    return jsonify(result)

@app.route("/api/regime/<symbol>")
def regime(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no regime"}), 404

@app.route("/api/regimes")
def all_regimes():
    conn = get_db()
    rows = conn.execute("SELECT * FROM market_regime ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/strategy/<symbol>")
def strategy(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no strategy"}), 404

@app.route("/api/strategies")
def all_strategies():
    conn = get_db()
    rows = conn.execute("SELECT * FROM strategies ORDER BY timestamp DESC").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/scenarios/<symbol>")
def scenarios(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no scenarios"}), 404

@app.route("/api/outlook/<symbol>")
def outlook(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no outlook"}), 404

@app.route("/api/outlooks")
def all_outlooks():
    conn = get_db()
    rows = conn.execute("SELECT * FROM ai_outlooks ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/options/<symbol>")
def options(symbol):
    expiry = request.args.get("expiry", "")
    conn = get_db()
    if expiry:
        rows = conn.execute("SELECT * FROM option_chain WHERE symbol=? AND expiry=? ORDER BY option_type, strike", (symbol, expiry)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM option_chain WHERE symbol=? ORDER BY fetched_at DESC LIMIT 200", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/options/expiries/<symbol>")
def option_expiries(symbol):
    conn = get_db()
    rows = conn.execute("SELECT * FROM option_expiries WHERE symbol=? ORDER BY expiry", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/breadth")
def breadth():
    conn = get_db()
    row = conn.execute("SELECT * FROM market_breadth ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no breadth"}), 404

@app.route("/api/breadth/history")
def breadth_history():
    limit = request.args.get("limit", 100, type=int)
    conn = get_db()
    rows = conn.execute("SELECT * FROM market_breadth ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in reversed(rows)])

@app.route("/api/snapshot")
def snapshot():
    conn = get_db()
    row = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no snapshot"}), 404

@app.route("/api/snapshots")
def snapshots():
    limit = request.args.get("limit", 50, type=int)
    conn = get_db()
    rows = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/fundamentals/<symbol>")
def fundamentals(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM fundamentals WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no fundamentals"}), 404

@app.route("/api/data_status")
def data_status():
    conn = get_db()
    rows = conn.execute("SELECT * FROM data_status ORDER BY symbol").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/etf")
def etf():
    conn = get_db()
    rows = conn.execute("SELECT * FROM etf_data ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/market")
def market():
    """Legacy shape: {instruments: {SYM: symbol_payload}, ai_outlook, last_updated, data_quality}."""
    conn = get_db()
    sym_rows = conn.execute("SELECT symbol FROM symbols WHERE active=1 ORDER BY type, symbol").fetchall()
    symbols = [r["symbol"] for r in sym_rows] or ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    conn.close()
    instruments = {}
    latest_ts = None
    # Reuse _symbol_data logic without extra HTTP: query directly.
    from flask import json as flask_json
    for sym in symbols:
        with app.test_request_context():
            resp = _symbol_data(sym)
            payload = resp.get_json()
        if payload and payload.get("quote"):
            instruments[sym] = payload
            ts = payload.get("last_updated")
            if ts and (not latest_ts or ts > latest_ts):
                latest_ts = ts
    nifty_ai = (instruments.get("NIFTY") or {}).get("ai_outlook", {})
    return jsonify({"source": "TradingAI DB (AI-assisted)", "last_updated": latest_ts, "data_quality": (nifty_ai.get("data_quality") or "GOOD"), "ai_outlook": nifty_ai, "instruments": instruments})

@app.route("/api/history")
def history():
    """Grouped {SYM: [...]} shape; covers history + monthly archive (1-year retention)."""
    symbol = request.args.get("symbol", "")
    days = request.args.get("days", 365, type=int)
    conn = get_db()
    if symbol:
        rows = conn.execute("SELECT *, 'live' AS _src FROM history WHERE UPPER(symbol)=UPPER(?) AND date >= date('now', '-' || ? || ' days') ORDER BY date DESC", (symbol, days)).fetchall()
        arch = conn.execute("SELECT *, 'archive' AS _src FROM history_archive WHERE UPPER(symbol)=UPPER(?) AND date >= date('now', '-' || ? || ' days') ORDER BY date DESC", (symbol, days)).fetchall()
    else:
        rows = conn.execute("SELECT *, 'live' AS _src FROM history WHERE date >= date('now', '-' || ? || ' days') ORDER BY symbol, date DESC", (days,)).fetchall()
        arch = conn.execute("SELECT *, 'archive' AS _src FROM history_archive WHERE date >= date('now', '-' || ? || ' days') ORDER BY symbol, date DESC", (days,)).fetchall()
    conn.close()
    rows = list(rows) + list(arch)
    grouped = {}
    for r in rows:
        d = row_to_dict(r)
        d.pop("_src", None)
        try:
            ntc = d.get("no_trade_conditions")
            d["no_trade_conditions"] = json.loads(ntc) if isinstance(ntc, str) and ntc else (ntc or [])
        except Exception:
            d["no_trade_conditions"] = []
        grouped.setdefault(d.get("symbol", "UNKNOWN"), []).append(d)
    for sym in grouped:
        grouped[sym].sort(key=lambda e: e.get("date", ""), reverse=True)
    return jsonify(grouped)

@app.route("/api/news")
def news():
    conn = get_db()
    rows = conn.execute("SELECT * FROM news ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
