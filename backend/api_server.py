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


def _to_ist_iso(ts):
    """Normalize DB timestamps to ISO with IST offset.

    price_1m candles are stored naive ('YYYY-MM-DD HH:MM:SS') in exchange-local
    (IST) time; other tables store UTC ISO. Returns ISO-8601 with offset, or None.
    """
    if not ts:
        return None
    s = str(ts).strip()
    try:
        if "T" in s:
            if s.endswith("Z"):
                return s
            if "+" in s[10:] or s[10:].count("-") > 2:
                return s
            return s + "+00:00"
        # Naive 'YYYY-MM-DD HH:MM:SS' -> IST.
        return s.replace(" ", "T") + "+05:30"
    except Exception:
        return None


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
        "timestamp": _to_ist_iso(d.get("timestamp")), "stale": False,
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


def _ist_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _locked_strategy(conn, symbol):
    """Today's 9:30 AM locked strategy (indexes), if the lock cron has run."""
    try:
        row = conn.execute("SELECT * FROM daily_strategy WHERE symbol=? AND date=?", (symbol, _ist_today())).fetchone()
    except Exception:
        return None
    if not row:
        return None
    d = row_to_dict(row)
    try:
        strategies = json.loads(d.get("strategy_json") or "[]")
    except Exception:
        strategies = []
    if not strategies:
        return None
    return {"strategies": strategies, "locked": True, "locked_at": d.get("locked_at", "09:30"),
            "regime": d.get("regime", ""), "timestamp": d.get("created_at")}


def _live_expiry(conn, symbol):
    """Nearest real NSE expiry per index from option_expiries (None if none stored).

    Classifies MONTHLY vs WEEKLY: an expiry on the last exchange-weekday of its
    month is the monthly contract, otherwise a weekly. NSE=Tuesday, BSE=Thursday.
    """
    from datetime import date as _date, timedelta as _td
    try:
        today = _ist_today()
    except Exception:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        rows = conn.execute("SELECT expiry FROM option_expiries WHERE symbol=? AND expiry>=? ORDER BY expiry", (symbol, today)).fetchall()
    except Exception:
        return None
    dates = []
    for r in rows:
        try:
            dates.append(_date.fromisoformat(str(r["expiry"])[:10]))
        except Exception:
            continue
    if not dates:
        return None
    weekday = 3 if symbol == "SENSEX" else 1
    day_label = "Thursday" if symbol == "SENSEX" else "Tuesday"
    exchange = "BSE" if symbol == "SENSEX" else "NSE"

    def is_monthly(d):
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        m = 1 if m > 12 else m
        last = _date(y, m, 1) - _td(days=1)
        while last.weekday() != weekday:
            last -= _td(days=1)
        return d == last

    def payload(d, tenor):
        return {"expiry_date": d.isoformat(), "expiry_label": d.strftime("%d %b %Y"),
                "expiry_weekday": day_label, "days_to_expiry": (d - _date.fromisoformat(today)).days,
                "tenor": tenor, "expiry_day": day_label, "source": "NSE",
                "timestamp": datetime.now(timezone.utc).isoformat()}

    monthlies = [d for d in dates if is_monthly(d)]
    weekly = next((d for d in dates if d not in monthlies), None)
    if symbol in ("BANKNIFTY", "FINNIFTY"):
        weekly = None  # monthly-only contracts
    first = weekly or (monthlies[0] if monthlies else None)
    if not first:
        return None
    out = payload(first, "WEEKLY" if weekly and first == weekly else "MONTHLY")
    out.update({"symbol": symbol, "exchange": exchange,
                "weekly": payload(weekly, "WEEKLY") if weekly else None,
                "monthly": payload(monthlies[0], "MONTHLY") if monthlies else None})
    return out


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
    strat = _locked_strategy(conn, symbol)
    if not strat:
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
        stype = conn.execute("SELECT type FROM symbols WHERE symbol=?", (symbol,)).fetchone()
        if stype and stype["type"] == "stock":
            inv = {}
            for r in conn.execute("SELECT * FROM investment_views WHERE symbol=? ORDER BY date DESC, horizon", (symbol,)).fetchall():
                d = row_to_dict(r)
                if d.get("horizon") not in inv:
                    inv[d.get("horizon")] = d
            if inv:
                result["investment"] = inv
    except Exception:
        pass
    try:
        srow = conn.execute("SELECT lot_size, lot_source, lot_as_of FROM symbols WHERE symbol=?", (symbol,)).fetchone()
        if srow and srow["lot_size"]:
            result["lot"] = {"size": srow["lot_size"], "source": srow["lot_source"] or "config", "as_of": srow["lot_as_of"]}
    except Exception:
        pass
    try:
        exp = _live_expiry(conn, symbol)
        if not exp:
            from expiry import get_current_expiry
            if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
                exp = get_current_expiry(symbol) if callable(get_current_expiry) else {}
        if exp:
            result["expiry"] = exp
    except Exception:
        pass
    # last_updated = MARKET DATA time (quote candle), never computation time.
    quote_ts = (result.get("quote") or {}).get("timestamp")
    result["last_updated"] = quote_ts
    result["computed_at"] = datetime.now(timezone.utc).isoformat()
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

@app.route("/api/investment/<symbol>")
def investment(symbol):
    """SHORT (weeks) + LONG (months) investment views for stocks."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM investment_views WHERE UPPER(symbol)=UPPER(?) ORDER BY date DESC, horizon", (symbol,)).fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = row_to_dict(r)
        if d.get("horizon") not in out:
            out[d.get("horizon")] = d
    return jsonify(out if out else {"error": "no investment views"}), 200 if out else 404


@app.route("/api/news")
def news():
    conn = get_db()
    rows = conn.execute("SELECT * FROM news ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/news/<symbol>")
def symbol_news(symbol):
    conn = get_db()
    rows = conn.execute("SELECT * FROM news WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 20", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/actions/<symbol>")
def symbol_actions():
    """Dividends + splits stored from Yahoo, newest first."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM corporate_actions WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 20", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/company/<symbol>")
def company(symbol):
    """Latest stored company snapshot: info + analyst views + financials keys."""
    conn = get_db()
    row = conn.execute("SELECT * FROM fundamentals WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "no company data"}), 404
    d = row_to_dict(row)
    data = _parse_json_field(d.get("data"), {}) or {}
    return jsonify({
        "symbol": symbol.upper(), "timestamp": d.get("timestamp"),
        "analyst_recommendation": data.get("analyst_recommendation", {}),
        "analyst_price_targets": data.get("analyst_price_targets", {}),
        "earnings_dates": data.get("earnings_dates", []),
        "latest_dividend": data.get("latest_dividend", {}),
        "latest_split": data.get("latest_split", {}),
        "has_financial_statements": any(k.startswith("financials.") or k.startswith("balance_sheet.") or k.startswith("cashflow.") or k == "financial_statements" for k in data.keys()),
        "info": {k: v for k, v in data.items() if not isinstance(v, (dict, list))},
    })

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
