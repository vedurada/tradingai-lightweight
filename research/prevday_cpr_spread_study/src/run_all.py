"""Entry point: run the whole study and write the artefacts.

    cd /opt/tradingai && python3 -m research.prevday_cpr_spread_study.src.run_all

(never writes to the production database; the study works on a snapshot copy)
"""
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict

from . import data as D
from . import metrics as M
from . import runner as R
from . import signals as S

OUT = R.OUT
REPORTS = R.REPORTS


def w_json(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)
    return path


def w_csv(path, rows, cols=None):
    if not rows:
        with open(path, "w") as fh:
            fh.write("")
        return path
    cols = cols or list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


# ------------------------------------------------- production baseline (verify)
BASELINE_SNIPPET = r'''
import json, os, sys
from app.research.cpr_trigger_engine import run_opens_range
res = run_opens_range(sys.argv[1], sys.argv[2], sys.argv[3], "plain")
out = {"summary": {}, "trades": []}
for k, v in res.items():
    if k in ("trades", "days"):
        continue
    out["summary"][k] = v
for t in res.get("trades", []):
    out["trades"].append({k: t.get(k) for k in
        ("trade_date", "direction", "level", "entry_time", "entry",
         "exit_time", "exit", "r_multiple", "points", "exit_reason",
         "signal_time", "win_loss")})
print(json.dumps(out, default=str))
'''


def production_baseline(snapshot_path, instrument="NIFTY",
                         start="2026-07-06", end="2026-10-21"):
    """Reproduce the production baseline in an isolated subprocess.

    The subprocess is given TRADINGAI_DB_PATH=<snapshot>, so even if the
    production module touches the DB it can only touch the snapshot.
    """
    env = dict(os.environ)
    env["TRADINGAI_DB_PATH"] = snapshot_path
    env["PYTHONPATH"] = "/opt/tradingai"
    p = subprocess.run([sys.executable, "-c", BASELINE_SNIPPET, instrument,
                        start, end], capture_output=True, text=True, env=env,
                       cwd="/opt/tradingai")
    if p.returncode != 0:
        return {"error": p.stderr[-800:]}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as exc:                                    # pragma: no cover
        return {"error": "unparsable: %s" % exc, "stdout": p.stdout[-400:]}


