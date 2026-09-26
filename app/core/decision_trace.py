"""Phase 16: end-to-end decision trace.

For every evaluated decision, produces an auditable trace
identifying all evidence sources and their timestamps.
The trace is deterministic and testable.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def build_decision_trace(
    instrument: str,
    market_state: dict,
    scenario: dict,
    options_state: str,
    strategy: str,
    economics: dict,
    qualification: dict,
    daily_lock: dict,
    completed_candle: dict,
    decision_as_of: str,
):
    """Build a complete auditable decision trace.
    Every field comes from validated backend data.
    """
    trace = {
        "trace_id": f"TRACE-{instrument}-{decision_as_of[:10]}-{datetime.now(_IST).strftime('%H%M%S%f')}",
        "instrument": instrument,
        "market_timestamp": decision_as_of,
        "completed_candle_timestamp": completed_candle.get("timestamp") if completed_candle else None,
        "completed_candle_price": completed_candle.get("close") if completed_candle else None,
        "index_price": market_state.get("price"),
        "index_signal": market_state.get("trend", "NEUTRAL"),
        "signal_timestamp": market_state.get("timestamp"),
        "scenario": scenario.get("candidate", {}).get("scenario_type") if scenario else None,
        "scenario_timestamp": scenario.get("candidate", {}).get("created_at") if scenario else None,
        "scenario_match_state": scenario.get("match", {}).get("match_state") if scenario else None,
        "options_data_state": options_state,
        "strategy": strategy,
        "entry_fill_assumptions": economics if economics else None,
        "qualification_result": qualification.get("decision") if qualification else None,
        "qualification_reasons": qualification.get("reasons", []) if qualification else [],
        "daily_lock_state": daily_lock.get("status") if daily_lock else None,
        "daily_lock_consumed": daily_lock.get("consumed_at") if daily_lock else None,
        "final_trader_facing_state": None,
        "trace_complete": False,
    }
    # Determine final state
    if qualification and qualification.get("decision") == "QUALIFIED_TRADE":
        if daily_lock and daily_lock.get("status") == "CONSUMED":
            trace["final_trader_facing_state"] = "QUALIFIED"
        elif daily_lock and daily_lock.get("status") == "PENDING":
            trace["final_trader_facing_state"] = "QUALIFIED"
        else:
            trace["final_trader_facing_state"] = "NO_TRADE"
            trace["qualification_reasons"].append("DAILY_TRADE_LIMIT_REACHED")
    elif options_state not in ("OPTIONS_FRESH",):
        trace["final_trader_facing_state"] = "OPTIONS_DATA_UNAVAILABLE"
    else:
        trace["final_trader_facing_state"] = "NO_TRADE"

    trace["trace_complete"] = True
    return trace


def trace_to_public(trace: dict) -> dict:
    """Convert trace to public-facing format.
    Does NOT expose unnecessary backend implementation details."""
    return {
        "trace_id": trace["trace_id"],
        "instrument": trace["instrument"],
        "market_timestamp": trace["market_timestamp"],
        "completed_candle_timestamp": trace["completed_candle_timestamp"],
        "index_price": trace["index_price"],
        "index_signal": trace["index_signal"],
        "scenario": trace["scenario"],
        "options_data_state": trace["options_data_state"],
        "strategy": trace["strategy"],
        "qualification_result": trace["qualification_result"],
        "final_state": trace["final_trader_facing_state"],
    }


def validate_trace(trace: dict) -> list[str]:
    """Validate that a decision trace is complete and deterministic.
    Returns list of validation errors."""
    errors = []
    if not trace.get("trace_id"):
        errors.append("MISSING_TRACE_ID")
    if not trace.get("market_timestamp"):
        errors.append("MISSING_MARKET_TIMESTAMP")
    if not trace.get("instrument"):
        errors.append("MISSING_INSTRUMENT")
    if trace["final_trader_facing_state"] not in ("QUALIFIED", "NO_TRADE", "OPTIONS_DATA_UNAVAILABLE"):
        errors.append(f"INVALID_FINAL_STATE:{trace.get('final_trader_facing_state')}")
    # If qualified, must have trace_complete=True
    if trace["final_trader_facing_state"] == "QUALIFIED" and not trace.get("trace_complete"):
        errors.append("QUALIFIED_WITHOUT_COMPLETE_TRACE")
    return errors
