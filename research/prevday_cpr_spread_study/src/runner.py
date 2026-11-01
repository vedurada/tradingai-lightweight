"""Orchestration for the prev-day / CPR direction study (spec.md §5-§8).

Read-only on the production database: everything runs against a snapshot copy
created with sqlite3's backup API.
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict

from . import data as D
from . import execution as X
from . import features as F
from . import metrics as M
from . import signals as S

STUDY_DIR = D.STUDY_DIR
OUT = D.OUTPUTS
REPORTS = os.path.join(STUDY_DIR, "reports")

IS = ("2026-07-06", "2026-08-31")
VAL = ("2026-09-01", "2026-09-30")
OOS = ("2026-10-01", "2026-10-21")
SPLITS = {"IS": IS, "VAL": VAL, "OOS": OOS}

SEED = 20261022
COST_GRID = (0.0, 0.05, 0.10, 0.15, 0.20)
PRIMARY_COST_R = 0.10          # proxy round-trip cost, production convention


# ------------------------------------------------------------------ helpers
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     default=str).encode()).hexdigest()


def in_split(d, split):
    lo, hi = SPLITS[split]
    return lo <= d <= hi


def split_of(d):
    for name, (lo, hi) in SPLITS.items():
        if lo <= d <= hi:
            return name
    return None


# ------------------------------------------------------------ model configs
def model_configs():
    cfgs = []
    for th in (0.60, 0.70, 0.80):
        cfgs.append(("A", {"th": th}))
    for acc in (False, True):
        cfgs.append(("B", {"accept2": acc}))
    for th in (0.60, 0.70, 0.80):
        for acc in (False, True):
            cfgs.append(("C", {"th": th, "accept2": acc}))
    for th in (0.60, 0.70, 0.80):
        for acc in (False, True):
            cfgs.append(("D", {"th": th, "accept2": acc,
                               "setup_types": ["CONTINUATION"]}))
    cfgs.append(("D", {"th": 0.70, "accept2": False,
                       "setup_types": ["CONTINUATION", "REVERSAL"]}))
    for lv in ("OR15", "PDH", "CPR"):
        for rt in (False, True):
            cfgs.append(("E", {"levels": [lv], "retest": rt}))
    for th in (0.60, 0.70, 0.80):
        cfgs.append(("F", {"th": th, "accept2": True}))
    out = []
    for m, c in cfgs:
        cfg = dict(S.MODEL_DEFAULTS.get(m, {}))
        cfg.update(c)
        out.append((m, cfg))
    return out


def stop_configs():
    return [
        ("PCT_0.25", {"type": "PCT", "value": 0.0025}),
        ("PCT_0.35", {"type": "PCT", "value": 0.0035}),
        ("PCT_0.50", {"type": "PCT", "value": 0.005}),
        ("STRUCT_10", {"type": "STRUCT", "buffer_pts": 10.0}),
        ("ATR_1.0", {"type": "ATR", "mult": 1.0}),
    ]


def target_configs():
    return [
        ("R_0.5", {"type": "R", "value": 0.5}),
        ("R_1.0", {"type": "R", "value": 1.0}),
        ("R_1.5", {"type": "R", "value": 1.5}),
        ("R_2.0", {"type": "R", "value": 2.0}),
        ("STRUCT", {"type": "STRUCT"}),
    ]


def structural_target(ctx, sig, entry, dirn):
    """Next structural level in the trade direction (pre-declared rule)."""
    if dirn == 1:
        cands = [ctx["pivots"]["r1"], ctx["pivots"]["r2"], ctx["pd_high"],
                 ctx["cpr"]["upper_cpr"]]
        cands = [c for c in cands if c > entry]
        return min(cands) if cands else None
    cands = [ctx["pivots"]["s1"], ctx["pivots"]["s2"], ctx["pd_low"],
             ctx["cpr"]["lower_cpr"]]
    cands = [c for c in cands if c < entry]
    return max(cands) if cands else None


# --------------------------------------------------------------- data prep
def prepare(instrument="NIFTY"):
    snap = D.snapshot(out_path=os.path.join(OUT, "snapshot.db"))
    con = D.connect(snap)
    candles = D.load_candles(con, instrument)
    con.close()
    sessions = D.group_sessions(candles)
    quality = {d: D.session_quality(bars) for d, bars in sessions.items()}
    usable = sorted(d for d in sessions if quality[d]["complete"] and
                    d <= OOS[1])
    prior = D.prior_sessions(usable)
    ctxs = F.build_context(sessions, usable, prior)
    # drop sessions whose previous session is stale (>3 calendar days)
    for d in list(ctxs):
        gap = D.calendar_gap_days(ctxs[d]["prev_date"], d)
        ctxs[d]["prev_gap_days"] = gap
        if gap > 3:
            ctxs[d]["stale_prev"] = True
        else:
            ctxs[d]["stale_prev"] = False
    return snap, candles, sessions, quality, usable, prior, ctxs


def data_quality_report(instrument, candles, sessions, quality, usable, ctxs):
    by_inst = defaultdict(int)
    for c in candles:
        by_inst[c["date"]] += 1
    sessions_all = sorted(sessions)
    short = {d: quality[d]["n_bars"] for d in sessions_all
             if quality[d]["n_bars"] != D.EXPECTED_BARS}
    missing_eod = {d: quality[d]["missing_bars"] for d in sessions_all
                   if not quality[d]["has_eod_bar"]}
    ohlc_bad = 0
    for c in candles:
        if c["h"] < c["l"] or c["h"] < max(c["o"], c["c"]) - 1e-9 or \
                c["l"] > min(c["o"], c["c"]) + 1e-9:
            ohlc_bad += 1
    vols = {c["v"] for c in candles}
    # PIT recomputation check: rebuild each context from a feed that ends at
    # the previous session (nothing after the previous session may leak in)
    pit_mismatch = 0
    pit_checked = 0
    dates = [d for d in usable if d in ctxs]
    for i, d in enumerate(dates):
        if i < 2:
            continue
        trunc = {k: v for k, v in sessions.items() if k < d}
        tdates = sorted(trunc)
        if len(tdates) < 2:
            continue
        tprior = D.prior_sessions(tdates + [d])
        sessions_pit = dict(trunc)
        sessions_pit[d] = ctxs[d]["bars"]      # only today's bars are used
        tctx = F.build_context(sessions_pit, tdates + [d], tprior).get(d)
        if tctx is None:
            continue
        pit_checked += 1
        for k in ("cpr", "pd_high", "pd_low", "pd_close", "pd_close_location",
                  "gap_points", "cpr_pos", "gap_dir"):
            a, b = tctx[k], ctxs[d][k]
            if isinstance(a, dict):
                a = {kk: a[kk] for kk in ("lower_cpr", "upper_cpr", "width_pct")}
                b = {kk: b[kk] for kk in ("lower_cpr", "upper_cpr", "width_pct")}
            if a != b:
                pit_mismatch += 1
                break
    rep = {
        "instrument": instrument,
        "rows": len(candles),
        "first_ts": candles[0]["ts"].isoformat(),
        "last_ts": candles[-1]["ts"].isoformat(),
        "session_days": len(sessions_all),
        "usable_sessions": len(usable),
        "usable_range": [usable[0], usable[-1]],
        "excluded_sessions": {"2026-10-22": "in_progress (30 bars) - EXCLUDED"},
        "short_sessions": short,
        "sessions_missing_eod_bar": missing_eod,
        "ohlc_violations": ohlc_bad,
        "volume_values_present": sorted(vols)[:5],
        "volume_all_zero": all(v == 0 for v in vols),
        "pit_recompute_checked": pit_checked,
        "pit_recompute_mismatches": pit_mismatch,
        "option_history": {"option_snapshots_rows": 0, "option_contracts_rows": 0,
                           "historical_option_premiums_available": False},
    }
    return rep


# ------------------------------------------------------------- signal layer
def run_signals(ctxs, model, cfg, usable):
    """One signal per session for a model configuration."""
    out = {}
    for d in usable:
        ctx = ctxs.get(d)
        if ctx is None:
            out[d] = {"session_date": d, "model": model, "direction": "NO_TRADE",
                      "reason": "NO_PREV_SESSION", "signal_bar_idx": None,
                      "entry_bar_idx": None, "setup_type": None, "level": None}
            continue
        if ctx.get("stale_prev"):
            out[d] = {"session_date": d, "model": model, "direction": "NO_TRADE",
                      "reason": "STALE_PREV_SESSION", "signal_bar_idx": None,
                      "entry_bar_idx": None, "setup_type": None, "level": None}
            continue
        out[d] = S.run_model(ctx, model, cfg)
    return out


def signal_recompute_check(ctxs, cfg_list, usable):
    """No-look-ahead proof for the signal layer.

    Every signal is re-computed on a context whose bar list is truncated at
    the signal bar. A model that peeked into later bars would change its
    answer here.
    """
    checked = 0
    mismatches = []
    for m, cfg, sigs in cfg_list:
        for d in usable:
            sig = sigs.get(d)
            if not sig or sig.get("signal_bar_idx") is None:
                continue
            ctx = ctxs[d]
            cut = sig["signal_bar_idx"] + 1
            sub = dict(ctx)
            sub["bars"] = ctx["bars"][:cut]
            new = S.run_model(sub, m, cfg)
            checked += 1
            if new["direction"] != sig["direction"] or \
                    new.get("level") != sig.get("level"):
                mismatches.append({
                    "model": m, "config": cfg, "session_date": d,
                    "expected_direction": sig["direction"],
                    "recomputed_direction": new["direction"],
                    "expected_level": sig.get("level"),
                    "recomputed_level": new.get("level"),
                })
    return {"checked": checked, "n_mismatches": len(mismatches),
            "mismatches": mismatches[:20]}


def enrich(trade, ctx):
    row = dict(trade)
    row.update({
        "gap_cell": ctx["gap_cell"], "gap_dir": ctx["gap_dir"],
        "gap_points": round(ctx["gap_points"], 2),
        "gap_pct": round(ctx["gap_pct"], 4),
        "cpr_pos": ctx["cpr_pos"], "prev_range_pos": ctx["prev_range_pos"],
        "pd_close_class": ctx["pd_close_class"],
        "pd_close_location": round(ctx["pd_close_location"], 4),
        "pd_day_type": ctx["pd_day_type"], "pd_structure": ctx["pd_structure"],
        "cpr_class": ctx["cpr_class"],
        "cpr_width_pct": round(ctx["cpr"]["width_pct"], 4),
        "cpr_width_pctile": (round(ctx["cpr_width_pctile"], 1)
                             if ctx["cpr_width_pctile"] is not None else None),
        "or15_high": ctx.get("_or15_high"), "or15_low": ctx.get("_or15_low"),
        "open_pos_vs_pd_range": ctx["prev_range_pos"],
        "split": split_of(ctx["session_date"]),
    })
    return row


def attach_or_levels(ctxs):
    for d, ctx in ctxs.items():
        orr = F.opening_range(ctx["bars"], 3)
        ctx["_or15_high"] = orr["or_high"] if orr else None
        ctx["_or15_low"] = orr["or_low"] if orr else None


# ------------------------------------------------------------- variant eval
def evaluate_variant(ctxs, sigs, stop_name, stop_cfg, target_name, target_cfg,
                     time_exit, usable):
    trades = []
    for d in usable:
        sig = sigs.get(d)
        if not sig or sig["direction"] == "NO_TRADE":
            continue
        ctx = ctxs[d]
        entry = sig.get("entry_ref_open")
        if entry is None:
            continue
        tcfg = dict(target_cfg)
        if tcfg.get("type") == "STRUCT":
            lvl = structural_target(ctx, sig, entry,
                                    1 if sig["direction"] == S.BULL else -1)
            if lvl is None:
                continue
            tcfg["level"] = lvl
        t = X.simulate(ctx, sig, stop_cfg, tcfg, time_exit=time_exit)
        if t is None:
            continue
        t = enrich(t, ctx)
        t["stop_name"] = stop_name
        t["target_name"] = target_name
        t["time_exit"] = time_exit
        trades.append(t)
    return trades


def split_trades(trades):
    out = defaultdict(list)
    for t in trades:
        out[split_of(t["session_date"])].append(t)
    return out


def variant_id(model, cfg, stop_name, target_name, time_exit):
    key = json.dumps({"m": model, "c": cfg, "s": stop_name, "t": target_name,
                       "x": time_exit}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:10]
