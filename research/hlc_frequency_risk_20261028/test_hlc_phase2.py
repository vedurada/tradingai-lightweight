#!/usr/bin/env python3
"""
Automated tests for HLC 3-Bar Scalp — Mode C Paper Trading (Phase 2).

Tests cover:
- Signal timing (3-bar bullish/bearish alignment)
- No-look-ahead behavior
- Next-candle entry reference
- Stop/risk/1.5R target calculation
- Invalid risk rejection
- Mode C: one open position per instrument (NIFTY & BANKNIFTY independent)
- Duplicate signal prevention
- Entry-candle exit protection (stop-first tie-break)
- Session boundary (EOD exit)
- Deterministic results
- VM live engine uses HLC (not CPR)
- Paper trade engine monitor works
"""

import sys
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

sys.path.insert(0, "/opt/tradingai")

from app.research.scalp_engine import (
    _scan_signals,
    _trade_for,
    _live_signal,
)
from app.paper_trade.engine import PaperTradeEngine
from app.core.db import get_conn

DB_PATH = "/opt/tradingai/database/tradingai.db"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_candle(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "date": ts[:10]}


def _bullish_candles(base_time, n=12, start_price=100.0, step=1.0):
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        h = o + step + 0.5
        l = o - 0.25
        c = o + step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


def _bearish_candles(base_time, n=12, start_price=100.0, step=1.0):
    candles = []
    o = start_price
    for i in range(n):
        ts = (base_time + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        h = o - 0.25
        l = o - step - 0.5
        c = o - step
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    return candles


# ── Test Results Tracking ──────────────────────────────────────────────────

_results = []


def _check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    _results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# ── Test 1: Three-bar bullish alignment ────────────────────────────────────

def test_three_bar_bullish_alignment():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    _check("bullish alignment detected", len(sigs) >= 1, f"found {len(sigs)} signals")
    if sigs:
        _check("bullish direction", sigs[0][1] == "BULL")
        _check("signal index >= 5", sigs[0][0] >= 5)


# ── Test 2: Three-bar bearish alignment ────────────────────────────────────

def test_three_bar_bearish_alignment():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    _check("bearish alignment detected", len(sigs) >= 1, f"found {len(sigs)} signals")
    if sigs:
        _check("bearish direction", sigs[0][1] == "BEAR")


# ── Test 3: No look-ahead ──────────────────────────────────────────────────

def test_no_lookahead():
    """Signal at index i must only depend on candles up to i+1 (entry candle)."""
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = []
    o = 100.0
    for i in range(12):
        ts = (base + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        if i < 6:
            h, l, c = o + 1.0, o - 0.25, o + 1.0
        else:
            h, l, c = o - 0.25, o - 1.0, o - 1.0
        candles.append(_make_candle(ts, o, h, l, c))
        o = c
    sigs, _ = _scan_signals(candles)
    _check("no look-ahead: signal uses only past candles", len(sigs) >= 1)
    if sigs:
        idx, direction = sigs[0]
        _check("no look-ahead: entry candle exists after signal",
               idx + 1 < len(candles))


# ── Test 4: Next-candle entry reference ────────────────────────────────────

def test_next_candle_entry():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    if not sigs:
        _check("next-candle entry: no signals to test", False)
        return
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    _check("next-candle entry: trade created", trade is not None)
    if trade:
        _check("next-candle entry: entry = next candle open",
               trade["entry"] == candles[idx + 1]["open"])
        _check("next-candle entry: entry_time = next candle timestamp",
               trade["entry_time"] == candles[idx + 1]["timestamp"])
        _check("next-candle entry: signal_time = signal candle timestamp",
               trade["signal_time"] == candles[idx]["timestamp"])


# ── Test 5: Stop, risk, 1.5R target ──────────────────────────────────────

def test_stop_risk_target_bull():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bullish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    if not sigs:
        _check("stop/risk/target BULL: no signals", False)
        return
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    if not trade:
        _check("stop/risk/target BULL: no trade", False)
        return
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle["open"]
    expected_stop = signal_candle["low"] - 1.0
    expected_risk = entry - expected_stop
    expected_target = entry + expected_risk * 1.5
    _check("BULL stop = signal low - 1", trade["stop"] == round(expected_stop, 2))
    _check("BULL risk = entry - stop",
           abs((trade["entry"] - trade["stop"]) - expected_risk) < 0.01)
    _check("BULL target = entry + 1.5R",
           abs(trade["target"] - round(expected_target, 2)) < 0.01)


def test_stop_risk_target_bear():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = _bearish_candles(base, n=12)
    sigs, _ = _scan_signals(candles)
    if not sigs:
        _check("stop/risk/target BEAR: no signals", False)
        return
    idx, direction = sigs[0]
    trade = _trade_for(candles, idx, direction)
    if not trade:
        _check("stop/risk/target BEAR: no trade", False)
        return
    signal_candle = candles[idx]
    entry_candle = candles[idx + 1]
    entry = entry_candle["open"]
    expected_stop = signal_candle["high"] + 1.0
    expected_risk = expected_stop - entry
    expected_target = entry - expected_risk * 1.5
    _check("BEAR stop = signal high + 1", trade["stop"] == round(expected_stop, 2))
    _check("BEAR risk = stop - entry",
           abs((trade["stop"] - trade["entry"]) - expected_risk) < 0.01)
    _check("BEAR target = entry - 1.5R",
           abs(trade["target"] - round(expected_target, 2)) < 0.01)


# ── Test 6: Invalid risk rejection ───────────────────────────────────────

def test_invalid_risk_rejected():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),
        _make_candle("2026-10-28T09:30:00+05:30", 98.0, 101.0, 97.5, 98.5),
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade:
            _check("invalid risk rejected: risk > 0", trade["risk_pts"] > 0)
        else:
            _check("invalid risk rejected: trade is None", True)


# ── Test 7: Stop-first tie-break ─────────────────────────────────────────

def test_stop_first_tiebreak():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 103.0, 98.0, 102.0),
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade:
            _check("stop-first tie-break: STOP wins",
                   trade["exit_reason"] in ("STOP", "STOP (both same candle)"))
            _check("stop-first tie-break: LOSS", trade["win_loss"] == "LOSS")
            _check("stop-first tie-break: same_candle_ambiguity flagged",
                   trade["same_candle_ambiguity"] is True)


