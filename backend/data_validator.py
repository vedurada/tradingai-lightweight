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


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "database/tradingai.db"
    results = validate_price_data(db_path)
    for r in results:
        print(r)