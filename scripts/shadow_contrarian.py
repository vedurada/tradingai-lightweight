#!/usr/bin/env python3
"""Shadow-only collector for the ContrarianMarketAnalyzer (NIFTY/BANKNIFTY).

Writes ONLY to a dedicated `contrarian_verdicts` table. This script is never
run automatically (no cron, no systemd); explicit invocation only, dry-run
by default unless --no-dry-run / --persist is given.

Usage:
  python3 scripts/shadow_contrarian.py --instrument NIFTY --dry-run
  python3 scripts/shadow_contrarian.py --instrument BANKNIFTY --date 2026-10-13
  python3 scripts/shadow_contrarian.py --instrument NIFTY --persist
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from app.research import contrarian_analyzer as CA  # noqa: E402


from app.research.cpr_strategy_engine import (  # noqa: E402
    calculate_cpr, pivot_levels, classify_cpr, classify_gap, is_virgin_cpr,
)

_IST_REQUIRE = None

CONTRARIAN_TABLE = "contrarian_verdicts"

CONTRARIAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS contrarian_verdicts (
    methodology_version TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    assessment_ts TEXT NOT NULL,
    data_timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_alignment TEXT,
    direction_pressure TEXT,
    candidate_setup_type TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    data_quality_json TEXT NOT NULL DEFAULT '{}',
    full_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    collection_source TEXT NOT NULL DEFAULT 'LIVE_COLLECT',
    collected_at TEXT,
    PRIMARY KEY (methodology_version, instrument_id, assessment_ts)
);
"""


def default_db() -> str:
    env = os.environ.get("TRADINGAI_DB_PATH")
    if env:
        return env
    return os.path.join(REPO, "database", "tradingai.db")


