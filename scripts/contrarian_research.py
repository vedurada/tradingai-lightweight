#!/usr/bin/env python3
"""Standalone historical evaluator for contrarian shadow observations.

READ-ONLY: never writes, never modifies trading outcomes or canonical decision
records. Compares the ContrarianMarketAnalyzer against (1) the canonical
decision baseline, (2) a continuation benchmark, (3) a mean-reversion
benchmark, (4) the contrarian-confirm subset and (5) the disagreement subset,
on identical eligible timestamps.

Index-point R is a PROXY -- never options P&L. Costs (0.10R round trip) and
slippage (0.05R entry) are explicit assumptions. A negative or inconclusive
result is a valid research outcome; the analyzer stays rejected otherwise.

Usage:
  PYTHONPATH=/opt/tradingai python3 scripts/contrarian_research.py --instrument NIFTY
  PYTHONPATH=/opt/tradingai python3 scripts/contrarian_research.py --instrument BANKNIFTY --max-sessions 12
"""
import argparse
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from app.research import contrarian_analyzer as CA  # noqa: E402

from app.research.cpr_strategy_engine import (  # noqa: E402
    calculate_cpr, pivot_levels, classify_cpr, classify_gap, is_virgin_cpr,
)

from scripts.shadow_contrarian import (  # noqa: E402
    default_db, ro_conn, prev_session_date, load_day_candles, canonical_decision,
    build_snapshot, completion_iso, parse_ts,
)

COST_R_PER_TRADE = 0.10   # research assumption (round trip, R units)
SLIPPAGE_R = 0.05         # research assumption (entry slippage, R units)
FIDELITY_CUTOFF = "2026-09-25"  # before this date candles are lower-fidelity backfill
STOP_PCT = 0.005
TARGET_PCT = 0.02
OPEN_MIN_HM = "09:20"
OPEN_EOD_HM = "15:20"
FLAT_HM = "15:20"


def default_params():
    return {
        "CLOSE_IN": CA.CLOSE_IN, "SUSTAIN": CA.SUSTAIN, "CONFIRM": CA.CONFIRM,
        "RECLAIM": CA.RECLAIM, "GAP_FIRST_BARS": CA.GAP_FIRST_BARS,
        "MIN_BARS": CA.MIN_BARS, "ACCEPT_FRAC": CA.ACCEPT_FRAC, "XEXT": CA.XEXT,
    }


def simulate_outcome(day_bars, assessment_iso, direction):
    """Engine-convention outcome from assessment_iso forward.

    Entry at the OPEN of the candle opening exactly at assessment_iso (the
    candle AFTER the signal), window [09:20, 15:20). Stop 0.5% / target 2%,
    STOP_FIRST on the same candle, flat at the 15:20 bar open. If the entry
    candle is missing, no price is fabricated. Returns dict or None.
    """
    if direction not in ("BULLISH", "BEARISH"):
        return None
    entry_bar = None
    entry_idx = None
    for i, b in enumerate(day_bars):
        if b["timestamp"] == assessment_iso:
            entry_bar = b
            entry_idx = i
            break
    if entry_bar is None:
        return {"r": None, "reason": "NEXT_BAR_MISSING"}
    hm = entry_bar["timestamp"][11:16]
    if not (OPEN_MIN_HM <= hm < OPEN_EOD_HM):
        return {"r": None, "reason": "ENTRY_WINDOW_CLOSED"}
    e = entry_bar["open"]
    long_ = direction == "BULLISH"
    stop = e * (1 - STOP_PCT) if long_ else e * (1 + STOP_PCT)
    tgt = e * (1 + TARGET_PCT) if long_ else e * (1 - TARGET_PCT)
    risk = abs(e - stop)
    if risk <= 0:
        return {"r": None, "reason": "ZERO_RISK"}
    exit_px = None
    reason = None
    for b in day_bars[entry_idx + 1:]:
        o, h, lo, c = b["open"], b["high"], b["low"], b["close"]
        bhm = b["timestamp"][11:16]
        if bhm == FLAT_HM:
            exit_px, reason = o, "FLAT_15:20"
            break
        if long_:
            if o <= stop:
                exit_px, reason = o, "OPEN_BEYOND_STOP"
            elif o >= tgt:
                exit_px, reason = o, "OPEN_BEYOND_TARGET"
            elif lo <= stop:
                exit_px, reason = stop, "STOP"
            elif h >= tgt:
                exit_px, reason = tgt, "TARGET"
            else:
                continue
        else:
            if o >= stop:
                exit_px, reason = o, "OPEN_BEYOND_STOP"
            elif o <= tgt:
                exit_px, reason = o, "OPEN_BEYOND_TARGET"
            elif h >= stop:
                exit_px, reason = stop, "STOP"
            elif lo <= tgt:
                exit_px, reason = tgt, "TARGET"
            else:
                continue
        break
    if exit_px is None:
        exit_px = day_bars[-1]["close"]
        reason = "SESSION_END"
    raw_r = ((exit_px - e) / risk) if long_ else ((e - exit_px) / risk)
    return {"r": round(raw_r, 4), "reason": reason, "entry": e, "exit": exit_px}