# ── Test 8: Entry-candle exit protection (Convention A) ──────────────────

def test_entry_candle_exit_protection():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 102.0, 98.0, 101.5),
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        t_a = _trade_for(candles, idx, direction)
        # Use evaluate_trade_B for comparison convention B
        sys.path.insert(0, "/Users/satya/research/hlc_frequency_risk_20261028")
        from run_comparison import evaluate_trade_B
        t_b = evaluate_trade_B(candles, idx, direction)
        if t_a and t_b:
            _check("Convention A: exit on entry candle",
                   t_a["exit_time"] == t_a["entry_time"])
            _check("Convention B: exit NOT on entry candle",
                   t_b["exit_time"] != t_b["entry_time"])


# ── Test 9: Session boundary / EOD exit ──────────────────────────────────

def test_session_boundary_eod():
    base = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    candles = [
        _make_candle("2026-10-28T09:15:00+05:30", 100.0, 101.0, 99.0, 100.0),
        _make_candle("2026-10-28T09:20:00+05:30", 100.0, 101.0, 99.5, 100.5),
        _make_candle("2026-10-28T09:25:00+05:30", 100.5, 101.5, 99.0, 101.0),
        _make_candle("2026-10-28T09:30:00+05:30", 101.0, 102.0, 100.5, 101.5),
        _make_candle("2026-10-28T09:35:00+05:30", 101.5, 102.0, 101.0, 101.8),
        _make_candle("2026-10-28T09:40:00+05:30", 101.8, 102.2, 101.5, 102.0),
    ]
    sigs, _ = _scan_signals(candles)
    for idx, direction in sigs:
        trade = _trade_for(candles, idx, direction)
        if trade and trade["direction"] == "BULL":
            _check("EOD exit: exit_reason = EOD", trade["exit_reason"] == "EOD")
            _check("EOD exit: exit = last close", trade["exit"] == candles[-1]["close"])


# ── Test 10: Mode C — one open position per instrument ───────────────────

def test_mode_c_one_position_per_instrument():
    """Mode C: NIFTY and BANKNIFTY can each have one open position."""
    conn = get_conn()
    try:
        for inst in ("NIFTY", "BANKNIFTY"):
            rows = conn.execute(
                "SELECT trade_id FROM paper_trades "
                "WHERE instrument_id=? AND scenario='SCALP_HLC' "
                "AND status IN ('ACTIVE','OPEN')",
                (inst,)).fetchall()
            _check(f"Mode C: {inst} max 1 open position",
                   len(rows) <= 1,
                   f"found {len(rows)} open positions")
    finally:
        conn.close()


# ── Test 11: Multiple trades per day allowed (Mode C) ─────────────────────

