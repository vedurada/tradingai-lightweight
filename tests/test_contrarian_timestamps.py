"""Causal timestamp tests for the ContrarianMarketAnalyzer.

Covers: future candles cannot influence a historical assessment, knowable_at
cannot precede its evidence, missing next candle yields no fabricated entry,
duplicate/stale/missing/out-of-order inputs are deterministic, and the
first-hour / four-bar gap windows respect real exchange timestamps.
"""
import copy
import hashlib
import unittest

from app.research import contrarian_analyzer as CA
from scripts import contrarian_research as CR

DAY = "2026-10-13"


def candle(hm, o, h, l, c):
    return {"timestamp": f"{DAY}T{hm}:00+05:30", "open": o, "high": h,
            "low": l, "close": c, "volume": 0, "is_complete": 1}


def bars_from(rows):
    return [candle(*r) for r in rows]


def decision():
    cpr = {
        "available": True, "session": "2026-10-10", "pivot": 22516.67,
        "bc": 22500.0, "tc": 22633.33, "width_pct": 0.59, "cpr_type": "NORMAL",
        "s1": 22433.33, "s2": 22400.0, "r1": 22633.33, "r2": 22666.67,
        "prev_high": 22600.0, "prev_low": 22400.0, "prev_close": 22550.0,
        "gap_points": 0.0, "gap_direction": "NEUTRAL",
        "price_position": "INSIDE_CPR", "virgin": True, "day_open": 22550.0,
    }
    return {
        "instrument": "NIFTY", "timestamp": f"{DAY}T09:35:00+05:30",
        "cpr": cpr, "gap_direction": "NEUTRAL", "gap_points": 0.0,
        "market_bias": "BULLISH", "market_regime": "RANGING",
        "volatility_state": "NORMAL", "strategy": "BULL_PUT_SPREAD",
        "strategy_direction": "BULLISH", "decision": "TRADE", "atr": None,
        "trade": {"direction": "BULLISH", "level": "S1",
                  "entry_time": f"{DAY}T09:20:00+05:30"},
    }


def decision_bull_gap():
    d = decision()
    d["cpr"] = dict(d["cpr"])
    d["cpr"]["gap_direction"] = "BULLISH"
    d["cpr"]["gap_points"] = 20.0
    d["cpr"]["day_open"] = 22570.0
    d["gap_direction"] = "BULLISH"
    d["gap_points"] = 20.0
    return d


