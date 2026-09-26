"""Phase 15: options package init."""
from app.options.strategy import (TradeResult, StrategyType,
                                      APPROVED_STRATEGIES,
                                      validate_leg, validate_legs,
                                      same_instrument, same_expiry,
                                      no_duplicates)
from app.options.economics import (calc_bull_put_spread,
                                       calc_bull_call_spread,
                                       calc_bear_call_spread,
                                       calc_bear_put_spread,
                                       calc_iron_condor)
from app.options.engine import OptionsStrategyEngine
from app.options.contract import (OptionsFreshness, VALID_INSTRUMENTS,
                                    VALID_OPTION_TYPES,
                                    validate_contract, classify_freshness,
                                    validate_underlying_consistency)
from app.options.cache import (get as cache_get, put as cache_put,
                                  invalidate as cache_invalidate,
                                  recompute_age)
from app.options.provider import (get_options_chain, get_option_contracts)
from app.options.db import init_option_tables, get_option_table_stats

__all__ = [
    "TradeResult", "StrategyType", "APPROVED_STRATEGIES",
    "validate_leg", "validate_legs",
    "same_instrument", "same_expiry", "no_duplicates",
    "calc_bull_put_spread", "calc_bull_call_spread",
    "calc_bear_call_spread", "calc_bear_put_spread", "calc_iron_condor",
    "OptionsStrategyEngine",
    "OptionsFreshness", "VALID_INSTRUMENTS", "VALID_OPTION_TYPES",
    "validate_contract", "classify_freshness", "validate_underlying_consistency",
    "cache_get", "cache_put", "cache_invalidate", "recompute_age",
    "get_options_chain", "get_option_contracts",
    "init_option_tables", "get_option_table_stats",
]
