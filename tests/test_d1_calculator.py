"""E.2 tests — defined-risk economics endpoint.

Covers:
  1. Every economic figure is delegated to app.options.economics (parity).
  2. The five approved structures all reconcile with the authoritative summary.
  3. Input validation never fabricates a value.
  4. The endpoint is read-only and isolated from trade/alert/db code.
  5. The frontend contains no pricing formula of its own.

These tests never modify app/options/economics.py and never write to the
database or to alert state.
"""
import ast
import hashlib
import pathlib
import re
import unittest

from app.api.app import app
from app.options import economics as authoritative
from app.options.strategy import APPROVED_STRATEGIES

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENDPOINT = "/api/economics/calculate"
TG_STATE = ROOT / "data" / "tg_state.json"

NIFTY = "instrument=NIFTY&expiry=30JAN2026"
# (label, query, expected leg list, expected authoritative calc)
FIXTURES = [
    ("bull_put", NIFTY + "&strategy=BULL_PUT_SPREAD&leg0_type=PE&leg0_strike=26000"
     "&leg0_premium=120&leg1_type=PE&leg1_strike=25500&leg1_premium=45&lots=1",
     [("PE", 26000.0, 120.0), ("PE", 25500.0, 45.0)], authoritative.calc_bull_put_spread),
    ("bull_call", NIFTY + "&strategy=BULL_CALL_SPREAD&leg0_type=CE&leg0_strike=25500"
     "&leg0_premium=180&leg1_type=CE&leg1_strike=26000&leg1_premium=130&lots=1",
     [("CE", 25500.0, 180.0), ("CE", 26000.0, 130.0)], authoritative.calc_bull_call_spread),
    ("bear_call", NIFTY + "&strategy=BEAR_CALL_SPREAD&leg0_type=CE&leg0_strike=26000"
     "&leg0_premium=95&leg1_type=CE&leg1_strike=26500&leg1_premium=45&lots=1",
     [("CE", 26000.0, 95.0), ("CE", 26500.0, 45.0)], authoritative.calc_bear_call_spread),
    ("bear_put", NIFTY + "&strategy=BEAR_PUT_SPREAD&leg0_type=PE&leg0_strike=25500"
     "&leg0_premium=90&leg1_type=PE&leg1_strike=25000&leg1_premium=50&lots=1",
     [("PE", 25500.0, 90.0), ("PE", 25000.0, 50.0)], authoritative.calc_bear_put_spread),
    ("iron_condor", "instrument=BANKNIFTY&expiry=30JAN2026&strategy=IRON_CONDOR"
     "&leg0_type=PE&leg0_strike=52000&leg0_premium=180"
     "&leg1_type=PE&leg1_strike=51000&leg1_premium=110"
     "&leg2_type=CE&leg2_strike=53000&leg2_premium=150"
     "&leg3_type=CE&leg3_strike=54000&leg3_premium=90&lots=1",
     [("PE", 52000.0, 180.0), ("PE", 51000.0, 110.0),
      ("CE", 53000.0, 150.0), ("CE", 54000.0, 90.0)], authoritative.calc_iron_condor),
]

client = app.test_client()


def get(qs):
    r = client.get(ENDPOINT + "?" + qs)
    return r.status_code, r.get_json()


def legs_of(spec, instrument):
    return [{"instrument": instrument, "expiry": "30JAN2026",
             "option_type": t, "strike": k, "bid": p, "ask": p}
            for t, k, p in spec]


class TestEnvelope(unittest.TestCase):
    def test_envelope_shape_and_methods(self):
        r = client.get(ENDPOINT)
        self.assertEqual(r.status_code, 404)  # no instrument supplied
        self.assertEqual(sorted(r.get_json()), ["data", "state", "timestamp"])
        self.assertEqual(client.post(ENDPOINT).status_code, 405)

    def test_state_vocabulary_is_closed(self):
        allowed = {"CALCULATED", "INPUT_REQUIRED", "INVALID_INPUT",
                   "SYSTEM_CALCULATION_ERROR", "UNAVAILABLE"}
        cases = [
            "",                                                        # no params
            "instrument=FOO&strategy=BULL_PUT_SPREAD&expiry=X&lots=1",  # bad instrument
            "instrument=NIFTY&strategy=NOPE&expiry=X&lots=1",           # bad strategy
            NIFTY + "&strategy=BULL_PUT_SPREAD&lots=1",                 # no legs
        ]
        for qs in cases:
            code, j = get(qs)
            self.assertIn(j["state"], allowed, qs)
            self.assertIsNotNone(j["timestamp"], qs)
            self.assertTrue(j["data"]["reasons"], qs)
            self.assertGreaterEqual(code, 400, qs)

    def test_valid_but_unusable_never_defaults_a_price(self):
        code, j = get(NIFTY + "&strategy=BULL_PUT_SPREAD&leg0_type=PE"
                         "&leg0_strike=26000&leg0_premium=100"
                         "&leg1_type=PE&leg1_strike=25500&leg1_premium=100&lots=1")
        self.assertEqual(j["state"], "INVALID_INPUT")
        self.assertNotIn("economics", j["data"])


