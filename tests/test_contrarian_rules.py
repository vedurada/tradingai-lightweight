"""Unit tests for ContrarianMarketAnalyzer rule logic (pure, additive).

Covers rules R1-R8 from the approved Phase 2 design: attempt (with the prior
inside-window requirement), sustained acceptance, failed move (incl. trapped
momentum), gap continuation/reversal, extension, CPR regime context, and the
insufficient-data state. Deterministic, no I/O.
"""
import copy
import unittest

from app.research import contrarian_analyzer as CA

DAY = "2026-10-13"


def candle(hm, o, h, l, c):
    return {"timestamp": f"{DAY}T{hm}:00+05:30", "open": o, "high": h,
            "low": l, "close": c, "volume": 0, "is_complete": 1}


def cpr_bull():
    # Previous session: high 22600 low 22400 close 22550 -> PP=22516.67,
    # TC=22633.33, BC=22500.00, width=133.33, NORMAL type.
    return {
        "available": True, "session": "2026-10-10", "pivot": 22516.67,
        "bc": 22500.0, "tc": 22633.33, "width_pct": 0.59, "cpr_type": "NORMAL",
        "s1": 22433.33, "s2": 22400.0, "r1": 22633.33, "r2": 22666.67,
        "prev_high": 22600.0, "prev_low": 22400.0, "prev_close": 22550.0,
        "gap_points": 20.0, "gap_direction": "BULLISH", "price_position": "INSIDE_CPR",
        "virgin": True, "day_open": 22570.0,
    }


def decision(extra=None):
    d = {
        "instrument": "NIFTY",
        "timestamp": f"{DAY}T09:35:00+05:30",
        "cpr": cpr_bull(),
        "gap_direction": "BULLISH",
        "gap_points": 20.0,
        "market_bias": "BULLISH",
        "market_regime": "RANGING",
        "volatility_state": "NORMAL",
        "strategy": "BULL_PUT_SPREAD",
        "strategy_direction": "BULLISH",
        "decision": "TRADE",
        "atr": None,
        "trade": {"direction": "BULLISH", "level": "S1",
                  "entry_time": f"{DAY}T09:20:00+05:30"},
    }
    if extra:
        d.update(extra)
    return d


def decision_flat_gap():
    """Same canonical snapshot but with a NEUTRAL gap (isolates level rules)."""
    d = decision()
    c = copy.deepcopy(d["cpr"])
    c["gap_direction"] = "NEUTRAL"
    c["gap_points"] = 0.0
    c["day_open"] = 22550.0
    d["cpr"] = c
    d["gap_direction"] = "NEUTRAL"
    d["gap_points"] = 0.0
    return d


def bars_from(rows):
    return [candle(*r) for r in rows]


class OutputContractTests(unittest.TestCase):
    def test_output_has_all_required_keys(self):
        v = CA.analyze("NIFTY", decision(), bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22565, 22585, 22550, 22570),
            ("09:25", 22570, 22590, 22555, 22575),
            ("09:30", 22575, 22595, 22560, 22580),
            ("09:35", 22580, 22600, 22565, 22585),
        ]))
        for key in (
            "methodology_version", "instrument", "assessment_ts", "data_timestamp",
            "bar_count", "market_regime_assessment", "prevailing_move",
            "failed_move_evidence", "contrarian_bias", "continuation_bias",
            "conflicting_evidence", "decision", "candidate_setup_type",
            "invalidation_conditions", "risk_notes", "unavailable_inputs", "status",
        ):
            self.assertIn(key, v, key)
        self.assertIn("alignment", v["decision"])
        self.assertIn(v["status"], CA.STATUSES)

    def test_unsupported_instrument_rejected(self):
        with self.assertRaises(ValueError):
            CA.analyze("INDIA_VIX", decision(), [])
        with self.assertRaises(ValueError):
            CA.analyze("gold", decision(), [])

    def test_missing_decision_rejected(self):
        with self.assertRaises(ValueError):
            CA.analyze("NIFTY", None, [])

    def test_not_enough_bars_is_insufficient(self):
        v = CA.analyze("NIFTY", decision(), bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
        ]))
        self.assertEqual(v["status"], CA.INSUFFICIENT_DATA)
        self.assertEqual(v["bar_count"], 1)

    def test_missing_cpr_is_insufficient_and_reported(self):
        bad = decision()
        bad["cpr"] = {"available": False, "reason": "CPR_DATA_UNAVAILABLE"}
        v = CA.analyze("NIFTY", bad, bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22565, 22585, 22550, 22570),
            ("09:25", 22570, 22590, 22555, 22575),
            ("09:30", 22575, 22595, 22560, 22580),
            ("09:35", 22580, 22600, 22565, 22585),
        ]))
        self.assertIn("CPR", v["unavailable_inputs"])
        self.assertIn("ATR", v["unavailable_inputs"])
        self.assertIn("VIX", v["unavailable_inputs"])

    def test_options_metrics_always_unavailable(self):
        v = CA.analyze("NIFTY", decision(), bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22565, 22585, 22550, 22570),
            ("09:25", 22570, 22590, 22555, 22575),
            ("09:30", 22575, 22595, 22560, 22580),
        ]))
        for code in ("PCR", "OI", "MAX_PAIN", "IV", "EXPECTED_MOVE"):
            self.assertIn(code, v["unavailable_inputs"])

    def test_unknown_param_rejected(self):
        with self.assertRaises(ValueError):
            CA.analyze("NIFTY", decision(), [], params={"NOPE": 1})


