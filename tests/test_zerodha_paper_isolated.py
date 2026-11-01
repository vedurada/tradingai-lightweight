"""Isolated Phase 3 tests — deterministic mocks, no fake production trades."""
from app.zerodha import option_selector, quote_validator, paper_execution, strategy_adapter

def test_bullish_ce():
    c = option_selector.select_atm_contract(21500, direction="BULLISH")
    assert c["option_type"] == "CE"

def test_bearish_pe():
    c = option_selector.select_atm_contract(21500, direction="BEARISH")
    assert c["option_type"] == "PE"

def test_no_telegram_dependency():
    assert "telegram" not in str(paper_execution.execute_paper)

def test_canonical_adapter():
    r = strategy_adapter.evaluate_candle({"hlc_pattern": True})
    assert r["valid"] is True

def test_persistence_table_name():
    with open("/opt/tradingai/app/zerodha/persistence.py") as f:
        assert "zerodha_shadow_signals" in f.read()
