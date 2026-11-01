"""Research-only NIFTY intraday swing/SMA20/MACD strategy backtest.

Causal pivots: a 2-left/2-right fractal becomes known two candles after its
pivot. No production/live signal code is imported or modified.
"""
from collections import defaultdict, deque
from app.core.db import get_conn
from app.research.cpr_trigger_engine import exits_opens, decay_win, run_opens_range
START, END, INSTRUMENT = '2026-07-06','2026-10-22','NIFTY'
STOP_PCT, TARGET_PCT = .005, .02
SIGNAL_CUTOFF, ENTRY_MIN, ENTRY_MAX, EOD = '15:00','09:20','15:00','15:20'


def ema(xs, span):
    a=2/(span+1); out=[]; v=None
    for x in xs:
        v=x if v is None else v+a*(x-v); out.append(v)
    return out

def calc_sma(xs, window):
    out=[]; q=deque(); total=0.0
    for x in xs:
        q.append(x); total+=x
        if len(q)>window: total-=q.popleft()
        out.append(total/window if len(q)==window else None)
    return out

def summary(ts):
    n=len(ts); wins=sum(x['label']=='WIN' for x in ts); losses=sum(x['label']=='LOSS' for x in ts)
    raw=sum(x['points']>0 for x in ts); gross=sum(x['R'] for x in ts)
    return {'trades':n,'label_wins':wins,'label_losses':losses,'label_win_rate_pct':round(100*wins/n,1) if n else 0,
            'raw_positive':raw,'raw_positive_rate_pct':round(100*raw/n,1) if n else 0,
            'gross_R':round(gross,2),'net_R_after_0.10R_cost':round(gross-.10*n,2),
            'points':round(sum(x['points'] for x in ts),1)}

def test():
    conn=get_conn()
    try:
        rows=conn.execute('SELECT timestamp,open,high,low,close FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)<=? ORDER BY timestamp',(INSTRUMENT,END)).fetchall()
    finally: conn.close()
    rows=[dict(r) for r in rows]
    closes=[float(r['close']) for r in rows]
    s20=calc_sma(closes,20); e12=ema(closes,12); e26=ema(closes,26); line=[a-b for a,b in zip(e12,e26)]; msig=ema(line,9)
    byts={r['timestamp']:(s20[i],line[i],msig[i],closes[i]) for i,r in enumerate(rows)}
    byday=defaultdict(list)
    for r in rows:
        if START<=r['timestamp'][:10]<=END: byday[r['timestamp'][:10]].append(r)
    variants={'reversal':[],'continuation':[],'combined':[]}
    skipped=defaultdict(int)
    for day,candles in sorted(byday.items()):
        # Only completed session candles and 15:00 signal cutoff.
        candles=[c for c in candles if c['timestamp'][11:16]<'15:25']
        piv_hi=[]; piv_lo=[]; known_hi=[]; known_lo=[]
        candidates=defaultdict(list)
        for i,c in enumerate(candles):
            ts=c['timestamp']; tm=ts[11:16]
            if i>=4:
                p=i-2; window=candles[p-2:p+3]
                ph=float(candles[p]['high']); pl=float(candles[p]['low'])
                if ph>=max(float(z['high']) for z in window) and ph>min(float(z['high']) for z in window):
                    known_hi.append((p,ph))
                if pl<=min(float(z['low']) for z in window) and pl<max(float(z['low']) for z in window):
                    known_lo.append((p,pl))
            if tm>=SIGNAL_CUTOFF or i==0: continue
            cur=byts.get(ts); prev=byts.get(candles[i-1]['timestamp'])
            if not cur or not prev or cur[0] is None or prev[0] is None: continue
            sma,macd,sig,cl=cur; psma,_,_,pcl=prev
            bull_macd=macd>sig; bear_macd=macd<sig
            bull_cross=pcl<=psma and cl>sma
            bear_cross=pcl>=psma and cl<sma
            recent_low=bool(known_lo and 0<=i-known_lo[-1][0]<=12)
            recent_high=bool(known_hi and 0<=i-known_hi[-1][0]<=12)
            rev=None
            if bull_cross and recent_low and bull_macd: rev=('BULL','swing_low_sma20_cross')
            elif bear_cross and recent_high and bear_macd: rev=('BEAR','swing_high_sma20_cross')
            cont=None
            # Structure uses only confirmed swings available as of this candle.
            if len(known_hi)>=2 and len(known_lo)>=2 and i>=1:
                hh=known_hi[-1][1]>known_hi[-2][1]; hl=known_lo[-1][1]>known_lo[-2][1]
                lh=known_hi[-1][1]<known_hi[-2][1]; ll=known_lo[-1][1]<known_lo[-2][1]
                # Pullback tests bars in the previous 1-4 candles; entry signal
                # is a close breakout beyond the immediately prior candle.
                lo0=max(0,i-4); prior=candles[i-1]
                pull_bull=any(byts[z['timestamp']][0] is not None and float(z['low'])<=byts[z['timestamp']][0]*1.002 and float(z['close'])>=byts[z['timestamp']][0]*.995 for z in candles[lo0:i])
                pull_bear=any(byts[z['timestamp']][0] is not None and float(z['high'])>=byts[z['timestamp']][0]*.998 and float(z['close'])<=byts[z['timestamp']][0]*1.005 for z in candles[lo0:i])
                if hh and hl and pull_bull and cl>sma and cl>float(prior['high']) and bull_macd: cont=('BULL','uptrend_pullback_resume')
                elif lh and ll and pull_bear and cl<sma and cl<float(prior['low']) and bear_macd: cont=('BEAR','downtrend_pullback_resume')
            for name,sigx in [('reversal',rev),('continuation',cont)]:
                if sigx: candidates[name].append((i,*sigx))
            if rev or cont:
                # Combined uses first qualifying bar; if both fire same candle,
                # classify reversal first to avoid double-counting.
                chosen=rev or cont
                candidates['combined'].append((i,*chosen))
        # Simulate one trade per day per strategy; next candle open entry.
        for mode in variants:
            sigs=candidates[mode]
            picked=None
            for item in sigs:
                i,dr,setup=item
                if i+1>=len(candles): continue
                ent_ts=candles[i+1]['timestamp']; ent_tm=ent_ts[11:16]
                if ENTRY_MIN<=ent_tm<=ENTRY_MAX:
                    picked=item; break
            if not picked: skipped[mode]+=1; continue
            i,dr,setup=picked; entry=float(candles[i+1]['open']); ent_ts=candles[i+1]['timestamp']
            opens=[(z['timestamp'],z['open']) for z in candles[i+2:] if z['timestamp'][11:16]<=EOD]
            eod=[z for z in candles if z['timestamp'][11:16]==EOD]
            if not eod: skipped[mode+'_missing_eod']+=1; continue
            hit=exits_opens(dr,entry,STOP_PCT,TARGET_PCT,opens)
            if hit is None:
                xp=float(eod[0]['open']); rr=abs(entry*STOP_PCT); move=xp-entry if dr=='BULL' else entry-xp; R=round(move/rr,3) if rr else 0; reason='EOD-1520'
            else: R,xp,reason,_=hit
            pts=round(xp-entry if dr=='BULL' else entry-xp,1)
            variants[mode].append({'date':day,'setup':setup,'direction':dr,'signal_time':candles[i]['timestamp'],'entry_time':ent_ts,'entry':round(entry,2),'exit':round(xp,2),'points':pts,'R':R,'label':decay_win(dr,entry,xp,R,INSTRUMENT),'exit_reason':reason})
    return variants,skipped,len(byday)

