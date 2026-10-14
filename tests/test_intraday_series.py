"""Session price-line series (/api/<symbol>/intraday) — read-only contract.

The dashboard draws one continuous 5-minute close line for a session across
the CPR band (09:15 → 15:30). This covers: series shape, day navigation,
engine-sourced CPR levels (never page-side maths), and input validation.
DB reads only; no writes, no provider calls.
"""
import re

from app.api.app import app
from app.core.db import get_conn

client = app.test_client()


def _latest_date(inst="NIFTY"):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(substr(timestamp,1,10)) AS d FROM market_candles_5m "
            "WHERE instrument_id=?", (inst,)).fetchone()
        return row["d"] if row else None
    finally:
        conn.close()


def test_latest_session_series_and_levels():
    r = client.get("/api/NIFTY/intraday")
    assert r.status_code == 200
    body = r.get_json()
    d = body["data"]
    assert body["state"] == "LIVE"
    assert d["instrument"] == "NIFTY"
    assert d["date"] == _latest_date()
    assert d["count"] == len(d["points"]) > 0
    # session line starts at the 09:15 open and never leaves the 09:15-15:30 window
    assert d["first"][11:16] == "09:15"
    for p in d["points"]:
        hhmm = p["timestamp"][11:16]
        assert "09:15" <= hhmm <= "15:30", hhmm
        assert p["close"] is not None
    assert d["session_start"] == "09:15" and d["session_end"] == "15:30"
    assert d["latest"] == d["points"][-1]["close"]


def test_cpr_levels_come_from_prior_session_engine():
    from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels
    d = client.get("/api/NIFTY/intraday").get_json()["data"]
    cp = d["cpr"]
    assert cp["available"] is True and cp["session"] == d["prev_date"]
    conn = get_conn()
    try:
        prev = conn.execute(
            "SELECT high, low, close FROM market_candles_5m "
            "WHERE instrument_id='NIFTY' AND substr(timestamp,1,10)=? "
            "ORDER BY timestamp", (cp["session"],)).fetchall()
    finally:
        conn.close()
    assert len(prev) >= 2
    p_h = max(float(c["high"]) for c in prev)
    p_l = min(float(c["low"]) for c in prev)
    p_c = float(prev[-1]["close"])
    base = calculate_cpr(p_h, p_l, p_c)
    lv = pivot_levels(p_h, p_l, base["pp"])
    for key in ("bc", "tc", "width_pct"):
        assert abs(cp[key] - base[key]) < 1e-6, key
    assert abs(cp["pivot"] - base["pp"]) < 1e-6
    for key in ("r1", "s1", "r2", "s2"):
        assert abs(cp[key] - lv[key]) < 1e-6, key
    assert cp["cpr_type"] in ("NARROW", "NORMAL", "WIDE")


def test_day_navigation_is_bidirectional():
    latest = client.get("/api/NIFTY/intraday").get_json()["data"]
    assert latest["next_date"] is None and latest["is_latest"] is True
    prev_date = latest["prev_date"]
    assert prev_date, "a stored session must have a previous session or null"
    prev = client.get(f"/api/NIFTY/intraday?date={prev_date}").get_json()["data"]
    assert prev["date"] == prev_date
    assert prev["next_date"] == latest["date"]
    assert prev["is_latest"] is False
    # selected day's own stored candles, not the latest day's
    assert prev["count"] > 0 and prev["first"][:10] == prev_date


def test_unknown_instrument_and_bad_date():
    assert client.get("/api/FOO/intraday").status_code == 404
    r = client.get("/api/NIFTY/intraday?date=2026-13-99")
    assert r.status_code == 400
    assert r.get_json()["data"]["reasons"] == ["INVALID_DATE"]


def test_empty_date_returns_no_data_without_levels_fabricated():
    d = client.get("/api/NIFTY/intraday?date=2030-01-01").get_json()["data"]
    assert d["count"] == 0 and d["points"] == []
    assert "NO_CANDLES_FOR_DATE" in d["reasons"]


def test_dashboard_renders_series_without_live_options_blocks():
    h = open("/opt/tradingai/frontend/nifty-intraday-dashboard.html").read()
    for marker in ('id="pathChart"', 'id="pathPrev"', 'id="pathNext"',
                   '"/api/"+INST+"/intraday"', 'class="pxline"'):
        assert marker in h, marker
    # live options data blocks are removed entirely: no placeholder cell,
    # no options API call and no rendering code.
    for banned in ('id="cellStrategy"', 'id="pStrategy"', 'showStrategyCell',
                   '/api/options', 'id="optBox"', 'id="apprBox"', 'id="advBox"',
                   'renderOpt', 'renderAppr', 'renderAdv'):
        assert banned not in h, banned
    # educational learning content is preserved
    assert 'New to NIFTY options?' in h
    assert '/bull-put-spread.html' in h and '/bear-call-spread.html' in h
    assert '/option-chain-guide.html' in h and '/pcr-guide.html' in h
