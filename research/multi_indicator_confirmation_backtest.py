"""Research-only indicator signals/confirmation backtest; does not touch live code."""
from collections import defaultdict, deque
from app.core.db import get_conn
from app.research.cpr_trigger_engine import day_levels, prev_session_ohlc, session_candles, exits_opens, decay_win, run_opens_range, OPEN_STOP_PCT, OPEN_TARGET_PCT
START,END,INST='2026-07-06','2026-10-22','NIFTY'
CUT='15:00'; EOD='15:20'; ENTRY_MIN='09:20'; ENTRY_MAX='15:00'

def sma(xs,n):
 q=deque(); total=0.; out=[]
 for x in xs:
  q.append(x); total+=x
  if len(q)>n: total-=q.popleft()
  out.append(total/n if len(q)==n else None)
 return out

def ema(xs,n):
 a=2/(n+1); out=[]; v=None
 for x in xs: v=x if v is None else v+a*(x-v); out.append(v)
 return out

def rsi_wilder(xs,n=14):
 out=[None]*len(xs); gains=[]; losses=[]; ag=al=None
 for i in range(1,len(xs)):
  d=xs[i]-xs[i-1]; g=max(d,0); l=max(-d,0)
  if ag is None:
   gains.append(g); losses.append(l)
   if len(gains)==n:
    ag=sum(gains)/n; al=sum(losses)/n
  else:
   ag=((n-1)*ag+g)/n; al=((n-1)*al+l)/n
  if ag is not None:
   out[i]=100. if al==0 else 100-100/(1+ag/al)
 return out

def stats(tr):
 n=len(tr); w=sum(t['label']=='WIN' for t in tr); pos=sum(t['points']>0 for t in tr); gross=sum(t['R'] for t in tr)
 return {'trades':n,'labeled_wins':w,'labeled_losses':sum(t['label']=='LOSS' for t in tr),'labeled_win_rate_pct':round(100*w/n,1) if n else 0,'raw_positive':pos,'raw_positive_pct':round(100*pos/n,1) if n else 0,'gross_R':round(gross,2),'net_R_after_0.10_cost':round(gross-.1*n,2),'points':round(sum(t['points'] for t in tr),1)}

