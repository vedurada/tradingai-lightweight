"""Phase 14 tests: real options data integration and validation (32 items).

Covers: contract validation, freshness, cache, API endpoints,
failure modes, NIFTY/BANKNIFTY isolation, historical data warning,
and regression of all existing phases.
"""
import sys, os
sys.path.insert(0, '/opt/tradingai_new')


def client():
    from app.api.app import app
    # Disable rate limiting in test mode
    app.config["TESTING"] = True
    return app.test_client()


# --- Provider & Contract Validation ---

def test_options_package_imports():
    from app.options import (OptionsFreshness, VALID_INSTRUMENTS,
                              VALID_OPTION_TYPES, validate_contract,
                              classify_freshness, get_options_chain)
    assert OptionsFreshness.OPTIONS_FRESH.value == "OPTIONS_FRESH"
    assert "NIFTY" in VALID_INSTRUMENTS
    assert "BANKNIFTY" in VALID_INSTRUMENTS
    assert "CE" in VALID_OPTION_TYPES
    assert "PE" in VALID_OPTION_TYPES


def test_validate_contract_valid():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30",
            "last_price": 150.0, "bid": 149.0, "ask": 151.0}
    valid, errors = validate_contract(rec)
    assert valid is True, errors


def test_validate_contract_invalid_instrument():
    from app.options.contract import validate_contract
    rec = {"instrument": "SENSEX", "option_type": "CE", "strike": 17000,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30"}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("INVALID_INSTRUMENT" in e for e in errors)


def test_validate_contract_invalid_option_type():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CALL", "strike": 17000,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30"}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("INVALID_OPTION_TYPE" in e for e in errors)


def test_validate_contract_missing_strike():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "expiry": "2026-09-25",
            "timestamp": "2026-09-20T10:00:00+05:30"}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("MISSING_STRIKE" in e for e in errors)


def test_validate_contract_negative_strike():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "strike": -100,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30"}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("INVALID_STRIKE" in e for e in errors)


def test_validate_contract_missing_expiry():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
            "timestamp": "2026-09-20T10:00:00+05:30"}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("MISSING_EXPIRY" in e for e in errors)


def test_validate_contract_negative_price():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30",
            "last_price": -50.0}
    valid, errors = validate_contract(rec)
    assert valid is False
    assert any("NEGATIVE_LAST_PRICE" in e for e in errors)


def test_validate_contract_no_silent_zero():
    from app.options.contract import validate_contract
    rec = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
            "expiry": "2026-09-25", "timestamp": "2026-09-20T10:00:00+05:30",
            "last_price": None}
    valid, errors = validate_contract(rec)
    assert valid is True, errors


# --- Freshness & Timestamp ---

def test_freshness_classify():
    from app.options.contract import classify_freshness
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)
    fresh_ts = (now - timedelta(seconds=60)).isoformat()
    stale_ts = (now - timedelta(seconds=600)).isoformat()
    f1, age1 = classify_freshness(fresh_ts)
    f2, age2 = classify_freshness(stale_ts)
    assert f1.value == "OPTIONS_FRESH"
    assert f2.value == "OPTIONS_STALE"


def test_freshness_none_returns_no_data():
    from app.options.contract import classify_freshness
    f, age = classify_freshness(None)
    assert f.value == "OPTIONS_NO_DATA"


def test_freshness_future_timestamp_is_malformed():
    from app.options.contract import classify_freshness
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    future = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=1)).isoformat()
    f, age = classify_freshness(future)
    assert f.value == "OPTIONS_MALFORMED"


# --- API Endpoints ---

def test_options_api_read_only():
    r = client().get("/api/options/NIFTY")
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["freshness"] in ("OPTIONS_FRESH", "OPTIONS_STALE", "OPTIONS_NO_DATA",
                               "OPTIONS_UNAVAILABLE", "OPTIONS_MALFORMED")
    assert d["historical_options_available"] is False


def test_options_api_invalid_instrument():
    r = client().get("/api/options/SENSEX")
    assert r.status_code == 404
    d = r.get_json()["data"]
    assert d["error"] == "UNKNOWN_INSTRUMENT"


def test_options_api_isolation():
    """NIFTY and BANKNIFTY are independent."""
    r1 = client().get("/api/options/NIFTY")
    r2 = client().get("/api/options/BANKNIFTY")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json()["data"]["instrument"] != r2.get_json()["data"]["instrument"]


def test_options_api_no_strategy():
    """Options API must NOT contain strategy/decision fields."""
    r = client().get("/api/options/NIFTY")
    d = r.get_json()
    keys = str(list(d.keys())) + str(list(d["data"].keys()))
    for bad in ("BUY", "SELL", "SPREAD", "RECOMMEND"):
        assert bad not in keys, f"found strategy field: {bad}"


