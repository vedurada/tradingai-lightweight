from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db"
)

DATA_READINESS_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "audit", "data_readiness_report.csv"
)

STATUS_AVAILABLE = "AVAILABLE"
STATUS_STALE = "STALE"
STATUS_MISSING = "MISSING"
STATUS_INVALID = "INVALID"
STATUS_UNAVAILABLE = "UNAVAILABLE"

OVERALL_READY = "READY"
OVERALL_LIMITED = "LIMITED"
OVERALL_UNAVAILABLE = "UNAVAILABLE"

STALE_THRESHOLDS_MINUTES: Dict[str, int] = {
    "price": 30,
    "1m": 10,
    "5m": 30,
    "vwap": 60,
    "vix": 60,
    "oi": 1440,
    "oi_change": 1440,
    "options_chain": 1440,
    "iv": 1440,
    "pcr": 1440,
    "ema": 60,
    "rsi": 60,
    "adx": 60,
    "cpr": 60,
    "market_structure": 1440,
    "positioning": 1440,
    "market_intent": 1440,
}

CRITICAL_FIELDS = [
    "price",
    "1m",
    "5m",
    "vwap",
    "rsi",
    "adx",
]


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _minutes_since(ts: Any, now: datetime) -> Optional[float]:
    dt = _parse_timestamp(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 60.0


def _fetchone(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, params).fetchone()


def _fetchall(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = _fetchone(
        conn,
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    if row is None:
        return False
    return row[0] > 0


def _get_latest_timestamp(conn: sqlite3.Connection, table: str, symbol_col: str = "symbol", symbol: str = "NIFTY") -> Optional[str]:
    if not _table_exists(conn, table):
        return None
    sql = f"SELECT MAX(timestamp) FROM [{table}]"
    if symbol_col:
        sql += f" WHERE {symbol_col} = ?"
        row = _fetchone(conn, sql, (symbol,))
    else:
        row = _fetchone(conn, sql)
    if row is None or row[0] is None:
        return None
    return row[0]


def _check_price(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT price, volume, timestamp FROM live_quotes WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    price = row["price"]
    ts = row["timestamp"]
    age = _minutes_since(ts, now)
    if price is None or price <= 0:
        return {"status": STATUS_INVALID, "value": price, "timestamp": ts, "age_minutes": age}
    threshold = STALE_THRESHOLDS_MINUTES.get("price", 30)
    if age is not None and age > threshold * 2:
        return {"status": STATUS_UNAVAILABLE, "value": price, "timestamp": ts, "age_minutes": age}
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": price, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": price, "timestamp": ts, "age_minutes": age}


def _check_1m_data(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    latest_ts = _get_latest_timestamp(conn, "price_1m", "symbol", symbol)
    if latest_ts is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    age = _minutes_since(latest_ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("1m", 10)
    if age is not None and age > threshold * 2:
        return {"status": STATUS_UNAVAILABLE, "value": None, "timestamp": latest_ts, "age_minutes": age}
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": None, "timestamp": latest_ts, "age_minutes": age}
    record_count = _fetchone(
        conn, "SELECT COUNT(*) FROM price_1m WHERE symbol = ? AND volume > 0", (symbol,)
    )
    if record_count and record_count[0] == 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "value": None,
            "timestamp": latest_ts,
            "age_minutes": age,
            "note": "volume_zero_for_index",
        }
    return {"status": STATUS_AVAILABLE, "value": None, "timestamp": latest_ts, "age_minutes": age}


def _check_5m_data(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    latest_ts = _get_latest_timestamp(conn, "price_5m", "symbol", symbol)
    if latest_ts is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    age = _minutes_since(latest_ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("5m", 30)
    if age is not None and age > threshold * 2:
        return {"status": STATUS_UNAVAILABLE, "value": None, "timestamp": latest_ts, "age_minutes": age}
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": None, "timestamp": latest_ts, "age_minutes": age}
    record_count = _fetchone(
        conn, "SELECT COUNT(*) FROM price_5m WHERE symbol = ? AND volume > 0", (symbol,)
    )
    if record_count and record_count[0] == 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "value": None,
            "timestamp": latest_ts,
            "age_minutes": age,
            "note": "volume_zero_for_index",
        }
    return {"status": STATUS_AVAILABLE, "value": None, "timestamp": latest_ts, "age_minutes": age}


def _check_vwap(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT vwap, timestamp FROM indicators WHERE symbol = ? AND vwap > 0 ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        row = _fetchone(
            conn,
            "SELECT vwap, timestamp FROM indicators WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        if row is None or row["vwap"] is None:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        if row["vwap"] == 0:
            return {"status": STATUS_INVALID, "value": 0.0, "timestamp": row["timestamp"], "age_minutes": _minutes_since(row["timestamp"], now)}
    age = _minutes_since(row["timestamp"], now)
    threshold = STALE_THRESHOLDS_MINUTES.get("vwap", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": row["vwap"], "timestamp": row["timestamp"], "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": row["vwap"], "timestamp": row["timestamp"], "age_minutes": age}


def _check_volume(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT volume, timestamp FROM live_quotes WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    volume = row["volume"]
    age = _minutes_since(row["timestamp"], now)
    if volume == 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "value": 0,
            "timestamp": row["timestamp"],
            "age_minutes": age,
            "note": "indices_do_not_have_volume",
        }
    if volume is None:
        return {"status": STATUS_INVALID, "value": None, "timestamp": row["timestamp"], "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": volume, "timestamp": row["timestamp"], "age_minutes": age}


def _check_oi(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT open_interest, fetched_at FROM oi_top_strikes WHERE symbol = ? ORDER BY fetched_at DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    oi = row["open_interest"]
    ts = row["fetched_at"]
    age = _minutes_since(ts, now)
    if oi is None or oi <= 0:
        return {"status": STATUS_INVALID, "value": oi, "timestamp": ts, "age_minutes": age}
    threshold = STALE_THRESHOLDS_MINUTES.get("oi", 1440)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": oi, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": oi, "timestamp": ts, "age_minutes": age}


def _check_oi_change(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT change_in_oi, fetched_at FROM option_chain WHERE symbol = ? AND change_in_oi IS NOT NULL ORDER BY fetched_at DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    oi_change = row["change_in_oi"]
    ts = row["fetched_at"]
    age = _minutes_since(ts, now)
    if oi_change is None:
        return {"status": STATUS_INVALID, "value": None, "timestamp": ts, "age_minutes": age}
    threshold = STALE_THRESHOLDS_MINUTES.get("oi_change", 1440)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": oi_change, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": oi_change, "timestamp": ts, "age_minutes": age}


def _check_options_chain(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT COUNT(*) as cnt, MAX(fetched_at) as last_fetch FROM option_chain WHERE symbol = ?",
        (symbol,),
    )
    if row is None or row[0] == 0:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    cnt = row[0]
    last_fetch = row[1]
    age = _minutes_since(last_fetch, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("options_chain", 1440)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": cnt, "timestamp": last_fetch, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": cnt, "timestamp": last_fetch, "age_minutes": age}


def _check_iv(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT COUNT(*) as total, SUM(CASE WHEN implied_volatility IS NOT NULL AND implied_volatility > 0 THEN 1 ELSE 0 END) as valid_iv FROM option_chain WHERE symbol = ?",
        (symbol,),
    )
    if row is None or row[0] == 0:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    total = row[0]
    valid_iv = row[1] or 0
    if valid_iv == 0:
        return {
            "status": STATUS_INVALID,
            "value": None,
            "timestamp": None,
            "age_minutes": None,
            "note": f"all_IV_null_out_of_{total}",
        }
    last_iv_row = _fetchone(
        conn,
        "SELECT implied_volatility, fetched_at FROM option_chain WHERE symbol = ? AND implied_volatility IS NOT NULL AND implied_volatility > 0 ORDER BY fetched_at DESC LIMIT 1",
        (symbol,),
    )
    if last_iv_row:
        age = _minutes_since(last_iv_row["fetched_at"], now)
        threshold = STALE_THRESHOLDS_MINUTES.get("iv", 1440)
        if age is not None and age > threshold:
            return {"status": STATUS_STALE, "value": last_iv_row["implied_volatility"], "timestamp": last_iv_row["fetched_at"], "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": valid_iv, "timestamp": None, "age_minutes": None}


def _check_pcr(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT pcr, date, pe_oi, ce_oi FROM pcr_history WHERE symbol = ? ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    pcr = row["pcr"]
    date_str = row["date"]
    pe_oi = row["pe_oi"]
    ce_oi = row["ce_oi"]
    if pcr is None:
        return {"status": STATUS_INVALID, "value": None, "timestamp": date_str, "age_minutes": None}
    ref_ts = f"{date_str} 15:30:00+00:00"
    age = _minutes_since(ref_ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("pcr", 1440)
    if age is not None and age > threshold * 2:
        return {"status": STATUS_UNAVAILABLE, "value": pcr, "timestamp": date_str, "age_minutes": age}
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": pcr, "timestamp": date_str, "age_minutes": age, "note": "pcr_is_eod_data"}
    return {"status": STATUS_AVAILABLE, "value": pcr, "timestamp": date_str, "age_minutes": age}


def _check_vix(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT close, timestamp FROM vix_data ORDER BY timestamp DESC LIMIT 1",
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    vix = row["close"]
    ts = row["timestamp"]
    age = _minutes_since(ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("vix", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": vix, "timestamp": ts, "age_minutes": age}
    if vix is None or vix <= 0:
        return {"status": STATUS_INVALID, "value": vix, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": vix, "timestamp": ts, "age_minutes": age}


def _check_ema(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT ema20, ema50, ema100, ema200, timestamp FROM indicators WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    ema20 = row["ema20"]
    ema50 = row["ema50"]
    ema100 = row["ema100"]
    ema200 = row["ema200"]
    ts = row["timestamp"]
    age = _minutes_since(ts, now)
    has_valid = (ema20 is not None and ema20 > 0) or (ema50 is not None and ema50 > 0)
    has_invalid = (ema100 is not None and ema100 == 0) or (ema200 is not None and ema200 == 0)
    if not has_valid and not has_invalid:
        return {"status": STATUS_MISSING, "value": None, "timestamp": ts, "age_minutes": age}
    if has_invalid:
        return {
            "status": STATUS_INVALID,
            "value": {"ema20": ema20, "ema50": ema50, "ema100": ema100, "ema200": ema200},
            "timestamp": ts,
            "age_minutes": age,
            "note": "ema100_200_zero_for_index",
        }
    threshold = STALE_THRESHOLDS_MINUTES.get("ema", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": {"ema20": ema20, "ema50": ema50}, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": {"ema20": ema20, "ema50": ema50}, "timestamp": ts, "age_minutes": age}


def _check_rsi(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT rsi, timestamp FROM indicators WHERE symbol = ? AND rsi IS NOT NULL AND rsi > 0 ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        row = _fetchone(
            conn,
            "SELECT rsi, timestamp FROM indicators WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        if row is None or row["rsi"] is None:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        if row["rsi"] == 0:
            return {"status": STATUS_INVALID, "value": 0.0, "timestamp": row["timestamp"], "age_minutes": _minutes_since(row["timestamp"], now)}
    age = _minutes_since(row["timestamp"], now)
    threshold = STALE_THRESHOLDS_MINUTES.get("rsi", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": row["rsi"], "timestamp": row["timestamp"], "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": row["rsi"], "timestamp": row["timestamp"], "age_minutes": age}


def _check_adx(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT adx, timestamp FROM indicators WHERE symbol = ? AND adx IS NOT NULL AND adx > 0 ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        row = _fetchone(
            conn,
            "SELECT adx, timestamp FROM indicators WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        if row is None or row["adx"] is None:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        if row["adx"] == 0:
            return {"status": STATUS_INVALID, "value": 0.0, "timestamp": row["timestamp"], "age_minutes": _minutes_since(row["timestamp"], now)}
    age = _minutes_since(row["timestamp"], now)
    threshold = STALE_THRESHOLDS_MINUTES.get("adx", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": row["adx"], "timestamp": row["timestamp"], "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": row["adx"], "timestamp": row["timestamp"], "age_minutes": age}


def _check_cpr(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT cpr_classification, timestamp FROM indicators WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    cpr = row["cpr_classification"]
    ts = row["timestamp"]
    age = _minutes_since(ts, now)
    if not cpr or cpr.strip() == "":
        return {"status": STATUS_INVALID, "value": None, "timestamp": ts, "age_minutes": age}
    threshold = STALE_THRESHOLDS_MINUTES.get("cpr", 60)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": cpr, "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": cpr, "timestamp": ts, "age_minutes": age}


def _check_market_structure(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT market_structure, date FROM history WHERE symbol = ? AND market_structure IS NOT NULL AND market_structure != '' ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        row = _fetchone(
            conn,
            "SELECT bullish_trigger, timestamp FROM scenarios WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        if row is None or not row["bullish_trigger"]:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        ts = row["timestamp"]
        age = _minutes_since(ts, now)
        threshold = STALE_THRESHOLDS_MINUTES.get("market_structure", 1440)
        if age is not None and age > threshold:
            return {"status": STATUS_STALE, "value": row["bullish_trigger"], "timestamp": ts, "age_minutes": age}
        return {"status": STATUS_AVAILABLE, "value": row["bullish_trigger"], "timestamp": ts, "age_minutes": age}
    date_str = row["date"]
    ms = row["market_structure"]
    ref_ts = f"{date_str} 15:30:00+00:00"
    age = _minutes_since(ref_ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("market_structure", 1440)
    if age is not None and age > threshold * 2:
        return {"status": STATUS_UNAVAILABLE, "value": ms, "timestamp": date_str, "age_minutes": age}
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": ms, "timestamp": date_str, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": ms, "timestamp": date_str, "age_minutes": age}


def _check_liquidity(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT volume FROM live_quotes WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
    volume = row["volume"]
    if volume == 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "value": 0,
            "timestamp": None,
            "age_minutes": None,
            "note": "indices_do_not_have_volume",
        }
    if volume is None:
        return {"status": STATUS_INVALID, "value": None, "timestamp": None, "age_minutes": None}
    return {"status": STATUS_AVAILABLE, "value": volume, "timestamp": None, "age_minutes": None}


def _check_positioning(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT total_oi, date FROM pcr_history WHERE symbol = ? ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        oi_row = _fetchone(
            conn,
            "SELECT open_interest FROM oi_top_strikes WHERE symbol = ? ORDER BY fetched_at DESC LIMIT 1",
            (symbol,),
        )
        if oi_row is None:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        return {"status": STATUS_AVAILABLE, "value": oi_row["open_interest"], "timestamp": None, "age_minutes": None}
    total_oi = row["total_oi"]
    date_str = row["date"]
    if total_oi is None or total_oi <= 0:
        return {"status": STATUS_INVALID, "value": total_oi, "timestamp": date_str, "age_minutes": None}
    ref_ts = f"{date_str} 15:30:00+00:00"
    age = _minutes_since(ref_ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("positioning", 1440)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": total_oi, "timestamp": date_str, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": total_oi, "timestamp": date_str, "age_minutes": age}


def _check_market_intent(conn: sqlite3.Connection, symbol: str, now: datetime) -> Dict[str, Any]:
    row = _fetchone(
        conn,
        "SELECT payload, created_at FROM market_outlooks WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
        (symbol,),
    )
    if row is None:
        row = _fetchone(
            conn,
            "SELECT timestamp, outlook FROM ai_outlooks WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        if row is None or not row["outlook"]:
            return {"status": STATUS_MISSING, "value": None, "timestamp": None, "age_minutes": None}
        ts = row["timestamp"]
        age = _minutes_since(ts, now)
        threshold = STALE_THRESHOLDS_MINUTES.get("market_intent", 1440)
        if age is not None and age > threshold:
            return {"status": STATUS_STALE, "value": row["outlook"], "timestamp": ts, "age_minutes": age}
        return {"status": STATUS_AVAILABLE, "value": row["outlook"], "timestamp": ts, "age_minutes": age}
    ts = row["created_at"]
    age = _minutes_since(ts, now)
    threshold = STALE_THRESHOLDS_MINUTES.get("market_intent", 1440)
    if age is not None and age > threshold:
        return {"status": STATUS_STALE, "value": row["payload"], "timestamp": ts, "age_minutes": age}
    return {"status": STATUS_AVAILABLE, "value": row["payload"], "timestamp": ts, "age_minutes": age}


FIELD_CHECKERS = {
    "price": _check_price,
    "1m": _check_1m_data,
    "5m": _check_5m_data,
    "vwap": _check_vwap,
    "volume": _check_volume,
    "oi": _check_oi,
    "oi_change": _check_oi_change,
    "options_chain": _check_options_chain,
    "iv": _check_iv,
    "pcr": _check_pcr,
    "vix": _check_vix,
    "ema": _check_ema,
    "rsi": _check_rsi,
    "adx": _check_adx,
    "cpr": _check_cpr,
    "market_structure": _check_market_structure,
    "liquidity": _check_liquidity,
    "positioning": _check_positioning,
    "market_intent": _check_market_intent,
}


def evaluate_readiness(symbol: str, db_path: str = DEFAULT_DB_PATH, now: Optional[datetime] = None) -> Dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)

    if not symbol:
        raise ValueError("symbol must be a non-empty string")

    if not os.path.exists(db_path):
        return {
            "symbol": symbol,
            "timestamp": now.isoformat(),
            "fields": {field: {"status": STATUS_UNAVAILABLE, "value": None, "timestamp": None, "age_minutes": None, "note": "db_not_found"} for field in FIELD_CHECKERS},
            "overall": OVERALL_UNAVAILABLE,
            "data_quality": "DB_NOT_FOUND",
            "db_path": db_path,
            "data_readiness_csv": DATA_READINESS_CSV_PATH,
        }

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return {
            "symbol": symbol,
            "timestamp": now.isoformat(),
            "fields": {field: {"status": STATUS_UNAVAILABLE, "value": None, "timestamp": None, "age_minutes": None, "note": f"db_error: {e}"} for field in FIELD_CHECKERS},
            "overall": OVERALL_UNAVAILABLE,
            "data_quality": "DB_ERROR",
            "db_path": db_path,
            "data_readiness_csv": DATA_READINESS_CSV_PATH,
        }

    try:
        fields: Dict[str, Dict[str, Any]] = {}
        for field_name, checker in FIELD_CHECKERS.items():
            try:
                fields[field_name] = checker(conn, symbol, now)
            except sqlite3.Error:
                fields[field_name] = {
                    "status": STATUS_UNAVAILABLE,
                    "value": None,
                    "timestamp": None,
                    "age_minutes": None,
                    "note": "query_error",
                }

        overall = _compute_overall(fields, symbol)
        data_quality = get_data_quality_label(fields)
        latest_timestamp = _find_latest_timestamp(fields)

        result: Dict[str, Any] = {
            "symbol": symbol,
            "timestamp": now.isoformat(),
            "fields": fields,
            "overall": overall,
            "data_quality": data_quality,
            "db_path": db_path,
            "data_readiness_csv": DATA_READINESS_CSV_PATH,
        }
        if latest_timestamp:
            result["latest_data_timestamp"] = latest_timestamp
        return result
    finally:
        conn.close()


def _find_latest_timestamp(fields: Dict[str, Dict[str, Any]]) -> Optional[str]:
    latest: Optional[str] = None
    for field_data in fields.values():
        ts = field_data.get("timestamp")
        if ts:
            if latest is None or ts > latest:
                latest = ts
    return latest


def _compute_overall(fields: Dict[str, Dict[str, Any]], symbol: str) -> str:
    statuses = [f["status"] for f in fields.values()]

    unavailable_count = sum(1 for s in statuses if s == STATUS_UNAVAILABLE)
    missing_count = sum(1 for s in statuses if s == STATUS_MISSING)
    invalid_count = sum(1 for s in statuses if s == STATUS_INVALID)
    stale_count = sum(1 for s in statuses if s == STATUS_STALE)

    if missing_count == len(statuses):
        return OVERALL_UNAVAILABLE

    for field in CRITICAL_FIELDS:
        if fields.get(field, {}).get("status") in (STATUS_MISSING, STATUS_UNAVAILABLE):
            if unavailable_count > len(statuses) // 2 or missing_count > len(statuses) // 2:
                return OVERALL_UNAVAILABLE
            return OVERALL_LIMITED

    if unavailable_count > 3:
        return OVERALL_UNAVAILABLE

    if unavailable_count > 0 or invalid_count > 2 or stale_count > 3:
        return OVERALL_LIMITED

    if stale_count > 0 or invalid_count > 0:
        return OVERALL_LIMITED

    return OVERALL_READY


def get_data_quality_label(fields: Dict[str, Dict[str, Any]]) -> str:
    statuses = {k: v["status"] for k, v in fields.items()}

    unavailable_fields = [k for k, s in statuses.items() if s == STATUS_UNAVAILABLE]
    invalid_fields = [k for k, s in statuses.items() if s == STATUS_INVALID]
    stale_fields = [k for k, s in statuses.items() if s == STATUS_STALE]
    missing_fields = [k for k, s in statuses.items() if s == STATUS_MISSING]

    parts: List[str] = []

    if unavailable_fields:
        if "volume" in unavailable_fields:
            parts.append("VOLUME_UNAVAILABLE")
        if "liquidity" in unavailable_fields:
            parts.append("LIQUIDITY_UNAVAILABLE")

    if invalid_fields:
        if "iv" in invalid_fields:
            parts.append("NO_IV")
        if "oi_change" in invalid_fields:
            parts.append("NO_OI_CHANGE")

    if "options_chain" in unavailable_fields or "options_chain" in missing_fields:
        parts.append("NO_FUTURES")

    if "oi" in unavailable_fields or "oi" in missing_fields:
        parts.append("NO_OI")

    if "pcr" in stale_fields:
        parts.append("PCR_STALE")

    if not parts:
        has_stale = len(stale_fields) > 0
        has_invalid = len(invalid_fields) > 0
        if not has_stale and not has_invalid:
            return "ADEQUATE"
        if has_stale and not has_invalid:
            return "LIMITED_STALE"
        if has_invalid and not has_stale:
            return "LIMITED_INVALID"
        return "LIMITED_STALE_INVALID"

    return "_".join(parts)


def write_readiness_csv(readiness_result: Dict[str, Any], csv_path: Optional[str] = None) -> str:
    if csv_path is None:
        csv_path = DATA_READINESS_CSV_PATH

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    fields = readiness_result.get("fields", {})
    header = [
        "symbol", "field", "status", "value", "timestamp",
        "age_minutes", "note", "evaluation_timestamp", "overall", "data_quality",
    ]

    file_exists = os.path.exists(csv_path)
    mode = "a" if file_exists else "w"

    with open(csv_path, mode, newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header)
        for field_name, field_data in fields.items():
            writer.writerow([
                readiness_result.get("symbol", ""),
                field_name,
                field_data.get("status", ""),
                str(field_data.get("value", "")) if field_data.get("value") is not None else "",
                field_data.get("timestamp", "") or "",
                field_data.get("age_minutes", "") if field_data.get("age_minutes") is not None else "",
                field_data.get("note", "") or "",
                readiness_result.get("timestamp", ""),
                readiness_result.get("overall", ""),
                readiness_result.get("data_quality", ""),
            ])

    return csv_path
