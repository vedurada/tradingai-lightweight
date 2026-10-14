"""Isolation tests for the ContrarianMarketAnalyzer + shadow persistence.

Must pass without touching the production database or any trading writer:
canonical CPR unchanged, decision payload hash unchanged, inputs not mutated,
no forbidden imports/writers invoked, VIX/options stay unavailable, shadow
write guard refuses canonical tables, and dry-run performs no DB writes.
"""
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.research import contrarian_analyzer as CA
from scripts import shadow_contrarian as SC

DAY = "2026-10-13"
ROOT = Path(__file__).resolve().parent.parent


def candle(hm, o, h, l, c):
    return {"timestamp": f"{DAY}T{hm}:00+05:30", "open": o, "high": h,
            "low": l, "close": c, "volume": 0, "is_complete": 1}


def bars():
    return [candle("09:15", 22560, 22580, 22540, 22560),
            candle("09:20", 22570, 22645, 22555, 22645),
            candle("09:25", 22640, 22650, 22500, 22510),
            candle("09:30", 22500, 22520, 22480, 22510)]


def decision():
    cpr = {
        "available": True, "session": "2026-10-10", "pivot": 22516.67,
        "bc": 22500.0, "tc": 22633.33, "width_pct": 0.59, "cpr_type": "NORMAL",
        "s1": 22433.33, "s2": 22400.0, "r1": 22633.33, "r2": 22666.67,
        "prev_high": 22600.0, "prev_low": 22400.0, "prev_close": 22550.0,
        "gap_points": 20.0, "gap_direction": "NEUTRAL",
        "price_position": "INSIDE_CPR", "virgin": True, "day_open": 22570.0,
    }
    return {
        "instrument": "NIFTY", "timestamp": f"{DAY}T09:35:00+05:30",
        "cpr": cpr, "gap_direction": "NEUTRAL", "gap_points": 20.0,
        "market_bias": "BULLISH", "market_regime": "RANGING",
        "volatility_state": "NORMAL", "strategy": "BULL_PUT_SPREAD",
        "strategy_direction": "BULLISH", "decision": "TRADE", "atr": None,
        "trade": {"direction": "BULLISH", "level": "S1",
                  "entry_time": f"{DAY}T09:20:00+05:30"},
    }


def payload_hash(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode()
    ).hexdigest()


FORBIDDEN_IMPORTS = (
    "from app.decision", "from app.live", "from app.api",
    "from app.strategies", "from app.options", "from app.core.qualification",
    "from app.core.db", "from app.core.config", "from app.core.decision_state",
    "from app.core.decision_trace", "from app.market", "from scripts.tg_alerts",
    "from scripts.paper_confluence", "from scripts.mistake_guard",
    "from scripts.loss_memory", "from scripts.learn_losses",
    "from app.research.cpr_strategy_engine",
)


class CanonicalUnaffectedTests(unittest.TestCase):
    def test_cpr_engine_outputs_untouched(self):
        src = (ROOT / "app" / "research" / "contrarian_analyzer.py").read_text()
        # The pure analyzer must never recompute CPR.
        self.assertNotIn("calculate_cpr", src)
        self.assertNotIn("classify_gap", src)
        self.assertNotIn("is_virgin_cpr", src)

    def test_decision_payload_hash_unchanged_after_analyze(self):
        d = decision()
        before = payload_hash(copy.deepcopy(d))
        CA.analyze("NIFTY", d, bars())
        self.assertEqual(payload_hash(d), before)

    def test_candle_input_not_mutated(self):
        rows = bars()
        before = payload_hash(copy.deepcopy(rows))
        CA.analyze("NIFTY", decision(), rows)
        self.assertEqual(payload_hash(rows), before)


class ImportIsolationTests(unittest.TestCase):
    def test_pure_module_has_no_forbidden_imports(self):
        src = (ROOT / "app" / "research" / "contrarian_analyzer.py").read_text()
        lowered = src.lower()
        for token in (t.lower() for t in FORBIDDEN_IMPORTS):
            self.assertNotIn(token, lowered, token)
        # Also no network / notification / DB socket modules.
        for token in ("import requests", "import sqlite3", "import smtplib",
                      "import urllib", "telegram", "http", "socket"):
            self.assertNotIn(token, lowered, token)


