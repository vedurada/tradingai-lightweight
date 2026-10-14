"""Focused tests for the live-provenance hard-stop in scripts/shadow_contrarian.py.

These tests never touch the production database: every invocation is pinned to
a private tmp_path SQLite file via --db, and write-capable turns are mocked.
"""

import sqlite3

from scripts import shadow_contrarian as sc

BASE_VERDICT = {
    "instrument": "NIFTY",
    "assessment_ts": "2026-09-10T15:30:00+05:30",
    "data_timestamp": "2026-09-10T15:25:00+05:30",
    "methodology_version": "research-shadow-v1",
    "status": "INDETERMINATE",
    "bar_count": 75,
    "candidate_setup_type": "SUSTAINED_BREAK",
    "decision": {"alignment": "NEUTRAL"},
    "contrarian_bias": None,
    "continuation_bias": None,
    "evidence": [],
    "unavailable_inputs": [],
}


def _verdict(**kw):
    v = dict(BASE_VERDICT)
    v.update(kw)
    return v


def _decision(**kw):
    d = {
        "instrument": "NIFTY",
        "timestamp": "2026-09-10T15:30:00+05:30",
        "price": 100.0,
        "data_status": "RECENT",
        "session": "LIVE",
        "market_bias": "UNAVAILABLE",
        "market_regime": "UNAVAILABLE",
        "cpr": {"available": True, "bc": 90.0, "tc": 110.0, "pp": 100.0,
                "width_pct": 1.0, "cpr_type": "TIGHT"},
        "direction": None,
    }
    d.update(kw)
    return d


def _mock_run_verdict(monkeypatch):
    monkeypatch.setattr(sc, "run_verdict", lambda *a, **kw: _verdict())
    monkeypatch.setattr(sc, "load_day_candles", lambda conn, inst, day: [])


def _precreate(path):
    sqlite3.connect(str(path)).close()
    return path


def _count_rows(path, table="contrarian_verdicts"):
    conn = sqlite3.connect(str(path))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()[0]
        if n == 0:
            return None, 0
        return table, conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
    finally:
        conn.close()


def test_no_date_persist_without_guard_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CONTRARIAN_LIVE_MODE", raising=False)
    monkeypatch.setattr(sc, "_is_live_mode_available", lambda: False)
    dbp = tmp_path / "t.db"
    rc = sc.main(["--instrument", "NIFTY", "--persist", "--db", str(dbp)])
    assert rc == 1
    assert "CONTRARIAN_LIVE_MODE=1" in capsys.readouterr().out
    assert not dbp.exists()


def test_no_date_persist_guard_reconstructed_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sc, "_is_live_mode_available", lambda: True)
    monkeypatch.setattr("app.decision.view.build_decision",
                        lambda inst, **kw: _decision(reconstructed=True))
    dbp = tmp_path / "t.db"
    rc = sc.main(["--instrument", "NIFTY", "--persist", "--db", str(dbp)])
    assert rc == 1
    assert "reconstructed" in capsys.readouterr().out
    assert not dbp.exists()


def test_no_date_live_dry_run_valid_takes_live_collect_without_writing(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sc, "_is_live_mode_available", lambda: True)
    monkeypatch.setattr("app.decision.view.build_decision",
                        lambda inst, **kw: _decision())
    _mock_run_verdict(monkeypatch)
    dbp = _precreate(tmp_path / "t.db")
    rc = sc.main(["--instrument", "NIFTY", "--db", str(dbp)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"mode": "live"' in out
    assert "LIVE_COLLECT" in out
    assert "no database write" in out
    assert _count_rows(dbp, "contrarian_verdicts") == (None, 0)


def test_date_backfill_persist_labels_backfill_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTRARIAN_LIVE_MODE", raising=False)
    monkeypatch.setattr(sc, "_is_live_mode_available", lambda: False)
    monkeypatch.setattr(sc, "build_snapshot",
                        lambda conn, inst, day, iso: (_decision(), None))
    _mock_run_verdict(monkeypatch)
    dbp = _precreate(tmp_path / "t.db")
    rc = sc.main(["--instrument", "NIFTY", "--date", "2026-09-10",
                  "--persist", "--db", str(dbp)])
    assert rc == 0
    assert _count_rows(dbp) == ("contrarian_verdicts", 1)
    conn = sqlite3.connect(str(dbp))
    got = conn.execute(
        "SELECT collection_source, COUNT(*) FROM contrarian_verdicts "
        "GROUP BY collection_source").fetchall()
    conn.close()
    assert got == [("BACKFILL", 1)]

    # idempotency: same primary key re-persisted, still exactly one row
    rc2 = sc.main(["--instrument", "NIFTY", "--date", "2026-09-10",
                   "--persist", "--db", str(dbp)])
    assert rc2 == 0
    assert _count_rows(dbp) == ("contrarian_verdicts", 1)


def test_date_backfill_dry_run_no_write(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTRARIAN_LIVE_MODE", raising=False)
    monkeypatch.setattr(sc, "_is_live_mode_available", lambda: False)
    monkeypatch.setattr(sc, "build_snapshot",
                        lambda conn, inst, day, iso: (_decision(), None))
    _mock_run_verdict(monkeypatch)
    dbp = _precreate(tmp_path / "t.db")
    rc = sc.main(["--instrument", "BANKNIFTY", "--date", "2026-09-10",
                  "--db", str(dbp)])
    assert rc == 0
    assert _count_rows(dbp) == (None, 0)