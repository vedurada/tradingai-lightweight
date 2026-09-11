/* Black-Scholes option pricing (European). */
function normCDF(x){var a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;var sign=x<0?-1:1;x=Math.abs(x)/Math.SQRT2;var t=1/(1+p*x),y=1-(a1*t+a2*t*t+a3*t*t*t+a4*t*t*t*t+a5*t*t*t*t*t)*Math.exp(-x*x);return 0.5*(1+sign*y);}
function bsPrice(type,S,K,T,r,sigma){if(T<=0||sigma<=0)return type==='call'?Math.max(S-K,0):Math.max(K-S,0);var d1=(Math.log(S/K)+(r+sigma*sigma/2)*T)/(sigma*Math.sqrt(T));var d2=d1-sigma*Math.sqrt(T);if(type==='call')return S*normCDF(d1)-K*Math.exp(-r*T)*normCDF(d2);return K*Math.exp(-r*T)*normCDF(-d2)-S*normCDF(-d1);}
function bsPayoff(type,S,K,premium){if(type==='call')return Math.max(S-K,0)-premium;return Math.max(K-S,0)-premium;}
/* VIX-based non-directional strategy engine (NIFTY weekly expiry only, all trading days).
 * Short strikes by VIX range: LOW ±100, NORMAL ±150, ELEVATED ±200, HIGH ±250.
 * Hedge is 500 pts from short strike (wing at short+500). Entry 9:30 AM, VIX <5% positive. Exit: VIX >5%↑, ₹2k loss, 3:20 PM.
 * Payoff uses Black-Scholes (r=0.06, T=7d).
 */
