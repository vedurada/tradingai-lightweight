#!/usr/bin/env python3
"""Phase 9C — Personal Trading Intelligence.

Deterministic statistics engine from journal data.
AI is excluded from all calculations. AI may explain findings later.

Every statistic:
- Is computed deterministically from journal entries
- Reports SUFFICIENT_DATA or INSUFFICIENT_DATA
- Includes sample size used
- Enforces minimum sample-size protection (MIN_SAMPLE_SIZE = 10)

Components:
- Setup-level, instrument, strategy, regime, direction statistics
- Time-of-day behavior analysis
- Entry-window, confirmation adherence
- Stop/target, risk-sizing behavior
- Exit patterns (manual/early/late)
- Compliance analysis (WAIT, NO_SETUP, after invalidation, skipped)
- TradingAI outcome vs user outcome
- Recurring mistake patterns
"""
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journal import (
    get_journal, list_journals, get_trade_count, has_minimum_sample,
    get_detailed_comparison, classify_all_journals, MIN_SAMPLE_SIZE,
    TradeJournalRecord,
)


def _sample_size(instrument: str = None, strategy: str = None,
                     date_from: str = None, date_to: str = None) -> int:
    return get_trade_count(instrument=instrument, strategy=strategy,
                           date_from=date_from, date_to=date_to)


def _sufficient(instrument: str = None, strategy: str = None,
                    date_from: str = None, date_to: str = None) -> bool:
    return has_minimum_sample(instrument=instrument, strategy=strategy,
                              date_from=date_from, date_to=date_to)


def _get_journals(instrument: str = None, strategy: str = None,
                      date_from: str = None, date_to: str = None) -> List[TradeJournalRecord]:
    records = list_journals(instrument=instrument, date_from=date_from,
                            date_to=date_to, limit=10000)
    return records


def _extract_hour(timestamp_str: str) -> Optional[int]:
    if not timestamp_str:
        return None
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return dt.hour
    except (ValueError, TypeError):
        return None


def _extract_time_of_day(hour: Optional[int]) -> str:
    if hour is None:
        return "UNKNOWN"
    if 9 <= hour < 11:
        return "0930-1100"
    elif 11 <= hour < 14:
        return "1100-1400"
    elif 14 <= hour < 15:
        return "1400-1500"
    elif 15 <= hour < 16:
        return "1500_CLOSE"
    return "OTHER"


