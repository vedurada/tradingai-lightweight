#!/usr/bin/env python3
"""TradingAI unattended live market monitor (paper-monitoring only)."""
import os, json, sqlite3, uuid, time, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

DB="/opt/tradingai/database/tradingai.db"
SETTINGS="/opt/tradingai/config/settings.json"
MON_DIR="/opt/tradingai/monitoring/live_watch"
LOG_DIR="/opt/tradingai/monitoring/live_watch/logs"
LOCK="/opt/tradingai/monitoring/live_watch/monitor.lock"
IST=ZoneInfo("Asia/Kolkata")
STRAT="SCALP_HLC"

def now_ist(): return dt.datetime.now(IST)
def parse_ist(s): return dt.datetime.fromisoformat(s)

def in_session(now):
    if now.weekday()>=5: return False
    try:
        import importlib.util
        spec=importlib.util.spec_from_file_location("nse_cal","/opt/tradingai/app/market/nse_calendar.py")
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        hol=set(getattr(m,'NSE_HOLIDAYS',[]) or [])
        if now.date().isoformat() in hol: return False
    except Exception: pass
    t=now.time()
    if t < dt.time(9,15) or t > dt.time(15,30): return False
    return True

def main():
    run_id="LM-"+now_ist().strftime("%Y%m%d_%H%M%S")+"-"+uuid.uuid4().hex[:6]
    start=now_ist(); problems=[]; errors=[]; recoveries=[]; signals=0; paper=0; alerts=0
    status="RUNNING"; market_state="UNKNOWN"; data_freshness="UNKNOWN"; strategy_mode=STRAT
    try:
        st=json.load(open(SETTINGS))
        sm=None
        if isinstance(st,dict):
            strat=st.get("strategies")
            if isinstance(strat,dict):
                d=strat.get("directional") or {}
                sm=d.get("name") if isinstance(d,dict) else None
            elif isinstance(strat,list):
                for s in strat:
                    if isinstance(s,dict) and s.get("name"):
                        sm=s.get("name"); break
        strategy_mode=str(sm or STRAT)
    except Exception as e: errors.append(str(e))
    try:
        now=now_ist(); in_s=in_session(now)
        market_state="IN_SESSION" if in_s else "OUT_OF_SESSION"
        if not in_s: status="OUT_OF_SESSION"
        else:
            con=sqlite3.connect("file:"+DB+"?mode=ro",uri=True); con.row_factory=sqlite3.Row
            latest={}
            for inst in ["NIFTY","BANKNIFTY"]:
                r=con.execute("SELECT timestamp,close,ingested_at,is_complete,data_state FROM market_candles_5m WHERE instrument_id=? AND is_complete=1 ORDER BY timestamp DESC LIMIT 1",(inst,)).fetchone()
                latest[inst]=dict(r) if r else None
            data_freshness={k:(v["timestamp"] if v else None) for k,v in latest.items()}
            for inst,v in latest.items():
                if not v: problems.append("NO_CANDLE_"+inst); data_freshness[inst]="NO_CANDLE"
                else:
                    try:
                        ing=parse_ist(v["ingested_at"]); age=(now-ing).total_seconds()/60
                        data_freshness[inst]="FRESH" if age<15 else "STALE"
                        if age>=15: problems.append("STALE_CANDLE_"+inst)
                    except Exception: problems.append("CANDLE_TS_ERR_"+inst); data_freshness[inst]="BAD_TS"
            signals=con.execute("SELECT COUNT(*) FROM scalp_signals").fetchone()[0]
            paper=con.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            alerts=con.execute("SELECT COUNT(*) FROM paper_trade_events").fetchone()[0]
            con.close()
            if problems: status="DATA_UNHEALTHY"
    except Exception as e:
        status="ERROR"; errors.append(str(e))
    finish=now_ist(); duration=(finish-start).total_seconds()
    log={"run_id":run_id,"start":start.isoformat(),"finish":finish.isoformat(),"duration_s":duration,
         "status":status,"strategy_mode":strategy_mode,"market_state":market_state,"data_freshness":data_freshness,
         "signals":signals,"paper_trades":paper,"alerts":alerts,"detected_problems":problems,
         "recovery_attempts":recoveries,"errors":errors}
    Path(LOG_DIR).mkdir(parents=True,exist_ok=True)
    with open(Path(LOG_DIR)/f"{run_id}.json","w") as f: json.dump(log,f,indent=2,default=str)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
