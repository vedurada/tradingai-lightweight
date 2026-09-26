"""Phase 15: options strategy engine with data gate and index signal gate.

Flow: INDEX MARKET ENGINE → SCENARIO → QUALIFICATION → OPTIONS DATA GATE → STRATEGY

If any gate fails, NO_TRADE with explicit reason.
Never fabricates contracts or prices.
Preserves one-trade/day, PIT logic, research isolation.
"""
from app.options.strategy import (TradeResult, StrategyType,
                                      validate_legs, same_instrument,
                                      same_expiry, no_duplicates)
from app.options.economics import (calc_bull_put_spread,
                                       calc_bull_call_spread,
                                       calc_bear_call_spread,
                                       calc_bear_put_spread,
                                       calc_iron_condor)
from app.options.contract import OptionsFreshness
from app.options.provider import get_options_chain, get_option_contracts
from app.options.cache import invalidate as cache_invalidate


# Required fields for a strategy leg
STRATEGY_REQUIRED_FIELDS = {"instrument", "expiry", "strike",
                            "option_type", "last_price", "bid",
                            "ask", "volume", "open_interest"}

# Liquidity gates
MIN_VOLUME = 1
MIN_OPEN_INTEREST = 50
MAX_SPREAD_WIDTH_PCT = 0.10  # 10% of strike


