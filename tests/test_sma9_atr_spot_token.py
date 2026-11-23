"""SMA9 ATR spot-regime feed must resolve the active broker's index token.

mStock's NSE instrument dump does not contain NIFTY 50, so the old
"NIFTY 50 spot token not found in NSE instruments" error disabled the regime
gate for a full 15-minute refresh window. The broker's own quote for
NSE:NIFTY 50 returns the correct history token for the active broker without
hardcoding a Zerodha token into a broker-agnostic scanner.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "sma9_atr_scanner" / "app" / "live_sma9_atr_scanner.py"
IST = timezone(timedelta(hours=5, minutes=30))


def at(hour, minute):
    return datetime(2026, 11, 23, hour, minute, tzinfo=IST)


@pytest.fixture
def scanner_module(monkeypatch):
    saved_app = {k: v for k, v in sys.modules.items()
                 if k == "app" or k.startswith("app.")}
    saved_path = list(sys.path)
    monkeypatch.syspath_prepend(str(SOURCE.parent.parent))
    for name in [n for n in sys.modules
                 if n == "app" or n.startswith("app.")]:
        del sys.modules[name]
    name = "sma9_atr_spot_token_test"
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    try:
        yield mod
    finally:
        sys.modules.pop(name, None)
        for key in [n for n in sys.modules
                    if n == "app" or n.startswith("app.")]:
            del sys.modules[key]
        sys.modules.update(saved_app)
        sys.path[:] = saved_path


def _feed(mod, *, quote_token=None, instruments=()):
    """Build a KiteFeed with a fake broker facade and no network calls."""
    feed = mod.KiteFeed.__new__(mod.KiteFeed)
    feed._spot_token = None

    def quote(symbols):
        if quote_token is None:
            return {}
        return {symbols[0]: {"instrument_token": quote_token,
                             "last_price": 25000.0}}

    feed.kite = SimpleNamespace(
        quote=quote,
        instruments=lambda _exchange: list(instruments),
    )
    return feed


def test_spot_token_uses_broker_quote_token(scanner_module):
    mod = scanner_module
    feed = _feed(mod, quote_token=26000)  # mStock's NIFTY 50 history token
    assert feed.spot_instrument_token() == 26000
    # Cached; no repeated broker lookup on later regime refreshes.
    feed.kite = None
    assert feed.spot_instrument_token() == 26000


def test_spot_token_uses_dump_when_quote_has_no_token(scanner_module):
    mod = scanner_module
    feed = _feed(mod, instruments=[
        {"tradingsymbol": "NIFTY 50", "segment": "NSE-INDICES",
         "instrument_token": 256265},
    ])
    assert feed.spot_instrument_token() == 256265


def test_spot_token_fails_closed_when_broker_has_no_index(scanner_module):
    feed = scanner_module.KiteFeed.__new__(scanner_module.KiteFeed)
    feed._spot_token = None

    def boom(_symbols):
        raise RuntimeError("temporary broker error")

    feed.kite = SimpleNamespace(quote=boom, instruments=lambda _e: [])
    with pytest.raises(RuntimeError, match="spot token not available"):
        feed.spot_instrument_token()


def test_regime_is_not_disabled_by_mstock_nse_dump(scanner_module):
    mod = scanner_module
    # mStock NSE master has no index row; its quote supplies token 26000.
    feed = _feed(mod, quote_token=26000,
                 instruments=[{"tradingsymbol": "INFY", "segment": "NSE",
                               "instrument_token": 12345}])

    candles = []
    for idx in range(12):
        start = at(9, 15) + timedelta(minutes=5 * idx)
        close = 25000.0 + idx * 20.0
        candles.append({"start": start, "open": close - 2, "high": close + 3,
                        "low": close - 5, "close": close, "volume": 0})
    feed.spot_candles = lambda: candles

    scanner = mod.Sma9AtrLiveScanner.__new__(mod.Sma9AtrLiveScanner)
    scanner.feed = feed
    scanner.regime_evaluated_at = None

    regime = scanner.regime(at(10, 15))
    assert regime["error"] is None
    assert regime["bias"] == "BULLISH"
    assert regime["allowed_option"] == "CE"
    assert regime["session_candles"] >= mod.REGIME_EMA_PERIOD + 1