class AttemptAndSustainTests(unittest.TestCase):
    BU = 0.15 * 133.33  # acceptance buffer from CPR width

    def test_attempt_requires_prior_inside_window(self):
        # Bar 09:30 closes ABOVE TC+buffer but the previous bar (09:25) closed
        # above TC, so no prior-inside-window => no attempt event.
        rows = bars_from([
            ("09:15", 22560, 22640, 22540, 22630),
            ("09:20", 22630, 22650, 22610, 22640),
            ("09:25", 22640, 22660, 22620, 22650),  # already beyond TC
            ("09:30", 22650, 22680, 22630, 22680),  # tries to attempt
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        ev = [e["type"] for e in v["evidence"]]
        self.assertNotIn("SUSTAINED_ACCEPT", ev)
        self.assertNotIn("FAILED_BREAKOUT", ev)

    def test_attempt_with_prior_inside_produces_failed_breakout(self):
        # TC=22633.33, buffer=0.15*133.33=20 -> TC window [22613.3, 22653.3].
        rows = bars_from([
            ("09:15", 22600, 22640, 22560, 22630),   # inside TC window
            ("09:20", 22640, 22670, 22630, 22660),   # beyond TC+buffer (attempt)
            ("09:25", 22650, 22670, 22600, 22620),   # back inside -> FAILED (trap)
            ("09:30", 22610, 22640, 22600, 22615),
        ])
        v = CA.analyze("NIFTY", decision_flat_gap(), rows)
        types = {e["type"]: e for e in v["evidence"]}
        self.assertIn("FAILED_BREAKOUT", types)
        self.assertEqual(types["FAILED_BREAKOUT"]["direction_pressure"], "BEARISH")
        self.assertTrue(types["FAILED_BREAKOUT"]["trap"])  # 09:20 made a session high
        self.assertEqual(v["status"], CA.BEARISH_CONTRARIAN)

    def test_sustained_acceptance_after_attempt(self):
        rows = bars_from([
            ("09:15", 22600, 22640, 22560, 22630),   # inside TC window
            ("09:20", 22640, 22670, 22630, 22660),   # attempt beyond TC+buffer
            ("09:25", 22650, 22680, 22640, 22670),   # sustained #2
            ("09:30", 22660, 22690, 22650, 22680),   # sustained #3
        ])
        v = CA.analyze("NIFTY", decision_flat_gap(), rows)
        types = {e["type"]: e for e in v["evidence"]}
        self.assertIn("SUSTAINED_ACCEPT", types)
        self.assertEqual(types["SUSTAINED_ACCEPT"]["direction_pressure"], "BULLISH")
        self.assertEqual(v["status"], CA.CONTINUATION)

    def test_extension_distance(self):
        rows = bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22570, 22645, 22550, 22645),        # attempt
            ("09:25", 22830, 22860, 22800, 22850),        # beyond TC+XEXT*width
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        self.assertIn("EXTENSION", [e["type"] for e in v["evidence"]])

    def test_failed_breakdown_pressure_bullish(self):
        rows = bars_from([
            ("09:15", 22510, 22560, 22495, 22510),  # inside BC window
            ("09:20", 22545, 22570, 22395, 22390),  # breakdown below BC-buffer
            ("09:25", 22400, 22510, 22380, 22500),  # back inside -> failed down
            ("09:30", 22500, 22520, 22480, 22510),
        ])
        v = CA.analyze("NIFTY", decision_flat_gap(), rows)
        types = {e["type"]: e for e in v["evidence"]}
        self.assertIn("FAILED_BREAKDOWN", types)
        self.assertEqual(types["FAILED_BREAKDOWN"]["direction_pressure"], "BULLISH")
        self.assertEqual(v["status"], CA.BULLISH_CONTRARIAN)


class GapTests(unittest.TestCase):
    def test_gap_continuation_bullish_after_four_bars(self):
        rows = bars_from([
            ("09:15", 22570, 22590, 22555, 22580),
            ("09:20", 22580, 22600, 22560, 22585),
            ("09:25", 22585, 22605, 22565, 22590),
            ("09:30", 22590, 22610, 22570, 22595),   # never below 22550
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        types = {e["type"]: e for e in v["evidence"]}
        self.assertIn("GAP_CONTINUATION", types)
        self.assertEqual(types["GAP_CONTINUATION"]["direction_pressure"], "BULLISH")
        self.assertEqual(v["continuation_bias"], "BULLISH")

    def test_gap_continuation_not_knowable_before_fourth_bar(self):
        rows = bars_from([
            ("09:15", 22570, 22590, 22555, 22580),
            ("09:20", 22580, 22600, 22560, 22585),
            ("09:25", 22585, 22605, 22565, 22590),
        ])
        v = CA.analyze("NIFTY", decision(), rows, assessment_ts=f"{DAY}T09:30:00+05:30")
        self.assertNotIn("GAP_CONTINUATION", [e["type"] for e in v["evidence"]])

    def test_gap_up_reversal_fades_to_bearish(self):
        rows = bars_from([
            ("09:15", 22570, 22590, 22555, 22580),
            ("09:20", 22575, 22595, 22520, 22540),  # closes below prev close
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        types = {e["type"]: e for e in v["evidence"]}
        self.assertIn("GAP_REVERSAL", types)
        self.assertEqual(types["GAP_REVERSAL"]["direction_pressure"], "BEARISH")


class MixedEvidenceTests(unittest.TestCase):
    def test_failed_breakdown_and_breakout_coexist_indeterminate(self):
        # BC window [22480,22520], TC window [22613.3,22653.3].
        rows = bars_from([
            ("09:15", 22500, 22560, 22490, 22500),   # inside BC window
            ("09:20", 22520, 22530, 22395, 22395),   # below BC-buffer (down attempt)
            ("09:25", 22420, 22550, 22400, 22510),   # reclaims inside -> FAILED down
            ("09:30", 22540, 22640, 22530, 22640),   # rises into TC window
            ("09:35", 22630, 22670, 22620, 22660),   # above TC+buffer (up attempt)
            ("09:40", 22630, 22660, 22600, 22620),   # back inside TC -> FAILED up
            ("09:45", 22610, 22630, 22590, 22605),
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        self.assertEqual(v["status"], CA.INDETERMINATE)
        self.assertTrue(v["conflicting_evidence"])

    def test_no_events_is_neutral(self):
        rows = bars_from([
            ("09:15", 22560, 22580, 22540, 22560),
            ("09:20", 22565, 22585, 22550, 22570),
            ("09:25", 22570, 22590, 22555, 22575),
            ("09:30", 22575, 22595, 22560, 22580),
            ("09:35", 22580, 22600, 22565, 22585),
        ])
        v = CA.analyze("NIFTY", decision(), rows)
        self.assertEqual(v["status"], CA.NEUTRAL)


class AlignmentTests(unittest.TestCase):
    def test_align_agree_when_contrarian_matches_canonical(self):
        rows = bars_from([
            ("09:15", 22510, 22560, 22495, 22510),
            ("09:20", 22545, 22570, 22395, 22390),  # breakdown attempt
            ("09:25", 22400, 22510, 22380, 22500),  # failed down -> BULLISH
            ("09:30", 22500, 22520, 22480, 22510),
        ])
        v = CA.analyze("NIFTY", decision_flat_gap(), rows)
        # Canonical is BULLISH; a failed breakdown points BULLISH => AGREE.
        self.assertEqual(v["status"], CA.BULLISH_CONTRARIAN)
        self.assertEqual(v["decision"]["alignment"], CA.ALIGN_AGREE)

    def test_align_disagree_when_contrarian_opposes_canonical(self):
        rows = bars_from([
            ("09:15", 22600, 22640, 22560, 22630),   # inside TC window
            ("09:20", 22640, 22670, 22630, 22660),   # breakout attempt
            ("09:25", 22650, 22670, 22600, 22620),   # failed up -> BEARISH
            ("09:30", 22610, 22640, 22600, 22615),
        ])
        v = CA.analyze("NIFTY", decision_flat_gap(), rows)
        self.assertEqual(v["status"], CA.BEARISH_CONTRARIAN)
        self.assertEqual(v["decision"]["alignment"], CA.ALIGN_DISAGREE)

    def test_align_insufficient_when_decision_not_yet_knowable(self):
        rows = bars_from([
            ("09:15", 22540, 22560, 22460, 22545),
            ("09:20", 22545, 22570, 22395, 22390),
            ("09:25", 22400, 22510, 22380, 22500),
            ("09:30", 22500, 22520, 22480, 22510),
        ])
        d = decision()
        d["trade"]["entry_time"] = f"{DAY}T14:00:00+05:30"  # way after assessment
        v = CA.analyze("NIFTY", d, rows, assessment_ts=f"{DAY}T09:35:00+05:30")
        self.assertEqual(v["decision"]["alignment"], CA.ALIGN_INSUFFICIENT)

    def test_align_insufficient_without_decision_direction(self):
        rows = bars_from([
            ("09:15", 22540, 22560, 22460, 22545),
            ("09:20", 22545, 22570, 22395, 22390),
            ("09:25", 22400, 22510, 22380, 22500),
        ])
        d = decision()
        d["strategy_direction"] = None
        d["market_bias"] = "NEUTRAL"
        v = CA.analyze("NIFTY", d, rows)
        self.assertEqual(v["decision"]["alignment"], CA.ALIGN_INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()