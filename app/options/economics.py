"""Phase 15: economics engine for approved options strategies.

Calculates deterministic risk/reward for each strategy type.
Uses actual provider prices when available. Never fabricates.
"""
from app.options.strategy import (TradeResult, StrategyType,
                                      validate_leg, validate_legs,
                                      same_instrument, same_expiry,
                                      no_duplicates)


def round2(v):
    return round(v, 2) if v is not None else None


def calc_bull_put_spread(legs):
    """SELL higher-strike PUT + BUY lower-strike PUT.
    Net credit. Max risk = spread width - credit. Max reward = credit."""
    if not same_instrument(legs) or not same_expiry(legs):
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_LEG_STRUCTURE",
                           errors=["LEGS_NOT_SAME_INSTRUMENT_OR_EXPIRY"])
    if not no_duplicates(legs):
        return TradeResult(status="NO_TRADE", reason="DUPLICATE_CONTRACTS",
                           errors=["DUPLICATE_CONTRACTS"])
    # Sort: sell put (higher strike) first, buy put (lower strike) second
    sorted_legs = sorted(legs, key=lambda l: l.get("strike", 0),
                         reverse=True)
    sell_put = sorted_legs[0]
    buy_put = sorted_legs[1]
    if buy_put.get("option_type") != "PE" or sell_put.get("option_type") != "PE":
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_OPTION_TYPES",
                           errors=["BULL_PUT_SPREAD_REQUIRES_PE"])
    sell_strike = sell_put["strike"]
    buy_strike = buy_put["strike"]
    if buy_strike >= sell_strike:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_SPREAD_ORDER",
                           errors=["BUY_PUT_STRIKE_MUST_BE_BELOW_SELL"])
    credit = sell_put["bid"] - buy_put["ask"]
    spread_width = sell_strike - buy_strike
    if credit <= 0:
        return TradeResult(status="NO_TRADE",
                           reason="NON_POSITIVE_CREDIT",
                           errors=["NET_CREDIT_NOT_POSITIVE"])
    max_risk = round2(spread_width - credit)
    max_reward = round2(credit)
    breakeven = round2(sell_strike - credit)
    return TradeResult(status="STRATEGY_VALID",
                       strategy=StrategyType.BULL_PUT_SPREAD,
                       legs=sorted_legs,
                       economics={"net_credit": max_reward,
                                   "max_risk": max_risk,
                                   "max_reward": max_reward,
                                   "breakeven": breakeven,
                                   "spread_width": round2(spread_width),
                                   "risk_reward": round2(max_risk / max_reward)
                                   if max_reward else None})


def calc_bull_call_spread(legs):
    """BUY lower-strike CALL + SELL higher-strike CALL.
    Net debit. Max risk = debit. Max reward = spread width - debit."""
    if not same_instrument(legs) or not same_expiry(legs):
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_LEG_STRUCTURE",
                           errors=["LEGS_NOT_SAME_INSTRUMENT_OR_EXPIRY"])
    if not no_duplicates(legs):
        return TradeResult(status="NO_TRADE", reason="DUPLICATE_CONTRACTS",
                           errors=["DUPLICATE_CONTRACTS"])
    sorted_legs = sorted(legs, key=lambda l: l.get("strike", 0))
    buy_call = sorted_legs[0]
    sell_call = sorted_legs[1]
    if buy_call.get("option_type") != "CE" or sell_call.get("option_type") != "CE":
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_OPTION_TYPES",
                           errors=["BULL_CALL_SPREAD_REQUIRES_CE"])
    buy_strike = buy_call["strike"]
    sell_strike = sell_call["strike"]
    if sell_strike <= buy_strike:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_SPREAD_ORDER",
                           errors=["SELL_CALL_STRIKE_MUST_BE_ABOVE_BUY"])
    debit = buy_call["ask"] - sell_call["bid"]
    spread_width = sell_strike - buy_strike
    if debit <= 0:
        return TradeResult(status="NO_TRADE",
                           reason="NON_POSITIVE_DEBIT",
                           errors=["NET_DEBIT_NOT_POSITIVE"])
    max_risk = round2(debit)
    max_reward = round2(spread_width - debit)
    breakeven = round2(buy_strike + debit)
    return TradeResult(status="STRATEGY_VALID",
                       strategy=StrategyType.BULL_CALL_SPREAD,
                       legs=sorted_legs,
                       economics={"net_debit": max_risk,
                                   "max_risk": max_risk,
                                   "max_reward": max_reward,
                                   "breakeven": breakeven,
                                   "spread_width": round2(spread_width),
                                   "risk_reward": round2(max_reward / max_risk)
                                   if max_risk else None})