function vixStrategy(v, vc){
  if(v==null)return null;
  var r={};
  if(v<12){r.range='LOW';r.risk='Low';r.strategy='Iron Condor Tight';r.edge='Range-bound in low vol';r.pos='60%';r.color='#15803d';r.strikeDist=100;r.hedgeDist=600;
    r.entry='SELL CALL +100 + PUT -100 | BUY CALL +600 + PUT -600 | Hedge: 500 pts from short';r.exit='VIX >5%↑ or 3:20 PM';r.T=7/365;r.sigma=v/100;r.netCredit=30;}
  else if(v<15){r.range='NORMAL';r.risk='Moderate';r.strategy='Iron Condor';r.edge='Neutral range capture';r.pos='50%';r.color='#1d4ed8';r.strikeDist=150;r.hedgeDist=650;
    r.entry='SELL CALL +150 + PUT -150 | BUY CALL +650 + PUT -650 | Hedge: 500 pts from short';r.exit='VIX >5%↑ or 3:20 PM';r.T=7/365;r.sigma=v/100;r.netCredit=35;}
  else if(v<20){r.range='ELEVATED';r.risk='Elevated';r.strategy='Iron Condor Wide';r.edge='Wider range, higher credit';r.pos='40%';r.color='#a16207';r.strikeDist=200;r.hedgeDist=700;
    r.entry='SELL CALL +200 + PUT -200 | BUY CALL +700 + PUT -700 | Hedge: 500 pts from short';r.exit='VIX >5%↑ or 3:20 PM';r.T=7/365;r.sigma=v/100;r.netCredit=40;}
  else if(v<25){r.range='HIGH';r.risk='High';r.strategy='Iron Condor XWide';r.edge='Max premium, wide wings';r.pos='30%';r.color='#c2410c';r.strikeDist=250;r.hedgeDist=750;
    r.entry='SELL CALL +250 + PUT -250 | BUY CALL +750 + PUT -750 | Hedge: 500 pts from short | Half-size';r.exit='VIX >5%↑ or 2k loss or 3:20 PM';r.T=7/365;r.sigma=v/100;r.netCredit=45;}
  else{r.range='VERY HIGH';r.risk='Extreme';r.strategy='NO TRADE';r.edge='Avoid | Exit all';r.pos='0%';r.color='#dc2626';r.strikeDist=0;r.hedgeDist=0;
    r.entry='WAIT — volatility too high';r.exit='Exit all positions';r.T=0;r.sigma=0;r.netCredit=0;}
  if(vc!=null&&vc>5)r.exitFlag=true; else r.exitFlag=false;
  return r;
}
function drawPayoff(id,str,atm){
  var cv=document.getElementById(id);if(!cv||!str)return;
  var dpr=window.devicePixelRatio||1,W=cv.clientWidth||600,H=220;
  cv.width=W*dpr;cv.height=H*dpr;
  var x=cv.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,W,H);
  var padL=40,padR=20,padT=20,padB=30;
  var pw=W-padL-padR,ph=H-padT-padB;
  var d=str.strikeDist||100;
  var steps=200;var minS=atm-600,maxS=atm+600;
  function X(s){return padL+((s-minS)/(maxS-minS))*pw;}
  var r=0.06;var T=str.T||7/365;var sigma=str.sigma||0.15;
  var profit=[];var hl=[];
  for(var i=0;i<=steps;i++){
    var s=minS+(maxS-minS)*i/steps;var p=0;
    if(str.strategy.indexOf('Iron Condor')===0){var cu=bsPrice('call',s,atm+d,T,r,sigma);var cd=bsPrice('put',s,atm-d,T,r,sigma);var bu=bsPrice('call',s,atm+d*2,T,r,sigma);var bd=bsPrice('put',s,atm-d*2,T,r,sigma);p=(cu+cd)-(bu+bd)+str.netCredit;}
    else p=0;
    profit.push(p);hl.push(p<-20?-20:null);
  }
  var mxP=Math.max.apply(null,profit),mnP=Math.min.apply(null,profit);
  var rng=mxP-mnP||1;
  function Y(p){return padT+ph-((p-mnP)/rng)*ph;}
  x.strokeStyle='#e2e8f0';x.lineWidth=1;x.beginPath();x.moveTo(0,Y(0));x.lineTo(W,Y(0));x.stroke();
  x.fillStyle='#64748b';x.font='9px sans-serif';x.fillText('0',X(atm)-8,Y(0)-4);
  x.strokeStyle=str.color||'#15803d';x.lineWidth=2;x.beginPath();
  for(var i=0;i<=steps;i++){var px=X(minS+(maxS-minS)*i/steps),py=Y(profit[i]);if(i===0)x.moveTo(px,py);else x.lineTo(px,py);}
  x.stroke();
  for(var i=0;i<=steps;i++){if(hl[i]!=null){var px=X(minS+(maxS-minS)*i/steps);x.strokeStyle='rgba(220,38,38,0.3)';x.lineWidth=3;x.beginPath();x.moveTo(px,Y(-20));x.lineTo(px,Y(hl[i]));x.stroke();}}
  x.fillStyle='#0f172a';x.font='bold 10px sans-serif';
  x.fillText(minS,X(minS),H-8);x.fillText(maxS,X(maxS)-20,H-8);
  x.fillText('P&L',2,padT+4);
  x.fillText('Strike',W/2-20,H-8);
  x.fillStyle=str.color;x.font='bold 11px sans-serif';
  x.fillText(str.range+' VIX | '+str.strategy,padL,padT-4);
  x.fillStyle='#64748b';x.font='9px sans-serif';
  x.fillText('BS premiums | Short ±'+d+' | Max profit: '+str.maxProfit+' | Max loss: '+str.maxLoss,padL,padT+10);
}
/* Intraday Iron Condor backtest: enter at 9:30 AM if VIX change <5% positive, exit at 3:20 PM or on VIX spike / 2k loss.
 * Uses intrinsic-value P&L (what actually matters for intraday short strangle/Iron Condor). */
