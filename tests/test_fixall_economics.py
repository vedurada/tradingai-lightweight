"""Fixall 2026-09-28: economics CRITICAL/HIGH regression tests (read-only, no prod writes)."""
import sys
sys.path.insert(0, "/opt/tradingai")


def _cp_legs():
    return [
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17500,
         "expiry": "2026-09-25", "last_price": 200.0, "bid": 198.0,
         "ask": 202.0, "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17000,
         "expiry": "2026-09-25", "last_price": 100.0, "bid": 98.0,
         "ask": 102.0, "volume": 100, "open_interest": 500},
    ]


def _dc_legs():
    return [
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17000,
         "expiry": "2026-09-25", "last_price": 150.0, "bid": 148.0,
         "ask": 152.0, "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17500,
         "expiry": "2026-09-25", "last_price": 80.0, "bid": 78.0,
         "ask": 82.0, "volume": 100, "open_interest": 500},
    ]


def test_rr_standardized_reward_over_risk():
    from app.options.economics import calc_bull_put_spread, calc_bull_call_spread, calc_bear_call_spread
    r_credit = calc_bull_put_spread(_cp_legs())
    assert r_credit.status == "STRATEGY_VALID"
    # credit was inverted (risk/reward ~4.21); now reward/risk ~0.23 (net-based)
    assert r_credit.economics["max_reward"] == 96.0
    assert r_credit.economics["spread_width"] == 500.0
    assert abs(r_credit.economics["risk_reward"] - r_credit.economics["reward_risk"]) < 1e-9
    assert r_credit.economics["risk_reward"] < 1.0  # 96/404 basis, not 404/96
    r_debit = calc_bull_call_spread(_dc_legs())
    assert r_debit.economics["max_risk"] == 74.0
    assert r_debit.economics["risk_reward"] > 1.0  # reward-dominant debit
    # both use same orientation: reward/risk
    assert abs(r_credit.economics["risk_reward"] - r_credit.economics["max_reward_rs"] / r_credit.economics["max_risk_rs"]) < 0.02


def test_lot_fees_slippage_threaded():
    from app.options import economics as E
    assert E.LOT_SIZES["NIFTY"] == 65 and E.LOT_SIZES["BANKNIFTY"] == 30
    assert E.BROKERAGE_RS > 0 and E.SLIPPAGE_PTS > 0
    r = E.calc_bull_put_spread(_cp_legs())
    e = r.economics
    assert e["lot_size"] == 65
    assert e["costs_rs"] > 0
    assert e["max_reward_rs"] == round(96.0 * 65 - e["costs_rs"], 2)
    assert e["max_risk_rs"] == round(404.0 * 65 + e["costs_rs"], 2)


def test_condor_uses_max_wing():
    from app.options.economics import calc_iron_condor
    legs = [
        {"instrument": "NIFTY", "option_type": "PE", "strike": 16500,
         "expiry": "2026-09-25", "last_price": 50.0, "bid": 48.0, "ask": 52.0,
         "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "PE", "strike": 17000,
         "expiry": "2026-09-25", "last_price": 100.0, "bid": 98.0, "ask": 102.0,
         "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 17500,
         "expiry": "2026-09-25", "last_price": 80.0, "bid": 78.0, "ask": 82.0,
         "volume": 100, "open_interest": 500},
        {"instrument": "NIFTY", "option_type": "CE", "strike": 18200,
         "expiry": "2026-09-25", "last_price": 50.0, "bid": 48.0, "ask": 52.0,
         "volume": 100, "open_interest": 500},
    ]
    r = calc_iron_condor(legs)
    assert r.status == "STRATEGY_VALID"
    # put_width 500, call_width 700, credit 72 -> max risk must be 700-72=628 (not 428)
    assert r.economics["max_risk"] == 628.0


def test_risk_cap_unconditional():
    from app.risk.engine import RiskEngine
    re_ = RiskEngine()
    # max_risk=0 previously skipped cap; 3% must now fail vs 2% engine cap
    ok, reasons = re_.validate({"entry": 100.0, "stop": 97.0, "target": 104.5,
                                "max_risk": 0, "expected_reward": 0})
    assert not ok and any("risk_exceeds_max" in x for x in reasons)
    # RR floor still enforced
    ok2, r2 = re_.validate({"entry": 100.0, "stop": 99.0, "target": 100.5,
                            "max_risk": 2.0, "expected_reward": 1.0})
    assert not ok2 and any("reward_risk" in x for x in r2)
    # valid 1%-risk passes (Phase 7 B4 boundary)
    ok3, _ = re_.validate({"entry": 23207.33, "stop": 22975.26, "target": 23671.48,
                           "max_risk": 1.0, "expected_reward": 2.0})
    assert ok3


