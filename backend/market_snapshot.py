from __future__ import annotations

import json
import os
import sys
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from indicators import calculate_all_indicators

logger = logging.getLogger("tradingai.snapshot")


def get_db():
    from db_schema import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def create_snapshot(
    symbol: str,
    candle_timestamp: str,
    ohlcv: list = None,
    quote: dict = None,
    prev_day_high: float = None,
    prev_day_low: float = None,
    vix: float = None,
    pcr: float = None,
    call_oi: float = None,
    put_oi: float = None,
    regime: str = None,
    data_state: str = "LIVE",
    data_timestamp: str = None,
) -> Optional[dict]:
    try:
        indicators = calculate_all_indicators(ohlcv or [], quote or {})
    except Exception as e:
        logger.error(f"Indicator calc failed for {symbol}: {e}")
        return None

    if not indicators:
        return None

    price_vs_vwap = _price_vs_vwap(
        indicators.get("vwap"), quote.get("close") or quote.get("price")
    )

    trend_state = _classify_trend(
        indicators.get("ema9"), indicators.get("ema21"), indicators.get("ema20"),
        indicators.get("ema200"), quote.get("close"), indicators.get("adx"),
    )

    volatility_state = _classify_volatility(
        indicators.get("atr"), quote.get("close"), indicators.get("bollinger_width"),
        vix, indicators.get("rsi"),
    )

    support_resistance = indicators.get("support_resistance", {})
    if isinstance(support_resistance, str):
        try:
            support_resistance = json.loads(support_resistance)
        except Exception:
            support_resistance = {}

    snapshot = {
        "symbol": symbol,
        "candle_timestamp": candle_timestamp,
        "snapshot_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open": ohlcv[-1].get("open") if ohlcv else None,
        "high": ohlcv[-1].get("high") if ohlcv else None,
        "low": ohlcv[-1].get("low") if ohlcv else None,
        "close": ohlcv[-1].get("close") if ohlcv else None,
        "volume": ohlcv[-1].get("volume") if ohlcv else None,
        "vwap": indicators.get("vwap"),
        "ema9": indicators.get("ema9"),
        "ema21": indicators.get("ema21"),
        "ema20": indicators.get("ema20"),
        "ema200": indicators.get("ema200"),
        "rsi": indicators.get("rsi"),
        "rsi_14": indicators.get("rsi"),
        "macd": indicators.get("macd", {}).get("macd") if isinstance(indicators.get("macd"), dict) else indicators.get("macd"),
        "macd_signal": indicators.get("macd", {}).get("signal") if isinstance(indicators.get("macd"), dict) else None,
        "adx": indicators.get("adx"),
        "atr": indicators.get("atr"),
        "cpr_upper": indicators.get("cpr", {}).get("tc") if isinstance(indicators.get("cpr"), dict) else None,
        "cpr_lower": indicators.get("cpr", {}).get("bc") if isinstance(indicators.get("cpr"), dict) else None,
        "pivot": indicators.get("pivot", {}).get("pivot") if isinstance(indicators.get("pivot"), dict) else None,
        "support": support_resistance.get("support", [None])[0] if support_resistance.get("support") else None,
        "resistance": support_resistance.get("resistance", [None])[0] if support_resistance.get("resistance") else None,
        "prev_day_high": prev_day_high,
        "prev_day_low": prev_day_low,
        "price_vs_vwap": price_vs_vwap,
        "trend_state": trend_state,
        "volatility_state": volatility_state,
        "regime": regime,
        "vix": vix,
        "pcr": pcr,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "expected_move": indicators.get("atr"),
        "max_pain": None,
        "data_state": data_state,
        "data_timestamp": data_timestamp or candle_timestamp,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    conn = get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO market_snapshots_5m
               (symbol, candle_timestamp, snapshot_time, open, high, low, close, volume,
                vwap, ema9, ema21, ema20, ema200, rsi, rsi_14, macd, macd_signal, adx, atr,
                cpr_upper, cpr_lower, pivot, support, resistance, prev_day_high, prev_day_low,
                price_vs_vwap, trend_state, volatility_state, regime, vix, pcr, call_oi, put_oi,
                expected_move, max_pain, data_state, data_timestamp, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                symbol, candle_timestamp, snapshot["snapshot_time"], snapshot["open"],
                snapshot["high"], snapshot["low"], snapshot["close"], snapshot["volume"],
                snapshot["vwap"], snapshot["ema9"], snapshot["ema21"], snapshot["ema20"],
                snapshot["ema200"], snapshot["rsi"], snapshot["rsi_14"], snapshot["macd"],
                snapshot["macd_signal"], snapshot["adx"], snapshot["atr"], snapshot["cpr_upper"],
                snapshot["cpr_lower"], snapshot["pivot"], snapshot["support"], snapshot["resistance"],
                snapshot["prev_day_high"], snapshot["prev_day_low"], snapshot["price_vs_vwap"],
                snapshot["trend_state"], snapshot["volatility_state"], snapshot["regime"],
                snapshot["vix"], snapshot["pcr"], snapshot["call_oi"], snapshot["put_oi"],
                snapshot["expected_move"], snapshot["max_pain"], snapshot["data_state"],
                snapshot["data_timestamp"], snapshot["created_at"],
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        logger.info(f"Snapshot for {symbol} {candle_timestamp} already exists (idempotent)")
    finally:
        conn.close()

    logger.info(f"Snapshot stored for {symbol} at {candle_timestamp}: trend={trend_state}, vwap={price_vs_vwap}")
    return snapshot


def get_latest_snapshot(symbol: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM market_snapshots_5m WHERE symbol=? ORDER BY candle_timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def get_snapshot_history(symbol: str, limit: int = 50) -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM market_snapshots_5m WHERE symbol=? ORDER BY candle_timestamp DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _price_vs_vwap(vwap: float, price: float) -> str:
    if vwap is None or price is None or vwap == 0:
        return "UNKNOWN"
    diff_pct = (price - vwap) / vwap * 100
    if diff_pct > 0.5:
        return "ABOVE"
    elif diff_pct < -0.5:
        return "BELOW"
    return "NEAR"


def _classify_trend(ema9, ema21, ema20, ema200, close, adx) -> str:
    if close is None:
        return "NEUTRAL"
    try:
        close = float(close)
    except (TypeError, ValueError):
        return "NEUTRAL"

    if adx is not None:
        try:
            adx = float(adx)
            if adx < 20:
                return "NEUTRAL"
        except (TypeError, ValueError):
            pass

    emas = []
    for e in (ema9, ema21, ema20, ema200):
        if e is not None:
            try:
                emas.append(float(e))
            except (TypeError, ValueError):
                pass

    if not emas:
        return "NEUTRAL"

    above_count = sum(1 for e in emas if close > e)
    if above_count >= len(emas) * 0.75:
        return "STRONG_UP" if (adx is not None and _safe(adx) > 30) else "UP"
    if above_count == 0:
        return "STRONG_DOWN" if (adx is not None and _safe(adx) > 30) else "DOWN"
    return "NEUTRAL"


def _classify_volatility(atr, close, bollinger_width, vix, rsi) -> str:
    score = 0.0
    if atr is not None:
        try:
            atr_val = float(atr)
            if atr_val > 0 and close is not None:
                ratio = atr_val / float(close) * 100
                if ratio > 1.5:
                    score += 2
                elif ratio > 0.8:
                    score += 1
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    if bollinger_width is not None:
        try:
            bw = float(bollinger_width)
            if bw > 2.0:
                score += 2
            elif bw > 1.0:
                score += 1
        except (TypeError, ValueError):
            pass

    if vix is not None:
        try:
            vix_val = float(vix)
            if vix_val > 20:
                score += 2
            elif vix_val > 15:
                score += 1
        except (TypeError, ValueError):
            pass

    if rsi is not None:
        try:
            rsi_val = float(rsi)
            if rsi_val > 70 or rsi_val < 30:
                score += 1
        except (TypeError, ValueError):
            pass

    if score >= 4:
        return "HIGH"
    if score >= 2:
        return "NORMAL"
    if score > 0:
        return "LOW"
    return "NORMAL"


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default
