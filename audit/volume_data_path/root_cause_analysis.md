# Volume=0 Root Cause Analysis

## Problem Statement

`/api/price/NIFTY` and `/api/price/BANKNIFTY` return `volume: 0` in production despite having access to real volume data.

## Affected Code

**File:** `backend/api_server.py`
**Function:** `_live_quote_row()` (called by `latest_price()`)
**Lines:** 595-632

## Code Path Analysis

### Step 1: Query price_1m (lines 595-598)
```python
price_row = conn.execute(
    'SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1',
    (symbol,)
).fetchone()
```
Result: Returns a `sqlite3.Row` with the most recent 1-minute candle.

### Step 2: Query live_quotes (lines 599-601)
```python
live_row = _live_quote_row(conn, symbol)
```
Returns a `sqlite3.Row` or None.

### Step 3: Extract volume from price_1m (lines 602-606)
```python
price_1m_volume_zero = False
if price_row:
    if (price_row.get('volume') or 0) == 0:  # ← BUG HERE
        price_1m_volume_zero = True
```

**BUG:** `price_row` is a `sqlite3.Row` object. In Python 3.10, `sqlite3.Row` does NOT have a `.get()` method. This line raises `AttributeError`.

### Step 4: Exception silently caught (lines 607-609)
```python
except Exception:
    pass
```
The `AttributeError` is silently caught. `live_row` remains whatever it was (possibly None). `price_1m_volume_zero` remains `False`.

### Step 5: Extract volume from live_row (lines 610-614)
Same bug pattern — `live_row.get('volume')` raises `AttributeError`, silently caught.

### Step 6: Fallback trigger condition (lines 615-622)
```python
if (not price_row and not live_row) or (price_1m_volume_zero and (not live_row or live_volume_zero)):
```

Since `price_1m_volume_zero` is always `False` (due to the bug), this condition is NEVER TRUE.
The fallback to `price_1d` is NEVER triggered.

### Step 7: Return result with volume=0

The function returns the price data but volume extraction failed, resulting in `volume: 0`.

## Compounding Issue: price_1d Midnight Rows

The fallback query:
```sql
SELECT * FROM price_1d WHERE symbol=? AND timestamp >= datetime('now','-24 hours') ORDER BY timestamp DESC LIMIT 1
```

Without `AND volume > 0`, this returns synthetic midnight rows (volume=0) that sort BEFORE actual trading day rows via `ORDER BY timestamp DESC`. Even if the fallback were triggered, it would find volume=0 rows first.

## Python Version Constraint

- **Production VM:** Python 3.10.12
- **`.get()` on sqlite3.Row:** Available only in Python 3.12+
- **Impact:** All volume extraction code in this path is broken on Python 3.10

## Why This Was Hard to Find

1. The exception is silently swallowed by `try/except: pass`
2. The API still returns 200 with valid price data — only volume is wrong
3. The fallback trigger condition has `price_1m_volume_zero` as a required input, which is always False due to the bug
4. Multiple layers of fallback logic mask the failure