class TestAuthorityParity(unittest.TestCase):
    def test_endpoint_matches_authoritative_module_exactly(self):
        for label, qs, spec, calc in FIXTURES:
            with self.subTest(label):
                code, j = get(qs)
                self.assertEqual(code, 200, j)
                self.assertEqual(j["state"], "CALCULATED")
                expect = calc(legs_of(spec, "BANKNIFTY" if "BANKNIFTY" in qs else "NIFTY"))
                self.assertEqual(j["data"]["economics"], expect.economics,
                                 "endpoint must not recompute economics")

    def test_leg_prices_are_mid_price_basis(self):
        _, j = get(FIXTURES[0][1])
        for leg in j["data"]["legs"]:
            self.assertEqual(leg["bid"], leg["ask"])
        self.assertEqual(j["data"]["premium_basis"], "MID_PRICE_BID_EQUALS_ASK")

    def test_all_five_structures_covered(self):
        seen = {get(qs)[1]["data"]["strategy"] for _, qs, _, _ in FIXTURES}
        self.assertEqual(seen, {s for s in APPROVED_STRATEGIES})
        self.assertEqual(len(seen), 5)

    def test_lot_size_default_is_authoritative(self):
        _, j = get(FIXTURES[0][1])
        self.assertEqual(j["data"]["lot_size"], authoritative.LOT_SIZES["NIFTY"])
        # not hardcoded in the adapter: changing LOT_SIZES must change it
        _, b = get(FIXTURES[4][1])
        self.assertEqual(b["data"]["lot_size"], authoritative.LOT_SIZES["BANKNIFTY"])

    def test_totals_scale_with_lots(self):
        _, one = get(FIXTURES[0][1])
        qs = FIXTURES[0][1].replace("lots=1", "lots=4")
        _, four = get(qs)
        for a, b in zip(one["data"]["curve"]["pnl_total_rs"],
                        four["data"]["curve"]["pnl_total_rs"]):
            self.assertAlmostEqual(b, a * 4, places=6)


class TestCurve(unittest.TestCase):
    def test_curve_extremes_match_summary(self):
        for label, qs, _, _ in FIXTURES:
            with self.subTest(label):
                _, j = get(qs)
                self.assertTrue(j["data"]["curve_reconciled"], label)
                e = j["data"]["economics"]
                self.assertAlmostEqual(max(j["data"]["curve"]["pnl_pts"]),
                                       e["max_reward"], places=2, msg=label)
                self.assertAlmostEqual(min(j["data"]["curve"]["pnl_pts"]),
                                       -e["max_risk"], places=2, msg=label)

    def test_leg_argument_order_does_not_matter(self):
        fwd = FIXTURES[0]
        rev = ("bull_put_rev", NIFTY + "&strategy=BULL_PUT_SPREAD&leg0_type=PE"
               "&leg0_strike=25500&leg0_premium=45&leg1_type=PE"
               "&leg1_strike=26000&leg1_premium=120&lots=1", None, None)
        _, a = get(fwd[1])
        _, b = get(rev[1])
        self.assertEqual(a["data"]["economics"], b["data"]["economics"])
        self.assertEqual(a["data"]["curve"]["pnl_pts"], b["data"]["curve"]["pnl_pts"])

    def test_curve_is_deterministic(self):
        _, a = get(FIXTURES[0][1])
        _, b = get(FIXTURES[0][1])
        self.assertEqual(a["data"]["curve"], b["data"]["curve"])

    def test_narrow_range_is_flagged_not_faked(self):
        _, j = get(FIXTURES[0][1] + "&range_low=25700&range_high=26100")
        self.assertEqual(j["state"], "CALCULATED")
        self.assertFalse(j["data"]["curve_reconciled"])