class OptionsStrategyEngine:
    """Deterministic options strategy validation engine.

    Data-gated: returns NO_TRADE when options data is unavailable.
    Never fabricates contracts, premiums, IV, OI, or expiry.
    """

    def __init__(self):
        self.last_result = None

    def get_data_state(self, instrument):
        """Check the options data gate.
        Returns (state, data_dict)."""
        state, data = get_options_chain(instrument)
        return state, data

    def validate_index_signal(self, instrument, index_state):
        """Index signal gate: if index data is stale/unavailable,
        no options trade."""
        if index_state is None or index_state == "NO_DATA":
            return False, "INDEX_SIGNAL_UNAVAILABLE"
        if index_state == "STALE":
            return False, "INDEX_SIGNAL_STALE"
        return True, None

    def validate_data_gate(self, instrument):
        """Options data gate: check chain availability, freshness,
        required contracts."""
        state, data = self.get_data_state(instrument)
        if state == "OPTIONS_UNAVAILABLE":
            return False, "OPTIONS_UNAVAILABLE", data
        if state == "OPTIONS_NO_DATA":
            return False, "OPTIONS_NO_DATA", data
        if state == "OPTIONS_RATE_LIMITED":
            return False, "OPTIONS_RATE_LIMITED", data
        if state == "OPTIONS_STALE":
            return False, "OPTIONS_STALE", data
        if state == "OPTIONS_MALFORMED":
            return False, "OPTIONS_MALFORMED", data
        # Fresh data available
        contracts = data.get("contracts", [])
        if len(contracts) == 0:
            return False, "OPTIONS_PARTIAL_CHAIN", data
        return True, None, data

    def select_expiry(self, instrument, preferred_expiry=None):
        """Deterministic expiry selection from provider data.
        Returns (expiry, errors)."""
        state, data = self.get_data_state(instrument)
        expiries = data.get("expiries", [])
        if not expiries:
            return None, ["OPTIONS_MISSING_EXPIRY"]
        if preferred_expiry and preferred_expiry in expiries:
            return preferred_expiry, None
        # Use earliest available expiry (deterministic rule)
        return expiries[0], None

    def select_strikes(self, instrument, option_type, underlying,
                       direction):
        """Deterministic strike selection from provider data.
        Returns (strikes, errors)."""
        state, data = self.get_data_state(instrument)
        contracts = data.get("contracts", [])
        if not contracts:
            return None, ["OPTIONS_MISSING_STRIKE"]
        # Filter by instrument and option type
        eligible = [c for c in contracts
                    if c.get("instrument") == instrument
                    and c.get("option_type") == option_type
                    and c.get("last_price") and c.get("last_price") > 0]
        if not eligible:
            return None, ["OPTIONS_MISSING_STRIKE"]
        # Sort by strike distance from underlying
        eligible.sort(key=lambda c: abs(c.get("strike", 0) - underlying))
        strikes = [c["strike"] for c in eligible]
        return strikes, None

    def validate_liquidity(self, contract):
        """Check liquidity gates for a contract."""
        errors = []
        vol = contract.get("volume")
        oi = contract.get("open_interest")
        bid = contract.get("bid")
        ask = contract.get("ask")
        strike = contract.get("strike", 0)
        if vol is not None and vol < MIN_VOLUME:
            errors.append(f"INSUFFICIENT_VOLUME:{vol}")
        if oi is not None and oi < MIN_OPEN_INTEREST:
            errors.append(f"INSUFFICIENT_OI:{oi}")
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            spread_pct = (ask - bid) / strike
            if spread_pct > MAX_SPREAD_WIDTH_PCT:
                errors.append(f"SPREAD_TOO_WIDE:{spread_pct:.4f}")
        return errors

    def build_strategy(self, instrument, strategy_type, legs,
                       index_state="LIVE"):
        """Build and validate a strategy.

        Flow:
        1. Index signal gate
        2. Options data gate
        3. Contract validation
        4. Liquidity gates
        5. Strategy-specific construction
        6. Economics calculation

        Returns TradeResult.
        """
        # Gate 1: Index signal
        idx_ok, idx_err = self.validate_index_signal(instrument,
                                                        index_state)
        if not idx_ok:
            return TradeResult(status="NO_TRADE",
                               reason=idx_err,
                               errors=[idx_err])

        # Gate 0: One-trade/day lock check (before data gate)
        from app.core.db import get_conn
        conn = get_conn()
        trade_date = __import__("datetime").datetime.now(
            __import__("zoneinfo").ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        existing = conn.execute(
            "SELECT COUNT(*) FROM daily_trade_locks WHERE instrument_id=? AND date=?",
            (instrument, trade_date)).fetchone()[0]
        conn.close()
        if existing > 0:
            return TradeResult(status="NO_TRADE",
                               reason="DAILY_TRADE_LIMIT_REACHED",
                               errors=["DAILY_TRADE_LIMIT_REACHED"])
        # Gate 2: Options data gate
        data_ok, data_err, data = self.validate_data_gate(instrument)
        if not data_ok:
            return TradeResult(status="NO_TRADE",
                               reason=data_err,
                               errors=[data_err],
                               data=data)

        # Gate 3: Contract validation
        valid, leg_errors = validate_legs(legs)
        if not valid:
            return TradeResult(status="NO_TRADE",
                               reason="CONTRACT_VALIDATION_FAILED",
                               errors=leg_errors)

        # Gate 4: Same instrument, expiry, no duplicates
        if not same_instrument(legs):
            return TradeResult(status="NO_TRADE",
                               reason="MIXED_INSTRUMENTS",
                               errors=["LEGS_NOT_SAME_INSTRUMENT"])
        if not same_expiry(legs):
            return TradeResult(status="NO_TRADE",
                               reason="MIXED_EXPIRIES",
                               errors=["LEGS_NOT_SAME_EXPIRY"])
        if not no_duplicates(legs):
            return TradeResult(status="NO_TRADE",
                               reason="DUPLICATE_CONTRACTS",
                               errors=["DUPLICATE_CONTRACTS"])

        # Gate 5: Liquidity validation per leg
        liquidity_errors = []
        for i, leg in enumerate(legs):
            liq_errs = self.validate_liquidity(leg)
            if liq_errs:
                liquidity_errors.append(f"LEG_{i}:{', '.join(liq_errs)}")
        if liquidity_errors:
            return TradeResult(status="NO_TRADE",
                               reason="INSUFFICIENT_LIQUIDITY",
                               errors=liquidity_errors)

        # Gate 6: Strategy-specific construction
        strategy_fn = {
            StrategyType.BULL_PUT_SPREAD: calc_bull_put_spread,
            StrategyType.BULL_CALL_SPREAD: calc_bull_call_spread,
            StrategyType.BEAR_CALL_SPREAD: calc_bear_call_spread,
            StrategyType.BEAR_PUT_SPREAD: calc_bear_put_spread,
            StrategyType.IRON_CONDOR: calc_iron_condor,
        }.get(StrategyType(strategy_type) if isinstance(strategy_type, str) else strategy_type)

        if strategy_fn is None:
            return TradeResult(status="NO_TRADE",
                               reason="UNKNOWN_STRATEGY",
                               errors=[f"UNKNOWN_STRATEGY:{strategy_type}"])

        result = strategy_fn(legs)
        return result

    def qualify(self, instrument, index_state="LIVE",
                strategy_type=None, legs=None):
        """Full qualification pipeline.

        Returns TradeResult with NO_TRADE when options data unavailable.
        Preserves one-trade/day logic.
        """
        from app.core.qualification import QualificationEngine
        from app.core.db import get_conn

        conn = get_conn()
        trade_date = __import__("datetime").datetime.now(
            __import__("zoneinfo").ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        lock_key = (instrument, trade_date)
        existing = conn.execute(
            "SELECT COUNT(*) FROM daily_trade_locks WHERE instrument_id=? AND date=?",
            (instrument, trade_date)).fetchone()[0]
        conn.close()

        if existing > 0:
            return TradeResult(status="NO_TRADE",
                               reason="DAILY_TRADE_LIMIT_REACHED",
                               errors=["DAILY_TRADE_LIMIT_REACHED"])

        if not instrument in ("NIFTY", "BANKNIFTY"):
            return TradeResult(status="NO_TRADE",
                               reason="UNKNOWN_INSTRUMENT",
                               errors=["UNKNOWN_INSTRUMENT"])

        if strategy_type is None or legs is None:
            return TradeResult(status="NO_TRADE",
                               reason="OPTIONS_DATA_UNAVAILABLE",
                               errors=["OPTIONS_DATA_UNAVAILABLE"])

        engine = OptionsStrategyEngine()
        result = engine.build_strategy(instrument, strategy_type, legs,
                                         index_state)
        self.last_result = result
        return result