def calc_bear_call_spread(legs):
    """SELL lower-strike CALL + BUY higher-strike CALL.
    Net credit. Max risk = spread width - credit. Max reward = credit."""
    if not same_instrument(legs) or not same_expiry(legs):
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_LEG_STRUCTURE",
                           errors=["LEGS_NOT_SAME_INSTRUMENT_OR_EXPIRY"])
    if not no_duplicates(legs):
        return TradeResult(status="NO_TRADE", reason="DUPLICATE_CONTRACTS",
                           errors=["DUPLICATE_CONTRACTS"])
    sorted_legs = sorted(legs, key=lambda l: l.get("strike", 0))
    sell_call = sorted_legs[0]
    buy_call = sorted_legs[1]
    if sell_call.get("option_type") != "CE" or buy_call.get("option_type") != "CE":
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_OPTION_TYPES",
                           errors=["BEAR_CALL_SPREAD_REQUIRES_CE"])
    sell_strike = sell_call["strike"]
    buy_strike = buy_call["strike"]
    if buy_strike <= sell_strike:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_SPREAD_ORDER",
                           errors=["BUY_CALL_STRIKE_MUST_BE_ABOVE_SELL"])
    credit = sell_call["bid"] - buy_call["ask"]
    spread_width = buy_strike - sell_strike
    if credit <= 0:
        return TradeResult(status="NO_TRADE",
                           reason="NON_POSITIVE_CREDIT",
                           errors=["NET_CREDIT_NOT_POSITIVE"])
    max_risk = round2(spread_width - credit)
    max_reward = round2(credit)
    breakeven = round2(sell_strike + credit)
    return TradeResult(status="STRATEGY_VALID",
                       strategy=StrategyType.BEAR_CALL_SPREAD,
                       legs=sorted_legs,
                       economics={"net_credit": max_reward,
                                   "max_risk": max_risk,
                                   "max_reward": max_reward,
                                   "breakeven": breakeven,
                                   "spread_width": round2(spread_width),
                                   "risk_reward": round2(max_risk / max_reward)
                                   if max_reward else None})


def calc_bear_put_spread(legs):
    """BUY higher-strike PUT + SELL lower-strike PUT.
    Net debit. Max risk = debit. Max reward = spread width - debit."""
    if not same_instrument(legs) or not same_expiry(legs):
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_LEG_STRUCTURE",
                           errors=["LEGS_NOT_SAME_INSTRUMENT_OR_EXPIRY"])
    if not no_duplicates(legs):
        return TradeResult(status="NO_TRADE", reason="DUPLICATE_CONTRACTS",
                           errors=["DUPLICATE_CONTRACTS"])
    sorted_legs = sorted(legs, key=lambda l: l.get("strike", 0),
                         reverse=True)
    buy_put = sorted_legs[0]
    sell_put = sorted_legs[1]
    if buy_put.get("option_type") != "PE" or sell_put.get("option_type") != "PE":
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_OPTION_TYPES",
                           errors=["BEAR_PUT_SPREAD_REQUIRES_PE"])
    buy_strike = buy_put["strike"]
    sell_strike = sell_put["strike"]
    if sell_strike >= buy_strike:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_SPREAD_ORDER",
                           errors=["SELL_PUT_STRIKE_MUST_BE_BELOW_BUY"])
    debit = buy_put["ask"] - sell_put["bid"]
    spread_width = buy_strike - sell_strike
    if debit <= 0:
        return TradeResult(status="NO_TRADE",
                           reason="NON_POSITIVE_DEBIT",
                           errors=["NET_DEBIT_NOT_POSITIVE"])
    max_risk = round2(debit)
    max_reward = round2(spread_width - debit)
    breakeven = round2(buy_strike - debit)
    return TradeResult(status="STRATEGY_VALID",
                       strategy=StrategyType.BEAR_PUT_SPREAD,
                       legs=sorted_legs,
                       economics={"net_debit": max_risk,
                                   "max_risk": max_risk,
                                   "max_reward": max_reward,
                                   "breakeven": breakeven,
                                   "spread_width": round2(spread_width),
                                   "risk_reward": round2(max_reward / max_risk)
                                   if max_risk else None})


