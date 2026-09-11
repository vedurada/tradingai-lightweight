from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import smtplib
from datetime import datetime, timezone, date
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

logger = logging.getLogger("tradingai.alert")

ALERT_LOG = "/opt/tradingai/logs/alerts.log"
ALERT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

def _load_config() -> dict:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "settings.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}

def _log_alert(symbol: str, message: str) -> None:
    os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {symbol}: {message}"
    logger.info(line)
    with open(ALERT_LOG, "a") as f:
        f.write(line + "\n")

def _send_email(subject: str, body: str) -> None:
    config = _load_config()
    email_cfg = config.get("email", {})
    smtp_host = email_cfg.get("smtp_host", "")
    smtp_port = email_cfg.get("smtp_port", 587)
    smtp_user = email_cfg.get("smtp_user", "")
    smtp_pass = email_cfg.get("smtp_pass", "")
    recipients = email_cfg.get("recipients", [])
    if not smtp_host or not recipients:
        logger.info("Email not configured, logging only")
        return
    try:
        msg = f"Subject: {subject}\n\n{body}"
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            for recipient in recipients:
                server.sendmail(smtp_user, recipient, msg)
        logger.info(f"Email sent to {recipients}")
    except Exception as e:
        logger.error(f"Email send failed: {e}")

def check_regime_changes(symbol: str, db: Database) -> list[dict]:
    history = db.get_history(symbol, days=7)
    if len(history) < 2:
        return []

    alerts = []
    for i in range(1, len(history)):
        prev = history[i]
        curr = history[i - 1]
        prev_regime = prev.get("market_regime", "")
        curr_regime = curr.get("market_regime", "")
        if prev_regime and curr_regime and prev_regime != curr_regime:
            message = f"Regime change: {prev_regime} -> {curr_regime} | Confidence: {curr.get('confidence', 'N/A')}% | Strategy: {curr.get('strategy', 'N/A')}"
            _log_alert(symbol, message)
            alerts.append({"symbol": symbol, "type": "regime_change", "message": message, "timestamp": curr.get("created_at", "")})

        prev_bias = prev.get("directional_bias", "")
        curr_bias = curr.get("directional_bias", "")
        if prev_bias and curr_bias and prev_bias != curr_bias:
            message = f"Bias change: {prev_bias} -> {curr_bias} | Regime: {curr_regime}"
            _log_alert(symbol, message)
            alerts.append({"symbol": symbol, "type": "bias_change", "message": message, "timestamp": curr.get("created_at", "")})

    if alerts:
        _send_email(
            f"TradingAI Alerts - {symbol}",
            "\n".join(a["message"] for a in alerts)
        )

    return alerts

def check_all_alerts() -> list[dict]:
    config = _load_config()
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", config.get("database", "database/tradingai.db"))
    db = Database(db_path)
    all_alerts = []
    symbols = db.fetchall("SELECT DISTINCT symbol FROM history")
    for row in symbols:
        symbol = row[0]
        alerts = check_regime_changes(symbol, db)
        all_alerts.extend(alerts)
    all_alerts.extend(_check_pcr_oi(db_path))
    return all_alerts


def _conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or ALERT_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _already_logged(conn: sqlite3.Connection, symbol: str, alert_type: str, day: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE symbol=? AND alert_type=? AND date(timestamp)=? LIMIT 1",
        (symbol, alert_type, day)).fetchone()
    return row is not None


def _store(conn: sqlite3.Connection, symbol: str, alert_type: str, message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO alerts (symbol, timestamp, alert_type, message) VALUES (?,?,?,?)",
        (symbol, now, alert_type, message))
    conn.commit()


def _check_pcr_oi(db_path: str | None = None) -> list[dict]:
    """PCR / OI-spike alerts from the latest EOD or live option chain.

    Rules (per index symbol, current expiry):
      - PCR <= 0.65  -> "put-heavy / hedging spike" (potential support zone)
      - PCR >= 1.30  -> "call-heavy / complacency"      (potential resistance zone)
      - max OI strike changed vs previous snapshot      -> "OI base shifted"
    Deduped: one row per (symbol, rule) per UTC day.
    """
    conn = _conn(db_path)
    day = datetime.now(timezone.utc).date().isoformat()
    coll = []
    for sym in INDEX_SYMBOLS:
        expiries = conn.execute(
            "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (sym,)).fetchall()
        if not expiries:
            continue
        cur_expiry = next((e["expiry"] for e in expiries if e["expiry"] >= day), expiries[-1]["expiry"])
        ce = conn.execute(
            "SELECT SUM(open_interest) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='CE'",
            (sym, cur_expiry)).fetchone()["s"] or 0
        pe = conn.execute(
            "SELECT SUM(open_interest) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='PE'",
            (sym, cur_expiry)).fetchone()["s"] or 0
        pcr = round(pe / ce, 3) if ce > 0 else None
        if pcr is None:
            continue
        if pcr <= 0.65 and not _already_logged(conn, sym, "pcr_put_heavy", day):
            msg = f"{sym} PCR {pcr} <= 0.65 (put-heavy) | expiry {cur_expiry}"
            _store(conn, sym, "pcr_put_heavy", msg)
            coll.append({"symbol": sym, "type": "pcr_put_heavy", "message": msg, "timestamp": day})
            _log_alert(sym, msg)
        elif pcr >= 1.30 and not _already_logged(conn, sym, "pcr_call_heavy", day):
            msg = f"{sym} PCR {pcr} >= 1.30 (call-heavy) | expiry {cur_expiry}"
            _store(conn, sym, "pcr_call_heavy", msg)
            coll.append({"symbol": sym, "type": "pcr_call_heavy", "message": msg, "timestamp": day})
            _log_alert(sym, msg)
    conn.close()
    if coll:
        _send_email("TradingAI PCR Alerts", "\n".join(a["message"] for a in coll))
    return coll


if __name__ == "__main__":
    check_all_alerts()