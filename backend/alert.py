from __future__ import annotations

import json
import logging
import os
import sys
import smtplib
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

logger = logging.getLogger("tradingai.alert")

ALERT_LOG = "/opt/tradingai/logs/alerts.log"

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
    return all_alerts

if __name__ == "__main__":
    check_all_alerts()