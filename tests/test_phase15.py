"""Phase 15 tests: options strategy validation & trade economics."""
import sys
sys.path.insert(0, '/opt/tradingai_new')

def client():
    from app.api.app import app
    app.config["TESTING"] = True
    return app.test_client()

def test_options_strategy_engine():
    from app.options.engine import OptionsStrategyEngine
    engine = OptionsStrategyEngine()
    result = engine.qualify('NIFTY', index_state='LIVE')
    assert result.status == "NO_TRADE"
    assert result.reason == "OPTIONS_DATA_UNAVAILABLE"

def test_bull_put_spread_no_data():
    from app.options.economics import calc_bull_put_spread
    assert calc_bull_put_spread([]).status == "NO_TRADE"

def test_bull_call_spread_no_data():
    from app.options.economics import calc_bull_call_spread
    assert calc_bull_call_spread([]).status == "NO_TRADE"

def test_bear_call_spread_no_data():
    from app.options.economics import calc_bear_call_spread
    assert calc_bear_call_spread([]).status == "NO_TRADE"

def test_bear_put_spread_no_data():
    from app.options.economics import calc_bear_put_spread
    assert calc_bear_put_spread([]).status == "NO_TRADE"

def test_iron_condor_no_data():
    from app.options.economics import calc_iron_condor
    assert calc_iron_condor([]).status == "NO_TRADE"

def test_validate_leg_valid():
    from app.options.strategy import validate_leg
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    contract = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
                "expiry": "2026-09-25", "timestamp": _now,
                "last_price": 150.0, "bid": 149.0, "ask": 151.0,
                "volume": 100, "open_interest": 500}
    assert validate_leg(contract)[0] is True

def test_validate_leg_invalid_instrument():
    from app.options.strategy import validate_leg
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    contract = {"instrument": "SENSEX", "option_type": "CE", "strike": 17000,
                "expiry": "2026-09-25", "timestamp": _now,
                "last_price": 150.0, "bid": 149.0, "ask": 151.0}
    assert not validate_leg(contract)[0]
    assert any("INVALID_INSTRUMENT" in e for e in validate_leg(contract)[1])

def test_validate_leg_stale():
    from app.options.strategy import validate_leg
    contract = {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
                "expiry": "2026-09-25", "timestamp": "2020-01-01T00:00:00+05:30",
                "last_price": 150.0, "bid": 149.0, "ask": 151.0}
    assert not validate_leg(contract)[0]
    assert any("NOT_FRESH" in e for e in validate_leg(contract)[1])

def test_bull_put_spread_economics():
    from app.options.economics import calc_bull_put_spread
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    legs = [
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17500,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 200.0, "bid": 198.0, "ask": 202.0,
         "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17000,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 100.0, "bid": 98.0, "ask": 102.0,
         "volume": 100, "open_interest": 500},
    ]
    result = calc_bull_put_spread(legs)
    assert result.status == "STRATEGY_VALID"
    assert result.economics["max_reward"] == 96.0
    assert result.economics["spread_width"] == 500.0

def test_bull_call_spread_economics():
    from app.options.economics import calc_bull_call_spread
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    legs = [
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 150.0, "bid": 148.0, "ask": 152.0,
         "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17500,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 80.0, "bid": 78.0, "ask": 82.0,
         "volume": 100, "open_interest": 500},
    ]
    result = calc_bull_call_spread(legs)
    assert result.status == "STRATEGY_VALID"
    assert result.economics["max_risk"] == 74.0

def test_iron_condor_4_legs():
    from app.options.economics import calc_iron_condor
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    legs = [
        {"instrument": "NIFTY", "option_type": "PE", "strike": 16500,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 50.0, "bid": 48.0, "ask": 52.0},
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17000,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 100.0, "bid": 98.0, "ask": 102.0},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17500,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 80.0, "bid": 78.0, "ask": 82.0},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 18000,
         "expiry": "2026-09-25", "timestamp": _now,
         "last_price": 50.0, "bid": 48.0, "ask": 52.0},
    ]
    assert calc_iron_condor(legs).status == "STRATEGY_VALID"

