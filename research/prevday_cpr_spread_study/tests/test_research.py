"""Unit tests for the prev-day / CPR direction study (research-only).

Run:  cd /opt/tradingai && python3 -m pytest research/prevday_cpr_spread_study/tests -q
"""
import os
import sys

import pytest

sys.path.insert(0, "/opt/tradingai")

from research.prevday_cpr_spread_study.src import data as D          # noqa: E402
from research.prevday_cpr_spread_study.src import execution as X      # noqa: E402
from research.prevday_cpr_spread_study.src import features as F       # noqa: E402
from research.prevday_cpr_spread_study.src import metrics as M        # noqa: E402
from research.prevday_cpr_spread_study.src import signals as S        # noqa: E402

STUDY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------- CPR
def test_cpr_matches_production_formula():
    """Same arithmetic as app/research/cpr_strategy_engine.calculate_cpr."""
    h, l, c = 23000.0, 22800.0, 22900.0
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = 2.0 * p - bc
    got = F.cpr_from(h, l, c)
    assert got["pp"] == pytest.approx(p)
    assert got["bc"] == pytest.approx(bc)
    assert got["tc"] == pytest.approx(tc)
    assert got["lower_cpr"] == pytest.approx(min(bc, tc))
    assert got["upper_cpr"] == pytest.approx(max(bc, tc))
    assert got["width_pts"] == pytest.approx(abs(tc - bc))


def test_cpr_handles_tc_below_bc():
    got = F.cpr_from(100.0, 90.0, 80.0)     # close far below -> TC < BC
    assert got["upper_cpr"] > got["lower_cpr"]
    assert got["width_pts"] == pytest.approx(got["upper_cpr"] - got["lower_cpr"])


def test_cpr_class_thresholds_match_production():
    assert F.cpr_class(0.10) == "NARROW"
    assert F.cpr_class(0.20) == "NORMAL"
    assert F.cpr_class(0.40) == "WIDE"


# ---------------------------------------------------------------- features
def test_close_location_handles_zero_range():
    bars = [{"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 0.0,
             "hhmm": "09:15", "ts": None, "date": "2026-07-06", "complete": 1}]
    s = F.daily_stats(bars)
    assert s["range"] == 0.0
    assert s["close_location"] == 0.0
    assert s["body_pct"] == 0.0


def test_gap_taxonomy_is_mutually_exclusive():
    g = F.gap_features(23150.0, 23000.0, 23200.0, 22800.0, 22900.0, 23100.0)
    assert g["gap_dir"] == "UP"
    assert g["cpr_pos"] == "ABOVE_CPR"
    assert g["prev_range_pos"] == "INSIDE_RANGE"
    assert g["gap_points"] == pytest.approx(150.0)
    g1 = F.gap_features(23050.0, 23000.0, 23200.0, 22800.0, 22900.0, 23100.0)
    assert g1["cpr_pos"] == "INSIDE_CPR"          # inside CPR -> single label
    g2 = F.gap_features(22700.0, 23000.0, 23200.0, 22800.0, 22900.0, 23100.0)
    assert g2["gap_dir"] == "DOWN"
    assert g2["cpr_pos"] == "BELOW_CPR"
    assert g2["prev_range_pos"] == "BELOW_PDL"


def test_vwap_proxy_is_equal_weight_not_volume_weighted():
    bars = [
        {"o": 100, "h": 102, "l": 98, "c": 100, "v": 0, "hhmm": "09:15",
         "ts": None, "date": "d", "complete": 1},
        {"o": 100, "h": 110, "l": 99, "c": 108, "v": 0, "hhmm": "09:20",
         "ts": None, "date": "d", "complete": 1},
    ]
    ser = F.vwap_proxy_series(bars)
    tp1 = (102 + 98 + 100) / 3.0
    tp2 = (110 + 99 + 108) / 3.0
    assert ser[0] == pytest.approx(tp1)
    assert ser[1] == pytest.approx((tp1 + tp2) / 2.0)