class UnavailableInputTests(unittest.TestCase):
    def test_vix_missing_stays_unavailable(self):
        v = CA.analyze("NIFTY", decision(), bars())
        self.assertIn("VIX", v["unavailable_inputs"])
        self.assertFalse(v["inputs"]["vix_present"])

    def test_stale_vix_does_not_count(self):
        v = CA.analyze("NIFTY", decision(), bars(),
                       vix_evidence={"timestamp": f"{DAY}T08:00:00+05:30",
                                     "value": 14.5})
        self.assertIn("VIX", v["unavailable_inputs"])
        self.assertFalse(v["inputs"]["vix_present"])

    def test_valid_vix_is_reported_present(self):
        v = CA.analyze("NIFTY", decision(), bars(),
                       vix_evidence={"timestamp": f"{DAY}T09:30:00+05:30",
                                     "value": 14.5})
        self.assertTrue(v["inputs"]["vix_present"])
        self.assertEqual(v["inputs"]["vix_value"], 14.5)
        self.assertNotIn("VIX", v["unavailable_inputs"])


class ShadowWriteIsolationTests(unittest.TestCase):
    def test_write_guard_rejects_canonical_tables(self):
        for tbl in ("paper_align", "paper_trades", "backtest_trades",
                    "qualified_trades", "trade_journal", "rule_registry"):
            with self.assertRaises(RuntimeError):
                SC.assert_own_table(tbl)
        SC.assert_own_table("contrarian_verdicts")  # only the dedicated table

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            dbp = os.path.join(td, "t.db")
            wc = sqlite3.connect(dbp)
            wc.row_factory = sqlite3.Row
            try:
                verdict = CA.analyze("NIFTY", decision(), bars())
                note = SC.write_verdict(wc, verdict, dry_run=True)
                self.assertEqual(note, "DRY_RUN")
                tables = [
                    r["name"] for r in wc.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                self.assertNotIn("contrarian_verdicts", tables)
            finally:
                wc.close()

    def test_persist_creates_only_dedicated_table(self):
        with tempfile.TemporaryDirectory() as td:
            dbp = os.path.join(td, "t.db")
            wc = sqlite3.connect(dbp)
            wc.row_factory = sqlite3.Row
            try:
                verdict = CA.analyze("NIFTY", decision(), bars())
                note = SC.write_verdict(wc, verdict, dry_run=False)
                self.assertEqual(note, "PERSISTED")
                tables = [
                    r["name"] for r in wc.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                self.assertEqual(tables, ["contrarian_verdicts"])
                row = wc.execute(
                    "SELECT methodology_version, instrument_id, assessment_ts, status "
                    "FROM contrarian_verdicts").fetchone()
                self.assertIsNotNone(row)
            finally:
                wc.close()

    def test_duplicate_assessments_are_upserted_not_duplicated(self):
        with tempfile.TemporaryDirectory() as td:
            dbp = os.path.join(td, "t.db")
            wc = sqlite3.connect(dbp)
            try:
                v1 = CA.analyze("NIFTY", decision(), bars())
                SC.write_verdict(wc, v1, dry_run=False)
                SC.write_verdict(wc, v1, dry_run=False)
                n = wc.execute("SELECT COUNT(*) FROM contrarian_verdicts").fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                wc.close()


class ReadOnlyConnectionTests(unittest.TestCase):
    def test_ro_connection_uri_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            dbp = os.path.join(td, "t.db")
            s = sqlite3.connect(dbp)
            s.execute("CREATE TABLE t (x)")
            s.commit()
            s.close()
            ro = SC.ro_conn(dbp)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    ro.execute("INSERT INTO t VALUES (1)")
            finally:
                ro.close()


if __name__ == "__main__":
    unittest.main()