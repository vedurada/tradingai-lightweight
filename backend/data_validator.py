"""Data quality validation infrastructure.

Detects:
- stale data
- missing timestamps
- duplicate records
- invalid prices (zero/negative)
- impossible OHLC relationships
- missing required fields
- unexpected future timestamps
- timestamp timezone inconsistencies

Does NOT automatically delete bad data.
Flags/quarantines/documents it.
"""
import datetime
import sqlite3
from typing import Dict, List, Optional

DATA_QUALITY_LIVE = "LIVE"
DATA_QUALITY_STALE = "STALE"
DATA_QUALITY_UNAVAILABLE = "DATA UNAVAILABLE"
DATA_QUALITY_PARTIAL = "PARTIAL"
DATA_QUALITY_INVALID = "INVALID"


class DataValidator:
    def __init__(self, db_path: str, now: Optional[datetime.datetime] = None):
        self.db_path = db_path
        self.now = now or datetime.datetime.utcnow()
        self.issues: List[Dict] = []

    def validate_price_record(self, record: Dict, table: str = "") -> List[str]:
        """Validate a single price record. Returns list of issues."""
        issues = []
        required = ["timestamp", "open", "high", "low", "close"]
        for field in required:
            if field not in record or record[field] is None:
                issues.append(f"missing_{field}")

        if "timestamp" in record and record["timestamp"]:
            try:
                ts = record["timestamp"]
                if isinstance(ts, str):
                    ts = ts.replace("Z", "+00:00")
                ts_dt = datetime.datetime.fromisoformat(str(ts))
                age = (self.now - ts_dt.replace(tzinfo=None)).total_seconds() / 60
                if age > 180:
                    issues.append(f"stale ({age:.0f}m old)")
                if ts_dt > self.now + datetime.timedelta(minutes=1):
                    issues.append("future_timestamp")
            except (ValueError, TypeError):
                issues.append("invalid_timestamp")

        for field in ["open", "high", "low", "close"]:
            if field in record and record[field] is not None:
                try:
                    val = float(record[field])
                    if val <= 0:
                        issues.append(f"non_positive_{field}")
                except (ValueError, TypeError):
                    issues.append(f"invalid_{field}")

        if all(f in record for f in ["high", "low", "open", "close"]):
            try:
                if record["high"] < record["low"]:
                    issues.append("high_below_low")
                if record["high"] < record["open"]:
                    issues.append("high_below_open")
                if record["high"] < record["close"]:
                    issues.append("high_below_close")
                if record["low"] > record["open"]:
                    issues.append("low_above_open")
                if record["low"] > record["close"]:
                    issues.append("low_above_close")
            except (TypeError, ValueError):
                pass

        return issues

    def validate_table(self, conn: sqlite3.Connection, table: str) -> Dict:
        """Validate all records in a table. Returns summary."""
        result = {"table": table, "total": 0, "valid": 0, "invalid": 0, "issues": []}
        try:
            rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
            cols = [d[0] for d in conn.description]
            result["total"] = len(rows)
            for i, row in enumerate(rows):
                record = dict(zip(cols, row))
                issues = self.validate_price_record(record, table)
                if issues:
                    result["invalid"] += 1
                    result["issues"].append(
                        {"row": i, "issues": issues, "record": {k: v for k, v in record.items()}}
                    )
                else:
                    result["valid"] += 1
        except sqlite3.Error as e:
            result["issues"].append({"error": str(e)})
        return result

    def check_duplicates(self, conn: sqlite3.Connection, table: str,
                         unique_cols: List[str]) -> List[Dict]:
        """Check for duplicate records."""
        duplicates = []
        if not unique_cols:
            return duplicates
        cols_str = ", ".join(unique_cols)
        try:
            rows = conn.execute(
                f"SELECT {cols_str}, COUNT(*) as cnt FROM [{table}] "
                f"GROUP BY {cols_str} HAVING cnt > 1"
            ).fetchall()
            for row in rows:
                duplicates.append({
                    "table": table,
                    "keys": dict(zip(unique_cols, row[:-1])),
                    "count": row[-1],
                })
        except sqlite3.Error:
            pass
        return duplicates

    def validate_all_price_tables(self, conn: sqlite3.Connection) -> List[Dict]:
        """Validate all price-related tables."""
        tables = ["prices", "price_1d", "price_5m", "price_15m", "price_1m",
                   "live_quotes", "market_snapshots"]
        results = []
        for table in tables:
            try:
                result = self.validate_table(conn, table)
                results.append(result)
            except Exception:
                pass
        return results

    def validate_timestamps(self, conn: sqlite3.Connection, table: str,
                            timestamp_col: str = "timestamp") -> Dict:
        """Check for timezone inconsistencies and missing timestamps."""
        result = {"table": table, "total": 0, "missing_ts": 0, "future_ts": 0,
                   "tz_inconsistent": 0}
        try:
            rows = conn.execute(f"SELECT {timestamp_col} FROM [{table}]").fetchall()
            result["total"] = len(rows)
            for row in rows:
                val = row[0]
                if val is None or val == "":
                    result["missing_ts"] += 1
                    continue
                val_str = str(val)
                if "Z" not in val_str and "+00:00" not in val_str and "UTC" not in val_str:
                    result["tz_inconsistent"] += 1
        except sqlite3.Error:
            pass
        return result