def intelligence_summary(instrument: str = None, strategy: str = None,
                            date_from: str = None, date_to: str = None) -> Dict[str, Any]:
    """Overall personal intelligence summary."""
    sample = _sample_size(instrument, strategy, date_from, date_to)
    sufficient = _sufficient(instrument, strategy, date_from, date_to)

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades for insights, have {sample}"
        return result

    journals = _get_journals(instrument, strategy, date_from, date_to)
    if not journals:
        result["data_status"] = "INSUFFICIENT_DATA"
        result["message"] = "No journal entries found"
        return result

    total = len(journals)
    wins = sum(1 for j in journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
    losses = sum(1 for j in journals if j.result and j.result.upper() in ("LOSS", "FAIL"))
    traded = sum(1 for j in journals if j.user_action == "TRADED")
    skipped = sum(1 for j in journals if j.user_action == "SKIPPED")
    paper = sum(1 for j in journals if j.user_action == "PAPER")
    mistakes = sum(1 for j in journals if j.mistake)

    result.update({
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        "took_trade": traded,
        "skipped": skipped,
        "paper_traded": paper,
        "trades_with_mistakes": mistakes,
        "avg_risk_actual": _avg(journals, "risk_actual"),
        "avg_risk_planned": _avg(journals, "risk_planned"),
        "categories": _categorize(journals),
    })

    return result


def _avg(records: List[TradeJournalRecord], field: str) -> Optional[float]:
    values = [getattr(r, field) for r in records if getattr(r, field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _categorize(records: List[TradeJournalRecord]) -> Dict[str, int]:
    by_action = Counter(r.user_action for r in records)
    by_regime = Counter(r.market_regime for r in records if r.market_regime)
    by_direction = Counter(r.direction for r in records if r.direction)
    by_result = Counter(r.result for r in records if r.result)

    return {
        "by_action": dict(by_action),
        "by_regime": dict(by_regime),
        "by_direction": dict(by_direction),
        "by_result": dict(by_result),
    }


def intelligence_instrument(symbol: str) -> Dict[str, Any]:
    """Per-instrument statistics."""
    sample = _sample_size(instrument=symbol)
    sufficient = _sufficient(instrument=symbol)

    result: Dict[str, Any] = {
        "symbol": symbol,
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals(instrument=symbol)
    total = len(journals)
    wins = sum(1 for j in journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
    losses = sum(1 for j in journals if j.result and j.result.upper() in ("LOSS", "FAIL"))

    by_strategy: Dict[str, Dict[str, Any]] = {}
    for strategy in set(j.strategy for j in journals if j.strategy):
        s_journals = [j for j in journals if j.strategy == strategy]
        s_total = len(s_journals)
        s_wins = sum(1 for j in s_journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
        by_strategy[strategy] = {
            "trades": s_total,
            "wins": s_wins,
            "win_rate": round(s_wins / s_total * 100, 2) if s_total > 0 else 0,
        }

    by_regime: Dict[str, Dict[str, Any]] = {}
    for regime in set(j.market_regime for j in journals if j.market_regime):
        r_journals = [j for j in journals if j.market_regime == regime]
        r_total = len(r_journals)
        r_wins = sum(1 for j in r_journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
        by_regime[regime] = {
            "trades": r_total,
            "wins": r_wins,
            "win_rate": round(r_wins / r_total * 100, 2) if r_total > 0 else 0,
        }

    result.update({
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        "by_strategy": by_strategy,
        "by_regime": by_regime,
    })

    return result


def intelligence_strategy(strategy: str) -> Dict[str, Any]:
    """Per-strategy statistics."""
    sample = _sample_size(strategy=strategy)
    sufficient = _sufficient(strategy=strategy)

    result: Dict[str, Any] = {
        "strategy": strategy,
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals(strategy=strategy)
    total = len(journals)
    wins = sum(1 for j in journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
    losses = sum(1 for j in journals if j.result and j.result.upper() in ("LOSS", "FAIL"))

    by_instrument = {}
    for instrument in set(j.instrument for j in journals if j.instrument):
        i_journals = [j for j in journals if j.instrument == instrument]
        i_total = len(i_journals)
        i_wins = sum(1 for j in i_journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
        by_instrument[instrument] = {
            "trades": i_total,
            "wins": i_wins,
            "win_rate": round(i_wins / i_total * 100, 2) if i_total > 0 else 0,
        }

    result.update({
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        "by_instrument": by_instrument,
    })

    return result


def intelligence_regime(regime: str) -> Dict[str, Any]:
    """Per-regime statistics."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "regime": regime,
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = [j for j in _get_journals() if j.market_regime and j.market_regime.upper() == regime.upper()]
    total = len(journals)

    if total == 0:
        result["data_status"] = "INSUFFICIENT_DATA"
        result["message"] = f"No trades in {regime} regime"
        return result

    wins = sum(1 for j in journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
    by_strategy: Dict[str, Dict[str, Any]] = {}
    for strategy in set(j.strategy for j in journals if j.strategy):
        s_journals = [j for j in journals if j.strategy == strategy]
        s_total = len(s_journals)
        s_wins = sum(1 for j in s_journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
        by_strategy[strategy] = {
            "trades": s_total,
            "wins": s_wins,
            "win_rate": round(s_wins / s_total * 100, 2) if s_total > 0 else 0,
        }

    result.update({
        "total_trades": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        "by_strategy": by_strategy,
    })

    return result


def intelligence_direction(direction: str) -> Dict[str, Any]:
    """Per-direction statistics."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "direction": direction.upper(),
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = [j for j in _get_journals() if j.direction and j.direction.upper() == direction.upper()]
    total = len(journals)

    if total == 0:
        result["data_status"] = "INSUFFICIENT_DATA"
        return result

    wins = sum(1 for j in journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
    avg_risk = _avg(journals, "risk_actual")

    result.update({
        "total_trades": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        "avg_risk_actual": avg_risk,
    })

    return result


def intelligence_time_of_day() -> Dict[str, Any]:
    """Time-of-day behavior analysis."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals()
    time_slots: Dict[str, List[TradeJournalRecord]] = {
        "0930-1100": [], "1100-1400": [], "1400-1500": [], "1500_CLOSE": [], "UNKNOWN": [],
    }

    for j in journals:
        hour = _extract_hour(j.actual_entry_at)
        slot = _extract_time_of_day(hour)
        if slot not in time_slots:
            slot = "OTHER"
        if slot not in time_slots:
            time_slots[slot] = []
        time_slots.setdefault(slot, []).append(j)

    time_stats: Dict[str, Dict[str, Any]] = {}
    for slot, slot_journals in time_slots.items():
        if not slot_journals:
            continue
        total = len(slot_journals)
        wins = sum(1 for j in slot_journals if j.result and j.result.upper() in ("WIN", "PROFIT"))
        time_stats[slot] = {
            "trades": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
        }

    result["time_slots"] = time_stats
    return result


def intelligence_adherence(instrument: str = None) -> Dict[str, Any]:
    """Entry-window, confirmation, stop/target adherence."""
    sample = _sample_size(instrument=instrument)
    sufficient = _sufficient(instrument=instrument)

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals(instrument=instrument)
    entry_window_violations = 0
    confirmation_violations = 0
    stop_violations = 0
    target_hits = 0
    entry_different = 0

    for j in journals:
        if j.actual_entry_at and j.entry_window_start and j.entry_window_end:
            if not (j.entry_window_start <= j.actual_entry_at <= j.entry_window_end):
                entry_window_violations += 1

        if j.actual_entry_at and j.confirmation_at:
            if j.actual_entry_at < j.confirmation_at:
                confirmation_violations += 1

        if j.stop is not None and j.actual_exit is not None:
            if j.direction == "LONG" and j.actual_exit > j.stop:
                stop_violations += 1
            elif j.direction == "SHORT" and j.actual_exit < j.stop:
                stop_violations += 1

        if j.target is not None and j.actual_exit is not None:
            if j.direction == "LONG" and j.actual_exit >= j.target:
                target_hits += 1
            elif j.direction == "SHORT" and j.actual_exit <= j.target:
                target_hits += 1

        if j.planned_entry is not None and j.actual_entry is not None:
            if abs(j.planned_entry - j.actual_entry) > 0.01:
                entry_different += 1

    traded_count = sum(1 for j in journals if j.user_action == "TRADED")
    total = len(journals)

    result.update({
        "total_trades": total,
        "entry_window_violations": entry_window_violations,
        "confirmation_violations": confirmation_violations,
        "stop_violations": stop_violations,
        "target_hits": target_hits,
        "entry_different": entry_different,
        "entry_window_rate": round(1 - entry_window_violations / max(traded_count, 1), 4),
        "confirmation_rate": round(1 - confirmation_violations / max(traded_count, 1), 4),
        "stop_hold_rate": round(1 - stop_violations / max(traded_count, 1), 4),
        "target_hit_rate": round(target_hits / max(traded_count, 1), 4),
    })

    return result


def intelligence_behavior() -> Dict[str, Any]:
    """Manual/early/late exit patterns, risk-sizing behavior."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals()
    manual_exits = 0
    early_exits = 0
    late_exits = 0
    risk_over = 0
    risk_under = 0
    risk_within = 0

    for j in journals:
        if j.user_action == "TRADED" and j.actual_exit is not None and j.target is not None and j.stop is not None:
            if j.direction == "LONG":
                if j.actual_exit >= j.target:
                    manual_exits += 1
                elif j.actual_exit <= j.stop:
                    pass
                else:
                    manual_exits += 1
            else:
                if j.actual_exit <= j.target:
                    manual_exits += 1
                elif j.actual_exit >= j.stop:
                    pass
                else:
                    manual_exits += 1

        if j.planned_entry is not None and j.actual_entry is not None:
            if j.direction == "LONG":
                if j.actual_entry > j.planned_entry * 1.001:
                    early_exits += 1
                elif j.actual_entry < j.planned_entry * 0.999:
                    early_exits += 1
            else:
                if j.actual_entry < j.planned_entry * 0.999:
                    early_exits += 1
                elif j.actual_entry > j.planned_entry * 1.001:
                    early_exits += 1

        if j.risk_planned is not None and j.risk_actual is not None and j.risk_planned > 0:
            ratio = j.risk_actual / j.risk_planned
            if ratio > 1.05:
                risk_over += 1
            elif ratio < 0.95:
                risk_under += 1
            else:
                risk_within += 1

    traded = sum(1 for j in journals if j.user_action == "TRADED")

    result.update({
        "total_trades": len(journals),
        "traded": traded,
        "exit_type_distribution": {
            "target": sum(1 for j in journals if j.actual_exit is not None and j.target is not None
                          and (j.direction == "LONG" and j.actual_exit >= j.target or
                               j.direction == "SHORT" and j.actual_exit <= j.target)),
            "stop": sum(1 for j in journals if j.actual_exit is not None and j.stop is not None
                        and (j.direction == "LONG" and j.actual_exit <= j.stop or
                             j.direction == "SHORT" and j.actual_exit >= j.stop)),
            "manual": manual_exits,
        },
        "risk_distribution": {
            "within_5pct": risk_within,
            "exceeded": risk_over,
            "under": risk_under,
        },
    })

    return result


def intelligence_compliance() -> Dict[str, Any]:
    """Compliance analysis: WAIT, NO_SETUP, after invalidation, skipped."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals()
    categories = classify_all_journals()

    result.update({
        "traded_when_was_wait": len(categories["traded_wait"]),
        "traded_no_setup": len(categories["traded_no_setup"]),
        "skipped_valid_setup": len(categories["skipped_valid_setup"]),
        "correctly_skipped_wait": len(categories["correctly_skipped_wait"]),
        "traded_after_invalidation": len(categories["traded_after_invalidation"]),
        "entered_before_confirmation": len(categories["entered_before_confirmation"]),
        "outcome_mismatch": len(categories["outcome_mismatch"]),
        "exited_before_stop": len(categories["exited_before_stop"]),
        "exited_at_target": len(categories["exited_at_target"]),
    })

    return result


def intelligence_mistakes() -> Dict[str, Any]:
    """Recurring mistake patterns."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = [j for j in _get_journals() if j.mistake]
    mistake_patterns = Counter(j.mistake.lower().strip() for j in journals if j.mistake)

    result["total_trades_with_mistakes"] = len(journals)
    result["mistake_patterns"] = dict(mistake_patterns.most_common(20))

    return result


def intelligence_setup_adherence(instrument: str = None) -> Dict[str, Any]:
    """TradingAI outcome vs user outcome comparison."""
    sample = _sample_size(instrument=instrument)
    sufficient = _sufficient(instrument=instrument)

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = _get_journals(instrument=instrument)
    ai_correct = 0
    ai_wrong = 0
    ai_neutral = 0

    for j in journals:
        comparison = get_detailed_comparison(j.journal_id)
        if comparison:
            match = comparison.get("setup_vs_user_outcome", {}).get("outcome_match")
            if match == "MATCH":
                ai_correct += 1
            elif match == "MISMATCH":
                ai_wrong += 1
            elif match == "PARTIAL":
                ai_neutral += 1

    total = len(journals)
    result.update({
        "total_trades": total,
        "ai_outcome_correct": ai_correct,
        "ai_outcome_wrong": ai_wrong,
        "ai_outcome_partial": ai_neutral,
        "ai_accuracy": round(ai_correct / max(total, 1) * 100, 2),
    })

    return result


def intelligence_risk_behavior() -> Dict[str, Any]:
    """Planned vs actual risk behavior analysis."""
    sample = _sample_size()
    sufficient = _sufficient()

    result: Dict[str, Any] = {
        "data_status": "SUFFICIENT_DATA" if sufficient else "INSUFFICIENT_DATA",
        "sample_size": sample,
        "minimum_required": MIN_SAMPLE_SIZE,
    }

    if not sufficient:
        result["message"] = f"Need {MIN_SAMPLE_SIZE} trades, have {sample}"
        return result

    journals = [j for j in _get_journals() if j.user_action == "TRADED" and j.risk_planned and j.risk_actual]
    total = len(journals)

    if total == 0:
        result["data_status"] = "INSUFFICIENT_DATA"
        result["message"] = "No traded trades with risk data"
        return result

    diffs = [j.risk_actual / j.risk_planned for j in journals if j.risk_planned > 0]
    avg_ratio = sum(diffs) / len(diffs) if diffs else 0
    max_ratio = max(diffs) if diffs else 0
    min_ratio = min(diffs) if diffs else 0

    result.update({
        "total_trades": total,
        "avg_risk_ratio": round(avg_ratio, 4),
        "max_risk_ratio": round(max_ratio, 4),
        "min_risk_ratio": round(min_ratio, 4),
        "avg_risk_planned": _avg(journals, "risk_planned"),
        "avg_risk_actual": _avg(journals, "risk_actual"),
    })

    return result