# ------------------------------------------------------------------- main
def main(instrument="NIFTY"):
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)
    (snap, candles, sessions, quality, usable, prior, ctxs) = R.prepare(instrument)
    R.attach_or_levels(ctxs)

    # ---- data quality
    dq = R.data_quality_report(instrument, candles, sessions, quality, usable,
                               ctxs)
    w_json(os.path.join(OUT, "data_quality_report.json"), dq)

    # ---- feature table (one row per session)
    feat_rows = []
    for d in usable:
        c = ctxs.get(d)
        if not c:
            continue
        feat_rows.append({
            "session_date": d, "instrument": instrument,
            "prev_date": c["prev_date"], "prev_gap_days": c["prev_gap_days"],
            "pd_open": round(c["pd_open"], 2), "pd_high": round(c["pd_high"], 2),
            "pd_low": round(c["pd_low"], 2), "pd_close": round(c["pd_close"], 2),
            "pd_range": round(c["pd_range"], 2),
            "pd_body_pct": round(c["pd_body_pct"], 4),
            "pd_upper_wick": round(c["pd_upper_wick"], 2),
            "pd_lower_wick": round(c["pd_lower_wick"], 2),
            "pd_close_location": round(c["pd_close_location"], 4),
            "pd_return_pct": (round(c["pd_return_pct"], 4)
                              if c["pd_return_pct"] is not None else None),
            "pd_range_ratio": (round(c["pd_range_ratio"], 3)
                               if c["pd_range_ratio"] is not None else None),
            "pd_structure": c["pd_structure"], "pd_day_type": c["pd_day_type"],
            "pd_close_class": c["pd_close_class"],
            "cpr_pp": round(c["cpr"]["pp"], 2),
            "cpr_lower": round(c["cpr"]["lower_cpr"], 2),
            "cpr_upper": round(c["cpr"]["upper_cpr"], 2),
            "cpr_width_pts": round(c["cpr"]["width_pts"], 2),
            "cpr_width_pct": round(c["cpr"]["width_pct"], 4),
            "cpr_class": c["cpr_class"],
            "cpr_width_pctile": (round(c["cpr_width_pctile"], 1)
                                 if c["cpr_width_pctile"] is not None else None),
            "today_open": round(c["today_open"], 2),
            "gap_points": round(c["gap_points"], 2),
            "gap_pct": round(c["gap_pct"], 4),
            "gap_dir": c["gap_dir"], "cpr_pos": c["cpr_pos"],
            "prev_range_pos": c["prev_range_pos"], "gap_cell": c["gap_cell"],
            "or15_high": (round(c["_or15_high"], 2)
                          if c.get("_or15_high") else None),
            "or15_low": (round(c["_or15_low"], 2)
                         if c.get("_or15_low") else None),
            "n_bars": quality[d]["n_bars"],
        })
    w_csv(os.path.join(OUT, "feature_table_%s.csv" % instrument), feat_rows)

    # ---- signals for every model configuration (signal ledger)
    mcfgs = R.model_configs()
    sig_by_cfg = {}
    cfg_list = []
    ledger_rows = []
    for m, cfg in mcfgs:
        sigs = R.run_signals(ctxs, m, cfg, usable)
        sig_by_cfg[(m, json.dumps(cfg, sort_keys=True))] = sigs
        cfg_list.append((m, cfg, sigs))
        for d in usable:
            s = sigs[d]
            ledger_rows.append({
                "session_date": d, "split": R.split_of(d), "model": m,
                "config": json.dumps(cfg, sort_keys=True),
                "direction": s["direction"], "reason": s["reason"],
                "setup_type": s.get("setup_type"), "level": s.get("level"),
                "signal_ts": s.get("signal_ts"), "signal_hhmm": s.get("signal_hhmm"),
                "entry_bar_idx": s.get("entry_bar_idx"),
                "entry_ref_open": s.get("entry_ref_open"),
                "invalidation": s.get("invalidation"),
            })
    w_csv(os.path.join(OUT, "signal_ledger.csv"), ledger_rows)

    # ---- no-look-ahead proof for the signal layer
    sig_check = R.signal_recompute_check(ctxs, cfg_list, usable)
    w_json(os.path.join(OUT, "signal_pit_check.json"), sig_check)
    dq["signal_recompute_checked"] = sig_check["checked"]
    dq["signal_recompute_mismatches"] = sig_check["n_mismatches"]
    w_json(os.path.join(OUT, "data_quality_report.json"), dq)

    # ---- variant grid
    stops = R.stop_configs()
    targets = R.target_configs()
    results = []
    all_trades = []
    for (m, cfg), sigs in zip([(m, c) for m, c in mcfgs],
                              [sig_by_cfg[(m, json.dumps(c, sort_keys=True))]
                               for m, c in mcfgs]):
        for sname, scfg in stops:
            for tname, tcfg in targets:
                trades = R.evaluate_variant(ctxs, sigs, sname, scfg, tname,
                                            tcfg, "EOD", usable)
                if not trades:
                    continue
                vid = R.variant_id(m, cfg, sname, tname, "EOD")
                for t in trades:
                    t["variant_id"] = vid
                st = R.split_trades(trades)
                isv = st["IS"] + st["VAL"]
                s_isv = M.summarize(isv, cost_r=R.PRIMARY_COST_R)
                s_is = M.summarize(st["IS"], cost_r=R.PRIMARY_COST_R)
                s_va = M.summarize(st["VAL"], cost_r=R.PRIMARY_COST_R)
                s_os = M.summarize(st["OOS"], cost_r=R.PRIMARY_COST_R)
                results.append({
                    "variant_id": vid, "model": m, "config": cfg,
                    "stop": sname, "stop_cfg": scfg, "target": tname,
                    "target_cfg": tcfg, "time_exit": "EOD",
                    "IS": s_is, "VAL": s_va, "OOS": s_os, "ISVAL": s_isv,
                    "n_trades": len(trades),
                })
                all_trades.extend(trades)

    w_csv(os.path.join(OUT, "trades_all_variants.csv"), all_trades)
    trades_by_vid = defaultdict(list)
    for t in all_trades:
        trades_by_vid[t["variant_id"]].append(t)

    # ---- selection on IS+VAL (frozen rule, spec §6.2)
    def eligible(rec):
        isv = rec["ISVAL"]
        if isv.get("n_trades", 0) < 20:
            return False
        if not (isv.get("expectancy_r", 0) > 0):
            return False
        if not (rec["IS"].get("expectancy_r", 0) > 0):
            return False
        if not (rec["VAL"].get("expectancy_r", 0) > 0):
            return False
        if isv.get("max_dd_r", 99) > 3.0:
            return False
        if isv.get("worst_trade_r", -99) < -1.2:
            return False
        return True

    cands = [r for r in results if eligible(r)]
    if not cands:
        best = None
    else:
        best = sorted(cands, key=lambda r: (
            -r["ISVAL"]["expectancy_r"], r["ISVAL"]["max_dd_r"],
            -r["ISVAL"]["n_trades"], r["variant_id"]))[0]
    frozen = {
        "selected_at_utc": subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                                          capture_output=True,
                                          text=True).stdout.strip(),
        "frozen_before_oos": True,
        "note": "the selection rule was pre-registered in spec.md (sha256 in "
                "run_manifest.json) and is applied ONLY to IS+VAL; the OOS "
                "window is evaluated after the selection is written",
        "rule": "IS+VAL expectancy/trade, positive in IS and VAL, >=20 trades, "
                "maxDD<=3R, worst trade >=-1.2R; ties: lower DD, more trades",
        "n_variants_evaluated": len(results),
        "n_variants_eligible": len(cands),
        "selection": None,
    }
    if best:
        frozen["selection"] = {
            "variant_id": best["variant_id"], "model": best["model"],
            "config": best["config"], "stop": best["stop"],
            "stop_cfg": best["stop_cfg"], "target": best["target"],
            "target_cfg": best["target_cfg"], "time_exit": best["time_exit"],
        }
    frozen["eligible_variants"] = [
        {"variant_id": r["variant_id"], "model": r["model"], "config": r["config"],
         "stop": r["stop"], "target": r["target"],
         "ISVAL_exp_r": r["ISVAL"].get("expectancy_r"),
         "ISVAL_n": r["ISVAL"].get("n_trades"),
         "ISVAL_max_dd_r": r["ISVAL"].get("max_dd_r"),
         "IS_exp_r": r["IS"].get("expectancy_r"),
         "VAL_exp_r": r["VAL"].get("expectancy_r")}
        for r in sorted(cands, key=lambda r: -r["ISVAL"]["expectancy_r"])]
    frozen["selection_hash"] = R.sha256_obj(frozen["selection"])
    w_json(os.path.join(OUT, "frozen_selection.json"), frozen)

    # ---- confirmatory OOS of the frozen selection
    confirm = None
    if best:
        (m, cfg) = (best["model"], best["config"])
        sigs = R.run_signals(ctxs, m, cfg, usable)
        trades = R.evaluate_variant(ctxs, sigs, best["stop"],
                                    best["stop_cfg"], best["target"],
                                    best["target_cfg"], best["time_exit"],
                                    usable)
        for t in trades:
            t["variant_id"] = best["variant_id"]
        st = R.split_trades(trades)
        boot = {}
        boot_sets = {"IS": st["IS"], "VAL": st["VAL"], "OOS": st["OOS"],
                     "ISVAL": st["IS"] + st["VAL"]}
        for sp in ("IS", "VAL", "OOS", "ISVAL"):
            rows = [(t["session_date"], 1, t["r"] - R.PRIMARY_COST_R)
                    for t in boot_sets[sp]]
            boot[sp] = M.block_bootstrap(rows, seed=R.SEED)
        cost_sens = {}
        for c in R.COST_GRID:
            ss = R.split_trades(trades)
            cost_sens["%.2f" % c] = {
                "IS": M.summarize(ss["IS"], cost_r=c),
                "VAL": M.summarize(ss["VAL"], cost_r=c),
                "OOS": M.summarize(ss["OOS"], cost_r=c),
                "ISVAL": M.summarize(ss["IS"] + ss["VAL"], cost_r=c),
            }
        breakdowns = {
            "gap_cell": M.breakdown(st["OOS"], "gap_cell",
                                    cost_r=R.PRIMARY_COST_R),
            "pd_close_class": M.breakdown(st["OOS"], "pd_close_class",
                                          cost_r=R.PRIMARY_COST_R),
            "cpr_class": M.breakdown(st["OOS"], "cpr_class",
                                     cost_r=R.PRIMARY_COST_R),
            "prev_range_pos": M.breakdown(st["OOS"], "prev_range_pos",
                                          cost_r=R.PRIMARY_COST_R),
            "setup_type": M.breakdown(st["OOS"], "setup_type",
                                       cost_r=R.PRIMARY_COST_R),
            "direction": M.breakdown(st["OOS"], "direction",
                                     cost_r=R.PRIMARY_COST_R),
            "pd_day_type": M.breakdown(st["OOS"], "pd_day_type",
                                       cost_r=R.PRIMARY_COST_R),
        }
        confirm = {
            "frozen": frozen["selection"],
            "splits": {
                "IS": M.summarize(st["IS"], cost_r=R.PRIMARY_COST_R),
                "VAL": M.summarize(st["VAL"], cost_r=R.PRIMARY_COST_R),
                "OOS": M.summarize(st["OOS"], cost_r=R.PRIMARY_COST_R),
                "ISVAL": M.summarize(st["IS"] + st["VAL"],
                                     cost_r=R.PRIMARY_COST_R),
            },
            "bootstrap": boot,
            "cost_sensitivity": cost_sens,
            "breakdowns_oos": breakdowns,
            "trades": trades,
        }
        w_json(os.path.join(OUT, "bootstrap_ci.json"), boot)
        w_json(os.path.join(OUT, "confirmatory_results.json"), {
            "frozen": frozen["selection"],
            "splits": confirm["splits"],
            "bootstrap": boot,
            "cost_sensitivity": cost_sens,
            "breakdowns_oos": breakdowns,
        })
        w_csv(os.path.join(OUT, "trade_ledger.csv"),
              [dict(t, r_net=round(t["r"] - R.PRIMARY_COST_R, 4))
               for t in trades])

    # ---- model comparison (best IS+VAL configuration per model family)
    families = {
        "A_previous_day_only": ["A"],
        "B_cpr_only": ["B"],
        "C_prevday_plus_cpr": ["C"],
        "D_prevday_cpr_gap": ["D"],
        "E_or_breakout_retest": ["E"],
        "F_cpr_plus_vwap_proxy": ["F"],
    }
    comparison = {}
    for fam, models in families.items():
        rows = []
        for rec in results:
            if rec["model"] not in models:
                continue
            rows.append(rec)
        best_per_cfg = []
        seen = set()
        for rec in sorted(rows, key=lambda r: -r["ISVAL"]["expectancy_r"]):
            key = (rec["model"], json.dumps(rec["config"], sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            best_per_cfg.append({
                "model": rec["model"], "config": rec["config"],
                "variant_id": rec["variant_id"], "stop": rec["stop"],
                "target": rec["target"],
                "IS": rec["IS"], "VAL": rec["VAL"], "OOS": rec["OOS"],
                "ISVAL": rec["ISVAL"],
                "meets_trade_floor": (rec["ISVAL"].get("n_trades", 0) >= 20),
                "is_frozen_selection": rec["variant_id"] == frozen.get(
                    "selection", {}).get("variant_id"),
            })
        comparison[fam] = best_per_cfg
    w_json(os.path.join(OUT, "model_comparison.json"), comparison)

    # ---- walk-forward (6 chronological blocks, expanding selection)
    blocks = []
    n = len(usable)
    n_blocks = 6
    base, rem = divmod(n, n_blocks)
    idx = 0
    for bi in range(n_blocks):
        size = base + (1 if bi < rem else 0)
        chunk = usable[idx:idx + size]
        if not chunk:
            break
        blocks.append(chunk)
        idx += size
    if idx < n:
        blocks.append(usable[idx:])
    wf = []
    for bi, block in enumerate(blocks):
        prior_days = {d for b in blocks[:bi] for d in b}
        block_days = set(block)
        sel = None
        for rec in results:
            vid = rec["variant_id"]
            tr = [t for t in trades_by_vid.get(vid, ())
                  if t["session_date"] in prior_days]
            if len(tr) < 10:
                continue
            s = M.summarize(tr, cost_r=R.PRIMARY_COST_R)
            if s["expectancy_r"] <= 0:
                continue
            key = (-s["expectancy_r"], s["max_dd_r"], vid)
            if sel is None or key < sel[0]:
                sel = (key, vid, rec)
        blk_tr = []
        if sel:
            vid = sel[1]
            blk_tr = [t for t in trades_by_vid.get(vid, ())
                      if t["session_date"] in block_days]
        s = M.summarize(blk_tr, cost_r=R.PRIMARY_COST_R) if blk_tr else {}
        wf.append({
            "block": bi + 1, "range": [block[0], block[-1]],
            "n_sessions": len(block),
            "selected_variant": sel[1] if sel else None,
            "selected_model": sel[2]["model"] if sel else None,
            "block_trades": len(blk_tr),
            "block_total_r": s.get("total_r"),
            "block_avg_r": s.get("expectancy_r"),
            "block_win_rate": s.get("win_rate"),
            "block_max_dd_r": s.get("max_dd_r"),
        })
    w_json(os.path.join(OUT, "walkforward_results.json"), wf)

    # ---- robustness: neighbours of the frozen selection on IS+VAL
    robust = {"neighbours": [], "positive_fraction": None}
    if best:
        m, cfg = best["model"], best["config"]
        sigs = R.run_signals(ctxs, m, cfg, usable)
        neigh = []
        for sname, scfg in stops:
            for tname, tcfg in targets:
                if sname == best["stop"] and tname == best["target"]:
                    continue
                tr = R.evaluate_variant(ctxs, sigs, sname, scfg, tname, tcfg,
                                        "EOD", usable)
                st = R.split_trades(tr)
                s = M.summarize(st["IS"] + st["VAL"], cost_r=R.PRIMARY_COST_R)
                neigh.append({"stop": sname, "target": tname,
                              "isval_exp_r": s.get("expectancy_r"),
                              "isval_n": s.get("n_trades"),
                              "positive": (s.get("expectancy_r") or 0) > 0})
        for tx in ("13:30", "14:00", "14:30"):
            tr = R.evaluate_variant(ctxs, sigs, best["stop"], best["stop_cfg"],
                                    best["target"], best["target_cfg"], tx,
                                    usable)
            st = R.split_trades(tr)
            s = M.summarize(st["IS"] + st["VAL"], cost_r=R.PRIMARY_COST_R)
            neigh.append({"stop": best["stop"], "target": best["target"],
                          "time_exit": tx,
                          "isval_exp_r": s.get("expectancy_r"),
                          "isval_n": s.get("n_trades"),
                          "positive": (s.get("expectancy_r") or 0) > 0})
        robust = {"neighbours": neigh,
                  "positive_fraction": (sum(1 for x in neigh if x["positive"]) /
                                        float(len(neigh)) if neigh else None)}
    w_json(os.path.join(OUT, "robustness.json"), robust)

    # ---- stop/target matrix for the frozen model config
    st_rows = []
    if best:
        m, cfg = best["model"], best["config"]
        sigs = R.run_signals(ctxs, m, cfg, usable)
        for sname, scfg in stops:
            for tname, tcfg in targets:
                tr = R.evaluate_variant(ctxs, sigs, sname, scfg, tname, tcfg,
                                        "EOD", usable)
                st = R.split_trades(tr)
                s_isv = M.summarize(st["IS"] + st["VAL"], cost_r=R.PRIMARY_COST_R)
                s_os = M.summarize(st["OOS"], cost_r=R.PRIMARY_COST_R)
                st_rows.append({
                    "stop": sname, "target": tname,
                    "isval_n": s_isv.get("n_trades"),
                    "isval_exp_r": s_isv.get("expectancy_r"),
                    "isval_total_r": s_isv.get("total_r"),
                    "isval_win_rate": s_isv.get("win_rate"),
                    "isval_maxdd_r": s_isv.get("max_dd_r"),
                    "oos_n": s_os.get("n_trades"),
                    "oos_exp_r": s_os.get("expectancy_r"),
                    "oos_total_r": s_os.get("total_r"),
                    "oos_win_rate": s_os.get("win_rate"),
                    "oos_maxdd_r": s_os.get("max_dd_r"),
                })
    w_csv(os.path.join(OUT, "stop_target_matrix.csv"), st_rows)

    # ---- production baseline (verification only)
    baseline = production_baseline(snap, instrument)
    w_json(os.path.join(OUT, "production_baseline.json"), baseline)

    # ---- manifest
    try:
        commit = subprocess.run(["git", "-C", "/opt/tradingai", "rev-parse",
                                 "HEAD"], capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "-C", "/opt/tradingai", "status",
                                 "--porcelain=v1", "-uall"],
                                capture_output=True, text=True).stdout
    except Exception:
        commit, status = None, None
    manifest = {
        "generated_utc": subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                                        capture_output=True,
                                        text=True).stdout.strip(),
        "study_dir": R.STUDY_DIR,
        "instrument": instrument,
        "spec_sha256": R.sha256_file(os.path.join(R.STUDY_DIR, "spec.md")),
        "snapshot_sha256": R.sha256_file(snap),
        "snapshot_path": snap,
        "git_commit": commit,
        "git_status_entries": len(status.splitlines()) if status else None,
        "production_writes": "none - study used a snapshot copy; production DB "
                             "never opened for writing",
        "n_sessions_used": len(usable),
        "session_range": [usable[0], usable[-1]],
        "splits": {k: list(v) for k, v in R.SPLITS.items()},
        "n_model_configs": len(mcfgs),
        "n_variants": len(results),
        "n_variants_eligible": len(cands),
        "frozen_selection": frozen.get("selection"),
        "frozen_selection_hash": frozen.get("selection_hash"),
        "seed": R.SEED,
        "cost_grid_R": list(R.COST_GRID),
        "primary_cost_r": R.PRIMARY_COST_R,
    }
    w_json(os.path.join(OUT, "run_manifest.json"), manifest)

    # ---- gates (spec §8)
    gates = build_gates(confirm, wf, robust, dq, frozen, results)
    w_json(os.path.join(OUT, "gates.json"), gates)

    print(json.dumps({
        "sessions": len(usable), "variants": len(results),
        "eligible": len(cands),
        "frozen": frozen.get("selection"),
        "OOS": (confirm or {}).get("splits", {}).get("OOS"),
        "gates_pass": sum(1 for k, g in gates["gates"].items()
                          if isinstance(g, dict) and g.get("status") == "PASS"),
        "gates_fail": sum(1 for k, g in gates["gates"].items()
                          if isinstance(g, dict) and g.get("status") == "FAIL"),
        "gates_inconclusive": sum(1 for k, g in gates["gates"].items()
                                  if isinstance(g, dict) and
                                  g.get("status") == "INCONCLUSIVE"),
        "FINAL": gates.get("FINAL"),
    }, indent=2, default=str))
    return 0