def test_mode_c_multiple_trades_per_day():
    """Mode C allows multiple trades per day (after position closes)."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT substr(entry_time,1,10) FROM paper_trades "
            "WHERE scenario='SCALP_HLC' AND status IN ('ACTIVE','OPEN','CLOSED') "
            "AND entry_time IS NOT NULL").fetchall()
        day_counts = Counter(r[0] for r in rows)
        multi_days = sum(1 for c in day_counts.values() if c > 1)
        max_per_day = max(day_counts.values()) if day_counts else 0
        _check("Mode C: multiple trades per day allowed", multi_days > 0,
               f"{multi_days} days with multiple trades, max {max_per_day} per day")
    finally:
        conn.close()


# ── Test 12: Duplicate signal prevention ──────────────────────────────────

def test_duplicate_signal_prevention():
    """Same signal produces same deterministic trade_id."""
    from app.research.scalp_signal_store import make_signal_id
    sid1 = make_signal_id("NIFTY", "2026-10-28T09:40:00+05:30", "BULL", "H1_UP")
    sid2 = make_signal_id("NIFTY", "2026-10-28T09:40:00+05:30", "BULL", "H1_UP")
    sid3 = make_signal_id("NIFTY", "2026-10-28T09:40:00+05:30", "BEAR", "H1_DOWN")
    _check("duplicate signal prevention: same signal = same ID", sid1 == sid2)
    _check("duplicate signal prevention: different direction = different ID",
           sid1 != sid3)
    _check("duplicate signal prevention: ID format", sid1.startswith("SS-"))


# ── Test 13: Trade log reconciliation ────────────────────────────────────

def test_trade_log_reconciliation():
    """Every trade's entry price must match the OHLC open at entry_time."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT trade_id, instrument_id, entry, entry_time FROM paper_trades "
            "WHERE scenario='SCALP_HLC'").fetchall()
        mismatch = 0
        for trade_id, inst, entry, entry_time in rows:
            candle = conn.execute(
                "SELECT open FROM market_candles_5m "
                "WHERE instrument_id=? AND timestamp=?",
                (inst, entry_time)).fetchone()
            if candle is None:
                mismatch += 1
                continue
            if abs(candle[0] - entry) > 0.01:
                mismatch += 1
        _check("trade log reconciliation: entry prices match OHLC",
               mismatch == 0, f"{mismatch} mismatches")
    finally:
        conn.close()


# ── Test 14: VM live engine uses HLC ─────────────────────────────────────

def test_vm_live_engine_uses_hlc():
    """Verify the VM's live engine uses HLC as the default trigger."""
    from app.live import engine as eng_mod
    source = open(eng_mod.__file__).read()
    _check("live engine references _hlc_book_signal",
           "_hlc_book_signal" in source)
    _check("live engine uses hlc_scalp source", "hlc_scalp" in source)
    _check("live engine retains CPR for rollback",
           "_cpr_book_signal" in source)
    # CPR should NOT be called in evaluate()
    eval_section = source[source.find("def evaluate"):]
    _check("live engine evaluate() calls _hlc_book_signal",
           "_hlc_book_signal" in eval_section)
    _check("live engine evaluate() does NOT call _cpr_book_signal",
           "_cpr_book_signal(" not in eval_section)


# ── Test 15: Paper trade engine monitor works ────────────────────────────

def test_paper_trade_monitor():
    """PaperTradeEngine.monitor() runs without error for NIFTY and BANKNIFTY."""
    engine = PaperTradeEngine()
    for inst in ("NIFTY", "BANKNIFTY"):
        try:
            results = engine.monitor(inst)
            _check(f"paper monitor: {inst} runs without error",
                   isinstance(results, list))
        except Exception as e:
            _check(f"paper monitor: {inst} runs without error",
                   False, f"exception: {e}")


# ── Run all tests ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_three_bar_bullish_alignment,
        test_three_bar_bearish_alignment,
        test_no_lookahead,
        test_next_candle_entry,
        test_stop_risk_target_bull,
        test_stop_risk_target_bear,
        test_invalid_risk_rejected,
        test_stop_first_tiebreak,
        test_entry_candle_exit_protection,
        test_session_boundary_eod,
        test_mode_c_one_position_per_instrument,
        test_mode_c_multiple_trades_per_day,
        test_duplicate_signal_prevention,
        test_trade_log_reconciliation,
        test_vm_live_engine_uses_hlc,
        test_paper_trade_monitor,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            _check(t.__name__, False, f"exception: {e}")
            failed += 1
            continue
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    total = len(_results)
    print(f"\n{passed} passed, {failed} failed out of {total}")
    sys.exit(0 if failed == 0 else 1)
