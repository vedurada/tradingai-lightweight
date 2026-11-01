import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_research as R

def test_classify_prev_direction():
    assert R.classify_prev_direction({"open": 100, "close": 100.5}) == "BULLISH"
    assert R.classify_prev_direction({"open": 100, "close": 99.5}) == "BEARISH"
    assert R.classify_prev_direction({"open": 100, "close": 100.1}) == "SIDEWAYS"

def test_gap_category():
    assert R.gap_category(101.0, 100.0) in ("SMALL_UP", "LARGE_UP")
    assert R.gap_category(99.0, 100.0) in ("SMALL_DOWN", "LARGE_DOWN")
    assert R.gap_category(100.1, 100.0) == "FLAT"

def test_evaluate_setup_no_prev():
    c = {"open":1,"high":2,"low":0.5,"close":1.5,"timestamp":"t","date":"d"}
    r = R.evaluate_setup(c, [c], None, False)
    assert r["setup"] == "INVALID_DATA"

def test_evaluate_setup_trade_open():
    c = {"open":1,"high":2,"low":0.5,"close":1.5,"timestamp":"t","date":"d"}
    r = R.evaluate_setup(c, [c], {"high":2,"low":0,"mid":1,"close":1,"cpr":None,"direction":"BULLISH"}, True)
    assert r["setup"] == "NO_TRADE"
    assert r["trigger"] == "OPEN_POSITION"