def _verdict_status_bias(verdict):
    if verdict["status"] == CA.BULLISH_CONTRARIAN:
        return "BULLISH"
    if verdict["status"] == CA.BEARISH_CONTRARIAN:
        return "BEARISH"
    if verdict["status"] == CA.CONTINUATION:
        return verdict.get("continuation_bias")
    return None


def evaluate_session(conn, instrument, day, params):
    """One eligible session -> a single observation (no overlap inflation).

    The assessment timestamp is the FIRST completed bar whose analyzer verdict
    is directional; otherwise the session's first eligible bar (bar_count >=
    MIN_BARS). Benchmarks use the same assessment timestamp.
    """
    day_bars = [dict(b) for b in load_day_candles(conn, instrument, day)]
    if len(day_bars) < params["MIN_BARS"]:
        return None, "NO_SESSION_CANDLES"
    min_count = params["MIN_BARS"]
    assessment_iso = None
    verdict = None
    first_eligible = None
    first_verdict = None
    for i in range(min_count - 1, len(day_bars)):
        at = completion_iso(day_bars[i]["timestamp"])
        snapshot, reason = build_snapshot(conn, instrument, day, at)
        if snapshot is None:
            return None, reason
        v = CA.analyze(instrument, snapshot, day_bars, assessment_ts=at, params=params)
        if i == min_count - 1:
            first_eligible = at
            first_verdict = v
        if _verdict_status_bias(v) is not None and assessment_iso is None:
            assessment_iso = at
            verdict = v
    if assessment_iso is None:
        assessment_iso = first_eligible
        verdict = first_verdict
    canon = canonical_decision(conn, instrument, day)
    return {
        "session": day,
        "instrument": instrument,
        "assessment_iso": assessment_iso,
        "fidelity": "LIVE_CANDLES" if day >= FIDELITY_CUTOFF else "BACKFILL_CANDLES",
        "verdict": verdict,
        "bias": _verdict_status_bias(verdict),
        "alignment": (verdict.get("decision") or {}).get("alignment"),
        "canonical_r": (canon or {}).get("r_multiple"),
        "canonical_dir": (canon or {}).get("direction"),
        "entry_time": (canon or {}).get("entry_time"),
    }, None


def run(conn, instrument, sessions, params):
    rows = []
    reasons = {}
    for s in sessions:
        r, why = evaluate_session(conn, instrument, s, params)
        if r is None:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        rows.append(r)
    return rows, reasons


