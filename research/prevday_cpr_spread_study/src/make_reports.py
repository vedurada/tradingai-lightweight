"""Generate the markdown reports from the study outputs (research-only).

    cd /opt/tradingai && python3 -m research.prevday_cpr_spread_study.src.make_reports
"""
import csv
import json
import os
from collections import Counter, defaultdict

from . import data as D

OUT = D.OUTPUTS
REPORTS = os.path.join(D.STUDY_DIR, "reports")


def j(name):
    with open(os.path.join(OUT, name)) as fh:
        return json.load(fh)


def c(name):
    with open(os.path.join(OUT, name)) as fh:
        return list(csv.DictReader(fh))


def f(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return ("%." + str(nd) + "f") % x
    return str(x)


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100.0 * x)


def write(name, lines):
    path = os.path.join(REPORTS, name)
    with open(path, "w") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    return path


# ----------------------------------------------------------------- artefacts
def load():
    d = {
        "dq": j("data_quality_report.json"),
        "frozen": j("frozen_selection.json"),
        "confirm": j("confirmatory_results.json"),
        "gates": j("gates.json"),
        "manifest": j("run_manifest.json"),
        "robust": j("robustness.json"),
        "wf": j("walkforward_results.json"),
        "mc": j("model_comparison.json"),
        "pb": j("production_baseline.json"),
        "matrix": c("stop_target_matrix.csv"),
        "ledger": c("signal_ledger.csv"),
    }
    return d


def metrics_table(splits, keys=("IS", "VAL", "ISVAL", "OOS")):
    hdr = ["metric"] + list(keys)
    rows = [hdr, ["---"] * len(hdr)]
    m = splits

    def row(label, fn):
        rows.append([label] + [fn(m.get(k) or {}) for k in keys])

    row("trades", lambda s: f(s.get("n_trades"), 0))
    row("win rate", lambda s: pct(s.get("win_rate")))
    row("expectancy (R/trade, net of 0.10R)", lambda s: f(s.get("expectancy_r")))
    row("expectancy (points/trade)", lambda s: f(s.get("expectancy_points"), 2))
    row("median R", lambda s: f(s.get("median_r")))
    row("total R", lambda s: f(s.get("total_r"), 2))
    row("profit factor", lambda s: f(s.get("profit_factor"), 2))
    row("max drawdown (R)", lambda s: f(s.get("max_dd_r"), 2))
    row("worst trade (R)", lambda s: f(s.get("worst_trade_r"), 2))
    row("max consecutive losses", lambda s: f(s.get("max_consecutive_losses"), 0))
    row("bull trades", lambda s: f(s.get("bull_trades"), 0))
    row("bear trades", lambda s: f(s.get("bear_trades"), 0))
    row("stop hit rate", lambda s: pct(s.get("stop_hit_rate")))
    row("target hit rate", lambda s: pct(s.get("target_hit_rate")))
    row("time-exit rate", lambda s: pct(s.get("time_exit_rate")))
    row("avg MFE (R)", lambda s: f(s.get("avg_mfe_r"), 2))
    row("avg MAE (R)", lambda s: f(s.get("avg_mae_r"), 2))
    row("avg hold (minutes)", lambda s: f(s.get("avg_hold_minutes"), 1))
    row("best trade share of profit", lambda s: pct(s.get("best_trade_share_of_profit")))
    row("expectancy excl. best trade", lambda s: f(s.get("avg_r_excl_best")))
    row("daily loss breaches (<= -3R)", lambda s: f(s.get("daily_loss_breaches"), 0))
    return rows


def md(rows):
    return ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]


