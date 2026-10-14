"""ContrarianMarketAnalyzer baseline-independence audit tests.

Post-implementation audit: the canonical baseline (paper_align 'plain'
outcome records) must be wholly independent of ContrarianMarketAnalyzer
output. A NEUTRAL/INDETERMINATE/INSUFFICIENT analyzer status must NEVER
re-label a canonical decision or its recorded outcome.

Hermetic: builds a temp-file copy of the two canonical tables
(market_candles_5m, paper_align) and exercises the deployed evaluator
functions read-only. No live production DB is touched.
"""
import os
import random
import sqlite3
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from scripts import contrarian_research as CR  # noqa: E402
from scripts.shadow_contrarian import ro_conn, canonical_decision, completion_iso  # noqa: E402
from app.research import contrarian_analyzer as CA  # noqa: E402

DAYS = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
        "2026-09-25", "2026-09-28", "2026-09-29"]


def _hm(i):
    return f"{9 + (15 + i * 5) // 60:02d}:{(15 + i * 5) % 60:02d}"


def _gen_candles(c, inst, day, base, drift=0.0, seed=3):
    rng = random.Random((hash((inst, day, seed)) % (2 ** 31)))
    o = base + drift
    for j in range(76):
        op = o
        hi = op * (1 + rng.uniform(0, 0.0025))
        lo = op * (1 - rng.uniform(0, 0.0025))
        cl = op + rng.gauss(0, 6)
        ts = f"{day}T{_hm(j)}:00+05:30"
        c.execute(
            "INSERT INTO market_candles_5m VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (f"c-{inst}-{day}-{j}", inst, ts, round(op, 2),
             round(max(op, hi, cl), 2), round(min(op, lo, cl), 2),
             round(cl, 2), 0, "TEST", "LIVE", f"{day}T09:00:00+05:30", day, ))
        o = cl


def _make_db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE market_candles_5m (candle_id TEXT PRIMARY KEY, "
              "instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, "
              "high REAL, low REAL, close REAL, volume INTEGER DEFAULT 0, "
              "source TEXT, data_state TEXT DEFAULT 'LIVE', ingested_at TEXT, "
              "session_id TEXT, is_complete INTEGER DEFAULT 0)")
    c.execute("CREATE UNIQUE INDEX ux_inst_ts ON market_candles_5m(instrument_id, timestamp)")
    c.execute("CREATE TABLE paper_align (session_date TEXT, instrument_id TEXT, "
              "variant TEXT DEFAULT 'aligned', state TEXT, direction TEXT, level TEXT, "
              "entry_time TEXT, entry_price REAL, stop_price REAL, target_price REAL, "
              "exit_time TEXT, exit_price REAL, exit_reason TEXT, r_multiple REAL, "
              "result TEXT, created_at TEXT, PRIMARY KEY (session_date, instrument_id, variant))")
    _gen_candles(c, "NIFTY", "2026-09-17", 22400.0)  # previous day for first session
    for i, day in enumerate(DAYS):
        _gen_candles(c, "NIFTY", day, 22500.0, drift=i * 4.0)
        direction = "BULL" if i % 3 == 0 else "BEAR"
        r = round(random.Random(1000 + i).gauss(0.6, 0.4), 3)
        c.execute(
            "INSERT INTO paper_align VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "NIFTY", "plain", "QUALIFIED", direction,
             "S1" if direction == "BULL" else "R1", f"{day} 09:20", 22500.0,
             22350.0, 22650.0, None, None, None, r,
             "WIN" if r > 0 else "LOSS", f"{day} 09:00"))
    c.commit()
    c.close()


class BaselineIndependenceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tmpdir = tempfile.mkdtemp()
        cls.dbpath = os.path.join(tmpdir, "audit.db")
        _make_db(cls.dbpath)
        cls.conn = ro_conn(cls.dbpath)
        cls.params = CR.default_params()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    # 1. Baseline tally is independent of analyzer output.
    def test_canonical_baseline_reads_only_paper_align(self):
        row, why = CR.evaluate_session(self.conn, "NIFTY", DAYS[2], self.params)
        self.assertIsNotNone(row, why)
        canon = canonical_decision(self.conn, "NIFTY", DAYS[2])
        self.assertEqual(row["canonical_r"], canon["r_multiple"])
        self.assertEqual(row["canonical_dir"], canon["direction"])
        net = CR._net_r(row=row, key="canonical_baseline")
        # Recorded r_multiple is already net of the real system's own costs, so
        # the canonical arm returns it directly (no research-cost re-subtraction).
        self.assertEqual(net, canon["r_multiple"])
        # Analyzer fields are kept in separate attributes.
        self.assertIn("bias", row)
        self.assertIn("alignment", row)
        self.assertIn("canonical_r", row)

    # 2. Collapsing every analyzer status to NEUTRAL cannot change the baseline.
    def test_neutral_analyzer_cannot_change_baseline_wins_losses(self):
        rows = []
        for day in DAYS:
            row, why = CR.evaluate_session(self.conn, "NIFTY", day, self.params)
            if row is None:
                continue
            before = CR._net_r(row=row, key="canonical_baseline")
            altered = dict(row)
            altered["verdict"] = {"status": CA.NEUTRAL}
            altered["bias"] = None
            after = CR._net_r(row=altered, key="canonical_baseline")
            self.assertEqual(before, after)
            rows.append((before, after))
        self.assertTrue(rows)
        for before, after in rows:
            self.assertEqual(before, after)

    # 3. Canonical decisions and historical outcomes remain unchanged by analysis.
    def test_canonical_rows_unchanged_by_analyzer(self):
        for day in DAYS:
            canon_before = canonical_decision(self.conn, "NIFTY", day)
            row, why = CR.evaluate_session(self.conn, "NIFTY", day, self.params)
            canon_after = canonical_decision(self.conn, "NIFTY", day)
            self.assertEqual(canon_before, canon_after)
            self.assertEqual(row["canonical_r"], canon_before["r_multiple"])
            self.assertEqual(row["canonical_dir"], canon_before["direction"])

    # 4. Non-directional statuses map to no bias (never a falsified label).
    def test_non_directional_statuses_carry_no_bias(self):
        self.assertIsNone(CR._verdict_status_bias({"status": CA.NEUTRAL}))
        self.assertIsNone(CR._verdict_status_bias({"status": CA.INDETERMINATE}))
        self.assertIsNone(CR._verdict_status_bias({"status": CA.INSUFFICIENT_DATA}))
        self.assertEqual(
            CR._verdict_status_bias({"status": CA.CONTINUATION, "continuation_bias": "BEARISH"}),
            "BEARISH")

    # 5. The analyzer never mutates candles passed to it.
    def test_analyze_does_not_mutate_candles(self):
        from scripts.shadow_contrarian import load_day_candles
        bars = load_day_candles(self.conn, "NIFTY", DAYS[2])
        snapshot, reason = CR.build_snapshot(
            self.conn, "NIFTY", DAYS[2], completion_iso(bars[3]["timestamp"]))
        self.assertIsNotNone(snapshot, reason)
        frozen = [tuple(b.items()) for b in bars]
        CA.analyze("NIFTY", snapshot, bars)
        self.assertEqual([tuple(b.items()) for b in bars], frozen)


if __name__ == "__main__":
    unittest.main()