function backtestVix(days){
  days=days||60;
  return Promise.all([
    fetchJSON('prices/NIFTY?interval=1d&limit='+days),
    fetchJSON('vix/daily?days='+days)
  ]).then(function(res){
    var prices=res[0]||[];
    var vixData=res[1]||[];
    if(!prices.length||!vixData.length)return null;
    var vixMap={};
    vixData.forEach(function(v){
      var d=v.date||(v.timestamp?v.timestamp.slice(0,10):'');
      if(d&&v.close!=null)vixMap[d]=v.close;
    });
    var priceMap={};
    prices.forEach(function(p){
      var d=p.timestamp?p.timestamp.slice(0,10):'';
      if(d&&p.close!=null)priceMap[d]={open:p.open,close:p.close};
    });
    var trades=[];
    var totalPnl=0, wins=0, losses=0, maxDrawdown=0, peak=0;
    var sortedDates=Object.keys(priceMap).sort();
    for(var i=0;i<sortedDates.length;i++){
      var d=sortedDates[i];
      var vix=vixMap[d];
      var pd=priceMap[d];
      if(vix==null||!pd)continue;
      var entrySpot=pd.open;
      var exitSpot=pd.close;
      var prevVix=null;
      if(i>0){var prevD=sortedDates[i-1];prevVix=vixMap[prevD];}
      var vc=null;
      if(prevVix!=null&&prevVix>0)vc=((vix-prevVix)/prevVix)*100;
      // Entry condition: VIX change <5% positive (stable VIX)
      if(vc!=null&&vc>5)continue;
      var str=vixStrategy(vix,vc);
      if(!str||str.range==='VERY HIGH')continue;
      var sd=str.strikeDist;
      var hd=str.hedgeDist;
      // Intrinsic-value Iron Condor P&L (what matters for intraday)
      function icvIntrinsic(spot,atm,s,h){
        if(spot>=atm+h)return s-h;
        if(spot>=atm+s)return atm+s-spot;
        if(spot>=atm-s)return 0;
        if(spot>=atm-h)return spot-atm+s;
        return s-h;
      }
      var entryVal=icvIntrinsic(entrySpot,entrySpot,sd,hd);
      var exitVal=icvIntrinsic(exitSpot,entrySpot,sd,hd);
      var pnl=entryVal-exitVal+str.netCredit;
      // Exit conditions: VIX spike >5%, 2k loss, EOD 3:20 PM
      var exited=false,exitReason='';
      if(vc!=null&&vc>5){exited=true;exitReason='VIX spike';pnl=-2000;}
      else if(pnl<-2000){exited=true;exitReason='2k loss';pnl=-2000;}
      else if(i>=sortedDates.length-1){exited=true;exitReason='EOD 3:20 PM';}
      totalPnl+=pnl;
      if(pnl>0)wins++;else if(pnl<0)losses++;
      if(totalPnl>peak)peak=totalPnl;
      var dd=peak-totalPnl;
      if(dd>maxDrawdown)maxDrawdown=dd;
      trades.push({date:d,vix:vix,entrySpot:entrySpot,exitSpot:exitSpot,str:str.range,strikeDist:sd,hedgeDist:hd,pnl:pnl,exited:exited,exitReason:exitReason});
    }
    var winRate=trades.length?wins/trades.length*100:0;
    return{trades:trades,totalPnl:totalPnl,winRate:winRate,losses:losses,maxDrawdown:maxDrawdown,totalTrades:trades.length};
  }).catch(function(){return null;});
}
function displayBacktest(){
  var el=document.getElementById('strategy-card');
  if(!el)return;
  el.innerHTML='<h3 style="margin:0 0 0.4rem;color:#fff">🎯 Backtest (60d)</h3><div class="status">Running...</div>';
  backtestVix(60).then(function(r){
    if(!r||!r.trades.length){if(el)el.innerHTML='<h3 style="margin:0 0 0.4rem;color:#fff">🎯 Backtest</h3><div class="status">Insufficient data</div>';return;}
    var pnlColor=r.totalPnl>=0?'#15803d':'#dc2626';
    var html='<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem">'
      +'<span class="badge" style="background:#15803d20;color:#15803d">Total: ₹'+r.totalPnl.toFixed(0)+'</span>'
      +'<span class="badge" style="background:#1d4ed820;color:#1d4ed8">Win Rate: '+r.winRate.toFixed(1)+'%</span>'
      +'<span class="badge" style="background:#a1620720;color:#a16207">Trades: '+r.totalTrades+'</span>'
      +'<span class="badge" style="background:#c2410c20;color:#c2410c">Max DD: ₹'+r.maxDrawdown.toFixed(0)+'</span>'
      +'</div><div style="max-height:200px;overflow-y:auto;font-size:0.75rem">'
      +'<table style="width:100%;border-collapse:collapse">'
      +'<tr style="color:#94a3b8"><th style="text-align:left;padding:2px 4px">Date</th><th>VIX</th><th>Entry</th><th>Exit</th><th>Range</th><th style="text-align:right">P&L</th><th>Exit</th></tr>';
    r.trades.forEach(function(t){
      var pc=t.pnl>=0?'#15803d':'#dc2626';
      html+='<tr style="border-top:1px solid #1e293b">'
        +'<td style="padding:1px 4px">'+t.date.slice(5)+'</td>'
        +'<td>'+t.vix.toFixed(1)+'</td>'
        +'<td>'+Math.round(t.entrySpot)+'</td>'
        +'<td>'+Math.round(t.exitSpot)+'</td>'
        +'<td>'+t.str+'</td>'
        +'<td style="text-align:right;color:'+pc+'">'+t.pnl.toFixed(0)+'</td>'
        +'<td>'+(t.exited?'<span style="color:#f59e0b">'+t.exitReason+'</span>':'—')+'</td>'
        +'</tr>';
    });
    html+='</table></div>';
    el.innerHTML='<h3 style="margin:0 0 0.4rem;color:#fff">🎯 Backtest (60d)</h3>'+html;
  });
}
function loadStrategy(){displayBacktest();}