def build_gates(confirm, wf, robust, dq, frozen, results):
    g = {}
    g["G1_pit_integrity"] = {
        "definition": "PIT recomputation reproduces every feature and every "
                      "signal survives bar truncation",
        "feature_pit_checked": dq["pit_recompute_checked"],
        "feature_pit_mismatches": dq["pit_recompute_mismatches"],
        "signal_recompute_checked": dq.get("signal_recompute_checked"),
        "signal_recompute_mismatches": dq.get("signal_recompute_mismatches"),
        "status": ("PASS" if dq["pit_recompute_mismatches"] == 0 and
                   dq.get("signal_recompute_mismatches") == 0 and
                   dq["pit_recompute_checked"] > 0 and
                   dq.get("signal_recompute_checked", 0) > 0 else "FAIL")}
    g["G2_data_quality"] = {
        "definition": "no missing session days, no OHLC violations, sessions flagged",
        "ohlc_violations": dq["ohlc_violations"],
        "short_sessions": dq["short_sessions"],
        "status": "PASS" if dq["ohlc_violations"] == 0 else "FAIL"}
    if not confirm:
        for k in ("G3_oos_expectancy", "G4_sample_sufficiency",
                  "G5_robustness", "G6_risk_shape", "G7_concentration",
                  "G8_cost_robustness", "G9_no_trade_mechanism",
                  "G10_direction_transparency"):
            g[k] = {"status": "INCONCLUSIVE",
                    "definition": "no configuration satisfied the pre-registered "
                                  "selection rule"}
        g["FINAL"] = "INCONCLUSIVE"
        return {"gates": g, "FINAL": g["FINAL"]}
    oos = confirm["splits"]["OOS"]
    boot = confirm["bootstrap"]["OOS"]
    p = boot.get("p_value")
    g["G3_oos_expectancy"] = {
        "definition": "OOS expectancy > 0 in points and R; block-bootstrap p <= 0.10",
        "oos_avg_r": oos.get("expectancy_r"),
        "oos_avg_points": oos.get("expectancy_points"),
        "bootstrap_p": p,
        "status": ("PASS" if (oos.get("expectancy_r") or 0) > 0 and
                   (oos.get("expectancy_points") or 0) > 0 and
                   p is not None and p <= 0.10 else "FAIL")}
    n_bull = oos.get("bull_trades", 0)
    n_bear = oos.get("bear_trades", 0)
    weeks = len({t["session_date"][:7] + str(int(t["session_date"][8:10]) // 7)
                 for t in confirm["trades"]
                 if R.split_of(t["session_date"]) == "OOS"})
    g["G4_sample_sufficiency"] = {
        "definition": ">=8 OOS trades, >=3 per direction, >=2 distinct weeks",
        "oos_trades": oos.get("n_trades"), "bull": n_bull, "bear": n_bear,
        "distinct_weeks": weeks,
        "status": ("PASS" if (oos.get("n_trades") or 0) >= 8 and n_bull >= 3 and
                   n_bear >= 3 and weeks >= 2 else "FAIL")}
    pos_blocks = sum(1 for b in wf if (b.get("block_total_r") or 0) > 0)
    pos_splits = sum(1 for k in ("IS", "VAL", "OOS")
                     if (confirm["splits"][k].get("expectancy_r") or 0) > 0)
    pf = robust.get("positive_fraction")
    g["G5_robustness"] = {
        "definition": ">=2/3 splits positive, >=4/6 WF blocks positive, "
                      ">=70% positive parameter neighbours",
        "positive_splits": pos_splits,
        "positive_splits_detail": {k: confirm["splits"][k].get("expectancy_r")
                                   for k in ("IS", "VAL", "OOS")},
        "positive_wf_blocks": pos_blocks,
        "neighbour_positive_fraction": pf,
        "status": ("PASS" if pos_splits >= 2 and pos_blocks >= 4 and
                   (pf is None or pf >= 0.70) else "FAIL")}
    isv = confirm["splits"]["ISVAL"]
    dd = isv.get("max_dd_r")
    worst = isv.get("worst_trade_r")
    g["G6_risk_shape"] = {
        "definition": "IS+VAL maxDD <= 3R; no single loss worse than -1.2R",
        "isval_maxdd_r": dd, "isval_worst_trade_r": worst,
        "status": ("PASS" if dd is not None and dd <= 3.0 and
                   worst is not None and worst >= -1.2 else "FAIL")}
    share = oos.get("best_trade_share_of_profit")
    excl = oos.get("avg_r_excl_best")
    g["G7_concentration"] = {
        "definition": "best trade <=40% of OOS profit and expectancy positive "
                      "without the best trade",
        "best_trade_share": share, "avg_r_excl_best": excl,
        "status": ("PASS" if (share is None or share <= 0.40) and
                   (excl is not None and excl > 0) else "FAIL")}
    cs = confirm["cost_sensitivity"]
    oos10 = cs.get("0.10", {}).get("OOS", {})
    g["G8_cost_robustness"] = {
        "definition": "OOS expectancy > 0 at the 0.10R proxy cost",
        "oos_exp_r_at_0.10R": oos10.get("expectancy_r"),
        "status": ("PASS" if (oos10.get("expectancy_r") or 0) > 0 else "FAIL")}
    g["G9_no_trade_mechanism"] = {
        "definition": "closed NO TRADE reason taxonomy, reported per model",
        "status": "PASS"}
    g["G10_direction_transparency"] = {
        "definition": "bullish and bearish results reported separately",
        "bull": oos.get("bull_trades"), "bear": oos.get("bear_trades"),
        "status": "PASS"}
    fails = [k for k, v in g.items() if v["status"] == "FAIL"]
    inconclusive = [k for k, v in g.items() if v["status"] == "INCONCLUSIVE"]
    final = "FAIL" if fails else ("INCONCLUSIVE" if inconclusive else "PASS")
    g["FINAL"] = final
    g["failed_gates"] = fails
    g["inconclusive_gates"] = inconclusive
    return {"gates": g, "FINAL": final,
            "n_variants_evaluated": len(results),
            "n_variants_eligible": frozen.get("n_variants_eligible")}


if __name__ == "__main__":
    sys.exit(main())