def test_iron_condor_wrong_leg_count():
    from app.options.economics import calc_iron_condor
    assert calc_iron_condor([]).status == "NO_TRADE"

def test_options_strategy_api_read_only():
    r = client().get("/api/options/strategy/NIFTY")
    assert r.status_code == 200
    assert r.get_json()["data"]["historical_options_available"] is False

def test_options_strategy_api_invalid_instrument():
    assert client().get("/api/options/strategy/SENSEX").status_code == 404

def test_options_strategy_api_unknown_strategy():
    assert client().get("/api/options/strategy/NIFTY?strategy=INVALID").status_code == 400

def test_options_strategy_api_no_fabricaed_economics():
    d = client().get("/api/options/strategy/NIFTY?strategy=BULL_PUT_SPREAD").get_json()["data"]
    assert d["economics"] is None

def test_nifty_banknifty_isolation():
    from app.options.engine import OptionsStrategyEngine
    engine = OptionsStrategyEngine()
    assert engine.qualify('NIFTY', index_state='LIVE').reason == "OPTIONS_DATA_UNAVAILABLE"
    assert engine.qualify('BANKNIFTY', index_state='LIVE').reason == "OPTIONS_DATA_UNAVAILABLE"

def test_data_gate_fresh():
    from app.options.engine import OptionsStrategyEngine
    ok, err, data = OptionsStrategyEngine().validate_data_gate('NIFTY')
    assert not ok

def test_index_signal_gate_stale():
    from app.options.engine import OptionsStrategyEngine
    ok, err = OptionsStrategyEngine().validate_index_signal('NIFTY', 'STALE')
    assert not ok and err == "INDEX_SIGNAL_STALE"

def test_index_signal_gate_unavailable():
    from app.options.engine import OptionsStrategyEngine
    ok, err = OptionsStrategyEngine().validate_index_signal('NIFTY', None)
    assert not ok and err == "INDEX_SIGNAL_UNAVAILABLE"

def test_one_trade_day_preserved():
    from app.options.engine import OptionsStrategyEngine
    from app.core.db import get_conn
    engine = OptionsStrategyEngine()
    conn = get_conn()
    conn.execute("DELETE FROM daily_trade_locks WHERE instrument_id='NIFTY' AND date='2026-09-20'")
    conn.execute("INSERT INTO daily_trade_locks (instrument_id, date, status, locked_at, created_at) VALUES ('NIFTY', '2026-09-20', 'LOCKED', '2026-09-20T10:00:00+05:30', '2026-09-20T10:00:00+05:30')")
    conn.commit()
    conn.close()
    result = engine.qualify('NIFTY', index_state='LIVE')
    assert result.reason == "DAILY_TRADE_LIMIT_REACHED"
    conn = get_conn()
    conn.execute("DELETE FROM daily_trade_locks WHERE instrument_id='NIFTY' AND date='2026-09-20'")
    conn.commit()
    conn.close()

def test_phase13_baselines_intact():
    import json
    n = json.load(open('/opt/tradingai_new/app/research/baseline_NIFTY_FULL.json'))
    b = json.load(open('/opt/tradingai_new/app/research/baseline_BANKNIFTY_FULL.json'))
    assert (n['summary']['trades'], n['summary']['total_R']) == (34, 16.21)
    assert (b['summary']['trades'], b['summary']['total_R']) == (31, 16.63)

def test_phase14_options_api_intact():
    assert client().get("/api/options/NIFTY").status_code == 200

def test_app_options_package_imports():
    from app.options import TradeResult, StrategyType, APPROVED_STRATEGIES, OptionsStrategyEngine
    assert len(APPROVED_STRATEGIES) == 5
    assert "BULL_PUT_SPREAD" in APPROVED_STRATEGIES
    assert "IRON_CONDOR" in APPROVED_STRATEGIES