def main():
 conn=get_conn()
 try:
  rows=[dict(r) for r in conn.execute('SELECT timestamp,open,high,low,close FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)<=? ORDER BY timestamp',(INST,END)).fetchall()]
  days=[r[0] for r in conn.execute('SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1',(INST,START,END)).fetchall()]
  # All historical candles seed indicators; only requested-period sessions trade.
  closes=[float(r['close']) for r in rows]; ma20=sma(closes,20); ma50=sma(closes,50)
  em12=ema(closes,12); em26=ema(closes,26); ml=[a-b for a,b in zip(em12,em26)]; ms=ema(ml,9); rv=rsi_wilder(closes,14)
  ind={r['timestamp']:{'close':closes[i],'sma20':ma20[i],'sma50':ma50[i],'macd':ml[i],'macds':ms[i],'rsi':rv[i]} for i,r in enumerate(rows)}
  allrows={r['timestamp']:r for r in rows}
  results=defaultdict(list); no_signal=defaultdict(int); eod_missing=defaultdict(int)
  for d in days:
   prev=prev_session_ohlc(conn,INST,d); lv=day_levels(prev['high'],prev['low'],prev['close']) if prev else None
   candles=session_candles(conn,INST,d)
   if not lv: continue
   # CPR-aware state based on prior-day central range/pivot.
   for i,c in enumerate(candles):
    ts=c['timestamp']; tm=ts[11:16]
    if tm>=CUT or i==0: continue
    cur=ind.get(ts); prv=ind.get(candles[i-1]['timestamp'])
    if not cur or not prv: continue
    cl=cur['close']; pc=prv['close']; states={}
    for key,ma in [('SMA20','sma20'),('SMA50','sma50')]:
     x,y=cur[ma],prv[ma]
     if x is not None: states[key]='BULL' if cl>x else ('BEAR' if cl<x else None)
    if cur['macd'] is not None and cur['macds'] is not None: states['MACD']='BULL' if cur['macd']>cur['macds'] else ('BEAR' if cur['macd']<cur['macds'] else None)
    if cur['rsi'] is not None: states['RSI']='BULL' if cur['rsi']>=55 else ('BEAR' if cur['rsi']<=45 else None)
    if cl>lv['tc']: states['CPR']='BULL'
    elif cl<lv['bc']: states['CPR']='BEAR'
    elif cl>lv['pp']: states['CPR']='BULL'
    elif cl<lv['pp']: states['CPR']='BEAR'
    else: states['CPR']=None
    ev={}
    # CPR reversal events: support/resistance touch followed by close rejection.
    lev=None
    for name,k in [('R2','r2'),('R1','r1'),('PDH','pdh')]:
     if float(c['high'])>=lv[k] and cl<lv[k]: lev=('BEAR','CPR_REV_'+name); break
    if lev is None:
     for name,k in [('S2','s2'),('S1','s1'),('PDL','pdl')]:
      if float(c['low'])<=lv[k] and cl>lv[k]: lev=('BULL','CPR_REV_'+name); break
    if lev: ev['CPR_REV']=lev
    # Breakouts: fresh close-cross across central CPR and pivot support/resistance.
    br=None
    for name,k in [('R2','r2'),('R1','r1'),('PDH','pdh'),('TC','tc'),('PP','pp')]:
     if pc<=lv[k]<cl: br=('BULL','CPR_BRK_'+name); break
    if br is None:
     for name,k in [('S2','s2'),('S1','s1'),('PDL','pdl'),('BC','bc'),('PP','pp')]:
      if pc>=lv[k]>cl: br=('BEAR','CPR_BRK_'+name); break
    if br: ev['CPR_BRK']=br
    # Indicator-specific signal events; directional states alone do not create trades.
    for key,ma in [('SMA20','sma20'),('SMA50','sma50')]:
     x,y=cur[ma],prv[ma]
     if x is not None and y is not None:
      if pc<=y and cl>x: ev[key]=('BULL',key+'_CROSS_UP')
      elif pc>=y and cl<x: ev[key]=('BEAR',key+'_CROSS_DOWN')
    if cur['macd'] is not None and cur['macds'] is not None and prv['macd'] is not None and prv['macds'] is not None:
     if prv['macd']<=prv['macds'] and cur['macd']>cur['macds']: ev['MACD']=('BULL','MACD_CROSS_UP')
     elif prv['macd']>=prv['macds'] and cur['macd']<cur['macds']: ev['MACD']=('BEAR','MACD_CROSS_DOWN')
    if cur['rsi'] is not None and prv['rsi'] is not None:
     if prv['rsi']<55<=cur['rsi']: ev['RSI']=('BULL','RSI_CROSS_55')
     elif prv['rsi']>45>=cur['rsi']: ev['RSI']=('BEAR','RSI_CROSS_45')
    # Evaluate candidate signal family solo or with k votes from independent
    # indicator states; same family is excluded from its own confirmation count.
    source_sets={'CPR_REV':['CPR_REV'],'CPR_BRK':['CPR_BRK'],'CPR_ALL':['CPR_REV','CPR_BRK'],
                 'SMA20':['SMA20'],'SMA50':['SMA50'],'MACD':['MACD'],'RSI':['RSI']}
    for source,names in source_sets.items():
     sig=next((ev[n] for n in names if n in ev),None)
     if not sig: continue
     dr,label=sig
     confirm_sources=[k for k in ['CPR','SMA20','SMA50','MACD','RSI'] if k not in (['CPR'] if source.startswith('CPR') else [source])]
     agree=sum(states.get(k)==dr for k in confirm_sources)
     for k in (0,1,2):
      if agree>=k: results[f'{source}_confirm_{k}'].append((d,ts,dr,label,i))
    # Broad consensus: one trigger event plus at least N of 5 directional states agree.
    for n in (3,4):
     for source,(dr,label) in ev.items():
      agree=sum(states.get(k)==dr for k in ['CPR','SMA20','SMA50','MACD','RSI'])
      if agree>=n:
       results[f'CONSENSUS_{n}_of_5'].append((d,ts,dr,label,i)); break
  # For each strategy retain only first qualified event/day, execute at next 5m open.
  trades_by={}
  for strat,signals in results.items():
   seen=set(); trades=[]
   for d,ts,dr,label,i in signals:
    if d in seen: continue
    dayc=session_candles(conn,INST,d); idx=next((j for j,c in enumerate(dayc) if c['timestamp']==ts),None)
    if idx is None or idx+1>=len(dayc): continue
    et=dayc[idx+1]['timestamp']; etm=et[11:16]
    if not (ENTRY_MIN<=etm<=ENTRY_MAX): continue
    eod=[c for c in dayc if c['timestamp'][11:16]==EOD]
    if not eod: eod_missing[strat]+=1; continue
    entry=float(dayc[idx+1]['open']); opens=[(c['timestamp'],c['open']) for c in dayc[idx+2:] if c['timestamp'][11:16]<=EOD]
    hit=exits_opens(dr,entry,OPEN_STOP_PCT,OPEN_TARGET_PCT,opens)
    if hit is None:
     xp=float(eod[0]['open']); risk=entry*OPEN_STOP_PCT; move=xp-entry if dr=='BULL' else entry-xp; rr=round(move/risk,3); reason='EOD-1520'; xt=eod[0]['timestamp']
    else: rr,xp,reason,xt=hit
    pts=round(xp-entry if dr=='BULL' else entry-xp,1)
    trades.append({'strategy':strat,'date':d,'direction':dr,'signal':label,'signal_time':ts,'entry_time':et,'exit_time':xt,'entry':round(entry,2),'exit':round(xp,2),'points':pts,'R':rr,'label':decay_win(dr,entry,xp,rr,INST),'exit_reason':reason})
    seen.add(d)
   trades_by[strat]=trades
  baseline=run_opens_range(INST,START,END,'plain')
  baseline_trades=[{'strategy':'CURRENT_CPR_BASELINE','date':t['trade_date'],'direction':t['direction'],'signal':t['level'],'signal_time':t['signal_time'],'entry_time':t['entry_time'],'exit_time':t['exit_time'],'entry':t['entry'],'exit':t['exit'],'points':t['points'],'R':t['r_multiple'],'label':t['win_loss'],'exit_reason':t['exit_reason']} for t in baseline['trades']]
 finally: conn.close()
 return days,baseline_trades,trades_by,dict(no_signal),dict(eod_missing)

