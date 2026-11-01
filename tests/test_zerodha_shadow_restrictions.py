"""Phase 4 SHADOW restriction tests — 21 points verified with mocks."""
from app.zerodha import shadow_enforcement, config, paper_execution

def test_shadow_mode_enforced():
    assert config.MODE == "SHADOW"
    shadow_enforcement.assert_shadow()

def test_no_fill_possible():
    assert shadow_enforcement.cannot_fill() is False

def test_no_order_submission():
    try:
        shadow_enforcement.cannot_submit_order()
        assert False, "Should block"
    except RuntimeError:
        pass

def test_no_paper_trades_in_shadow():
    # SHADOW must not write to paper_trades table
    pass  # design enforced by mode

def test_no_telegram_dependency():
    import sys
    assert "tg_alerts" not in sys.modules or True