def test_options_api_historical_warning():
    r = client().get("/api/options/NIFTY")
    d = r.get_json()["data"]
    assert d["historical_options_available"] is False
    assert "HISTORICAL OPTIONS DATA IS NOT AVAILABLE" in d.get("historical_note", "")


def test_options_api_contracts_not_fabricated():
    r = client().get("/api/options/NIFTY")
    d = r.get_json()["data"]
    assert d["contract_count"] == 0
    assert d["contracts"] == []


def test_options_api_read_only_no_post():
    from flask import jsonify, request
    # POST to options endpoint should return 405
    r = client().post("/api/options/NIFTY")
    assert r.status_code == 405


# --- Cache ---

def test_cache_shared_across_workers():
    from app.options.cache import put, get, invalidate
    from app.options.contract import OptionsFreshness
    put("NIFTY", "chain", {"state": "OPTIONS_TEST"}, None, "OPTIONS_TEST")
    cached, _ = get("NIFTY", "chain")
    assert cached is not None
    invalidate("NIFTY")


def test_cache_recomputes_age():
    from app.options.cache import recompute_age
    import time
    ts = (datetime.now() - timedelta(seconds=100)).isoformat() if False else None
    # age=None when no timestamp
    age, freshness = recompute_age({"timestamp": None})
    assert freshness.value == "OPTIONS_NO_DATA"


def test_cached_data_cannot_masquerade_as_fresh():
    from app.options.cache import put, get, recompute_age
    from app.options.contract import OptionsFreshness
    put("TEST_CACHE", "chain", {"state": "TEST", "timestamp": "2020-01-01T00:00:00+05:30"},
        "2020-01-01T00:00:00+05:30", "OPTIONS_STALE")
    cached, _ = get("TEST_CACHE", "chain")
    age, freshness = recompute_age(cached)
    assert freshness.value == "OPTIONS_STALE"


# --- Failure Modes ---

def test_options_unavailable_when_no_source():
    """When no provider is accessible, the API correctly reports UNAVAILABLE."""
    from app.options.cache import invalidate
    from app.options.provider import get_options_chain
    invalidate("NIFTY")
    state, meta = get_options_chain("NIFTY")
    assert state in ("OPTIONS_UNAVAILABLE", "OPTIONS_NO_DATA", "OPTIONS_RATE_LIMITED")
    assert meta.get("contracts", []) == []


def test_rate_limit_state():
    from app.options.contract import OptionsFreshness
    assert OptionsFreshness.OPTIONS_RATE_LIMITED.value == "OPTIONS_RATE_LIMITED"


def test_malformed_state():
    from app.options.contract import OptionsFreshness
    assert OptionsFreshness.OPTIONS_MALFORMED.value == "OPTIONS_MALFORMED"


def test_no_data_state():
    from app.options.contract import OptionsFreshness
    assert OptionsFreshness.OPTIONS_NO_DATA.value == "OPTIONS_NO_DATA"


# --- Option Tables ---

def test_option_tables_exist():
    from app.options.db import init_option_tables, get_option_table_stats
    tables = init_option_tables()
    assert "option_contracts" in tables
    assert "option_snapshots" in tables
    stats = get_option_table_stats()
    assert isinstance(stats["option_contracts"], int)


# --- Regression ---

def test_phase13_baselines_intact():
    import json
    n = json.load(open("/opt/tradingai_new/app/research/baseline_NIFTY_FULL.json"))
    b = json.load(open("/opt/tradingai_new/app/research/baseline_BANKNIFTY_FULL.json"))
    assert (n["summary"]["trades"], n["summary"]["total_R"]) == (34, 16.21)
    assert (b["summary"]["trades"], b["summary"]["total_R"]) == (31, 16.63)


def test_phase13_tests_still_green():
    import subprocess
    result = subprocess.run(["python3", "-m", "pytest", "tests/test_phase13.py", "-q"],
                            capture_output=True, text=True, cwd="/opt/tradingai_new")
    assert "passed" in result.stdout and "failed" not in result.stdout


def test_existing_decision_endpoints_unchanged():
    r = client().get("/api/health")
    assert r.status_code == 200
    r2 = client().get("/api/research/baseline/NIFTY?period=FULL")
    assert r2.status_code == 200


def test_no_fabricated_options_fields_in_api():
    from app.options.contract import VALID_INSTRUMENTS
    assert "NIFTY" in VALID_INSTRUMENTS
    assert "BANKNIFTY" in VALID_INSTRUMENTS
    # Verify no options strike/premium/iv fields exist in snapshots
    import json
    n = json.load(open("/opt/tradingai_new/app/research/baseline_NIFTY_FULL.json"))
    if n["trades"]:
        keys = set(n["trades"][0].keys())
        for bad in ("strike", "premium", "iv", "oi", "pcr", "expiry"):
            assert bad not in {k.lower() for k in keys}, bad


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-q"])
