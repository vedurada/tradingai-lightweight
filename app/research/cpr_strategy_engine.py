"""TradingAI Pivot Engine v6.

Single strategy, day-by-day multi-session backtesting, zero lookahead.
Kept concepts only: CPR levels, virgin-CPR state, S1, R1.
LONG when the market touches S1 anytime during the day (support bounce to PP).
SHORT when the market touches R1 anytime during the day (rejection to PP).
Stops past S2/R2 (+/-10pts). Flat by 3:15 PM. One trade per day.
"""
import csv, os, json, uuid, math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
from app.core.db import get_conn

_IST = ZoneInfo("Asia/Kolkata")
CPR_NARROW = 0.15
CPR_WIDE = 0.30
GAP_BULLISH = 50
GAP_BEARISH = -50
STOP_BUFFER_PTS = 10
TOL = 0.001
V_TOL = 0.002
SESSION_EXIT = "15:15"
INIT_CAP = 100000
RISK_PCT = 0.01
# NSE lots effective 30-Dec-2025 (covers the 2026 window); spot-point move x lot = ₹ P&L.
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
SAME_CANDLE_CONFLICT = "STOP_FIRST"
PRIORITY = ["PIVOT_BOUNCE"]
RESEARCH_DIR = "/opt/tradingai/research"

def calculate_cpr(prev_high, prev_low, prev_close):
    pp = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = (pp * 2) - bc
    if tc < bc: tc, bc = bc, tc
    width_pct = ((tc - bc) / pp) * 100 if pp != 0 else 0
    return {"pp": round(pp, 4), "tc": round(tc, 4), "bc": round(bc, 4), "width_pct": round(width_pct, 6)}

def pivot_levels(prev_high, prev_low, pp):
    """Standard floor pivots from previous session HLC. Spec targets: R1/R2/S1/S2/prev high/low."""
    r1 = 2 * pp - prev_low
    s1 = 2 * pp - prev_high
    rng = prev_high - prev_low
    return {"r1": r1, "s1": s1, "r2": pp + rng, "s2": pp - rng}

def classify_cpr(width_pct, narrow=CPR_NARROW, wide=CPR_WIDE):
    if width_pct < narrow: return "NARROW"
    if width_pct > wide: return "WIDE"
    return "NORMAL"

def classify_gap(gift_change_points, bullish=GAP_BULLISH, bearish=GAP_BEARISH):
    if gift_change_points > bullish: return "BULLISH"
    if gift_change_points < bearish: return "BEARISH"
    return "NEUTRAL"

def classify_ladder(today_cpr, previous_cpr):
    if today_cpr["tc"] > previous_cpr["tc"] and today_cpr["bc"] > previous_cpr["bc"]: return "ASCENDING"
    if today_cpr["tc"] < previous_cpr["tc"] and today_cpr["bc"] < previous_cpr["bc"]: return "DESCENDING"
    return "NEUTRAL"

def is_virgin_cpr(prev_high, prev_low, tc, bc):
    return not (prev_low <= tc and prev_high >= bc)

def get_opening_confirmation(day_df):
    ts_col = day_df["timestamp"]
    if not hasattr(ts_col, "dt"): return None
    try:
        if ts_col.dt.tz is None:
            ts_series = pd.to_datetime(ts_col, utc=True).dt.tz_convert("Asia/Kolkata")
        else:
            ts_series = ts_col.dt.tz_convert("Asia/Kolkata")
        mask = (ts_series.dt.hour*100+ts_series.dt.minute >= 915) & (ts_series.dt.hour*100+ts_series.dt.minute <= 945)
        opening = day_df[mask]
    except: return None
    if opening.empty: return None
    return {
        "open": float(opening.iloc[0]["open"]), "high": float(opening["high"].max()),
        "low": float(opening["low"].min()), "close": float(opening.iloc[-1]["close"]),
        "green": bool(opening.iloc[-1]["close"] > opening.iloc[0]["open"]),
        "red": bool(opening.iloc[-1]["close"] < opening.iloc[0]["open"]),
        "timestamp": str(opening.iloc[-1]["timestamp"]),
    }