def metrics(netRs, seed=7):
    if not netRs:
        return {"n": 0}
    n = len(netRs)
    exp = sum(netRs) / n
    pos = sum(r for r in netRs if r > 0)
    neg = sum(r for r in netRs if r < 0)
    pf = (pos / abs(neg)) if neg else (pos if pos > 0 else 0.0)
    cum = []
    cc = 0.0
    peak = 0.0
    maxdd = 0.0
    for r in netRs:
        cc += r
        cum.append(cc)
        peak = max(peak, cc)
        dd = peak - cc
        maxdd = max(maxdd, dd)
    tail = sorted(netRs)[:max(1, int(round(0.05 * n)))]
    rng = random.Random(seed)
    means = []
    for _ in range(2000):
        sample = [netRs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(round(0.025 * (len(means) - 1)))]
    hi = means[int(round(0.975 * (len(means) - 1)))]
    return {
        "n": n, "expectancy_r": round(exp, 4), "net_r": round(sum(netRs), 2),
        "profit_factor": round(pf, 3) if pf else None,
        "max_drawdown_r": round(maxdd, 2),
        "worst5_mean_r": round(sum(tail) / len(tail), 4),
        "boot95_ci": [round(lo, 4), round(hi, 4)],
        "wins": sum(1 for r in netRs if r > 0),
        "losses": sum(1 for r in netRs if r < 0),
        "flat": sum(1 for r in netRs if r == 0),
    }


def _net_r(*, raw=None, row=None, key=None):
    if raw is None and row is not None and key is not None:
        if key == "canonical_baseline":
            return row["canonical_r"]
        at = row["assessment_iso"]
        if key == "continuation_bench":
            d = "BULLISH"
        elif key == "meanrev_bench":
            d = "BEARISH"
        elif key in ("analyzer_signal", "contrarian_confirm", "disagree_subset"):
            if row["bias"] is None:
                return None
            if key == "contrarian_confirm" and row.get("alignment") != CA.ALIGN_AGREE:
                return None
            if key == "disagree_subset" and row.get("alignment") != CA.ALIGN_DISAGREE:
                return None
            d = row["bias"]
        else:
            return None
        o = simulate_outcome(load_day_candles(_rconn(), row["instrument"], row["session"]), at, d)
        if o is None or o.get("r") is None:
            return None
        raw = o["r"]
    if raw is None:
        return None
    return round(raw - COST_R_PER_TRADE - SLIPPAGE_R, 4)


def print_arm(name, rows):
    net = [v for _, v in rows]
    m = metrics(net)
    print(f"  {name}: n={m['n']} exp={m['expectancy_r']} netR={m['net_r']} "
          f"PF={m['profit_factor']} maxDD={m['max_drawdown_r']} "
          f"worst5={m['worst5_mean_r']} boot95={m['boot95_ci']} "
          f"W/L/F={m['wins']}/{m['losses']}/{m['flat']}")


def _rconn(db_path=None):
    p = db_path or DB_PATH
    if p not in _ro_cache:
        _ro_cache[p] = ro_conn(p)
    return _ro_cache[p]


