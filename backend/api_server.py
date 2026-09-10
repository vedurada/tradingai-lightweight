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
    if row:
        return jsonify(row_to_dict(row))
    conn.close()
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

def _symbol_data(symbol):
    conn = get_db()
    result = {}
    price_row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if price_row:
        result["quote"] = row_to_dict(price_row)
    ind_row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if ind_row:
        result["indicators"] = row_to_dict(ind_row)
    regime_row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if regime_row:
        result["regime"] = row_to_dict(regime_row)
    strat_row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if strat_row:
        result["strategy"] = row_to_dict(strat_row)
    scen_row = conn.execute("SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if scen_row:
        result["scenarios"] = [row_to_dict(scen_row)]
    outlook_row = conn.execute("SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if outlook_row:
        result["ai_outlook"] = row_to_dict(outlook_row)
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
    conn = get_db()
    result = {}
    for sym in ["NIFTY", "BANKNIFTY", "SENSEX", "VIX"]:
        row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (sym,)).fetchone()
        if row:
            result[sym] = row_to_dict(row)
    vix_row = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
    if vix_row:
        result["VIX"] = row_to_dict(vix_row)
    snap_row = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
    if snap_row:
        result["snapshot"] = row_to_dict(snap_row)
    conn.close()
    return jsonify(result)

@app.route("/api/history")
def history():
    symbol = request.args.get("symbol", "")
    days = request.args.get("days", 30, type=int)
    conn = get_db()
    if symbol:
        rows = conn.execute("SELECT * FROM history WHERE symbol=? AND date >= date('now', '-' || ? || ' days') ORDER BY date DESC", (symbol, days)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM history WHERE date >= date('now', '-' || ? || ' days') ORDER BY symbol, date DESC", (days,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/news")
def news():
    conn = get_db()
    rows = conn.execute("SELECT * FROM news ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