def calc_iron_condor(legs):
    """Four legs: BUY lower put + SELL higher put + SELL lower call + BUY higher call.
    Net credit. Max risk = min spread width - credit."""
    if len(legs) != 4:
        return TradeResult(status="NO_TRADE", reason="IRON_CONDOR_REQUIRES_4_LEGS",
                           errors=["EXACTLY_4_LEGS_REQUIRED"])
    if not same_instrument(legs) or not same_expiry(legs):
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_LEG_STRUCTURE",
                           errors=["LEGS_NOT_SAME_INSTRUMENT_OR_EXPIRY"])
    if not no_duplicates(legs):
        return TradeResult(status="NO_TRADE", reason="DUPLICATE_CONTRACTS",
                           errors=["DUPLICATE_CONTRACTS"])
    # Classify legs
    puts = [l for l in legs if l.get("option_type") == "PE"]
    calls = [l for l in legs if l.get("option_type") == "CE"]
    if len(puts) != 2 or len(calls) != 2:
        return TradeResult(status="NO_TRADE",
                           reason="IRON_CONDOR_REQUIRES_2_PUTS_2_CALLS",
                           errors=["MUST_HAVE_2_PUTS_AND_2_CALLS"])
    # Sort puts: higher strike = sell, lower strike = buy
    puts_sorted = sorted(puts, key=lambda l: l.get("strike", 0),
                         reverse=True)
    sell_put = puts_sorted[0]
    buy_put = puts_sorted[1]
    # Sort calls: lower strike = sell, higher strike = buy
    calls_sorted = sorted(calls, key=lambda l: l.get("strike", 0))
    sell_call = calls_sorted[0]
    buy_call = calls_sorted[1]
    # Validate strike ordering
    if buy_put["strike"] >= sell_put["strike"]:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_PUT_STRIKE_ORDER",
                           errors=["BUY_PUT_MUST_BE_BELOW_SELL_PUT"])
    if sell_call["strike"] >= buy_call["strike"]:
        return TradeResult(status="NO_TRADE",
                           reason="INVALID_CALL_STRIKE_ORDER",
                           errors=["SELL_CALL_MUST_BE_BELOW_BUY_CALL"])
    # Validate put spread is below call spread
    if sell_put["strike"] >= sell_call["strike"]:
        return TradeResult(status="NO_TRADE",
                           reason="PUT_SPREAD_NOT_BELOW_CALL_SPREAD",
                           errors=["SELL_PUT_MUST_BE_BELOW_SELL_CALL"])
    put_credit = sell_put["bid"] - buy_put["ask"]
    call_credit = sell_call["bid"] - buy_call["ask"]
    credit = put_credit + call_credit
    put_width = sell_put["strike"] - buy_put["strike"]
    call_width = buy_call["strike"] - sell_call["strike"]
    max_risk = round2(min(put_width, call_width) - credit)
    max_reward = round2(credit)
    breakeven_lower = round2(sell_put["strike"] - credit)
    breakeven_upper = round2(sell_call["strike"] + credit)
    if credit <= 0 or max_risk <= 0:
        return TradeResult(status="NO_TRADE",
                           reason="NON_POSITIVE_ECONOMICS",
                           errors=["NON_POSITIVE_CREDIT_OR_RISK"])
    return TradeResult(status="STRATEGY_VALID",
                       strategy=StrategyType.IRON_CONDOR,
                       legs=[buy_put, sell_put, sell_call, buy_call],
                       economics={"net_credit": max_reward,
                                   "max_risk": max_risk,
                                   "max_reward": max_reward,
                                   "breakeven_lower": breakeven_lower,
                                   "breakeven_upper": breakeven_upper,
                                   "put_width": round2(put_width),
                                   "call_width": round2(call_width),
                                   "risk_reward": round2(max_risk / max_reward)
                                   if max_reward else None})