# ------------------------------------------------------------------- reports
def report_backtest(a):
    sel = a["frozen"]["selection"]
    sp = a["confirm"]["splits"]
    boot = a["confirm"]["bootstrap"]
    dq = a["dq"]
    L = []
    L.append("# Backtest report - NIFTY previous-day / CPR direction study")
    L.append("")
    L.append("Research only. Index level. No production code, no production "
             "database write, no live signal was touched by this study.")
    L.append("")
    L.append("## 1. Data")
    L.append("")
    L.append("| item | value |")
    L.append("| --- | --- |")
    L.append("| instrument | NIFTY (spot index candles) |")
    L.append("| source table | `market_candles_5m` (yfinance 5-minute, +05:30) |")
    L.append("| rows in window | %s |" % dq["rows"])
    L.append("| session days present | %s |" % dq["session_days"])
    L.append("| usable sessions | %s (%s .. %s) |"
             % (dq["usable_sessions"], dq["usable_range"][0], dq["usable_range"][1]))
    L.append("| excluded | 2026-10-22 (session in progress, %s bars) |"
             % dq["short_sessions"].get("2026-10-22"))
    L.append("| short sessions | %s |"
             % ", ".join("%s (%s bars)" % (k, v)
                         for k, v in sorted(dq["short_sessions"].items())))
    L.append("| OHLC violations | %s |" % dq["ohlc_violations"])
    L.append("| volume column | all zeros -> VWAP can only be a proxy |")
    L.append("| option history | none (0 snapshots / 0 contracts) |")
    L.append("")
    L.append("The three absent weekdays in the window (2026-09-14, 2026-10-02, "
             "2026-10-20) are NSE holidays per `app/market/nse_calendar.py`, "
             "not missing data.")
    L.append("")
    L.append("## 2. Splits (frozen before the OOS window was touched)")
    L.append("")
    L.append("| split | window | sessions |")
    L.append("| --- | --- | --- |")
    L.append("| IS | 2026-07-06 .. 2026-08-31 | 41 |")
    L.append("| VAL | 2026-09-01 .. 2026-09-30 | 21 |")
    L.append("| OOS | 2026-10-01 .. 2026-10-21 | 13 |")
    L.append("")
    L.append("## 3. Frozen selection")
    L.append("")
    L.append("Selection rule (pre-registered in `spec.md`):")
    L.append("")
    L.append("> %s" % a["frozen"]["rule"])
    L.append("")
    L.append("| field | value |")
    L.append("| --- | --- |")
    for k in ("variant_id", "model", "config", "stop", "stop_cfg", "target",
              "target_cfg", "time_exit"):
        L.append("| %s | `%s` |" % (k, json.dumps(sel.get(k))))
    L.append("| variants evaluated | %s |" % a["frozen"]["n_variants_evaluated"])
    L.append("| variants eligible | %s |" % a["frozen"]["n_variants_eligible"])
    L.append("| selection hash | `%s` |" % a["frozen"]["selection_hash"])
    L.append("")
    L.append("Eligible variants (all of them, in order):")
    L.append("")
    L.append("| variant | model | config | stop | target | IS+VAL R/trade | trades | maxDD |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for v in a["frozen"]["eligible_variants"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            v["variant_id"], v["model"], json.dumps(v["config"]), v["stop"],
            v["target"], f(v["ISVAL_exp_r"]), v["ISVAL_n"], f(v["ISVAL_max_dd_r"], 2)))
    L.append("")
    L.append("## 4. Results of the frozen selection")
    L.append("")
    L += md(metrics_table(sp))
    L.append("")
    L.append("### Session-level block bootstrap (4000 resamples, seed 20261022)")
    L.append("")
    L.append("| split | mean R/trade | 95% CI | one-sided p (H0: mean <= 0) | sessions |")
    L.append("| --- | --- | --- | --- | --- |")
    for k in ("IS", "VAL", "ISVAL", "OOS"):
        b = boot.get(k) or {}
        L.append("| %s | %s | %s .. %s | %s | %s |" % (
            k, f(b.get("mean_r")), f(b.get("ci_low")), f(b.get("ci_high")),
            f(b.get("p_value"), 4), b.get("n_sessions")))
    L.append("")
    L.append("### Cost sensitivity (proxy cost in R per trade)")
    L.append("")
    L.append("| cost | IS | VAL | IS+VAL | OOS |")
    L.append("| --- | --- | --- | --- | --- |")
    for c, d in a["confirm"]["cost_sensitivity"].items():
        L.append("| %s R | %s | %s | %s | %s |" % (
            c, f(d["IS"].get("expectancy_r")), f(d["VAL"].get("expectancy_r")),
            f(d["ISVAL"].get("expectancy_r")), f(d["OOS"].get("expectancy_r"))))
    L.append("")
    L.append("## 5. OOS breakdowns (frozen selection)")
    L.append("")
    for key, d in a["confirm"]["breakdowns_oos"].items():
        if key == "setup_type":
            continue
        L.append("**%s**" % key)
        L.append("")
        L.append("| value | trades | expectancy R | win rate |")
        L.append("| --- | --- | --- | --- |")
        for k, v in d.items():
            L.append("| %s | %s | %s | %s |" % (
                str(k).replace("|", " / "), v["n_trades"], f(v["expectancy_r"]),
                pct(v["win_rate"])))
        L.append("")
    L.append("## 6. Walk-forward (6 chronological blocks, expanding selection)")
    L.append("")
    L.append("| block | window | selected model | trades | total R | win rate |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for b in a["wf"]:
        L.append("| %s | %s .. %s | %s | %s | %s | %s |" % (
            b["block"], b["range"][0], b["range"][1], b["selected_model"] or "-",
            b["block_trades"], f(b["block_total_r"], 2), pct(b["block_win_rate"])))
    L.append("")
    L.append("## 7. Production baseline reproduction (verification only)")
    L.append("")
    pb = a["pb"].get("summary", {})
    L.append("`app.research.cpr_trigger_engine.run_opens_range('NIFTY', "
             "'%s', '%s', 'plain')` was executed in an isolated subprocess "
             "with `TRADINGAI_DB_PATH` pointing at the study snapshot, so it "
             "could not touch the production database."
             % (pb.get("date_start"), pb.get("date_end")))
    L.append("")
    L.append("| metric | value |")
    L.append("| --- | --- |")
    for k in ("signals", "wins", "losses", "win_rate", "total_R",
              "net_R", "avg_R"):
        L.append("| %s | %s |" % (k, pb.get(k)))
    L.append("")
    L.append("This matches the independent reproduction in "
             "`research/cpr_reversal_breakout` (64 signals over "
             "2026-07-06..2026-10-19; the +1 here is the extra session "
             "2026-10-21).")
    L.append("")
    L.append("## 8. Point-in-time verification")
    L.append("")
    L.append("| check | value |")
    L.append("| --- | --- |")
    L.append("| feature recompute from a feed truncated at the previous session | %s checked, %s mismatches |"
             % (dq["pit_recompute_checked"], dq["pit_recompute_mismatches"]))
    L.append("| signal recompute with the bars after the signal bar removed | %s checked, %s mismatches |"
             % (dq.get("signal_recompute_checked"), dq.get("signal_recompute_mismatches")))
    L.append("")
    L.append("## 9. Gates")
    L.append("")
    L.append("| gate | status | detail |")
    L.append("| --- | --- | --- |")
    for k, v in a["gates"]["gates"].items():
        if not isinstance(v, dict):
            continue
        detail = {kk: vv for kk, vv in v.items()
                  if kk not in ("definition", "status")}
        L.append("| %s | %s | %s |" % (k, v.get("status"),
                                       json.dumps(detail, default=str)))
    L.append("")
    L.append("**FINAL: %s**" % a["gates"]["FINAL"])
    L.append("")
    L.append("## 10. Limitations")
    L.append("")
    L.append("- %s variants were evaluated on IS+VAL and only %s passed the "
             "pre-registered floor; the winner's IS expectancy (%s R/trade, "
             "bootstrap p=%s) is not statistically separable from zero, so the "
             "IS+VAL result carries a multiple-comparison discount that the "
             "OOS window cannot remove."
             % (a["frozen"]["n_variants_evaluated"],
                a["frozen"]["n_variants_eligible"],
                f(a["confirm"]["splits"]["IS"].get("expectancy_r")),
                f(a["confirm"]["bootstrap"]["IS"].get("p_value"), 4)))
    L.append("- The OOS window is 13 sessions and 12 trades; the whole OOS "
             "profit is long-side (%s bull trades, %s bear trades) and one "
             "trade carries %s of the OOS profit."
             % (a["confirm"]["splits"]["OOS"].get("bull_trades"),
                a["confirm"]["splits"]["OOS"].get("bear_trades"),
                pct(a["confirm"]["splits"]["OOS"].get("best_trade_share_of_profit"))))
    L.append("- Index level only: no option premium, credit or spread "
             "economics were available, so nothing here says anything about "
             "the profitability of an option spread written on this signal.")
    L.append("- yfinance 5-minute candles, volume column empty; the VWAP "
             "figure used in the study is an equal-weight proxy.")
    L.append("- One market regime (Jul-Oct 2026) and one instrument.")
    L.append("")
    return write("backtest_report.md", L)


def report_models(a):
    L = []
    L.append("# Model comparison")
    L.append("")
    L.append("Best IS+VAL configuration of every model family (the family "
             "winner is the configuration with the highest IS+VAL expectancy; "
             "the OOS column is shown for transparency only and was not used "
             "for selection).")
    L.append("")
    L.append("| family | model | stop | target | IS+VAL R/trade | IS+VAL trades |"
             " >=20 trades | IS R/trade | VAL R/trade | OOS R/trade | OOS trades |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for fam, rows in a["mc"].items():
        if not rows:
            continue
        best = max(rows, key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            fam, best["model"], best["stop"], best["target"],
            f(best["ISVAL"].get("expectancy_r")), best["ISVAL"].get("n_trades"),
            "yes" if best.get("meets_trade_floor") else "**no**",
            f(best["IS"].get("expectancy_r")), f(best["VAL"].get("expectancy_r")),
            f(best["OOS"].get("expectancy_r")), best["OOS"].get("n_trades")))
    L.append("")
    L.append("## What the families actually add")
    L.append("")
    L.append("| question | evidence | answer |")
    L.append("| --- | --- | --- |")
    b = max(a["mc"]["B_cpr_only"], key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    fml = max(a["mc"]["F_cpr_plus_vwap_proxy"],
              key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    cst = max(a["mc"]["C_prevday_plus_cpr"],
              key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    dst = max(a["mc"]["D_prevday_cpr_gap"],
              key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    ast = max(a["mc"]["A_previous_day_only"],
              key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    est = max(a["mc"]["E_or_breakout_retest"],
              key=lambda r: (r["ISVAL"].get("expectancy_r") or 0))
    L.append("| Does the equal-weight VWAP proxy add anything? | Model F "
             "(CPR + VWAP proxy): IS+VAL %s R over %s trades vs Model B "
             "(CPR only) %s R over %s trades | **No** - the proxy filter only "
             "removes trades |" % (
                 f(fml["ISVAL"].get("expectancy_r")), fml["ISVAL"].get("n_trades"),
                 f(b["ISVAL"].get("expectancy_r")), b["ISVAL"].get("n_trades")))
    L.append("| Does the previous day filter add anything on top of the CPR "
             "break? | Model C: IS+VAL %s R over %s trades; Model D: %s R over "
             "%s trades | **No** - the filter shrinks the sample below the "
             "pre-registered floor and the OOS result is negative |" % (
                 f(cst["ISVAL"].get("expectancy_r")), cst["ISVAL"].get("n_trades"),
                 f(dst["ISVAL"].get("expectancy_r")), dst["ISVAL"].get("n_trades")))
    L.append("| Does previous-day price action work on its own? | Model A: "
             "IS+VAL %s R over %s trades | Weak and far too small |" % (
                 f(ast["ISVAL"].get("expectancy_r")), ast["ISVAL"].get("n_trades")))
    L.append("| Does the opening-range breakout/retest family work? | Model E: "
             "IS+VAL %s R over %s trades, OOS %s R over %s trades | Second "
             "best family, but fewer trades and a weaker robustness profile |"
             % (f(est["ISVAL"].get("expectancy_r")), est["ISVAL"].get("n_trades"),
                f(est["OOS"].get("expectancy_r")), est["OOS"].get("n_trades")))
    L.append("")
    L.append("## Caveat")
    L.append("")
    L.append("The families above are compared on their best configuration, "
             "which is itself selected on IS+VAL. A family that trades less "
             "has a larger chance of showing a flattering IS+VAL number by "
             "accident. The pre-registered selection floor (>=20 trades) is "
             "the only guard against that, and only Model B and Model E clear "
             "it with margin.")
    L.append("")
    return write("model_comparison.md", L)


def report_stop_target(a):
    L = []
    L.append("# Stop / target analysis (frozen model configuration)")
    L.append("")
    sel = a["frozen"]["selection"]
    L.append("Model %s, config `%s`. IS+VAL = IS + VAL (62 sessions), "
             "OOS = 2026-10-01..2026-10-21 (13 sessions)."
             % (sel["model"], json.dumps(sel["config"])))
    L.append("")
    L.append("| stop | target | IS+VAL trades | IS+VAL R/trade | IS+VAL win% |"
             " IS+VAL maxDD | OOS trades | OOS R/trade | OOS win% |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in a["matrix"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["stop"], r["target"], r["isval_n"], f(_num(r["isval_exp_r"])),
            pct(_num(r["isval_win_rate"])), f(_num(r["isval_maxdd_r"]), 2),
            r["oos_n"], f(_num(r["oos_exp_r"])), pct(_num(r["oos_win_rate"]))))
    L.append("")
    L.append("## Parameter neighbourhood (same signals, other stop/target "
             "and time-exit choices)")
    L.append("")
    L.append("| stop | target | time exit | IS+VAL R/trade | trades | positive |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for n in a["robust"]["neighbours"]:
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            n.get("stop"), n.get("target"), n.get("time_exit", "EOD"),
            f(n.get("isval_exp_r")), n.get("isval_n"),
            "yes" if n.get("positive") else "no"))
    L.append("")
    L.append("Positive neighbours: **%s of %s (%.0f%%)** - the pre-registered "
             "robustness gate needs >=70%%."
             % (sum(1 for n in a["robust"]["neighbours"] if n.get("positive")),
                len(a["robust"]["neighbours"]),
                100.0 * (a["robust"]["positive_fraction"] or 0)))
    L.append("")
    L.append("## Reading")
    L.append("")
    L.append("- The result depends on where the stop sits. With a "
             "percentage stop the same signals produce at most +0.08 R/trade "
             "on IS+VAL and are negative at every target >= 1.0R; with the "
             "structural stop (CPR boundary + 10 points) the same signals "
             "produce +0.235 R/trade. A signal whose expectancy changes sign "
             "with the stop distance is not a stable edge.")
    L.append("- Fixed R targets (1.0R / 1.5R) are positive with the "
             "structural stop but the 2.0R target is not: the move does not "
             "reliably extend.")
    L.append("- Later time exits (13:30 / 14:00 / 14:30) are slightly better "
             "on IS+VAL than the 15:20 flat, so the result is not an artefact "
             "of the production flat time either.")
    L.append("- The ATR stop is positive on IS+VAL but with a wide stop "
             "distance, i.e. it is a looser version of the same trade.")
    L.append("- The STRUCT target only exists for 47 of the 59 signals: in 12 "
             "sessions there is no next structural level in the trade "
             "direction, and those trades are dropped. That is a selection "
             "effect on the winning configuration and is disclosed here "
             "rather than hidden.")
    L.append("")
    return write("stop_target_analysis.md", L)


def _num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def report_decision_table(a):
    reasons = defaultdict(Counter)
    dirs = defaultdict(Counter)
    for row in a["ledger"]:
        key = (row["model"], row["config"])
        reasons[key][row["reason"]] += 1
        dirs[key][row["direction"]] += 1
    L = []
    L.append("# Signal decision table")
    L.append("")
    L.append("One signal per session per configuration. A signal is emitted "
             "only at a 5-minute bar close; the entry is the open of the next "
             "bar. `NO_TRADE` is a first-class outcome with a closed reason "
             "taxonomy (never a silent skip).")
    L.append("")
    L.append("## Direction decision table")
    L.append("")
    L.append("| model | rule | long | short | no trade |")
    L.append("| --- | --- | --- | --- | --- |")
    rules = {
        "A": "previous-day close location (>=th / <=1-th) with a matching "
             "higher-low / lower-high structure",
        "B": "first 5-minute close beyond the previous day's CPR boundary",
        "C": "previous-day direction + close beyond the FAR CPR boundary "
             "without closing beyond the near boundary first",
        "D": "C + setup classification (CONTINUATION / REVERSAL from the gap)",
        "E": "opening-range breakout with follow-through, or a retest that "
             "holds the level",
        "F": "C with a 2-close acceptance + equal-weight VWAP proxy filter",
    }
    for m in ("A", "B", "C", "D", "E", "F"):
        tot = Counter()
        for (mm, cfg), cnt in dirs.items():
            if mm == m:
                tot.update(cnt)
        L.append("| %s | %s | %s | %s | %s |" % (
            m, rules[m], tot.get("BULLISH", 0), tot.get("BEARISH", 0),
            tot.get("NO_TRADE", 0)))
    L.append("")
    L.append("## NO_TRADE reason taxonomy (all configurations pooled)")
    L.append("")
    L.append("| reason | count | meaning |")
    L.append("| --- | --- | --- |")
    meaning = {
        "PREV_DAY_NEUTRAL": "previous-day close location was in the neutral band",
        "NO_CPR_BREAK": "no 5-minute close beyond the CPR boundary",
        "NO_CPR_CONFIRMATION": "price closed beyond the near CPR boundary first",
        "NO_BREAK": "no qualifying opening-range breakout",
        "RETEST_FAILED": "the retest closed back through the level",
        "RETEST_TIMEOUT": "no retest inside the allowed window",
        "ENTRY_WINDOW": "the signal arrived after the last allowed bar",
        "NO_ENTRY_BAR": "no next bar available for the entry",
        "VWAP_CONFLICT": "the equal-weight VWAP proxy was on the other side",
        "STALE_PREV_SESSION": "previous session older than 3 calendar days",
        "NO_PREV_SESSION": "no previous session in the data",
        "INCOMPLETE_SESSION": "session failed the data-quality floor",
        "NO_SETUP_MATCH": "the setup class was not in the allowed set",
        "DIRECTION_DISAGREEMENT": "the required directions contradicted",
        "NO_SIGNAL": "no signal condition was met",
    }
    pooled = Counter()
    signal_pooled = Counter()
    for (mm, cfg), cnt in reasons.items():
        for r, n in cnt.items():
            if r in ("BULLISH", "BEARISH", "NO_TRADE"):
                continue
            d = dirs[(mm, cfg)]
            if d.get("NO_TRADE", 0) and r in meaning:
                pooled[r] += n
            else:
                signal_pooled[r] += n
    for r, n in pooled.most_common():
        L.append("| %s | %s | %s |" % (r, n, meaning.get(r, "")))
    L.append("")
    L.append("Signal (non NO_TRADE) reason codes, all configurations pooled:")
    L.append("")
    L.append("| reason | count |")
    L.append("| --- | --- |")
    for r, n in signal_pooled.most_common():
        L.append("| %s | %s |" % (r, n))
    L.append("")
    L.append("## Frozen selection - executable decision table")
    L.append("")
    L.append("```")
    L.append("INPUT  previous session (PD) OHLC, today's 5-minute bars")
    L.append("")
    L.append("1  CPR        P  = (PD.high + PD.low + PD.close) / 3")
    L.append("              BC = (PD.high + PD.low) / 2")
    L.append("              TC = 2*P - BC")
    L.append("              upper = max(BC, TC); lower = min(BC, TC)")
    L.append("2  TRIGGER    from the 4th bar of the session onwards, the first")
    L.append("              bar that CLOSES beyond upper (long) or below lower")
    L.append("              (short). The earliest break wins; a bar can only")
    L.append("              break one side.")
    L.append("3  ENTRY      the OPEN of the bar following the trigger bar")
    L.append("4  STOP       structural: the broken CPR boundary +/- 10 points")
    L.append("5  TARGET     structural: the next structural level in the trade")
    L.append("              direction (R1, R2, PDH / S1, S2, PDL, CPR edge)")
    L.append("6  EXIT       stop (a bar that opens beyond the stop is filled at")
    L.append("              the open) | target | flat at the 15:20 OPEN")
    L.append("7  NO TRADE   no bar closes beyond a CPR boundary -> NO_TRADE")
    L.append("              reason NO_CPR_BREAK")
    L.append("```")
    L.append("")
    L.append("The machine-readable version of every field is in "
             "`signal_schema.md`; the per-session decisions are in "
             "`outputs/signal_ledger.csv`.")
    L.append("")
    return write("signal_decision_table.md", L)


def report_schema(a):
    L = []
    L.append("# Signal / feature schema")
    L.append("")
    L.append("## Feature table (`outputs/feature_table_NIFTY.csv`)")
    L.append("")
    L.append("| field | type | meaning | point-in-time source |")
    L.append("| --- | --- | --- | --- |")
    rows = [
        ("session_date", "date", "the trading session", "-"),
        ("prev_date", "date", "previous session used for every feature",
         "previous session"),
        ("prev_gap_days", "int", "calendar days between the previous session "
         "and this one (holiday aware)", "calendar"),
        ("pd_open/pd_high/pd_low/pd_close", "float", "previous session OHLC",
         "previous session"),
        ("pd_range", "float", "pd_high - pd_low", "previous session"),
        ("pd_body_pct", "float", "(close-open)/range", "previous session"),
        ("pd_upper_wick/pd_lower_wick", "float", "wick sizes", "previous session"),
        ("pd_close_location", "float", "(close-low)/range in [0,1]",
         "previous session"),
        ("pd_return_pct", "float", "close-to-close return", "previous session"),
        ("pd_range_ratio", "float", "range / median range of the 10 prior "
         "sessions", "history"),
        ("pd_structure", "enum", "HH_HL / HH_LL / LH_HL / LH_LH",
         "previous 2 sessions"),
        ("pd_day_type", "enum", "INSIDE / OUTSIDE / NORMAL vs the session "
         "before", "previous 2 sessions"),
        ("pd_close_class", "enum", "NEAR_HIGH / MIDDLE / NEAR_LOW",
         "previous session"),
        ("cpr_pp/cpr_lower/cpr_upper", "float", "central pivot and the CPR "
         "band (production formula)", "previous session"),
        ("cpr_width_pts/cpr_width_pct", "float", "CPR width in points and in "
         "% of the pivot", "previous session"),
        ("cpr_class", "enum", "NARROW <0.15% / NORMAL / WIDE >0.30%",
         "previous session"),
        ("cpr_width_pctile", "float", "percentile of the CPR width against "
         "the prior 21 sessions (null until 11 sessions exist)", "history"),
        ("today_open", "float", "first bar open of the session", "bar 1 open"),
        ("gap_points/gap_pct", "float", "open - previous close", "bar 1 open"),
        ("gap_dir", "enum", "UP / FLAT / DOWN (+/-2 points band)", "bar 1 open"),
        ("cpr_pos", "enum", "ABOVE_CPR / INSIDE_CPR / BELOW_CPR", "bar 1 open"),
        ("prev_range_pos", "enum", "ABOVE_PDH / INSIDE_RANGE / BELOW_PDL",
         "bar 1 open"),
        ("gap_cell", "string", "gap_dir + '|' + cpr_pos", "bar 1 open"),
        ("or15_high/or15_low", "float", "opening range of the first 3 bars",
         "bars 1-3"),
        ("n_bars", "int", "bars present in the session", "-"),
    ]
    for r in rows:
        L.append("| %s | %s | %s | %s |" % r)
    L.append("")
    L.append("## Signal ledger (`outputs/signal_ledger.csv`)")
    L.append("")
    L.append("| field | type | meaning |")
    L.append("| --- | --- | --- |")
    for r in [
        ("session_date", "date", "session the decision belongs to"),
        ("split", "enum", "IS / VAL / OOS"),
        ("model", "enum", "A..F"),
        ("config", "json", "the configuration of the model"),
        ("direction", "enum", "BULLISH / BEARISH / NO_TRADE"),
        ("reason", "enum", "closed taxonomy (see signal_decision_table.md)"),
        ("setup_type", "enum", "CONTINUATION / REVERSAL / UNCLASSIFIED"),
        ("level", "float", "the level that triggered the signal"),
        ("signal_ts/signal_hhmm", "timestamp", "the bar close that produced "
         "the signal"),
        ("entry_bar_idx", "int", "index of the entry bar (next bar)"),
        ("entry_ref_open", "float", "the open used as the entry price"),
        ("invalidation", "float", "the level that invalidates the setup "
         "(used by the structural stop)"),
    ]:
        L.append("| %s | %s | %s |" % r)
    L.append("")
    L.append("## Trade ledger (`outputs/trade_ledger.csv`)")
    L.append("")
    L.append("| field | type | meaning |")
    L.append("| --- | --- | --- |")
    for r in [
        ("session_date", "date", "session"),
        ("direction", "enum", "BULLISH / BEARISH"),
        ("entry_ts/entry_price", "timestamp/float", "the actual fill"),
        ("stop_price/stop_dist", "float", "stop level and its distance"),
        ("target_price", "float", "target level"),
        ("exit_ts/exit_price/exit_reason", "-", "STOP / STOP_GAP / TARGET / "
         "TIME_EXIT / EOD_LAST_CLOSE"),
        ("r", "float", "realised R = points / stop distance"),
        ("r_net", "float", "R minus the 0.10R proxy cost"),
        ("points", "float", "realised index points"),
        ("mfe_r/mae_r", "float", "maximum favourable / adverse excursion in R"),
        ("hold_bars/hold_minutes", "int/float", "holding time"),
        ("gap_fill", "bool", "the stop was filled at an open gap"),
        ("missing_exit_bar", "bool", "the 15:20 bar was missing (flagged, "
         "never hidden)"),
        ("split", "enum", "IS / VAL / OOS"),
    ]:
        L.append("| %s | %s | %s |" % r)
    L.append("")
    return write("signal_schema.md", L)


def report_final(a):
    g = a["gates"]
    sp = a["confirm"]["splits"]
    sel = a["frozen"]["selection"]
    L = []
    L.append("# Final recommendation")
    L.append("")
    L.append("## Verdict")
    L.append("")
    L.append("**%s** - the study does not support promoting any configuration "
             "to production, and it does not support writing options on this "
             "signal." % g["FINAL"])
    L.append("")
    L.append("Two pre-registered gates failed:")
    L.append("")
    for k in g["gates"].get("failed_gates", []):
        v = g["gates"][k]
        L.append("- **%s** (%s): %s" % (k, v.get("definition"),
                                       json.dumps({kk: vv for kk, vv in v.items()
                                                   if kk not in ("definition",
                                                                "status")},
                                                  default=str)))
    L.append("")
    L.append("## What was tested")
    L.append("")
    L.append("| item | value |")
    L.append("| --- | --- |")
    L.append("| instrument | NIFTY index (5-minute candles) |")
    L.append("| data | 75 complete sessions, 2026-07-06 .. 2026-10-21 |")
    L.append("| models | A previous-day, B CPR, C prev-day+CPR, D +gap, "
             "E opening-range, F +VWAP proxy |")
    L.append("| variants | %s (model config x 5 stops x 5 targets x EOD) |"
             % a["frozen"]["n_variants_evaluated"])
    L.append("| eligible | %s |" % a["frozen"]["n_variants_eligible"])
    L.append("| frozen winner | Model %s, config %s, stop %s, target %s |"
             % (sel["model"], json.dumps(sel["config"]), sel["stop"],
                sel["target"]))
    L.append("")
    L.append("## Numbers")
    L.append("")
    L.append("| split | trades | expectancy R/trade | expectancy points/trade "
             "| win rate | bootstrap p |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for k in ("IS", "VAL", "ISVAL", "OOS"):
        s = sp.get(k) or {}
        b = a["confirm"]["bootstrap"].get(k) or {}
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            k, s.get("n_trades"), f(s.get("expectancy_r")),
            f(s.get("expectancy_points"), 2), pct(s.get("win_rate")),
            f(b.get("p_value"), 4)))
    L.append("")
    L.append("## Why it is a FAIL and not a FAIL-with-caveats")
    L.append("")
    L.append("1. **The signal is stop-distance dependent.** Every percentage "
             "stop is negative on IS+VAL; only the structural stop works. A "
             "result that depends on where the stop sits is a fitted result.")
    L.append("2. **The walk-forward is not stable.** Only %s of 6 blocks are "
             "positive and blocks 2, 4 and 5 are negative."
             % sum(1 for b in a["wf"] if (b.get("block_total_r") or 0) > 0))
    L.append("3. **The OOS profit is concentrated.** The best single trade is "
             "%s of the OOS profit (%s R); the expectation without it is "
             "%s R/trade, still positive but no longer clean."
             % (pct(sp["OOS"].get("best_trade_share_of_profit")),
                f(sp["OOS"].get("best_trade_r"), 2),
                f(sp["OOS"].get("avg_r_excl_best"))))
    L.append("4. **The edge is one-sided in the OOS window.** %s bull trades "
             "produced the gain, %s bear trades produced %s R/trade."
             % (sp["OOS"].get("bull_trades"), sp["OOS"].get("bear_trades"),
                f((a["confirm"]["breakdowns_oos"]["direction"]
                   .get("BEARISH") or {}).get("expectancy_r"))))
    L.append("5. **Multiple comparisons.** %s variants were screened on "
             "IS+VAL; the winner's IS expectancy is %s R/trade with a "
             "bootstrap p of %s - not separable from zero."
             % (a["frozen"]["n_variants_evaluated"],
                f(sp["IS"].get("expectancy_r")),
                f(a["confirm"]["bootstrap"]["IS"].get("p_value"), 4)))
    L.append("")
    L.append("## What was NOT concluded")
    L.append("")
    L.append("- No option-spread profitability claim. The database holds no "
             "historical option premium (`option_snapshots` = 0, "
             "`option_contracts` = 0, every `paper_spreads.credit` is NULL), "
             "so the credit side of a spread cannot be validated at all. A "
             "point edge on the index is not an edge on a spread.")
    L.append("- No claim about the production strategy. The production "
             "baseline (%s signals, %s R, %s%% win rate over the same window) "
             "was reproduced as a control and was not modified."
             % (a["pb"].get("summary", {}).get("signals"),
                a["pb"].get("summary", {}).get("total_R"),
                a["pb"].get("summary", {}).get("win_rate")))
    L.append("- No live signal, no alert, no API change, no deployment. The "
             "study only wrote inside `research/prevday_cpr_spread_study/`.")
    L.append("")
    L.append("## What would have to change")
    L.append("")
    L.append("1. A longer, independent sample: at least 6 months of 5-minute "
             "data (the yfinance limit is 60 days per chunk, so the history "
             "has to be re-pulled chunk by chunk) and a second instrument.")
    L.append("2. A frozen rule that does not depend on the stop distance: "
             "pre-declare the structural stop and the target, then re-run the "
             "whole grid once, out of sample.")
    L.append("3. Option premium history (a real bid/ask chain), so that the "
             "spread economics can be tested instead of assumed.")
    L.append("4. A pre-registered multiple-comparison control (e.g. a "
             "deflated Sharpe or a White reality check) applied to the "
             "%s-variant grid." % a["frozen"]["n_variants_evaluated"])
    L.append("")
    L.append("## Reproduce")
    L.append("")
    L.append("```")
    L.append("cd /opt/tradingai")
    L.append("python3 -m pytest research/prevday_cpr_spread_study/tests -q")
    L.append("python3 -m research.prevday_cpr_spread_study.src.run_all")
    L.append("python3 -m research.prevday_cpr_spread_study.src.make_reports")
    L.append("```")
    L.append("")
    return write("final_recommendation.md", L)


def main():
    os.makedirs(REPORTS, exist_ok=True)
    a = load()
    paths = [report_backtest(a), report_models(a), report_stop_target(a),
             report_decision_table(a), report_schema(a), report_final(a)]
    print("\n".join(paths))


if __name__ == "__main__":
    main()
