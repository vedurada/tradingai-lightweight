"""Tests for the all-scanner minimum-premium ITM strike gate."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCANNERS = {
    "sma9": ("scripts/sma9_scanner/app/live_sma9_scanner.py", "Sma9LiveScanner"),
    "sma9_5min": ("scripts/sma9_5min_scanner/app/live_sma9_5min_scanner.py", "Sma9LiveScanner"),
    "sma9_adx": ("scripts/sma9_adx_scanner/app/live_sma9_adx_scanner.py", "Sma9AdxLiveScanner"),
    "sma9_atr": ("scripts/sma9_atr_scanner/app/live_sma9_atr_scanner.py", "Sma9AtrLiveScanner"),
    "sma9_high": ("scripts/sma9_high_scanner/app/live_sma9_high_scanner.py", "Sma9HighLiveScanner"),
    "sma9_high_trail": (
        "scripts/sma9_high_trail_scanner/app/live_sma9_high_trail_scanner.py",
        "TrailLiveScanner",
    ),
    "sma9_live": (
        "scripts/sma9_live_scanner/app/live_sma9_live_scanner.py",
        "Sma9LiveScanner",
    ),
    "sma9_trail": (
        "scripts/sma9_trail_scanner/app/live_sma9_trail_scanner.py",
        "TrailLiveScanner",
    ),
}

def _load(name: str, rel_path: str, class_name: str):
    """Load one scanner with an isolated ``app`` package search path.

    Each scanner keeps its engine in its own ``app`` directory, so the
    synthetic package must include both that directory and the repository's
    shared app directory.  The real ``sys.modules`` state is restored after
    import so other tests are unaffected.
    """
    mod_name = f"_sma9_premium_gate_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)

    saved_app_modules = {
        key: value
        for key, value in sys.modules.items()
        if key == "app" or key.startswith("app.")
    }
    saved_sys_path = list(sys.path)
    synthetic_app = ModuleType("app")
    synthetic_app.__path__ = [str(ROOT / "app"), str((ROOT / rel_path).parent)]
    synthetic_app.__package__ = "app"
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    sys.modules["app"] = synthetic_app
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(saved_app_modules)
        sys.path[:] = saved_sys_path
    return mod, getattr(mod, class_name)


_saved_env = {
    key: os.environ.get(key)
    for key in ("SMA9_MIN_PREMIUM", "SMA9_STRIKE_STEP", "SMA9_ITM_MAX_STEPS")
}
os.environ["SMA9_MIN_PREMIUM"] = "120"
os.environ["SMA9_STRIKE_STEP"] = "50"
os.environ["SMA9_ITM_MAX_STEPS"] = "8"

MODULES = {}
for _name, (_path, _class) in SCANNERS.items():
    MODULES[_name] = _load(_name, _path, _class)

for _key, _value in _saved_env.items():
    if _value is None:
        os.environ.pop(_key, None)
    else:
        os.environ[_key] = _value


EXPIRY = date(2026, 12, 1)


def _contract(option_type: str, strike: float) -> dict:
    return {
        "tradingsymbol": f"NIFTY26D01{int(strike)}{option_type}",
        "instrument_token": int(strike),
        "strike": float(strike),
        "expiry": EXPIRY,
    }


def _quote(price: float) -> dict:
    return {"last_price": price}


class FakeFeed:
    def __init__(self, contracts: dict, prices: dict):
        self.contracts = contracts
        self.prices = prices
        self.quote_calls = []

    def find_contract(self, strike, expiry, option_type):
        if expiry != EXPIRY:
            return None
        return self.contracts.get((option_type, float(strike)))

    def quote(self, symbols):
        self.quote_calls.append(list(symbols))
        return {sym: self.prices[sym] for sym in symbols if sym in self.prices}


def _fake_scanner(feed: FakeFeed, ce_position=None, pe_position=None):
    return SimpleNamespace(
        states={
            "CE": SimpleNamespace(position=ce_position),
            "PE": SimpleNamespace(position=pe_position),
        },
        feed=feed,
        _premium_gate={},
    )


def _run_gate(name: str, scanner, quotes: dict, symbol_for: dict):
    errors = []
    mod, cls = MODULES[name]
    cls._apply_min_premium(scanner, quotes, symbol_for, errors)
    return mod, cls, errors


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_itm_strikes_walk_ce_down_and_pe_up(name):
    mod, _ = MODULES[name]
    assert mod.MIN_PREMIUM == 120.0
    assert mod.STRIKE_STEP == 50.0
    assert mod.ITM_MAX_STEPS == 8
    assert mod._itm_strikes(25350, "CE")[:3] == [25300.0, 25250.0, 25200.0]
    assert mod._itm_strikes(25350, "PE")[:3] == [25400.0, 25450.0, 25500.0]


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_atm_premium_above_floor_keeps_atm(name):
    ce = _contract("CE", 25350)
    pe = _contract("PE", 25350)
    prices = {
        f"NFO:{ce['tradingsymbol']}": _quote(263.55),
        f"NFO:{pe['tradingsymbol']}": _quote(242.9),
    }
    feed = FakeFeed({}, prices)
    scanner = _fake_scanner(feed)
    symbol_for = {
        "CE": (f"NFO:{ce['tradingsymbol']}", ce),
        "PE": (f"NFO:{pe['tradingsymbol']}", pe),
    }

    mod, cls, errors = _run_gate(name, scanner, prices.copy(), symbol_for)

    assert errors == []
    assert feed.quote_calls == []
    assert symbol_for["CE"][1] == ce
    assert symbol_for["PE"][1] == pe
    assert scanner._premium_gate["CE"] == {
        "ok": True, "reason": "ATM_PREMIUM_OK", "ltp": 263.55,
    }
    assert scanner._premium_gate["PE"]["reason"] == "ATM_PREMIUM_OK"
    assert cls._premium_ok(scanner, "CE") is True
    assert cls._premium_ok(scanner, "PE") is True


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_low_atm_premium_walks_itm_to_first_qualifying_price(name):
    strikes = {
        ("CE", 25350.0): _contract("CE", 25350),
        ("PE", 25350.0): _contract("PE", 25350),
        ("CE", 25300.0): _contract("CE", 25300),
        ("CE", 25250.0): _contract("CE", 25250),
        ("PE", 25400.0): _contract("PE", 25400),
    }
    ce = strikes[("CE", 25350.0)]
    pe = strikes[("PE", 25350.0)]
    prices = {
        f"NFO:{ce['tradingsymbol']}": _quote(100),
        f"NFO:{pe['tradingsymbol']}": _quote(110),
        f"NFO:{strikes[('CE', 25300.0)]['tradingsymbol']}": _quote(90),
        f"NFO:{strikes[('CE', 25250.0)]['tradingsymbol']}": _quote(145.5),
        f"NFO:{strikes[('PE', 25400.0)]['tradingsymbol']}": _quote(125.25),
    }
    feed = FakeFeed(strikes, prices)
    scanner = _fake_scanner(feed)
    symbol_for = {
        "CE": (f"NFO:{ce['tradingsymbol']}", ce),
        "PE": (f"NFO:{pe['tradingsymbol']}", pe),
    }

    _, cls, errors = _run_gate(name, scanner, prices.copy(), symbol_for)

    assert errors == []
    assert len(feed.quote_calls) == 1
    assert symbol_for["CE"][1] == strikes[("CE", 25250.0)]
    assert symbol_for["PE"][1] == strikes[("PE", 25400.0)]
    assert scanner._premium_gate["CE"] == {
        "ok": True, "reason": "ITM_PREMIUM_OK",
        "strike": 25250.0, "ltp": 145.5,
    }
    assert scanner._premium_gate["PE"] == {
        "ok": True, "reason": "ITM_PREMIUM_OK",
        "strike": 25400.0, "ltp": 125.25,
    }
    assert cls._premium_ok(scanner, "CE") is True
    assert cls._premium_ok(scanner, "PE") is True


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_no_qualifying_itm_premium_blocks_entries(name):
    strikes = {
        ("CE", 25350.0): _contract("CE", 25350),
        ("PE", 25350.0): _contract("PE", 25350),
        ("CE", 25300.0): _contract("CE", 25300),
        ("PE", 25400.0): _contract("PE", 25400),
    }
    ce = strikes[("CE", 25350.0)]
    pe = strikes[("PE", 25350.0)]
    prices = {
        f"NFO:{ce['tradingsymbol']}": _quote(100),
        f"NFO:{pe['tradingsymbol']}": _quote(115),
        f"NFO:{strikes[('CE', 25300.0)]['tradingsymbol']}": _quote(120),
        f"NFO:{strikes[('PE', 25400.0)]['tradingsymbol']}": _quote(119.9),
    }
    feed = FakeFeed(strikes, prices)
    scanner = _fake_scanner(feed)
    symbol_for = {
        "CE": (f"NFO:{ce['tradingsymbol']}", ce),
        "PE": (f"NFO:{pe['tradingsymbol']}", pe),
    }

    _, cls, errors = _run_gate(name, scanner, prices.copy(), symbol_for)

    assert errors == []
    assert symbol_for["CE"][1] == ce
    assert symbol_for["PE"][1] == pe
    assert scanner._premium_gate["CE"] == {
        "ok": False, "reason": "NO_ITM_PREMIUM",
    }
    assert scanner._premium_gate["PE"]["reason"] == "NO_ITM_PREMIUM"
    assert cls._premium_ok(scanner, "CE") is False
    assert cls._premium_ok(scanner, "PE") is False


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_missing_atm_quote_blocks_without_itm_lookup(name):
    ce = _contract("CE", 25350)
    pe = _contract("PE", 25350)
    feed = FakeFeed({}, {})
    scanner = _fake_scanner(feed)
    symbol_for = {
        "CE": (f"NFO:{ce['tradingsymbol']}", ce),
        "PE": (f"NFO:{pe['tradingsymbol']}", pe),
    }

    _, cls, errors = _run_gate(name, scanner, {}, symbol_for)

    assert errors == []
    assert feed.quote_calls == []
    assert scanner._premium_gate["CE"] == {
        "ok": False, "reason": "NO_ATM_QUOTE",
    }
    assert scanner._premium_gate["PE"]["reason"] == "NO_ATM_QUOTE"
    assert cls._premium_ok(scanner, "CE") is False
    assert cls._premium_ok(scanner, "PE") is False


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_open_position_keeps_contract_and_is_not_gated(name):
    ce = _contract("CE", 25350)
    pe = _contract("PE", 25350)
    prices = {
        f"NFO:{ce['tradingsymbol']}": _quote(20),
        f"NFO:{pe['tradingsymbol']}": _quote(300),
    }
    feed = FakeFeed({}, prices)
    scanner = _fake_scanner(
        feed, ce_position=SimpleNamespace(tradingsymbol=ce["tradingsymbol"]))
    symbol_for = {
        "CE": (f"NFO:{ce['tradingsymbol']}", ce),
        "PE": (f"NFO:{pe['tradingsymbol']}", pe),
    }

    _, cls, errors = _run_gate(name, scanner, prices.copy(), symbol_for)

    assert errors == []
    assert feed.quote_calls == []
    assert symbol_for["CE"][1] == ce
    assert scanner._premium_gate["CE"] == {
        "ok": True, "reason": "OPEN_POSITION",
    }
    assert cls._premium_ok(scanner, "CE") is True


@pytest.mark.parametrize("name", sorted(SCANNERS))
def test_scanner_source_is_wired_to_gate(name):
    rel_path, _ = SCANNERS[name]
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    assert 'MIN_PREMIUM = float(os.environ.get("SMA9_MIN_PREMIUM", "120"))' in source
    assert "self._premium_gate = {}" in source
    assert "self._apply_min_premium(quotes, symbol_for, errors)" in source
    assert "self._premium_ok(opt)" in source
    assert '"premium_gate": getattr(self, "_premium_gate", {}),' in source