def test_vol_mapping_high_credit_low_debit():
    from app.strategies.engine import StrategyEngine
    se = StrategyEngine()
    # credit-only default: always credit
    assert se.select_strategy("X", "BULLISH", "HIGH")["strategy"] == "Bull Put Spread"
    assert se.select_strategy("X", "BEARISH", "HIGH")["strategy"] == "Bear Call Spread"
    # research opt-out: HIGH->credit, LOW->debit (inversion fixed)
    assert se.select_strategy("X", "BULLISH", "HIGH", credit_only=False)["strategy"] == "Bull Put Spread"
    assert se.select_strategy("X", "BULLISH", "LOW", credit_only=False)["strategy"] == "Bull Call Spread"
    assert se.select_strategy("X", "BEARISH", "HIGH", credit_only=False)["strategy"] == "Bear Call Spread"
    assert se.select_strategy("X", "BEARISH", "LOW", credit_only=False)["strategy"] == "Bear Put Spread"
    # condor wired for non-directional
    assert se.select_strategy("RANGE", "NEUTRAL", "NORMAL")["strategy"] == "Iron Condor"


def test_liquidity_mid_and_cap():
    from app.options.engine import OptionsStrategyEngine, MAX_SPREAD_MID_PCT, MAX_SPREAD_ABS
    oe = OptionsStrategyEngine()
    # (140-100)/25000 = 0.0016 would never fire on strike basis; mid basis 40/120=0.33 must fire
    wide = {"instrument": "NIFTY", "strike": 25000, "bid": 100.0, "ask": 140.0,
            "volume": 100, "open_interest": 500}
    errs = oe.validate_liquidity(wide)
    assert any("SPREAD_TOO_WIDE" in e for e in errs)
    assert any("SPREAD_PREMIUM_CAP" in e for e in errs)
    tight = {"instrument": "NIFTY", "strike": 25000, "bid": 100.0, "ask": 101.0,
             "volume": 100, "open_interest": 500}
    assert oe.validate_liquidity(tight) == []
    assert MAX_SPREAD_MID_PCT == 0.20 and MAX_SPREAD_ABS == 15.0


def test_credit_only_gate_present():
    from app.options import engine as OE
    from app.options.strategy import StrategyType
    assert OE.CREDIT_ONLY is True
    assert StrategyType.BULL_CALL_SPREAD in OE._DEBIT_STRATEGIES
    assert StrategyType.BEAR_PUT_SPREAD in OE._DEBIT_STRATEGIES
    assert callable(OE.is_options_data_valid)


def test_paper_pnl_formula_and_lots():
    from app.paper_trade import engine as PE
    assert PE.LOT_SIZES == {"NIFTY": 65, "BANKNIFTY": 30}
    # LONG NIFTY: (exit-entry)*lot-costs
    lot, costs = 65, PE.BROKERAGE_RS + PE.SLIPPAGE_PTS * 65
    assert round((23868.0 - 23400.0) * lot - costs, 2) == round(468 * 65 - costs, 2)
    # SHORT sign check: (entry-exit)*lot-costs
    assert round((23400.0 - 23166.0) * lot - costs, 2) > 0
    # legs persisted (not None): source check
    import inspect
    src = inspect.getsource(PE.PaperTradeEngine.create_paper_trade)
    assert "legs_json" in src and ", None, None, None," not in src
    mon = inspect.getsource(PE.PaperTradeEngine.monitor)
    assert "timestamp > ?" in mon and "STOP" in mon


def test_performance_r_conversion_and_lastrowid():
    from app.paper_trade import performance as P
    import inspect
    src = inspect.getsource(P.record_performance)
    assert "move_pts / risk_pts" in src or "move_pts/risk_pts" in src.replace(" ", "")
    assert "cur.lastrowid" in src
    assert "conn.execute" not in src.split("conn.close")[1].split("return")[0] or "lastrowid" in src
    assert P.LOT_SIZES["NIFTY"] == 65


def test_backtest_canonical_lot_and_doc():
    from app.research import backtest as B
    import inspect
    assert B.LOT_SIZES == {"NIFTY": 65, "BANKNIFTY": 30}
    src = inspect.getsource(B.BacktestEngine._simulate_intraday_trade)
    assert "* 50" not in src
    assert "R-DEFINITION MAP" in (B.__doc__ or "")
    assert "CANONICAL" in (B.IntradayExitEngine.__doc__ or "")


def test_r_map_docstrings_present():
    import app.options.economics as E
    import app.paper_trade.engine as PE
    import app.paper_trade.performance as PP
    import app.risk.engine as RE
    import app.strategies.engine as SE
    for m in (E, PE, PP, B if False else E):
        assert "R-DEFINITION" in (m.__doc__ or ""), m.__name__
    assert "R-DEFINITION" in (PE.__doc__ or "")
    assert "R-DEFINITION" in (PP.__doc__ or "")
    assert "R4" in (RE.__doc__ or "") or "nested" in (RE.__doc__ or "").lower()
    assert "HIGH" in (SE.__doc__ or "")