(function(){
function fmt(n){return n!=null?Number(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';}
function hexA(hex,a){var h=hex.replace('#','');var r=parseInt(h.substring(0,2),16),g=parseInt(h.substring(2,4),16),b=parseInt(h.substring(4,6),16);return 'rgba('+r+','+g+','+b+','+a+')';}
function istDateStr(){var p={};new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).forEach(function(x){p[x.type]=x.value;});return p.year+'-'+p.month+'-'+p.day;}
function pcrColor(v){if(v==null)return'#64748b';if(v>=1.2)return'#15803d';if(v<=0.8)return'#dc2626';return'#a16207';}
function pcrLabel(v){if(v==null)return'N/A';if(v>=1.5)return'Strong Bullish';if(v>=1.2)return'Bullish';if(v>=1.0)return'Neutral Bullish';if(v>=0.8)return'Neutral Bearish';if(v>=0.5)return'Bearish';return'Strong Bearish';}
function setup(cv){var dpr=window.devicePixelRatio||1;var W=cv.clientWidth||600,H=parseInt(cv.getAttribute('data-h'))||200;cv.width=W*dpr;cv.height=H*dpr;var x=cv.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,W,H);return{x:x,W:W,H:H};}
function apiPath(p){var b=(window.API_BASE&&window.API_BASE!=='.')?window.API_BASE:'..';return b.replace(/\/$/,'')+'/api/'+p;}
function fetchJSON(path){return fetch(apiPath(path)).then(function(r){return r.ok?r.json():Promise.reject();}).catch(function(){return null;});}

function drawArea(id,rows,mn,mx,maxPain){
  var cv=document.getElementById(id);if(!cv)return;
  var s=setup(cv),x=s.x,W=s.W,H=s.H;
  var bodyH=H-16-8,M=Math.max;function Y(v){return 8+bodyH-((v-mn)/(mx-mn))*bodyH;}
  var n=rows.length,last=rows[n-1];
  var up=last.close>=(rows[0].open!=null?rows[0].open:rows[0].close);
  x.strokeStyle=up?'#15803d':'#dc2626';x.lineWidth=2;x.beginPath();
  for(var i=0;i<n;i++){var px=(W-2)*(i/(n-1));var py=Y(rows[i].close);if(i===0)x.moveTo(px,py);else x.lineTo(px,py);}
  x.stroke();
  drawMaxPain(x,W,Y,mn,mx,maxPain);
  x.fillStyle='#0f172a';x.font='bold 11px sans-serif';x.fillText(fmt(last.close),W-70,14);
}
function drawMaxPain(x,W,Y,mn,mx,levels){
  for(var m=0;m<(levels||[]).length;m++){
    var p=levels[m];if(p==null||p<mn||p>mx)continue;
    var yy=Y(p);
    x.setLineDash([5,4]);x.strokeStyle=hexA('#c2410c',0.85);x.lineWidth=1.5;
    x.beginPath();x.moveTo(0,yy);x.lineTo(W,yy);x.stroke();x.setLineDash([]);
    x.fillStyle='#c2410c';x.font='bold 10px sans-serif';
    x.fillText('MaxPain '+fmt(p),Math.max(2,W-150),Math.max(10,yy-4));
  }
}

function drawCandles(id,rows,maxPain){
  var cv=document.getElementById(id);if(!cv||!rows||!rows.length)return;
  var s=setup(cv),x=s.x,W=s.W,H=s.H;
  var padL=14,padT=14,padB=12;
  var lows=rows.map(function(r){return r.low!=null?r.low:r.close;});
  var highs=rows.map(function(r){return r.high!=null?r.high:r.close;});
  var mn=Math.min.apply(null,lows),mx=Math.max.apply(null,highs);
  if(!(mx>mn)){mx+=1;mn-=1;}
  var bodyH=H-padT-padB;
  function Y(v){return padT+bodyH-((v-mn)/(mx-mn))*bodyH;}
  var n=rows.length,step=W/n;
  if(step<3){drawArea(id,rows,mn,mx,maxPain);return;}
  var cw=Math.max(2,step*0.7);
  x.strokeStyle='#f1f5f9';x.lineWidth=1;
  for(var g=0;g<4;g++){var gy=padT+bodyH*g/3;x.beginPath();x.moveTo(0,gy);x.lineTo(W,gy);x.stroke();}
  var last=null;
  for(var i=0;i<n;i++){
    var r=rows[i];
    var o=r.open!=null?r.open:r.close,c=r.close!=null?r.close:r.open;
    var h=r.high!=null?r.high:Math.max(o,c),l=r.low!=null?r.low:Math.min(o,c);
    var cx=padL+(W-padL-2)*(i/(n-1));
    var up=c>=o;
    var col=up?'#15803d':'#dc2626';
    x.strokeStyle=col;x.fillStyle=col;x.lineWidth=1;
    var yh=Y(h),yl=Y(l);
    x.beginPath();x.moveTo(cx,yh);x.lineTo(cx,yl);x.stroke();
    var top=Math.min(Y(o),Y(c)),bot=Math.max(Y(o),Y(c));
    if(bot-top<1)bot=top+1;
    x.fillRect(cx-cw/2,top,cw,bot-top);
    last={close:c,col:col};
  }
  drawMaxPain(x,W,Y,mn,mx,maxPain);
  x.fillStyle='#0f172a';x.font='bold 12px sans-serif';
  x.fillText(fmt(last.close),W-80,padT+4);
  x.fillStyle='#94a3b8';x.font='10px sans-serif';
  x.fillText(fmt(mx),2,padT+4);
  x.fillText(fmt(mn),2,H-4);
}

function drawPcrHistory(id,data){
  var cv=document.getElementById(id);if(!cv||!data||data.length<2)return;
  var s=setup(cv),x=s.x,W=s.W,H=s.H;
  var padT=12,padB=16;
  var vals=data.map(function(d){return d.pcr;});
  var mx=Math.max.apply(null,vals.concat([1]))*1.15;if(!(mx>0))mx=1.1;
  var bodyH=H-padT-padB;function Y(v){return padT+bodyH-(v/mx)*bodyH;}
  var bl=Y(1);
  x.strokeStyle='#cbd5e1';x.setLineDash([4,4]);x.beginPath();x.moveTo(0,bl);x.lineTo(W,bl);x.stroke();x.setLineDash([]);
  x.fillStyle='#94a3b8';x.font='9px sans-serif';x.fillText('1.0',2,bl-2);
  var n=data.length,cw=Math.max(4,W/n*0.6);
  for(var i=0;i<n;i++){
    var d=data[i],pcr=d.pcr||0;
    var col=pcr>=1?'#15803d':'#dc2626';
    var yb=Y(pcr),y0=Y(0);
    x.fillStyle=col;
    x.fillRect((W/n)*i+W/(n*2)-cw/2,Math.min(yb,y0),cw,Math.max(1,Math.abs(yb-y0)));
    x.font='bold 9px sans-serif';
    x.fillText(pcr.toFixed(2),(W/n)*i+W/(n*2)-cw/2,(pcr>=1?y0+9:yb-3)+0);
    if(i===0){x.fillStyle='#94a3b8';x.fillText((d.date||'').slice(5),2,H-4);}
    if(i===n-1){x.fillText((d.date||'').slice(5),W-x.measureText((d.date||'').slice(5)).width-2,H-4);}
  }
}

function currentExpiry(exps){var t=istDateStr();for(var i=0;i<exps.length;i++){if(exps[i].expiry>=t)return exps[i];}return exps[exps.length-1];}

/* Load OPTIONS INTELLIGENCE box + PCR-history chart for the given symbol.
 * cfg: {symbol, boxId, pcrCanvasId, maxPainRef}  -> resolves with the current-expiry max-pain (or null).
 * If window.__loadPcrBox is set (static fallback), override the box content instead of fetching. */
function loadOptionsBox(cfg){
  var sym=cfg.symbol||'NIFTY';
  var box=document.getElementById(cfg.boxId||'options-box');if(!box)return Promise.resolve(null);
  if(window.__loadPcrBox){try{window.__loadPcrBox(box,SYM,cfg)}catch(e){};return Promise.resolve(null);}
  return Promise.all([
    fetchJSON('pcr?symbols='+sym),
    fetchJSON('maxpain?symbols='+sym),
    fetchJSON('pcr-history?symbols='+sym+'&days=6')
  ]).then(function(res){
    var pcrData=(res[0]&&res[0][sym])||[];
    var mpData=(res[1]&&res[1][sym])||[];
    var hist=(res[2]&&res[2][sym])||[];
    var cur=pcrData.length?currentExpiry(pcrData):null;
    var mpCur=cur?mpData.filter(function(e){return e.expiry===cur.expiry;})[0]:null;
    var mp=mpCur&&mpCur.max_pain!=null?mpCur.max_pain:null;
    if(cur){
      var c=pcrColor(cur.pcr);
      box.innerHTML='<span class="badge" style="background:#15803d20;color:#15803d">'+sym+'</span> '
        +'<span class="badge" style="background:#1e40af20;color:#1e40af">Expiry '+cur.expiry+'</span>'
        +'<div style="font-size:1.7rem;font-weight:800;color:'+c+';margin:0.2rem 0">'+((cur.pcr!=null)?cur.pcr.toFixed(3):'—')+'<span style="font-size:0.85rem;color:#64748b;font-weight:600">&nbsp;PCR · '+pcrLabel(cur.pcr)+'</span></div>'
        +'<div class="status">Max Pain: <strong>'+((mp!=null)?fmt(mp):'—')+'</strong></div>'
        +'<div class="status">Call OI: '+fmt(cur.ce_oi)+'  ·  Put OI: '+fmt(cur.pe_oi)+'</div>'
        +'<div class="status" style="color:#64748b">EOD NSE bhavcopy</div>';
    } else {
      box.innerHTML='<div class="status">No NSE options data yet.</div>';
    }
    var pcv=document.getElementById(cfg.pcrCanvasId||'pcr-chart');
    if(pcv&&hist.length)drawPcrHistory(pcv.id,hist);
    if(cfg.maxPainRef)cfg.maxPainRef.value=mp;
    return mp;
  }).catch(function(){box.innerHTML='<div class="status">Options data unavailable.</div>';return null;});
}

window.TAIcharts={drawCandles:drawCandles,drawPcrHistory:drawPcrHistory,loadOptionsBox:loadOptionsBox,currentExpiry:currentExpiry,pcrLabel:pcrLabel,pcrColor:pcrColor,fmt:fmt,vixStrategy:vixStrategy,drawPayoff:drawPayoff,loadStrategy:loadStrategy};
})();