class CausalAssessmentTests(unittest.TestCase):
    def test_future_candles_cannot_affect_historical_assessment(self):
        early_only = bars_from([
            ("09:15", 22500, 22520, 22490, 22500),
            ("09:20", 22505, 22530, 22500, 22510),
            ("09:25", 22510, 22540, 22505, 22515),
            ("09:30", 22515, 22550, 22510, 22520),
        ])
        full = early_only + bars_from([
            ("09:35", 22680, 22700, 22660, 22690),  # later violent breakout
            ("09:40", 22690, 22710, 22670, 22700),
        ])
        at = f"{DAY}T09:35:00+05:30"
        v_early = CA.analyze("NIFTY", decision(), early_only, assessment_ts=at)
        v_full = CA.analyze("NIFTY", decision(), full, assessment_ts=at)
        self.assertEqual(v_early["status"], v_full["status"])
        self.assertEqual(v_early["bar_count"], 4)
        self.assertEqual(v_full["bar_count"], 4)
        self.assertEqual(
            [e["event_ts"] for e in v_early["evidence"]],
            [e["event_ts"] for e in v_full["evidence"]],
        )

    def test_decision_timestamp_cannot_leak_future_bars(self):
        bars = bars_from([
            ("09:15", 22500, 22520, 22490, 22500),
            ("09:20", 22505, 22530, 22500, 22510),
            ("09:25", 22510, 22540, 22505, 22515),
            ("09:30", 22515, 22550, 22510, 22520),
            ("09:35", 22680, 22700, 22660, 22690),
        ])
        d = decision()
        d["timestamp"] = f"{DAY}T09:25:00+05:30"  # decision dated before 09:30+ bars
        v = CA.analyze("NIFTY", d, bars)  # no explicit assessment
        self.assertLessEqual(v["bar_count"], 3)

    def test_knowable_at_not_before_attempt_evidence(self):
        rows = bars_from([
            ("09:15", 22600, 22640, 22560, 22630),   # inside TC window
            ("09:20", 22640, 22670, 22630, 22660),   # attempt
            ("09:25", 22650, 22670, 22600, 22620),   # failure
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        self.assertTrue(v["evidence"])
        for e in v["evidence"]:
            ev = CA._parse_ts(e["event_ts"])
            ka = CA._parse_ts(e["knowable_at"])
            at = CA._parse_ts(e["attempt_ts"])
            self.assertIsNotNone(ev)
            self.assertEqual(ev, ka)
            if at is not None:
                self.assertLessEqual(at, ka)

    def test_gap_continuation_four_bar_window_is_exact(self):
        rows = bars_from([
            ("09:15", 22580, 22590, 22555, 22585),
            ("09:20", 22585, 22600, 22560, 22590),
            ("09:25", 22590, 22610, 22565, 22595),
            ("09:30", 22595, 22615, 22570, 22600),
            ("09:35", 22600, 22620, 22580, 22610),
        ])
        # Before the 4th bar completes (assessment = 09:30 completion) not knowable.
        v_pre = CA.analyze("NIFTY", decision_bull_gap(), rows, assessment_ts=f"{DAY}T09:30:00+05:30")
        self.assertNotIn("GAP_CONTINUATION", [e["type"] for e in v_pre["evidence"]])
        # At/after 09:35 completion it is knowable.
        v_post = CA.analyze("NIFTY", decision_bull_gap(), rows, assessment_ts=f"{DAY}T09:35:00+05:30")
        self.assertIn("GAP_CONTINUATION", [e["type"] for e in v_post["evidence"]])

    def test_gap_reversal_fires_only_inside_first_hour_window(self):
        quiet = bars_from([
            ("09:15", 22580, 22590, 22555, 22585),
            ("09:20", 22585, 22600, 22560, 22590),
            ("09:25", 22590, 22610, 22565, 22595),
            ("09:30", 22595, 22615, 22570, 22600),
            ("09:35", 22600, 22620, 22580, 22610),
        ])
        # A crossing that completes at 10:30 (10:25 bar) is inside the window.
        v_in = CA.analyze("NIFTY", decision_bull_gap(),
                          quiet + bars_from([("10:25", 22610, 22630, 22480, 22540)]),
                          assessment_ts=f"{DAY}T10:30:00+05:30")
        self.assertIn("GAP_REVERSAL", [e["type"] for e in v_in["evidence"]])
        # A crossing that completes at 10:40 (10:35 bar) is OUTSIDE the window.
        v_out = CA.analyze("NIFTY", decision_bull_gap(),
                           quiet + bars_from([("10:35", 22610, 22630, 22480, 22540)]),
                           assessment_ts=f"{DAY}T11:00:00+05:30")
        self.assertNotIn("GAP_REVERSAL", [e["type"] for e in v_out["evidence"]])


class DeterministicInputTests(unittest.TestCase):
    def test_out_of_order_and_duplicate_bars_deterministic(self):
        rows = bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22570, 22645, 22555, 22645),
            ("09:25", 22640, 22650, 22500, 22510),
        ])
        shuffled = [rows[2], rows[0], rows[2], rows[1]]  # dup + out-of-order
        v1 = CA.analyze("NIFTY", decision(), shuffled)
        v2 = CA.analyze("NIFTY", decision(), rows)
        self.assertEqual(v1["status"], v2["status"])
        self.assertEqual(v1["bar_count"], v2["bar_count"])
        self.assertEqual(v1["inputs"]["duplicates_dropped"], v2["inputs"]["duplicates_dropped"] + 1)

    def test_malformed_completely_invalid_candles_safe(self):
        bad = [None, {"timestamp": "garbage", "open": "x", "close": None}, {}]
        v = CA.analyze("NIFTY", decision(), bad)
        self.assertEqual(v["status"], CA.INSUFFICIENT_DATA)
        self.assertEqual(v["bar_count"], 0)
        self.assertTrue(v["inputs"]["bars_excluded"] >= 3)

    def test_duplicate_keep_last_is_deterministic(self):
        rows = [candle("09:15", 1, 2, 0, 1),
                candle("09:15", 3, 4, 2, 3),
                candle("09:20", 3, 4, 2, 3),
                candle("09:25", 3, 4, 2, 3),
                candle("09:30", 3, 4, 2, 3)]
        v = CA.analyze("NIFTY", decision(), rows)
        self.assertEqual(v["evidence"], [])
        self.assertEqual(v["inputs"]["duplicates_dropped"], 1)
        self.assertEqual(v["bar_count"], 4)


class OutcomeCausalityTests(unittest.TestCase):
    def test_missing_next_candle_produces_no_fabricated_entry(self):
        # Signal completes at 09:25 (assessment 09:30); the 09:30 bar open is the
        # required entry candle. If it is absent, no entry may be fabricated.
        bars = bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22570, 22645, 22555, 22645),
            ("09:25", 22640, 22650, 22500, 22510),
            # note: no 09:30 candle
        ])
        out = CR.simulate_outcome(bars, f"{DAY}T09:30:00+05:30", "BEARISH")
        self.assertEqual(out["r"], None)
        self.assertEqual(out["reason"], "NEXT_BAR_MISSING")

    def test_entry_window_closed_after_1520(self):
        bars = bars_from([
            ("15:20", 22600, 22620, 22590, 22610),
            ("15:25", 22610, 22630, 22600, 22620),
        ])
        out = CR.simulate_outcome(bars, f"{DAY}T15:20:00+05:30", "BULLISH")
        self.assertEqual(out["reason"], "ENTRY_WINDOW_CLOSED")

    def test_flat_at_1520_open(self):
        bars = bars_from([
            ("09:20", 22600, 22620, 22590, 22610),
            ("09:25", 22610, 22630, 22600, 22620),
            ("15:20", 22450, 22500, 22440, 22490),  # would-be stop gap irrelevant
        ])
        out = CR.simulate_outcome(bars, f"{DAY}T09:20:00+05:30", "BULLISH")
        self.assertEqual(out["reason"], "FLAT_15:20")
        self.assertEqual(out["exit"], 22450.0)
        self.assertEqual(out["entry"], 22600.0)


if __name__ == "__main__":
    unittest.main()