class TestValidation(unittest.TestCase):
    BASE = (NIFTY + "&strategy=BULL_PUT_SPREAD&leg0_type=PE&leg0_strike=26000"
            "&leg0_premium=120&leg1_type=PE&leg1_strike=25500"
            "&leg1_premium=45&lots=1")

    def assertRejects(self, qs, code=None):
        status, j = get(qs)
        self.assertIn(j["state"], ("INVALID_INPUT", "INPUT_REQUIRED"), j)
        self.assertNotIn("economics", j["data"])
        if code:
            self.assertEqual(status, code, j)

    def test_rejects_bad_input_without_inventing_values(self):
        for qs in [
            self.BASE.replace("leg0_premium=120", "leg0_premium=-5"),
            self.BASE.replace("leg0_premium=120", "leg0_premium=abc"),
            self.BASE.replace("leg0_strike=26000", "leg0_strike=0"),
            self.BASE.replace("leg0_type=PE", "leg0_type=XX"),
            self.BASE + "&leg2_type=CE&leg2_strike=27000&leg2_premium=10",
            self.BASE.replace("lots=1", "lots=0"),
            self.BASE.replace("lots=1", "lots=-3"),
            self.BASE.replace("lots=1", "lots=1.5"),
            self.BASE + "&points=0",
            self.BASE + "&range_low=90000&range_high=1000",
            self.BASE + "&range_low=abc&range_high=30000",
            self.BASE + "&range_low=25000",
            "instrument=NIFTY&strategy=BULL_PUT_SPREAD&expiry=X&lots=1",
            "instrument=NIFTY&strategy=BULL_PUT_SPREAD&leg0_type=PE&leg0_strike=26000"
            "&leg0_premium=120&leg1_type=PE&leg1_strike=25500&leg1_premium=45",
        ]:
            self.assertRejects(qs)

    def test_rejects_incomplete_iron_condor(self):
        qs = (FIXTURES[4][1].split("&leg2")[0] + "&lots=1")
        self.assertRejects(qs)

    def test_zero_credit_is_rejected_not_shown(self):
        self.assertRejects(self.BASE.replace("leg1_premium=45", "leg1_premium=120"))

    def test_no_probability_or_advice_fields(self):
        _, j = get(FIXTURES[0][1])
        blob = repr(j["data"]).lower()
        for word in ("probability", "confidence", "outlook", "recommend",
                     "target", "expected_move", "bias"):
            self.assertNotIn(word, blob, word)


class TestIsolationAndReadOnly(unittest.TestCase):
    SRC = (ROOT / "app" / "api" / "e2_economics.py").read_text()

    def test_module_imports_no_trade_alert_or_db_code(self):
        # inspect real import statements only (the docstring names these
        # modules precisely to state what is NOT imported)
        tree = ast.parse(self.SRC)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        for forbidden in ("app.core.db", "app.options.engine", "app.live",
                          "app.decision", "app.core.qualification", "app.scenarios",
                          "app.ai", "app.research", "app.paper_trade",
                          "app.options.provider", "app.options.nse_chain",
                          "sqlite3"):
            self.assertNotIn(forbidden, imported,
                             "endpoint must not import %s" % forbidden)
        # and no function-level import of a forbidden module either
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
                self.fail("endpoint uses dynamic import")

    def test_endpoint_does_not_write_alert_state(self):
        before = hashlib.md5(TG_STATE.read_bytes()).hexdigest() if TG_STATE.exists() else None
        for _, qs, _, _ in FIXTURES:
            get(qs)
        get("instrument=FOO&strategy=BULL_PUT_SPREAD")
        after = hashlib.md5(TG_STATE.read_bytes()).hexdigest() if TG_STATE.exists() else None
        self.assertEqual(before, after, "endpoint must not touch alert state")

    def test_readme_of_boundary_present(self):
        self.assertIn("ISOLATION CONTRACT", self.SRC)

    def test_existing_routes_untouched(self):
        rules = {r.rule for r in app.url_map.iter_rules()}
        for frozen in ("/api/decision/<instrument>", "/api/options/<instrument>",
                       "/api/alerts/status", "/api/health", "/api/quote/<instrument>",
                       "/api/backtest/cpr-triggers", "/api/research/scenarios"):
            self.assertIn(frozen, rules)


class TestNoFrontendFormula(unittest.TestCase):
    JS = (ROOT / "frontend" / "fixed-loss-calc.js").read_text()
    HTML = (ROOT / "frontend" / "fixed-loss-options.html").read_text()

    def test_client_calls_the_endpoint(self):
        self.assertIn("/api/economics/calculate", self.JS)
        self.assertIn('method: \'GET\'', self.JS)

    def test_client_has_no_cost_or_lot_constants(self):
        for token in ("STT", "GST", "brokerage", "stamp_duty", "slippage",
                      "charges", "LOT_SIZE", "0.0003", "0.001",
                      "0.18", "0.06", "0.006"):
            self.assertNotIn(token, self.JS, "client must not encode %s" % token)

    def test_client_has_no_pricing_arithmetic(self):
        # no assignment that derives an economic figure from leg prices
        bad = re.findall(r"\+ *-|\* *leg|/ *premium|premium *\+|strike *\*", self.JS)
        self.assertEqual(bad, [], bad)

    def test_page_delegates_and_warns(self):
        self.assertIn("fixed-loss-calc.js", self.HTML)
        self.assertIn("not investment advice", self.HTML.lower())
        self.assertIn("no pricing formula of its own", self.HTML.lower())


if __name__ == "__main__":
    unittest.main()