def test_opening_range_requires_complete_bars():
    bars = [{"o": 100, "h": 101, "l": 99, "c": 100, "v": 0, "hhmm": "09:15",
             "ts": None, "date": "d", "complete": 0}]
    assert F.opening_range(bars, 3) is None


# ------------------------------------------------------------------ signals
def _ctx(bars, **kw):
    ctx = {
        "session_date": "2026-07-07", "bars": bars,
        # non-degenerate CPR: upper 23000, lower 22933.33
        "cpr": F.cpr_from(23200.0, 22800.0, 22900.0),
        "pivots": F.pivots_from(23200.0, 22800.0, 22900.0),
        "pd_high": 23200.0, "pd_low": 22800.0, "pd_close": 22900.0,
        "pd_close_location": 0.5, "pd_higher_low": True, "pd_higher_high": False,
        "pd_day_type": "NORMAL", "pd_structure": "LH_HL",
        "gap_dir": "UP", "cpr_pos": "ABOVE_CPR", "prev_range_pos": "INSIDE_RANGE",
        "gap_points": 10.0, "gap_cell": "UP|ABOVE_CPR", "prev_atr5m": 20.0,
    }
    ctx.update(kw)
    return ctx


def _bars(n=8, start="09:15"):
    from datetime import datetime, timedelta
    out = []
    t = datetime(2026, 7, 7, 9, 15)
    for i in range(n):
        out.append({"o": 22950.0, "h": 22970.0, "l": 22930.0, "c": 22960.0,
                    "v": 0.0, "hhmm": (t + timedelta(minutes=5 * i)).strftime("%H:%M"),
                    "ts": t + timedelta(minutes=5 * i), "date": "2026-07-07",
                    "complete": 1})
    return out


def test_entry_is_next_bar_open_not_signal_close():
    bars = _bars()
    for i in range(3, len(bars)):
        bars[i]["c"] = 23050.0            # closes above upper CPR (23000)
    ctx = _ctx(bars)
    sig = S.run_model(ctx, "B", {"accept2": False})
    assert sig["direction"] == "BULLISH"
    assert sig["signal_bar_idx"] == 3
    assert sig["entry_bar_idx"] == 4
    assert sig["entry_ref_open"] == bars[4]["o"]
    assert sig["entry_ref_open"] != bars[3]["c"]


def test_accept2_requires_two_consecutive_closes():
    bars = _bars()
    bars[3]["c"] = 23050.0          # break above upper CPR (23000)
    bars[4]["c"] = 22950.0          # back inside -> no acceptance
    sig = S.run_model(_ctx(bars), "B", {"accept2": True})
    assert sig["direction"] == "NO_TRADE"
    assert sig["reason"] == "NO_CPR_BREAK"


def test_no_trade_reason_codes_are_closed_taxonomy():
    ctx = _ctx(_bars())
    for m in ("A", "B", "C", "D", "E", "F"):
        sig = S.run_model(ctx, m, {})
        if sig["direction"] == "NO_TRADE":
            assert sig["reason"] in S.REASONS


def test_model_a_neutral_previous_day_is_no_trade():
    ctx = _ctx(_bars(), pd_close_location=0.5, pd_higher_low=False)
    sig = S.run_model(ctx, "A", {"th": 0.7})
    assert sig["direction"] == "NO_TRADE"
    assert sig["reason"] == "PREV_DAY_NEUTRAL"


def test_model_e_breakout_needs_follow_through():
    bars = _bars(10)
    orr = F.opening_range(bars, 3)
    bars[3]["c"] = orr["or_high"] + 5.0     # break
    bars[3]["h"] = orr["or_high"] + 5.0
    bars[4]["c"] = orr["or_high"] - 5.0     # failed follow-through
    bars[4]["h"] = orr["or_high"] - 5.0
    sig = S.run_model(_ctx(bars), "E", {"levels": ["OR15"], "retest": False})
    assert sig["direction"] == "NO_TRADE"
    assert sig["reason"] == "NO_BREAK"