def validate_price_data(db_path: str) -> List[Dict]:
    """Convenience function: validate all price data in DB."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    validator = DataValidator(db_path)
    results = validator.validate_all_price_tables(conn)
    conn.close()
    return results


class MarketValidator:
    """Phase 2 market-specific validation."""

    EXPECTED_TIMEFRAMES = {"1m", "5m", "15m", "1d"}

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.now = datetime.datetime.utcnow()

    def validate_candle_continuity(self, conn: sqlite3.Connection, symbol: str,
                                    table: str = "price_1m", expected_gap_minutes: int = 1,
                                    lookback_hours: int = 24) -> Dict:
        """Check for missing candles (gaps) in a price table.

        Returns: {total: int, gaps: [{timestamp, expected, actual}], missing_count: int}
        """
        result = {"symbol": symbol, "table": table, "total": 0, "gaps": [],
                   "missing_count": 0, "continuous": True}
        try:
            rows = conn.execute(
                f"SELECT timestamp FROM {table} WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, lookback_hours * 60 // expected_gap_minutes + 10),
            ).fetchall()
            result["total"] = len(rows)
            if len(rows) < 2:
                return result
            timestamps = [r[0] for r in rows]
            for i in range(len(timestamps) - 1):
                try:
                    t1 = datetime.datetime.strptime(timestamps[i], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.datetime.strptime(timestamps[i + 1], "%Y-%m-%d %H:%M:%S")
                    gap = (t1 - t2).total_seconds() / 60
                    if gap > expected_gap_minutes * 1.5:
                        result["gaps"].append({
                            "after": timestamps[i + 1],
                            "before": timestamps[i],
                            "gap_minutes": round(gap),
                            "expected_gap": expected_gap_minutes,
                        })
                        result["missing_count"] += int(gap / expected_gap_minutes) - 1
                        result["continuous"] = False
                except (ValueError, TypeError):
                    continue
        except sqlite3.Error:
            pass
        return result


    def validate_ist_timestamps(self, conn: sqlite3.Connection, table: str,
                                 timestamp_col: str = "timestamp") -> Dict:
        """Check if timestamps are in IST timezone (per Phase 2 requirement).

        Returns: {table: str, total: int, ist_count: int, non_ist_count: int,
                   non_ist_examples: [str]}
        """
        result = {"table": table, "total": 0, "ist_count": 0, "non_ist_count": 0,
                   "non_ist_examples": []}
        try:
            rows = conn.execute(f"SELECT {timestamp_col} FROM [{table}]").fetchall()
            result["total"] = len(rows)
            for row in rows:
                val = str(row[0]) if row[0] else ""
                if "+05:30" in val or "Asia/Kolkata" in val or "+0530" in val:
                    result["ist_count"] += 1
                elif "Z" in val or "+00:00" in val or "UTC" in val:
                    result["non_ist_count"] += 1
                    if len(result["non_ist_examples"]) < 3:
                        result["non_ist_examples"].append(val[:30])
                else:
                    result["non_ist_count"] += 1
        except sqlite3.Error:
            pass
        return result


    def validate_candle_ohlc(self, conn: sqlite3.Connection, table: str = "price_5m") -> Dict:
        """Validate OHLC relationships in candle tables.

        Returns: {table: str, total: int, valid: int, invalid: int,
                   issues: [{row, issue, timestamp}]}
        """
        result = {"table": table, "total": 0, "valid": 0, "invalid": 0, "issues": []}
        try:
            cur = conn.execute(f"SELECT * FROM [{table}]")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            result["total"] = len(rows)
            for i, row in enumerate(rows):
                rec = dict(zip(cols, row))
                issues = []
                if rec.get("high", 0) < rec.get("low", 0):
                    issues.append("high_below_low")
                if rec.get("high", 0) < rec.get("open", 0):
                    issues.append("high_below_open")
                if rec.get("high", 0) < rec.get("close", 0):
                    issues.append("high_below_close")
                if rec.get("low", 0) > rec.get("open", 0):
                    issues.append("low_above_open")
                if rec.get("low", 0) > rec.get("close", 0):
                    issues.append("low_above_close")
                if rec.get("open", 0) <= 0 and rec.get("close", 0) <= 0:
                    issues.append("zero_open_close")
                if issues:
                    result["invalid"] += 1
                    result["issues"].append({
                        "row": i, "issues": issues,
                        "timestamp": rec.get("timestamp", ""),
                    })
                else:
                    result["valid"] += 1
        except sqlite3.Error:
            pass
        return result


    def validate_market_candles(self, conn: sqlite3.Connection) -> Dict:
        """Validate market_candles table integrity.

        Returns: {table: str, total: int, timeframes: {str: int},
                   symbols: [str], issues: [str]}
        """
        result = {"table": "market_candles", "total": 0, "timeframes": {},
                   "symbols": [], "issues": []}
        try:
            rows = conn.execute("SELECT DISTINCT timeframe FROM market_candles").fetchall()
            for r in rows:
                tf = r[0]
                count = conn.execute(
                    "SELECT COUNT(*) FROM market_candles WHERE timeframe=?", (tf,)
                ).fetchone()[0]
                result["timeframes"][tf] = count

            syms = conn.execute("SELECT DISTINCT symbol FROM market_candles").fetchall()
            result["symbols"] = [r[0] for r in syms]

            total = conn.execute("SELECT COUNT(*) FROM market_candles").fetchone()[0]
            result["total"] = total

            for tf in ["1m", "5m", "15m", "1d"]:
                if tf not in result["timeframes"]:
                    result["issues"].append(f"missing_timeframe: {tf}")
        except sqlite3.Error as e:
            result["issues"].append(str(e))
        return result


    def validate_expected_range(self, price: float, expected_low: float,
                                  expected_high: float) -> List[str]:
        """Validate that a price is within an expected range.

        Returns list of issues (empty = valid).
        """
        issues = []
        if price <= 0 or expected_low <= 0 or expected_high <= 0:
            return ["invalid_input"]
        if expected_low > expected_high:
            issues.append("range_inverted: low > high")
        if price < expected_low:
            issues.append(f"price_below_range: {price} < {expected_low}")
        if price > expected_high:
            issues.append(f"price_above_range: {price} > {expected_high}")
        return issues


def validate_market_data(db_path: str) -> List[Dict]:
    """Convenience function: validate all market data."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    validator = MarketValidator(db_path)
    results = []
    try:
        mv = MarketValidator(db_path)
        for symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]:
            for table, gap in [("price_1m", 1), ("price_5m", 5)]:
                try:
                    cont = mv.validate_candle_continuity(conn, symbol, table, gap)
                    if cont["gaps"]:
                        results.append(cont)
                except Exception:
                    pass
        for table in ["price_1m", "price_5m", "price_1d"]:
            try:
                ohlc = mv.validate_candle_ohlc(conn, table)
                if ohlc["invalid"] > 0:
                    results.append(ohlc)
            except Exception:
                pass
        try:
            mc = mv.validate_market_candles(conn)
            if mc["issues"]:
                results.append(mc)
        except Exception:
            pass
    except Exception:
        pass
    conn.close()
    return results


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "database/tradingai.db"
    results = validate_price_data(db_path)
    for r in results:
        print(r)
    print("---")
    mresults = validate_market_data(db_path)
    for r in mresults:
        print(r)