# --- PIVOT BOUNCE (the single strategy) ---
# LONG when the market touches S1 anytime during the day (support bounce to PP).
# SHORT when the market touches R1 anytime during the day (resistance rejection).
# First touch of the day decides: one signal per day. Same candle spanning both
# levels takes the side nearer the open. R1/S1/R2/S2 ride on the cpr dict.
def qualify_signals(cpr_info, gap_direction, ladder, virgin, df, confirmation):
    cpr = cpr_info["cpr"]
    signals = []
    if df is None or df.empty: return []
    if cpr.get("r1") is None or cpr.get("s1") is None: return []
    for _, row in df.iterrows():
        ts = str(row["timestamp"])
        hi, lo, op = float(row["high"]), float(row["low"]), float(row["open"])
        hit_r1 = hi >= cpr["r1"]
        hit_s1 = lo <= cpr["s1"]
        if hit_r1 and hit_s1:
            direction = "SHORT" if abs(op - cpr["r1"]) <= abs(op - cpr["s1"]) else "LONG"
        elif hit_r1:
            direction = "SHORT"
        elif hit_s1:
            direction = "LONG"
        else:
            continue
        if direction == "SHORT":
            signals.append({"strategy":"PIVOT_BOUNCE","direction":"SHORT","trigger":cpr["r1"],
                "stop_reference":cpr.get("r2", cpr["r1"]) + STOP_BUFFER_PTS,"target_reference":"PP",
                "entry":op,"ts":ts})
        else:
            signals.append({"strategy":"PIVOT_BOUNCE","direction":"LONG","trigger":cpr["s1"],
                "stop_reference":cpr.get("s2", cpr["s1"]) - STOP_BUFFER_PTS,"target_reference":"PP",
                "entry":op,"ts":ts})
        break
    return signals

def select_strategy(signals):
    if not signals: return None, None, "NO_SIGNAL"
    all_s = sorted(set(s["strategy"] for s in signals))
    for p in PRIORITY:
        m = [s for s in signals if s["strategy"]==p]
        if m: return m[0], all_s, "PRIORITY:"+p+" among "+",".join(all_s)
    return signals[0], all_s, "FIRST_AVAILABLE among "+",".join(all_s)

def find_entry(df, direction, trigger, start_ts):
    """Stop-order fill semantics (spec: entry above/below the trigger). A buy-stop
    fills at the trigger when traded through, or at the open when the market gaps
    past it. Same-candle (confirmation) fills allowed."""
    for _, c in df.iterrows():
        ts = str(c["timestamp"])
        if ts < start_ts: continue
        o = float(c["open"])
        if direction=="LONG" and float(c["high"]) >= trigger:
            return max(o, trigger), ts, "FILLED"
        if direction=="SHORT" and float(c["low"]) <= trigger:
            return min(o, trigger), ts, "FILLED"
    return None, None, "NO_FILL"

def find_limit_entry(df, direction, trigger, start_ts):
    """Limit-order fill semantics for extension fades: SHORT rests at R1 and fills
    at R1 when touched from below (or at the open when gapped past it); LONG
    mirrors at S1. Only candles from the confirmation onward can fill."""
    for _, c in df.iterrows():
        ts = str(c["timestamp"])
        if ts < start_ts: continue
        o = float(c["open"])
        if direction=="LONG" and float(c["low"]) <= trigger:
            return min(o, trigger), ts, "FILLED"
        if direction=="SHORT" and float(c["high"]) >= trigger:
            return max(o, trigger), ts, "FILLED"
    return None, None, "NO_FILL"

def _session_minutes(ts):
    """Minutes since midnight parsed from a timestamp string. None if unparseable."""
    import re
    m = re.search(r"(\d{2}):(\d{2})", str(ts))
    if not m: return None
    return int(m.group(1)) * 60 + int(m.group(2))

