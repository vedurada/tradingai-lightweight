from flask import Blueprint, jsonify
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
bp = Blueprint("zerodha_paper_report", __name__)
DB_HLC = "/opt/tradingai/database/tradingai.db"
DB_ZER = "/opt/tradingai/database/zerodha_execution.db"
@bp.route("/api/zerodha-paper/status")
def status():
    return jsonify({"mode":"SHADOW","service":"tradingai-zerodha-paper","market_open":True,"last_update":datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M")})
@bp.route("/api/zerodha-paper/summary")
def summary():
    d = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(DB_HLC)
        hlc = len(conn.execute("SELECT 1 FROM scalp_signals WHERE trade_date=? AND status=TRADED", (d,)).fetchall())
        conn.close()
    except Exception:
        hlc = 0
    try:
        conn = sqlite3.connect(DB_ZER)
        zer = len(conn.execute("SELECT 1 FROM zerodha_paper_trades").fetchall())
        conn.close()
    except Exception:
        zer = 0
    return jsonify({"date_ist":d,"hlc_closed_today":hlc,"zerodha_option_closed_today":zer,"mode":"SHADOW","note":"Real historical data only; SHADOW active"})