def ro_conn(db_path: str) -> sqlite3.Connection:
    """Strictly read-only connection to canonical tables (URI mode=ro)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def assert_own_table(name: str) -> None:
    """Write-isolation guard: only the dedicated table may be written."""
    if name != CONTRARIAN_TABLE:
        raise RuntimeError(f"WRITE_ISOLATION_VIOLATION:{name}")


def parse_ts(value):
    dt = CA._parse_ts(value)
    if dt is None:
        raise ValueError(f"INVALID_TIMESTAMP:{value!r}")
    return dt


def completion_iso(open_iso: str) -> str:
    return (parse_ts(open_iso) + CA.timedelta(minutes=5)).isoformat()


def prev_session_date(conn: sqlite3.Connection, instrument: str, on_date: str):
    rows = conn.execute(
        "SELECT substr(timestamp,1,10) AS d FROM market_candles_5m "
        "WHERE instrument_id=? GROUP BY d HAVING COUNT(*) >= 30 ORDER BY d",
        (instrument,),
    ).fetchall()
    days = [r["d"] for r in rows]
    prev = [d for d in days if d < on_date]
    return prev[-1] if prev else None


def load_day_candles(conn: sqlite3.Connection, instrument: str, day: str):
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume, is_complete "
        "FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=? "
        "ORDER BY timestamp", (instrument, day),
    ).fetchall()
    return [dict(r) for r in rows]


def canonical_decision(conn: sqlite3.Connection, instrument: str, day: str):
    row = conn.execute(
        "SELECT direction, level, entry_time, r_multiple, result "
        "FROM paper_align WHERE instrument_id=? AND session_date=? AND variant='plain'",
        (instrument, day),
    ).fetchone()
    return dict(row) if row else None


def _ohlc(bars):
    high = max(b["high"] for b in bars)
    low = min(b["low"] for b in bars)
    close = bars[-1]["close"]
    return high, low, close


def build_snapshot(conn: sqlite3.Connection, instrument: str, day: str,
                   assessment_iso: str, ref_price=None):
    """Reconstruct a canonical-shaped decision snapshot for historical day.

    Returns (decision_dict, None) or (None, reason). Read-only. The CPR values
    are recomputed from stored previous-session OHLC using the SAME engine
    functions (pure) -- the analyzer itself never computes CPR.
    """
    prev_day = prev_session_date(conn, instrument, day)
    if not prev_day:
        return None, "NO_PREV_SESSION"
    prev_bars = load_day_candles(conn, instrument, prev_day)
    if len(prev_bars) < 30:
        return None, "PREV_SESSION_INCOMPLETE"
    ph, pl, pc = _ohlc(prev_bars)
    cpr = calculate_cpr(ph, pl, pc)
    piv = pivot_levels(ph, pl, cpr["pp"])
    ctype = classify_cpr(cpr["width_pct"])

    day_bars = load_day_candles(conn, instrument, day)
    if not day_bars:
        return None, "NO_SESSION_CANDLES"
    if assessment_iso is None:
        assessment_iso = completion_iso(day_bars[-1]["timestamp"])
    bars = [dict(b) for b in day_bars]
    day_open = bars[0]["open"]
    gap_pts = round(day_open - pc, 2)
    gap_dir = classify_gap(gap_pts)

    upt = [b for b in bars if completion_iso(b["timestamp"]) <= assessment_iso]
    if not upt:
        return None, "NO_BARS_BY_ASSESSMENT"
    ref = ref_price if ref_price is not None else upt[-1]["close"]
    pos = None
    if ref > cpr["tc"]:
        pos = "ABOVE_TC"
    elif ref < cpr["bc"]:
        pos = "BELOW_BC"
    else:
        pos = "INSIDE_CPR"
    h = max(b["high"] for b in upt)
    l = min(b["low"] for b in upt)
    virgin = bool(is_virgin_cpr(h, l, cpr["tc"], cpr["bc"]))

    can = canonical_decision(conn, instrument, day)
    direction = (can or {}).get("direction")
    decision = {
        "instrument": instrument,
        "timestamp": assessment_iso,
        "price": ref,
        "data_status": "RECENT",
        "session": "LIVE",
        "market_bias": direction or "UNAVAILABLE",
        "market_regime": "UNAVAILABLE",
        "cpr": {
            "available": True,
            "session": prev_day,
            "pivot": cpr["pp"], "bc": cpr["bc"], "tc": cpr["tc"],
            "width_pct": cpr["width_pct"], "cpr_type": ctype,
            "s1": round(piv["s1"], 2), "s2": round(piv["s2"], 2),
            "r1": round(piv["r1"], 2), "r2": round(piv["r2"], 2),
            "prev_high": ph, "prev_low": pl, "prev_close": pc,
            "gap_points": gap_pts, "gap_direction": gap_dir,
            "price_position": pos, "virgin": virgin, "day_open": day_open,
        },
        "gap_direction": gap_dir,
        "gap_points": gap_pts,
        "atr": None,
        "volatility_state": None,
        "strategy": "NONE",
        "strategy_direction": direction,
        "decision": "TRADE" if direction else "NO TRADE",
        "trade": {
            "direction": direction,
            "level": (can or {}).get("level"),
            "entry_time": (can or {}).get("entry_time"),
        } if direction else None,
        "read_only": True,
        "reconstructed": True,
    }
    return decision, None


def run_verdict(instrument: str, day: str, assessment_iso: str,
                decision, bars, vix_evidence=None):
    ver = CA.analyze(
        instrument, decision, bars, assessment_ts=assessment_iso,
        vix_evidence=vix_evidence,
    )
    return ver


def write_verdict(wc: sqlite3.Connection, verdict: dict, dry_run: bool = False,
                  collection_source: str = "LIVE_COLLECT") -> str:
    """Persist one verdict to the dedicated table (idempotent per key)."""
    if dry_run:
        return "DRY_RUN"
    assert_own_table(CONTRARIAN_TABLE)
    evidence = verdict.get("evidence") or []
    status = verdict.get("status") or "INSUFFICIENT_DATA"
    in_ = verdict.get("inputs") or {}
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    wc.execute(CONTRARIAN_SCHEMA)
    wc.execute(
        "INSERT OR REPLACE INTO " + CONTRARIAN_TABLE + " ("
        "methodology_version, instrument_id, assessment_ts, data_timestamp, status,"
        " decision_alignment, direction_pressure, candidate_setup_type,"
        " evidence_json, data_quality_json, full_json, collection_source, collected_at, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            verdict.get("methodology_version"),
            verdict.get("instrument"),
            verdict.get("assessment_ts"),
            verdict.get("data_timestamp"),
            status,
            (verdict.get("decision") or {}).get("alignment"),
            verdict.get("contrarian_bias") or verdict.get("continuation_bias"),
            verdict.get("candidate_setup_type"),
            json.dumps(evidence),
            json.dumps({
                "bar_count": verdict.get("bar_count"),
                "unavailable_inputs": verdict.get("unavailable_inputs"),
                "inputs": in_,
                "risk_notes": verdict.get("risk_notes"),
            }),
            json.dumps(verdict, sort_keys=True),
            collection_source,
            now_iso,
            now_iso,
        ),
    )
    wc.commit()
    return "PERSISTED"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Shadow ContrarianMarketAnalyzer collector")
    ap.add_argument("--instrument", required=True, choices=("NIFTY", "BANKNIFTY"))
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (backfill). Default: today IST.")
    ap.add_argument("--assessment", default=None, help="HH:MM (backfill only). Default: latest completed bar.")
    ap.add_argument("--persist", action="store_true", help="Persist to contrarian_verdicts (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="Never write; safe default")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    db_path = args.db or default_db()
    from datetime import datetime as _dt
    ist_now = _dt.now(CA.IST)
    day = args.date or ist_now.date().isoformat()
    dry_run = args.dry_run or not args.persist
    live_guard = _is_live_mode_available()

    if args.date:
        use_live = False
        collection_source = "BACKFILL"
    elif live_guard:
        use_live = True
        collection_source = "LIVE_COLLECT"
    else:
        if not dry_run:
            print(json.dumps({"mode": "live", "instrument": args.instrument,
                              "day": day,
                              "error": "live persistence refused: CONTRARIAN_LIVE_MODE=1 not set; "
                                       "a reconstructed-snapshot row must not be labeled LIVE_COLLECT"},
                             indent=2))
            return 1
        use_live = False
        collection_source = "BACKFILL"

    conn = None
    try:
        if use_live:
            from app.decision.view import build_decision as live_decision
            decision = live_decision(args.instrument)
            mode = "live"
            reason = None
            if not dry_run and bool(decision and decision.get("reconstructed")):
                print(json.dumps({"mode": "live", "instrument": args.instrument,
                                  "day": day,
                                  "error": "live persistence refused: live input reconstructed/unavailable"},
                                 indent=2))
                return 1
        else:
            conn = ro_conn(db_path)
            decision, reason = build_snapshot(
                conn, args.instrument, day,
                _latest_completion_iso(conn, args.instrument, day, args.assessment),
            )
            mode = "backfill"
    finally:
        if conn is not None:
            conn.close()

    if decision is None:
        print(json.dumps({"mode": mode, "instrument": args.instrument,
                          "day": day, "error": reason}, indent=2))
        return 1

    bars = load_day_candles(ro_conn(db_path), args.instrument, day)
    verdict = run_verdict(args.instrument, day,
                          decision.get("timestamp"),
                          decision, bars)
    print(json.dumps({"mode": mode, "dry_run": dry_run,
                      "summary": {
                          "instrument": verdict["instrument"],
                          "assessment_ts": verdict["assessment_ts"],
                          "bar_count": verdict["bar_count"],
                          "status": verdict["status"],
                          "alignment": (verdict["decision"] or {}).get("alignment"),
                          "candidate": verdict["candidate_setup_type"],
                          "collection_source": collection_source,
                      },
                      "decision_input_reconstructed": bool(decision.get("reconstructed"))}, indent=2))

    if not dry_run:
        wc = sqlite3.connect(db_path)
        try:
            note = write_verdict(wc, verdict, dry_run=False,
                                 collection_source=collection_source)
        finally:
            wc.close()
        print(json.dumps({"write": note}, indent=2))
    else:
        print("dry-run: no database write performed.")
    return 0


def _latest_completion_iso(conn, instrument, day, assessment_hm):
    bars = load_day_candles(conn, instrument, day)
    if not bars:
        return None if assessment_hm is None else _hm_to_iso(day, assessment_hm)
    last = bars[-1]["timestamp"]
    return completion_iso(last)


def _hm_to_iso(day, hm):
    if not hm:
        return None
    return f"{day}T{hm}:00+05:30"


def _is_live_mode_available():
    # Live mode needs the canonical decision path; backfill is the safe default.
    # Use env switch to enable (keeps this script inert out of the box).
    return os.environ.get("CONTRARIAN_LIVE_MODE") == "1"


if __name__ == "__main__":
    sys.exit(main())