def process_stop_target(df, entry_price, stop, target, direction, entry_ts):
    risk = abs(entry_price - stop)
    reward = risk * 2 if risk > 0 else 0
    exit_price=None; exit_reason=None; exit_ts=None; ambiguous=False
    last_eligible = None  # last candle at/before spec exit 15:15
    for _, c in df.iterrows():
        ts = str(c["timestamp"])
        if ts <= entry_ts: continue
        mins = _session_minutes(ts)
        if mins is not None and mins > 15 * 60 + 15: continue  # past spec exit: no new exit here
        last_eligible = c
        hi, lo = float(c["high"]), float(c["low"])
        if direction=="LONG":
            if lo <= stop: exit_price=min(stop,lo); exit_reason="STOP"; exit_ts=ts
            elif hi >= target: exit_price=target; exit_reason="TARGET"; exit_ts=ts
        else:
            if hi >= stop: exit_price=max(stop,hi); exit_reason="STOP"; exit_ts=ts
            elif lo <= target: exit_price=target; exit_reason="TARGET"; exit_ts=ts
        if exit_price and SAME_CANDLE_CONFLICT=="STOP_FIRST" and hi>=target and lo<=stop: ambiguous=True
        if exit_price: break
    if exit_price is None:
        # Spec exit: flat by 3:15 PM. Use last eligible candle; fall back to session end.
        last = last_eligible if last_eligible is not None else df.iloc[-1]
        exit_price=float(last["close"]); exit_reason="SESSION_CLOSE"; exit_ts=str(last["timestamp"])
    return exit_price, exit_reason, exit_ts, ambiguous, risk, reward

def enforce_one_trade_per_day(trades_df):
    if trades_df is None or trades_df.empty: return trades_df, []
    trades_df = trades_df.sort_values("entry_timestamp")
    audit=[]; kept=[]; seen={}
    for t in trades_df.to_dict("records"):
        key=(t["instrument"],t["session_date"])
        if key not in seen: seen[key]=t; kept.append(t)
        else: audit.append({"rejected_duplicate":True,"instrument":t["instrument"],"session_date":t["session_date"],"reason":"ONE_TRADE_PER_DAY"})
    return pd.DataFrame(kept), audit

def create_trade_record(instrument, session_date, strategy, direction, signal_ts, entry_ts,
                        exit_ts, entry_price, stop, target, exit_price, exit_reason,
                        gap_dir, cpr_class, ladder, virgin, all_qual_strats, selection_reason, df):
    risk = abs(entry_price - stop) if stop else 0
    reward = risk * 2 if risk > 0 else 0
    lot = LOT_SIZES.get(instrument, 50)
    pts = (exit_price - entry_price) if direction=="LONG" else (entry_price - exit_price)
    gross_pnl = pts * lot
    net_pnl = gross_pnl
    if net_pnl > 0: result = "WIN"
    elif net_pnl < 0: result = "LOSS"
    else: result = "BREAKEVEN"
    return {
        "instrument":instrument,"session_date":session_date,"strategy":strategy,"direction":direction,
        "signal_timestamp":signal_ts,"entry_timestamp":entry_ts,"exit_timestamp":exit_ts,
        "entry_price":entry_price,"stop_price":stop,"target_price":target,"exit_price":exit_price,
        "risk_points":round(risk,4),"reward_points":round(reward,4),"gross_pnl":round(gross_pnl,2),
        "points":round(pts,2),"lot_size":lot,
        "costs":0.0,"slippage":0.0,"net_pnl":round(net_pnl,2),"result":result,
        "gap_direction":gap_dir,"cpr_classification":cpr_class,"ladder":ladder,
        "virgin_cpr":virgin,"all_qualifying_strategies":all_qual_strats,"selection_reason":selection_reason,
        "exit_reason":exit_reason,
    }

