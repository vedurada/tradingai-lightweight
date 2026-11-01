"""Explicit SHADOW enforcement — code-level, not only config."""
from app.zerodha import config

def assert_shadow():
    if config.MODE != "SHADOW":
        raise RuntimeError("SHADOW mode required; execution blocked")
    if config.LIVE_EXECUTION_AUTHORIZED is not False:
        raise RuntimeError("Live execution not authorized")

def cannot_fill():
    assert_shadow()
    return False

def cannot_submit_order():
    assert_shadow()
    raise RuntimeError("Broker order submission disabled in SHADOW")
