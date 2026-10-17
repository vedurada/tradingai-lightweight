#!/usr/bin/env python3
"""Shadow promote/hold report for the scope-2 skip-Friday rule (read-only).

Scope 2 (2026-10-17) staged "skip Friday signals" as a NON-blocking shadow
(SHADOW_SKIP_FRIDAY in app/research/cpr_trigger_engine.py). This report
aggregates the realized outcomes of the short (BEAR) book split by weekday so
the shadow can be promoted to a hard gate on evidence, not vibes.

It never mutates data (SELECT only).

    cd /opt/tradingai && /usr/bin/python3 scripts/shadow_friday.py

Exit codes:
    0  HOLD    -- keep shadow (insufficient or ambiguous evidence)
    2  PROMOTE -- Friday shorts are a persistent, recent drag; enforce skip
    3  unexpected error (cron safety net)

Thresholds are deliberately conservative because the original signal is
small-n and the loss-memory decay engine already overturned one early read.
"""
import argparse
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.core.db import get_conn  # noqa: E402

MIN_FRIDAY_SAMPLES = 20   # need real evidence before enforcing a hard gate
RECENT_SESSIONS = 21      # ~1 month, matches the loss-memory decay window


def _stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "total_r": 0.0, "avg_r": 0.0}
    wins = sum(1 for r in rows if r["win_loss"] == "WIN")
    tot = sum(r["r_multiple"] for r in rows)
    return {"n": n, "wins": wins, "win_rate": 100.0 * wins / n,
            "total_r": tot, "avg_r": tot / n}


def _fmt(s):
    return ("n=%3d  win=%5.1f%%  avgR=%+.3f  totR=%+6.1f"
            % (s["n"], s["win_rate"], s["avg_r"], s["total_r"]))


def main():
    ap = argparse.ArgumentParser(description="skip-Friday shadow report")
    ap.add_argument("--variant", default="all", help="all|plain|aligned")
    ap.add_argument("--instrument", default=None, help="NIFTY|BANKNIFTY")
    args = ap.parse_args()

    conn = get_conn()
    try:
        # Source: paper_align -- the approved-spec opens-execution book that
        # drives paper.html/signals and reaches the latest session (fresh). The
        # old trade_journal source has had no production writer since the
        # Phase-9 backend was removed, and was stale (last session 2026-10-12).
        q = ("SELECT session_date, instrument_id, r_multiple, result "
             "FROM paper_align WHERE direction='BEAR' AND state='SIGNAL'")
        p = []
        if args.variant != "all":
            q += " AND variant=?"
            p.append(args.variant)
        if args.instrument:
            q += " AND instrument_id=?"
            p.append(args.instrument.upper())
        else:
            # Default scope = the TRADED book only. INDIA_VIX is not traded or
            # alerted (tg_alerts watches NIFTY/BANKNIFTY), and blending it in
            # distorts the Friday verdict the gate is meant to decide.
            q += " AND instrument_id IN ('NIFTY','BANKNIFTY')"
        rows = [dict(session_date=r[0], instrument_id=r[1],
                     dow=datetime.strptime(r[0], "%Y-%m-%d").strftime("%a"),
                     r_multiple=r[2] or 0.0, win_loss=r[3] or "")
                for r in conn.execute(q, p).fetchall()]
    finally:
        conn.close()

    if not rows:
        print("shadow-friday: no BEAR trades found -> HOLD")
        return 0

    sessions = sorted({r["session_date"] for r in rows})
    cut = (sessions[-RECENT_SESSIONS] if len(sessions) >= RECENT_SESSIONS
           else sessions[0])
    fri_all = [r for r in rows if r["dow"] == "Fri"]
    nonfri = [r for r in rows if r["dow"] != "Fri"]
    fri_rec = [r for r in fri_all if r["session_date"] >= cut]

    book = _stats(rows)
    fri = _stats(fri_all)
    nfri = _stats(nonfri)
    frec = _stats(fri_rec)

    print("shadow-friday report (%s%s) @ %s  sessions=%d"
          % (args.variant,
             ("/" + args.instrument.upper()) if args.instrument else "",
             sessions[-1], len(sessions)))
    print("  BEAR book (all)      " + _fmt(book))
    print("  Fridays              " + _fmt(fri))
    print("  non-Friday           " + _fmt(nfri))
    print("  Fridays recent(%2d)   %s" % (len(fri_rec), _fmt(frec)))
    print("  if Friday skipped:   " + _fmt(nfri)
          + "  delta totR=%+.1f  delta win=%+.1fpp"
          % (nfri["total_r"] - book["total_r"],
             nfri["win_rate"] - book["win_rate"]))

    reasons = []
    if fri["n"] < MIN_FRIDAY_SAMPLES:
        reasons.append("only %d Friday signals (< %d)"
                       % (fri["n"], MIN_FRIDAY_SAMPLES))
    if fri["total_r"] >= 0:
        reasons.append("Fridays net non-negative (%+.1fR)" % fri["total_r"])
    if fri["win_rate"] >= nfri["win_rate"]:
        reasons.append("Friday win-rate not below non-Friday")
    if frec["n"] and frec["total_r"] > 0:
        reasons.append("recent Fridays positive (%+.1fR)" % frec["total_r"])

    if reasons:
        print("  => HOLD (keep shadow): " + "; ".join(reasons))
        return 0

    print("  => PROMOTE: Friday shorts are a persistent, recent drag; "
          "enforce skip-Friday (promote SHADOW_SKIP_FRIDAY to a hard gate).")
    print("     basis: n=%d, net %+.1fR, win %.1f%% vs %.1f%% non-Friday."
          % (fri["n"], fri["total_r"], fri["win_rate"], nfri["win_rate"]))
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("shadow-friday: unexpected error: %s" % e)
        raise SystemExit(3)