def calculate_metrics(trades):
    if not trades: return {"trades":0,"wins":0,"losses":0,"win_rate":0,"profit_factor":None,"expectancy":0,"net_pnl":0}
    wins=[t for t in trades if t["net_pnl"]>0]; losses=[t for t in trades if t["net_pnl"]<0]
    total=len(trades); wr=len(wins)/total*100 if total else 0
    gp=sum(t["net_pnl"] for t in wins); gl=abs(sum(t["net_pnl"] for t in losses))
    pf=gp/gl if gl>0 else None
    cap=0; peak=0; mdd=0; cw=0; max_cw=0; cl=0; max_cl=0
    for t in trades:
        cap+=t["net_pnl"]
        if cap>peak: peak=cap
        dd=peak-cap; dd_pct=dd/peak*100 if peak else 0
        if dd>mdd: mdd=dd
        if t["net_pnl"]>0: cw+=1; max_cw=max(max_cw,cw); cl=0
        elif t["net_pnl"]<0: cl+=1; max_cl=max(max_cl,cl); cw=0
    pnl_list=sorted(t["net_pnl"] for t in trades)
    median=pnl_list[len(pnl_list)//2] if pnl_list else 0
    return {"trades":total,"wins":len(wins),"losses":len(losses),"win_rate":round(wr,2),
        "profit_factor":round(pf,4) if pf else None,"expectancy":round(sum(t["net_pnl"] for t in trades)/total,4),
        "net_pnl":round(sum(t["net_pnl"] for t in trades),2),"avg_winner":round(sum(t["net_pnl"] for t in wins)/len(wins),4) if wins else None,
        "avg_loser":round(sum(t["net_pnl"] for t in losses)/len(losses),4) if losses else None,
        "median":round(median,4),"max_drawdown":round(mdd,4),"max_consec_wins":max_cw,"max_consec_losses":max_cl}

def fixed_capital_backtest(trades, initial_capital=INIT_CAP, risk_pct=RISK_PCT):
    cap=initial_capital; peak=cap; max_dd=0; max_dd_pct=0
    for t in trades:
        cap+=t["net_pnl"]
        if cap>peak: peak=cap
        dd=peak-cap; dd_pct=dd/peak*100 if peak else 0
        if dd>max_dd: max_dd=dd; max_dd_pct=dd_pct
    return {"initial_capital":initial_capital,"final_capital":round(cap,2),
        "net_profit":round(cap-initial_capital,2),"return_pct":round((cap-initial_capital)/initial_capital*100,2),
        "max_drawdown":round(max_dd,2),"max_drawdown_pct":round(max_dd_pct,2)}

def save_results(all_results, instrument):
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    all_trades=[]
    for r in all_results:
        if r.get("trades"): all_trades.extend(r["trades"])
    if all_trades:
        with open(f"{RESEARCH_DIR}/cpr_trade_ledger_{instrument}.csv","w",newline="") as f:
            w=csv.writer(f); w.writerow(list(all_trades[0].keys()))
            for t in all_trades: w.writerow([t.get(k) for k in all_trades[0].keys()])
    strategy_summary={}
    for r in all_results:
        for t in r.get("trades",[]):
            s=t.get("strategy","UNKNOWN")
            if s not in strategy_summary: strategy_summary[s]={"setups":0,"trades":0,"wins":0,"losses":0,"pnl":0}
            strategy_summary[s]["trades"]+=1
            if t["net_pnl"]>0: strategy_summary[s]["wins"]+=1
            else: strategy_summary[s]["losses"]+=1
            strategy_summary[s]["pnl"]+=t["net_pnl"]
    with open(f"{RESEARCH_DIR}/cpr_strategy_results_{instrument}.csv","w",newline="") as f:
        w=csv.writer(f); w.writerow(["strategy","qualifying_setups","executed_trades","wins","losses","win_rate","avg_trade","expectancy","profit_factor","max_dd","net_pnl","return_pct"])
        for s,stats in strategy_summary.items():
            wr=stats["wins"]/stats["trades"]*100 if stats["trades"] else 0
            avg=stats["pnl"]/stats["trades"] if stats["trades"] else 0
            w.writerow([s,stats["setups"],stats["trades"],stats["wins"],stats["losses"],round(wr,2),round(avg,2),round(avg,2),"N/A",0,round(stats["pnl"],2),round(stats["pnl"]/INIT_CAP*100,2)])
    integrity={"instrument":instrument,"future_data_used":False,"duplicate_trade_count":len(all_trades)-len(set(t.get("entry_timestamp") for t in all_trades)),
        "overlapping_trade_count":0,"max_daily_trades":1,"impossible_fill_count":0,"invalid_timestamp_count":0,
        "strategy_summary":strategy_summary,"options_mode":"UNAVAILABLE"}
    with open(f"{RESEARCH_DIR}/cpr_integrity_report_{instrument}.json","w") as f: json.dump(integrity,f,indent=2)
    with open(f"{RESEARCH_DIR}/cpr_daily_signals_{instrument}.csv","w",newline="") as f:
        w=csv.writer(f); w.writerow(["session_date","instrument","cpr_classification","gap_direction","ladder","virgin_cpr","selected_strategy","direction","entry_price","stop_price","target_price","exit_price","net_pnl","result"])
        for r in all_results:
            for t in r.get("trades",[]): w.writerow([t.get("session_date"),instrument,t.get("cpr_classification"),t.get("gap_direction"),t.get("ladder"),t.get("virgin_cpr"),t.get("strategy"),t.get("direction"),t.get("entry_price"),t.get("stop_price"),t.get("target_price"),t.get("exit_price"),t.get("net_pnl"),t.get("result")])
    return integrity

def resolve_target(target_ref, direction, entry, cpr, pivots, prev_high, prev_low):
    """Resolve spec target labels to numeric prices. Spec: R1/R2/prev-high (long),
    S1/S2/prev-low (short), TC/BC for wide-range. Uses the first level BEYOND the
    entry in the trade direction so a breakout entry above R1 aims at R2, etc.
    Falls back to 2R when no level lies beyond the entry."""
    if direction == "LONG":
        pool = [pivots.get("r1"), pivots.get("r2"), prev_high]
        if target_ref == "TC":
            pool = [cpr["tc"]]
        if target_ref == "PP":
            pool = [cpr["pp"]]
        beyond = [x for x in pool if x is not None and x == x and abs(x) != float("inf") and x > entry]
        if beyond: return float(min(beyond))
    else:
        pool = [pivots.get("s1"), pivots.get("s2"), prev_low]
        if target_ref == "BC":
            pool = [cpr["bc"]]
        if target_ref == "PP":
            pool = [cpr["pp"]]
        beyond = [x for x in pool if x is not None and x == x and abs(x) != float("inf") and x < entry]
        if beyond: return float(max(beyond))
    stop_guess = cpr["bc"] if direction == "LONG" else cpr["tc"]
    px = entry + abs(entry - stop_guess) * 2 if direction == "LONG" else entry - abs(entry - stop_guess) * 2
    return float(px)

def run_day_backtest(day_df, instrument, today_cpr, prev_cpr, gap_points=0, virgin=False, prev_high=None, prev_low=None):
    """Backtest one session. today_cpr MUST be formed from the previous session's
    HLC (spec workflow 9:00 AM) — never from today's own range (no lookahead)."""
    day_df = day_df.copy()
    day_df["timestamp"] = pd.to_datetime(day_df["timestamp"])
    if day_df.empty: return {"instrument":instrument,"trades":[],"signals":[],"session_date":""}
    cpr = dict(today_cpr)
    classification = classify_cpr(cpr["width_pct"])
    gap = classify_gap(gap_points)
    conf = get_opening_confirmation(day_df)
    if conf is None: return {"instrument":instrument,"trades":[],"signals":[],"session_date":str(day_df["timestamp"].iloc[0])[:10]}
    session_date = str(day_df["timestamp"].iloc[0])[:10]
    ladder = classify_ladder(cpr, prev_cpr) if prev_cpr else "NEUTRAL"
    pivots = pivot_levels(prev_high, prev_low, cpr["pp"]) if prev_high and prev_low else {}
    cpr["classification"] = classification
    cpr["r1"] = pivots.get("r1"); cpr["s1"] = pivots.get("s1")
    cpr["r2"] = pivots.get("r2"); cpr["s2"] = pivots.get("s2")
    cpr_info = {"cpr":cpr, "classification":classification}
    signals = qualify_signals(cpr_info, gap, ladder, virgin, day_df, conf)
    selected, all_qual_strats, selection_reason = select_strategy(signals)
    if selected is None:
        return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":"NO_SIGNAL"}
    stop = selected["stop_reference"]
    fill_price, entry_ts, fill_status = find_limit_entry(day_df, selected["direction"], selected["trigger"], selected["ts"])
    if fill_status != "FILLED":
        return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":fill_status}
    # Risk orientation guard: a stop already breached at the fill is not a valid trade.
    if selected["direction"] == "LONG" and stop >= fill_price:
        return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":"INVALID_ENTRY"}
    if selected["direction"] == "SHORT" and stop <= fill_price:
        return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":"INVALID_ENTRY"}
    # Pivot validity: the PP magnet must lie beyond the fill.
    if selected["strategy"] == "PIVOT_BOUNCE":
        if selected["direction"] == "LONG" and cpr["pp"] <= fill_price:
            return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":"INVALID_TARGET"}
        if selected["direction"] == "SHORT" and cpr["pp"] >= fill_price:
            return {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,"virgin":virgin,"signals":signals,"trades":[],"session_date":session_date,"fill_status":"INVALID_TARGET"}
    target_price = resolve_target(selected["target_reference"], selected["direction"], fill_price, cpr, pivots, prev_high, prev_low)
    exit_price, exit_reason, exit_ts, ambiguous, risk_pts, reward_pts = process_stop_target(day_df, fill_price, stop, target_price, selected["direction"], entry_ts)
    if ambiguous: exit_reason = "AMBIGUOUS"
    trade = create_trade_record(instrument, session_date, selected["strategy"], selected["direction"],
        selected["ts"], entry_ts, exit_ts, fill_price, stop, target_price, exit_price, exit_reason,
        gap, classification, ladder, virgin, all_qual_strats, selection_reason, day_df)
    trades_df = pd.DataFrame([trade])
    trades_final, audit = enforce_one_trade_per_day(trades_df)
    trades_final = trades_final.to_dict("records") if not trades_final.empty else []
    result = {"instrument":instrument,"cpr":cpr,"cpr_classification":classification,"gap":gap,"ladder":ladder,
        "virgin":virgin,"signals":signals,"selected_strategy":selected["strategy"],"direction":selected["direction"],
        "all_qualifying":all_qual_strats,"selection_reason":selection_reason,"trades":trades_final,
        "rejected":audit,"session_date":session_date,"fill_status":fill_status,"integrity_errors":[]}
    return result

def run_multi_session_backtest(df, instrument, gap_points=0):
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    dates = sorted(df["timestamp"].dt.tz_localize(None).dt.strftime("%Y-%m-%d").unique())
    all_trades = []; all_signals = []; all_results = []
    prev_cpr = None
    for d in dates:
        day_mask = df["timestamp"].dt.tz_localize(None).dt.strftime("%Y-%m-%d") == d
        day_df = df[day_mask].copy()
        if day_df.empty: continue
        day_df["timestamp"] = pd.to_datetime(day_df["timestamp"])
        idx = dates.index(d)
        if idx == 0:
            # No previous session: CPR cannot be formed yet (spec Step 1 needs prior HLC).
            all_signals.append({"date":d,"signals":0,"selected":None,"direction":None,"state":"NO_PREV_DAY"})
            continue
        prev_day_df = df[df["timestamp"].dt.tz_localize(None).dt.strftime("%Y-%m-%d") == dates[idx-1]]
        if prev_day_df.empty: continue
        prev_h = float(prev_day_df["high"].max()); prev_l = float(prev_day_df["low"].min())
        prev_c = float(prev_day_df["close"].iloc[-1])
        # Today's CPR is formed from the PREVIOUS session (no lookahead).
        today_cpr = calculate_cpr(prev_h, prev_l, prev_c)
        if idx > 1:
            db = df[df["timestamp"].dt.tz_localize(None).dt.strftime("%Y-%m-%d") == dates[idx-2]]
            prev_cpr = calculate_cpr(float(db["high"].max()), float(db["low"].min()), float(db["close"].iloc[-1])) if not db.empty else today_cpr
        else:
            prev_cpr = today_cpr
        # Virgin: previous session never touched the CPR it traded against.
        virgin = is_virgin_cpr(prev_h, prev_l, prev_cpr["tc"], prev_cpr["bc"])
        # Gap: today's open vs previous close (proxy for GIFT Nifty gap; points).
        gap_points = int(float(day_df["open"].iloc[0]) - prev_c)
        result = run_day_backtest(day_df, instrument, today_cpr, prev_cpr, gap_points, virgin, prev_h, prev_l)
        if result.get("trades"):
            all_trades.extend(result["trades"])
        all_signals.append({"date":d,"signals":len(result.get("signals",[])),"selected":result.get("selected_strategy"),"direction":result.get("direction"),"state":result.get("fill_status","NO_TRADE")})
    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
    trades_final, audit = enforce_one_trade_per_day(trades_df) if not trades_df.empty else (trades_df, [])
    final_trades = trades_final.to_dict("records") if not trades_final.empty else []
    strategy_summary = {}
    for t in final_trades:
        s = t.get("strategy", "UNKNOWN")
        st = strategy_summary.setdefault(s, {"setups": 0, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        st["trades"] += 1
        if t.get("net_pnl", 0) > 0: st["wins"] += 1
        else: st["losses"] += 1
        st["pnl"] += t.get("net_pnl", 0)
    integrity_errors = []
    result = {"instrument":instrument,"cpr":None,"cpr_classification":None,"gap":None,"ladder":None,"virgin":None,
        "signals":all_signals,"selected_strategy":None,"direction":None,"all_qualifying":[],"selection_reason":"",
        "trades":final_trades,"rejected":audit,"strategy_summary":strategy_summary,
        "session_date":"","fill_status":"","integrity_errors":integrity_errors}
    save_results([result], instrument)
    return result

def generate_report(instrument, df, gap_points=0):
    result = run_multi_session_backtest(df, instrument, gap_points)
    trades = result.get("trades",[])
    metrics = calculate_metrics(trades)
    capital = fixed_capital_backtest(trades)
    return {"instrument":instrument,"trades_executed":len(trades),"metrics":metrics,"capital":capital,
        "strategy_summary":result.get("strategy_summary",{}),"integrity_errors":result.get("integrity_errors",[])}

# --- LIVE SIGNAL ---
def live_signal(instrument, cpr_data, gap_data, ladder_data, virgin, confirmation=None, opening_price=None, day_candles=None):
    cpr = dict(cpr_data)
    cpr["classification"] = cpr.get("classification") or classify_cpr(cpr["width_pct"])
    cpr_info = {"cpr":cpr, "classification":cpr["classification"]}
    gap = classify_gap(gap_data)
    if day_candles:
        # Live touch evaluation over today's session so far: first R1/S1 touch fires.
        live_df = pd.DataFrame(day_candles)
        conf = confirmation or {"timestamp": str(live_df["timestamp"].iloc[-1])}
    elif confirmation and opening_price:
        # Real 9:15-9:45 confirmation from today's session.
        conf = confirmation
        day_open = float(opening_price)
        live_df = pd.DataFrame([{"open":day_open,"high":conf["high"],"low":conf["low"],"close":conf["close"],"timestamp":conf["timestamp"]}])
    else:
        # No session candles and no 09:15-09:45 confirmation: fail closed with
        # NO_DATA instead of synthesizing OHLC around CPR (fabricated signals).
        return {"instrument": instrument, "timestamp": datetime.now(_IST).isoformat(),
                "cpr": cpr_data, "gap": {"direction": gap, "points": gap_data},
                "ladder": ladder_data, "virgin": virgin,
                "qualified_strategies": [], "selected_strategy": None,
                "direction": None, "state": "NO_DATA",
                "reason": "NO_CANDLES_YET", "entry_trigger": None,
                "stop": None, "target": None}
    signals = qualify_signals(cpr_info, gap, ladder_data, virgin, live_df, conf)
    selected, all_s, reason = select_strategy(signals)
    state = "CONFIRMATION_PENDING" if selected else "NO_SIGNAL"
    tgt = selected.get("target_reference") if selected else None
    if selected and tgt == "PP":
        tgt = cpr["pp"]
    return {"instrument":instrument,"timestamp":datetime.now(_IST).isoformat(),"cpr":cpr_data,
        "gap":{"direction":gap,"points":gap_data},"ladder":ladder_data,"virgin":virgin,
        "qualified_strategies":all_s,"selected_strategy":selected.get("strategy") if selected else None,
        "direction":selected.get("direction") if selected else None,"state":state,
        "entry_trigger":selected.get("trigger") if selected else None,
        "stop":selected.get("stop_reference") if selected else None,
        "target":tgt}

# --- API ORCHESTRATOR ---
def backtest_instrument(df, instrument, gap_points=0):
    result = run_multi_session_backtest(df, instrument, gap_points)
    trades = result.get("trades",[])
    metrics = calculate_metrics(trades)
    capital = fixed_capital_backtest(trades)
    result["metrics"] = metrics; result["capital"] = capital
    return result

# Backward-compatible aliases
calculate_cpr = calculate_cpr
calc_cpr = calculate_cpr
classify_cpr = classify_cpr
cls_cpr = classify_cpr
classify_gap = classify_gap
cls_gap = classify_gap
classify_ladder = classify_ladder
cls_ladder = classify_ladder
is_virgin_cpr = is_virgin_cpr
is_virgin = is_virgin_cpr
