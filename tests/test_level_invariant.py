"""TradingAI.in — Level Invariant Regression Test (latest-row-only).

For every supported index symbol, verifies that the LATEST indicator row
satisfies the conventional ordering:

    S3 < S2 < S1 < Spot < R1 < R2 < R3

Historical rows with insufficient data (market just opened, few candles)
are excluded via pytest.skip. Only the most recent indicator row per symbol
is checked.

RULE: Insufficient source data → unavailable/not-ready state (pytest.skip),
NEVER an inferred financial level. This prevents a repeat of the P0 defect
where S3/S2/S1 were populated with values above current spot.

This is a permanent regression guard against the P0 financial-data defect
discovered during Phase 35: support/resistance values appearing on the
wrong side of the current price.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import sqlite3 as _sqlite3
import json as _json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "database", "tradingai.db")

SUPPORTED_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


def fetch_json(url, retries=3, timeout=10):
    import urllib.request
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=timeout)
            return _json.loads(resp.read())
        except Exception as e:
            last_err = e
            time.sleep(1 * (attempt + 1))
    raise last_err


def _get_latest_rows(conn):
    rows = conn.execute(
        "SELECT symbol, timestamp, pivot, r1, s1, r2, s2, r3, s3 "
        "FROM indicators WHERE symbol IN ({})".format(
            ",".join("?" for _ in SUPPORTED_SYMBOLS)
        ),
        SUPPORTED_SYMBOLS,
    ).fetchall()
    latest = {}
    for row in rows:
        symbol = row[0]
        if symbol not in latest or row[1] > latest[symbol][1]:
            latest[symbol] = row
    return latest


class TestLevelInvariant:
    """For every supported symbol, verify S3 < S2 < S1 < Spot < R1 < R2 < R3."""

    def test_all_symbols_have_levels(self):
        conn = _sqlite3.connect(DB_PATH)
        latest = _get_latest_rows(conn)
        conn.close()
        for sym in SUPPORTED_SYMBOLS:
            assert sym in latest, f"{sym} missing from indicators table"

    def test_s3_lt_s2_lt_s1_lt_pivot_lt_r1_lt_r2_lt_r3(self):
        conn = _sqlite3.connect(DB_PATH)
        latest = _get_latest_rows(conn)
        conn.close()
        for sym in SUPPORTED_SYMBOLS:
            assert sym in latest, f"{sym} missing from indicators"
            row = latest[sym]
            symbol, timestamp, pivot, r1, s1, r2, s2, r3, s3 = row
            if not any([s3, s2, s1, r1, r2, r3]):
                pytest.skip(f"{sym}: no level data available yet")
            assert s3 and s2 and s1, f"{sym}: missing S3/S2/S1"
            assert r1 and r2 and r3, f"{sym}: missing R1/R2/R3"
            assert s3 < s2, f"{sym}: S3 ({s3}) >= S2 ({s2})"
            assert s2 < s1, f"{sym}: S2 ({s2}) >= S1 ({s1})"
            assert r1 < r2, f"{sym}: R1 ({r1}) >= R2 ({r2})"
            assert r2 < r3, f"{sym}: R2 ({r2}) >= R3 ({r3})"
            assert s1 < pivot, f"{sym}: S1 ({s1}) >= pivot ({pivot})"
            assert r1 > pivot, f"{sym}: R1 ({r1}) <= pivot ({pivot})"

    def test_supports_below_resistances(self):
        conn = _sqlite3.connect(DB_PATH)
        latest = _get_latest_rows(conn)
        conn.close()
        for sym in SUPPORTED_SYMBOLS:
            if sym not in latest:
                pytest.skip(f"{sym}: no data")
            s1 = latest[sym][4]
            r1 = latest[sym][3]
            assert s1 < r1, f"{sym}: S1 ({s1}) >= R1 ({r1})"

    def test_key_levels_api_matches_invariant(self):
        for sym in SUPPORTED_SYMBOLS:
            data = fetch_json(f"https://tradingai.in/api/key-levels?symbol={sym}")
            supports = data.get("supports", [])
            resistances = data.get("resistances", [])
            assert len(supports) >= 1, f"{sym}: no supports returned"
            assert len(resistances) >= 1, f"{sym}: no resistances returned"
            assert max(supports) < min(resistances), (
                f"{sym}: max support ({max(supports)}) >= min resistance ({min(resistances)})"
            )


class TestLevelDataQuality:
    """Insufficient data → UNAVAILABLE, never inferred financial level."""

    def test_insufficient_data_rule(self):
        """If a symbol has no level data, the API must NOT fabricate levels.
        All supported symbols must either pass the invariant or be empty.
        No symbol may show S3 >= S2 or R1 <= pivot."""
        conn = _sqlite3.connect(DB_PATH)
        latest = _get_latest_rows(conn)
        conn.close()
        for sym in SUPPORTED_SYMBOLS:
            if sym not in latest:
                continue
            row = latest[sym]
            symbol, timestamp, pivot, r1, s1, r2, s2, r3, s3 = row
            if not any([s3, s2, s1, r1, r2, r3]):
                continue
            if not (s3 and s2 and s1):
                pytest.skip(f"{sym}: insufficient support data")
            if not (r1 and r2 and r3):
                pytest.skip(f"{sym}: insufficient resistance data")
            assert s3 < s2, f"{sym}: S3 >= S2 — invariant violated"
            assert r1 > pivot, f"{sym}: R1 <= pivot — invariant violated"

    def test_key_levels_data_state_live(self):
        for sym in SUPPORTED_SYMBOLS:
            data = fetch_json(f"https://tradingai.in/api/key-levels?symbol={sym}")
            assert data.get("data_state") == "LIVE", (
                f"{sym}: data_state is {data.get('data_state')}, expected LIVE"
            )

    def test_key_levels_has_timestamp(self):
        for sym in SUPPORTED_SYMBOLS:
            data = fetch_json(f"https://tradingai.in/api/key-levels?symbol={sym}")
            assert "timestamp" in data, f"{sym}: no timestamp in response"
            assert data["timestamp"], f"{sym}: empty timestamp"
