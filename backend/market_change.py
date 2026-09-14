from __future__ import annotations

import json
import os
import sys
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_schema import DB_PATH

logger = logging.getLogger("tradingai.market_change")

REGIMES = {"BULLISH", "BEARISH", "SIDEWAYS", "HIGH_VOLATILITY", "UNKNOWN"}

MATERIAL_THRESHOLDS = {
    "regime_change": True,
    "confidence_swing": 15.0,
    "vix_move_points": 5.0,
    "price_move_pct": 1.0,
    "bias_reversal": True,
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_state(conn: sqlite3.Connection, symbol: str) -> dict:
    reg = conn.execute(
        "SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    ind = conn.execute(
        "SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    vix = conn.execute(
        "SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    price = conn.execute(
        "SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    ).fetchone()

    regime = {}
    if reg:
        reg = dict(reg)
        regime = {
            "regime": reg["regime"],
            "confidence": reg["confidence"],
            "trend": reg.get("trend"),
            "momentum": reg.get("momentum"),
            "volatility": reg.get("volatility"),
            "breadth": reg.get("breadth"),
            "vix_regime": reg.get("vix_regime"),
            "timestamp": reg["timestamp"],
        }

    indicators = {}
    if ind:
        ind = dict(ind)
        indicators = {
            "rsi": ind.get("rsi"),
            "macd": ind.get("macd"),
            "adx": ind.get("adx"),
            "volume": ind.get("volume"),
        }

    vix_data = {}
    if vix:
        vix = dict(vix)
        vix_data = {
            "close": vix.get("close"),
            "change": vix.get("change"),
            "change_pct": vix.get("change_pct"),
            "timestamp": vix.get("timestamp"),
        }

    price_data = {}
    if price:
        price = dict(price)
        price_data = {
            "close": price.get("close"),
            "change_pct": price.get("change_pct"),
            "timestamp": price.get("timestamp"),
        }

    return {
        "symbol": symbol,
        "regime": regime,
        "indicators": indicators,
        "vix": vix_data,
        "price": price_data,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }


def get_previous_snapshot(conn: sqlite3.Connection, symbol: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM market_change_snapshots WHERE symbol=? ORDER BY captured_at DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row:
        row = dict(row)
        if isinstance(row.get("state"), str):
            try:
                row["state"] = json.loads(row["state"])
            except (json.JSONDecodeError, TypeError):
                pass
        return row
    return None
    if row:
        row = dict(row)
        if isinstance(row.get("state"), str):
            try:
                row["state"] = json.loads(row["state"])
            except (json.JSONDecodeError, TypeError):
                pass
        return row
    return None


def is_material_change(current: dict, previous: Optional[dict]) -> dict:
    if previous is None:
        return {"material": True, "reason": "initial_snapshot", "changes": []}

    changes = []
    prev_state = previous.get("state", previous)
    cur_regime = (current.get("regime") or {}).get("regime")
    prev_regime = (prev_state.get("regime") or {}).get("regime")
    cur_bias = (current.get("regime") or {}).get("trend")
    prev_bias = (prev_state.get("regime") or {}).get("trend")
    cur_conf = (current.get("regime") or {}).get("confidence")
    prev_conf = (prev_state.get("regime") or {}).get("confidence")
    cur_vix = (current.get("vix") or {}).get("close")
    prev_vix = (prev_state.get("vix") or {}).get("close")
    cur_price = (current.get("price") or {}).get("close")
    prev_price = (prev_state.get("price") or {}).get("close")
    cur_price_pct = (current.get("price") or {}).get("change_pct")

    if cur_regime and prev_regime and cur_regime != prev_regime:
        changes.append({
            "type": "regime_change",
            "from": prev_regime,
            "to": cur_regime,
            "severity": "high",
        })

    if cur_bias and prev_bias and cur_bias != prev_bias:
        if cur_bias.upper() in ("BULLISH", "BEARISH") and prev_bias.upper() in ("BULLISH", "BEARISH"):
            if cur_bias.upper() != prev_bias.upper():
                changes.append({
                    "type": "bias_reversal",
                    "from": prev_bias,
                    "to": cur_bias,
                    "severity": "high",
                })

    if cur_conf is not None and prev_conf is not None:
        swing = abs(cur_conf - prev_conf)
        if swing >= MATERIAL_THRESHOLDS["confidence_swing"]:
            changes.append({
                "type": "confidence_swing",
                "from": prev_conf,
                "to": cur_conf,
                "swing": swing,
                "severity": "medium" if swing < 25 else "high",
            })

    if cur_vix is not None and prev_vix is not None:
        vix_move = abs(cur_vix - prev_vix)
        if vix_move >= MATERIAL_THRESHOLDS["vix_move_points"]:
            changes.append({
                "type": "vix_move",
                "from": prev_vix,
                "to": cur_vix,
                "move_points": round(vix_move, 2),
                "severity": "medium" if vix_move < 8 else "high",
            })

    if cur_price_pct is not None and abs(cur_price_pct) >= MATERIAL_THRESHOLDS["price_move_pct"]:
        changes.append({
            "type": "price_move",
            "change_pct": cur_price_pct,
            "severity": "medium" if abs(cur_price_pct) < 2 else "high",
        })

    material = len(changes) > 0
    return {"material": material, "reason": "threshold_exceeded" if material else "no_significant_change", "changes": changes}


def store_snapshot(conn: sqlite3.Connection, symbol: str, state: dict, material: bool, changes: list) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn.execute(
        """INSERT INTO market_change_snapshots (symbol, captured_at, state, material_change, changes)
           VALUES (?,?,?,?,?)""",
        (symbol, ts, json.dumps(state), int(material), json.dumps(changes)),
    )
    conn.commit()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn.execute(
        "DELETE FROM market_change_snapshots WHERE symbol=? AND captured_at < ?",
        (symbol, cutoff),
    )
    conn.commit()


def analyze(symbol: str = "NIFTY") -> dict:
    conn = get_conn()
    try:
        current = get_current_state(conn, symbol)
        previous = get_previous_snapshot(conn, symbol)
        result = is_material_change(current, previous)
        store_snapshot(conn, symbol, current, result["material"], result["changes"])
        prev_display = None
        if previous:
            ps = previous.get("state", previous)
            if isinstance(ps, dict):
                prev_display = {k: ps.get(k) for k in ("regime", "price", "vix")}
        return {
            "symbol": symbol,
            "material": result["material"],
            "reason": result["reason"],
            "changes": result["changes"],
            "current": {k: current[k] for k in ("regime", "price", "vix")},
            "previous": prev_display,
            "captured_at": current["captured_at"],
        }
    finally:
        conn.close()


def should_regenerate_ai(symbol: str = "NIFTY", max_age_minutes: int = 120) -> dict:
    conn = get_conn()
    try:
        current = get_current_state(conn, symbol)
        previous = get_previous_snapshot(conn, symbol)
        result = is_material_change(current, previous)

        age_ok = False
        outlook_ts = None
        row = conn.execute(
            "SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row:
            outlook_ts = dict(row)["timestamp"]
            try:
                outlook_dt = datetime.fromisoformat(outlook_ts.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - outlook_dt).total_seconds() / 60
                age_ok = age >= max_age_minutes
            except (ValueError, TypeError):
                age_ok = True
        else:
            age_ok = True

        regen = result["material"] or age_ok
        return {
            "symbol": symbol,
            "regenerate": regen,
            "reason": "material_change" if result["material"] else ("max_age_exceeded" if age_ok else "no_change"),
            "material_changes": result["changes"],
            "ai_outlook_age_minutes": round((datetime.now(timezone.utc) - datetime.fromisoformat(outlook_ts.replace("Z", "+00:00"))).total_seconds() / 60) if outlook_ts else None,
            "max_age_minutes": max_age_minutes,
            "captured_at": current["captured_at"],
        }
    finally:
        conn.close()