if __name__=='__main__':
 import csv,json
 from pathlib import Path
 days,baseline,trade_map,ns,me=main(); split='2026-08-28'
 report={'period':{'instrument':INST,'start':START,'end':END,'sessions':len(days)},
 'definitions':{'CPR_REV':'resistance touch+close below PDH/R1/R2 or support touch+close above PDL/S1/S2','CPR_BRK':'completed close crosses TC/PP/BC, PDH/PDL, R1/R2/S1/S2; direction follows break','SMA20/SMA50':'close crosses its simple moving average','MACD':'12/26 line crosses 9-period signal','RSI':'Wilder RSI14 crosses 55 bull / 45 bear; confirmation state neutral between 45 and 55','confirmation':'other-source direction states at signal close; each candidate source excluded; CPR state uses above/below CPR/PP; entry at next open, 0.5% SL, 2% target, cutoff 15:00, EOD 15:20','labels':'adverse move under 30 points counts labeled WIN; raw-positive rate separately; net R subtracts estimated 0.10R per trade'},
 'baseline_current_CPR':stats(baseline),'strategies':{},'missing_eod_by_strategy':me}
 alltrades=list(baseline)
 for name,ts in sorted(trade_map.items()):
  # Multiple repeated confirmations produce same events; retain independent statistics.
  bysetup=defaultdict(list)
  for t in ts: bysetup[t['signal']].append(t)
  report['strategies'][name]={'all':stats(ts),'first_half':stats([t for t in ts if t['date']<=split]),'second_half':stats([t for t in ts if t['date']>split]),'by_signal':{k:stats(v) for k,v in bysetup.items()},'no_trade_days':len(days)-len(ts)}
  alltrades.extend(ts)
 root=Path(__file__).resolve().parent
 (root/'multi_indicator_confirmation_results.json').write_text(json.dumps(report,indent=2)+'\n')
 fields=['strategy','date','direction','signal','signal_time','entry_time','exit_time','entry','exit','points','R','label','exit_reason']
 with (root/'multi_indicator_confirmation_trades.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(alltrades)
 print('PERIOD',report['period']); print('BASELINE',report['baseline_current_CPR'])
 for k,v in report['strategies'].items(): print(k,v['all'],'first_half',v['first_half'],'second_half',v['second_half'],'no_trade_days',v['no_trade_days'])
 print('JSON',root/'multi_indicator_confirmation_results.json'); print('CSV',root/'multi_indicator_confirmation_trades.csv')