_ro_cache = {}
DB_PATH = default_db()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--instrument", required=True, choices=("NIFTY", "BANKNIFTY"))
    ap.add_argument("--start", default="2026-07-06")
    ap.add_argument("--end", default="2026-10-13")
    ap.add_argument("--holdout-frac", type=float, default=0.20)
    ap.add_argument("--max-sessions", type=int, default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    global DB_PATH
    DB_PATH = args.db or default_db()
    conn = ro_conn(DB_PATH)
    params = default_params()
    zero = parse_ts(f"{args.start}T09:15:00+05:30").date().isoformat()
    sessions = [
        r["d"] for r in conn.execute(
            "SELECT substr(timestamp,1,10) AS d FROM market_candles_5m "
            "WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? "
            "GROUP BY d HAVING COUNT(*) >= 30 ORDER BY d",
            (args.instrument, zero, args.end),
        ).fetchall()
    ]
    # Only sessions with a recorded canonical plain decision are eligible.
    eligible = [
        s for s in sessions
        if canonical_decision(conn, args.instrument, s) is not None
    ]
    if args.max_sessions:
        eligible = eligible[:args.max_sessions]
    if not eligible:
        print("No eligible sessions.")
        return 1

    rows, reasons = run(conn, args.instrument, eligible, params)
    if not rows:
        print("No evaluable sessions. Exclusions:")
        for k, v in reasons.items():
            print(f"  {k}: {v}")
        return 1

    print(f"instrument={args.instrument} sessions_eligible={len(eligible)} "
          f"evaluated={len(rows)}")
    print("Exclusions:")
    for k, v in sorted(reasons.items()):
        print(f"  {k}: {v}")
    print("Fidelity split:")
    for fid in ("LIVE_CANDLES", "BACKFILL_CANDLES"):
        cnt = sum(1 for r in rows if r["fidelity"] == fid)
        print(f"  {fid}: {cnt}")

    n_split = max(1, int(round(len(rows) * (1 - args.holdout_frac))))
    train_rows = rows[:n_split]
    holdout_rows = rows[n_split:]

    def arm_rows(rows_, key):
        return [(r, v) for r in rows_ if (v := _net_r(row=r, key=key)) is not None]

    def holdout_rejects():
        hold_sig = [r for r in holdout_rows if r["bias"]]
        if not hold_sig:
            return "no-directional-signals", None
        netrs = [v for r in hold_sig if (v := _net_r(row=r, key="analyzer_signal")) is not None]
        m = metrics(netrs)
        threshold_r = 1.5 / 50.0
        reject = (m["n"] < 20) or (m["expectancy_r"] < threshold_r) \
            or (m["boot95_ci"][0] <= 0 <= m["boot95_ci"][1])
        return ("reject" if reject else "pass"), m

    print("\n=== Full sample (all eligible sessions) ===")
    for key in ("canonical_baseline", "continuation_bench", "meanrev_bench",
                "analyzer_signal", "contrarian_confirm", "disagree_subset"):
        print_arm(key, arm_rows(rows, key))

    print(f"\n=== Time split: TRAIN (first {len(train_rows)}) ===")
    for key in ("canonical_baseline", "continuation_bench", "meanrev_bench",
                "analyzer_signal", "contrarian_confirm", "disagree_subset"):
        print_arm(key + ".train", arm_rows(train_rows, key))

    print(f"\n=== HOLD-OUT (last {len(holdout_rows)}, untouched) ===")
    for key in ("canonical_baseline", "continuation_bench", "meanrev_bench",
                "analyzer_signal", "contrarian_confirm", "disagree_subset"):
        print_arm(key + ".holdout", arm_rows(holdout_rows, key))

    print("\n=== Expanding-window walk-forward (train only) ===")
    if len(train_rows) >= 8:
        fracs = [0.25, 0.50, 0.75, 1.0]
        for f in fracs:
            n = max(4, int(round(len(train_rows) * f)))
            seg = train_rows[:n]
            m_sig = metrics([v for r in seg if (v := _net_r(row=r, key="analyzer_signal")) is not None])
            m_can = metrics([v for r in seg if (v := _net_r(row=r, key="canonical_baseline")) is not None])
            print(f"  window={len(seg)} ({f:.0%}): signal n={m_sig['n']} exp={m_sig['expectancy_r']} "
                  f"netR={m_sig['net_r']} | canonical n={m_can['n']} exp={m_can['expectancy_r']} netR={m_can['net_r']}")

    # Voluntary signal decision rule (predeclared, provisional research criteria):
    # reject unless holdout has >= 20 signal observations, expectancy >= +1.5R/50
    # and a bootstrap 95% CI that does not straddle zero.
    verdict, m = holdout_rejects()
    print("\n=== Holdout decision (provisional research criteria) ===")
    if m is None:
        print("  No directional signals in the untouched holdout: analyzer is shadow-only until more data.")
    else:
        threshold_r = 1.5 / 50.0
        print(f"  signal observation n (holdout) = {m['n']}  (>=20 required for any weight)")
        print(f"  holdout expectancy = {m['expectancy_r']}  (predeclared need >= +1.5R per 50 = {threshold_r})")
        print(f"  boot 95% CI = {m['boot95_ci']}  (must not straddle zero)")
        print("  REJECTED / shadow-only" if verdict == "reject"
              else "  PASSES predeclared OOS bar (still no trading activation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())