# ---------------------------------------------------------------- execution
def test_conservative_stop_first_inside_one_bar():
    bars = _bars(6)
    bars[1]["l"] = 22000.0     # stop hit
    bars[1]["h"] = 24000.0     # target also inside the same bar
    sig = {"model": "T", "direction": "BULLISH", "signal_bar_idx": 0,
           "entry_bar_idx": 1, "entry_ref_open": bars[1]["o"],
           "invalidation": 22800.0}
    ctx = _ctx(bars)
    t = X.simulate(ctx, sig, {"type": "PCT", "value": 0.005},
                   {"type": "R", "value": 1.0}, time_exit="EOD")
    assert t["exit_reason"] == "STOP"


def test_gap_through_stop_fills_at_open():
    """A bar that OPENS beyond the stop is filled at the open (worse)."""
    bars = _bars(6)
    bars[2]["o"] = 22500.0          # opens below the stop -> gap fill
    bars[2]["l"] = 22400.0
    bars[2]["h"] = 22550.0
    sig = {"model": "T", "direction": "BULLISH", "signal_bar_idx": 0,
           "entry_bar_idx": 1, "entry_ref_open": bars[1]["o"],
           "invalidation": 22800.0}
    t = X.simulate(_ctx(bars), sig, {"type": "PCT", "value": 0.005},
                   {"type": "R", "value": 1.0}, time_exit="EOD")
    assert t["exit_reason"] == "STOP_GAP"
    assert t["exit_price"] == 22500.0
    assert t["r"] < -1.0                        # worse than the nominal stop


def test_eod_exit_uses_1520_open():
    from datetime import datetime, timedelta
    bars = []
    t = datetime(2026, 7, 7, 9, 15)
    for i in range(75):
        bars.append({"o": 22950.0, "h": 22960.0, "l": 22940.0, "c": 22950.0,
                     "v": 0.0, "hhmm": (t + timedelta(minutes=5 * i)).strftime("%H:%M"),
                     "ts": t + timedelta(minutes=5 * i), "date": "2026-07-07",
                     "complete": 1})
    sig = {"model": "T", "direction": "BULLISH", "signal_bar_idx": 0,
           "entry_bar_idx": 1, "entry_ref_open": bars[1]["o"],
           "invalidation": 22800.0}
    tr = X.simulate(_ctx(bars), sig, {"type": "PCT", "value": 0.005},
                    {"type": "R", "value": 2.0}, time_exit="EOD")
    assert tr["exit_reason"] == "TIME_EXIT"
    assert tr["exit_price"] == bars[73]["o"]      # 15:20 bar open


# ------------------------------------------------------------------ metrics
def test_wilson_ci_brackets_point_estimate():
    p, lo, hi = M.wilson_ci(7, 10)
    assert lo < p < hi
    assert 0.0 <= lo and hi <= 1.0


def test_block_bootstrap_is_deterministic():
    rows = [("2026-07-07", 1, 0.5), ("2026-07-08", 1, -0.2),
            ("2026-07-09", 1, 1.0), ("2026-07-10", 1, 0.3)]
    a = M.block_bootstrap(rows, n_boot=200, seed=123)
    b = M.block_bootstrap(rows, n_boot=200, seed=123)
    assert a == b
    assert a["p_value"] is not None


def test_max_drawdown_peak_to_trough():
    mdd, ln, peak, trough = M.max_drawdown(
        [("a", 1.0), ("b", 3.0), ("c", 1.0), ("d", 2.0)])
    assert mdd == pytest.approx(2.0)
    assert peak == "b" and trough == "c"


# --------------------------------------------------------------------- data
def test_calendar_marks_the_three_absent_weekdays_as_holidays():
    for d in ("2026-09-14", "2026-10-02", "2026-10-20"):
        assert not D.is_session(d)


def test_snapshot_is_read_only_source():
    assert D.PROD_DB.endswith("tradingai.db")
    con = D.connect(D.PROD_DB)
    try:
        with pytest.raises(Exception):
            con.execute("create table if not exists __write_probe (x int)")
    finally:
        con.close()