if __name__=='__main__':
    import csv, json
    from pathlib import Path
    variants,skipped,nd=test()
    base=run_opens_range(INSTRUMENT,START,END,'plain')
    baseline=[{'date':t['trade_date'],'setup':'current_cpr','direction':t['direction'],'signal_time':t.get('signal_time'),'entry_time':t['entry_time'],'entry':t['entry'],'exit':t['exit'],'points':t['points'],'R':t['r_multiple'],'label':t['win_loss'],'exit_reason':t['exit_reason']} for t in base['trades']]
    all_trades=[{'strategy':'current_cpr',**t} for t in baseline]
    report={'range':{'instrument':INSTRUMENT,'start':START,'end':END,'sessions':nd},
            'method':{'swing':'2-left/2-right fractal; pivot is usable only after two right-hand candles complete',
                      'reversal':'confirmed swing low/high followed within 12 bars by a close cross above/below simple SMA20, MACD(12,26,9) line aligned with signal',
                      'continuation':'confirmed higher-high+higher-low or lower-high+lower-low structure; 4-bar pullback near SMA20; close breaks prior candle high/low in trend direction with MACD aligned',
                      'execution':'one trade per day per strategy; first qualifying setup before 15:00; next 5-minute open; 0.5% stop, 2% target, subsequent opens, 15:20 EOD; <30 adverse points counts as labeled WIN; costs shown as estimated 0.10R/trade'},
            'baseline_current_cpr':summary([{'label':t['label'],'points':t['points'],'R':t['R']} for t in baseline]),'variants':{},'skipped':dict(skipped)}
    mid='2026-08-28'
    for name,ts in variants.items():
        by=defaultdict(list)
        for t in ts: by[t['setup']].append(t)
        report['variants'][name]={'overall':summary(ts),
             'first_half':summary([t for t in ts if t['date']<=mid]),
             'second_half':summary([t for t in ts if t['date']>mid]),
             'by_setup':{k:summary(v) for k,v in by.items()},
             'skipped_no_signal':skipped[name], 'skipped_missing_eod':skipped[name+'_missing_eod']}
        all_trades.extend({'strategy':name,**t} for t in ts)
    root=Path(__file__).resolve().parent
    (root/'trend_reversal_continuation_results.json').write_text(json.dumps(report,indent=2)+'\n')
    fields=['strategy','date','setup','direction','signal_time','entry_time','entry','exit','points','R','label','exit_reason']
    with (root/'trend_reversal_continuation_trades.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(all_trades)
    print('RANGE',report['range'])
    print('BASELINE_CURRENT_CPR',report['baseline_current_cpr'])
    for name,metrics in report['variants'].items(): print(name.upper(),metrics)
    print('OUTPUT_JSON',root/'trend_reversal_continuation_results.json')
    print('OUTPUT_CSV',root/'trend_reversal_continuation_trades.csv')
