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
  if(r.netCredit>0){r.maxProfit=r.netCredit;r.maxLoss=(r.hedgeDist-r.strikeDist)-r.netCredit;}
  return r;
}
function drawPayoff(id,str,atm){
  var cv=document.getElementById(id);if(!cv||!str)return;
  var dpr=window.devicePixelRatio||1,W=cv.clientWidth||600,H=220;
  cv.width=W*dpr;cv.height=H*dpr;
  var x=cv.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,W,H);
  atm=Math.round(atm/50)*50;
  var padL=40,padR=18,padT=20,padB=30;
  var pw=W-padL-padR,ph=H-padT-padB;
  var d=str.strikeDist||100;
  var hd=str.hedgeDist||d*2;
  var credit=str.netCredit||0;
  var half=hd+80;
  var minS=atm-half,maxS=atm+half;
  var steps=300;
  function X(s){return padL+((s-minS)/(maxS-minS))*pw;}
  var maxV=credit,minV=credit-(hd-d);
  var rng=(maxV-minV)||1;
  function Y(p){return padT+ph-((p-minV)/rng)*ph;}
  var profit=[];
  for(var i=0;i<=steps;i++){
    var s=minS+(maxS-minS)*i/steps;
    var loss=Math.max(0,s-(atm+d))+Math.max(0,(atm-d)-s)-Math.max(0,s-(atm+hd))-Math.max(0,(atm-hd)-s);
    profit.push(credit-loss);
  }
  x.strokeStyle='#e2e8f0';x.lineWidth=1;
  for(var g=0;g<4;g++){var gy=padT+ph*g/3;x.beginPath();x.moveTo(padL,gy);x.lineTo(W-padR,gy);x.stroke();}
  // Shade profit zone (above zero) and loss zone (below zero) along the payoff curve
  function shadeZone(zoneAbove,color){
    var pts=[];var active=false;
    function flush(){
      if(pts.length>=6){
        x.fillStyle=color;
        x.beginPath();
        x.moveTo(pts[0],pts[1]);
        for(var i=2;i<pts.length;i+=2)x.lineTo(pts[i],pts[i+1]);
        x.closePath();x.fill();
      }
      pts=[];
    }
    for(var i=0;i<=steps;i++){
      var s=minS+(maxS-minS)*i/steps;
      var p=profit[i];
      var inZone=(p>=0)===zoneAbove;
      if(inZone){
        if(pts.length===0){pts.push(X(s),Y(0),X(s),Y(p));}
        else{pts.push(X(s),Y(p));}
        active=true;
      }else if(active){
        if(i>0){
          var p0=profit[i-1];
          if((p0>=0)===zoneAbove){
            var s0=minS+(maxS-minS)*(i-1)/steps;
            var t0=p0/(p0-p);
            var sx=s0*(1-t0)+s*t0;
            pts.push(X(sx),Y(0));
          }
        }
        pts.push(X(s),Y(0));
        flush();
        active=false;
      }
    }
    if(active)flush();
  }
  shadeZone(true,'rgba(22,163,74,0.16)');
  shadeZone(false,'rgba(220,38,38,0.16)');
  x.strokeStyle='#94a3b8';x.setLineDash([4,3]);x.beginPath();x.moveTo(padL,Y(0));x.lineTo(W-padR,Y(0));x.stroke();x.setLineDash([]);
  x.fillStyle='#64748b';x.font='9px sans-serif';x.fillText('0',padL+2,Y(0)-3);
  x.strokeStyle='rgba(22,163,74,0.35)';x.setLineDash([4,3]);x.beginPath();x.moveTo(padL,Y(maxV));x.lineTo(W-padR,Y(maxV));x.stroke();x.setLineDash([]);
  x.fillStyle='#15803d';x.font='9px sans-serif';x.fillText('Max +'+credit+' pts',padL+2,Y(maxV)-3);
  var markers=[atm-hd,atm-d,atm+d,atm+hd];
  for(var k=0;k<markers.length;k++){
    var st=markers[k];if(st<minS||st>maxS)continue;
    var sx=X(st),isShort=(st===atm-d||st===atm+d);
    var isCall=(st-atm)>0;
    x.strokeStyle=isShort?'rgba(220,38,38,0.55)':'rgba(59,130,246,0.45)';
    x.setLineDash([3,3]);x.beginPath();x.moveTo(sx,padT);x.lineTo(sx,padT+ph);x.stroke();x.setLineDash([]);
    x.fillStyle=isShort?'#dc2626':'#2563eb';x.font='8px sans-serif';
    var mtxt=(isShort?'S·':'B·')+(isCall?'CE ':'PE ')+Math.round(st).toLocaleString('en-IN');
    x.fillText(mtxt,sx-Math.round(x.measureText(mtxt).width/2),padT+ph+12);
  }
  x.strokeStyle=str.color||'#15803d';x.lineWidth=2.2;x.beginPath();
  for(var i=0;i<=steps;i++){var px=X(minS+(maxS-minS)*i/steps),py=Y(profit[i]);if(i===0)x.moveTo(px,py);else x.lineTo(px,py);}
  x.stroke();
  x.fillStyle='#0f172a';x.font='10px sans-serif';x.fillText('ATM '+Math.round(atm),padL+2,H-8);
  x.fillStyle=str.color;x.font='bold 11px sans-serif';
  x.fillText(str.range+' VIX | '+str.strategy,padL,padT-6);
  x.fillStyle='#64748b';x.font='8px sans-serif';
  var f=function(n){return Math.round(n).toLocaleString('en-IN');};
  var info='SELL CE '+f(atm+d)+' · SELL PE '+f(atm-d)+'  |  BUY CE '+f(atm+hd)+' · BUY PE '+f(atm-hd);
  x.fillText(info,W-padR-x.measureText(info).width,H-8);
}
/* Session-based Iron Condor backtest: enter at 9:30 AM if VIX change <5% positive, exit at 3:20 PM or on VIX spike / 2k loss.
 * Runs over the last N TRADING SESSIONS (prices are per-session; VIX is fetched for ~1.5x days so every session has VIX data).
 * P&L model: intrinsic value + partial time decay - collects the full net credit, then subtracts only the theta
 * that decays during the ~6.5h hold (6.5h / 7 days of the weekly option) plus any intrinsic loss if spot crosses
 * the short strikes before EOD. Middle ground between intrinsic-only (over-optimistic) and full BS (over-pessimistic). */
function backtestVix(days){
  days=days||60;
  return Promise.all([
    fetchJSON('prices/NIFTY?interval=1d&limit='+(days+20)),
    fetchJSON('vix/daily?days='+Math.ceil(days*1.5))
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
    var sortedDates=Object.keys(priceMap).filter(function(d){return vixMap[d]!=null;}).sort().slice(-days);
    var lotSize=65;
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
      // Entry condition: VIX change <5% positive
      if(vc!=null&&vc>5)continue;
      var str=vixStrategy(vix,vc);
      if(!str||str.range==='VERY HIGH')continue;
      var sd=str.strikeDist;
      var hd=str.hedgeDist;
      // NIFTY strikes are multiples of 50: anchor the iron condor to the nearest 50 strike from entry spot
      var atm=Math.round(entrySpot/50)*50;
      // Intrinsic cost of the Iron Condor at a given spot (strikes anchored at rounded ATM)
      function icIntrinsic(spot){
        return Math.max(0,spot-(atm+sd))+Math.max(0,(atm-sd)-spot)-Math.max(0,spot-(atm+hd))-Math.max(0,(atm-hd)-spot);
      }
      // Day-varying credit: scale the band's base credit by today's VIX vs its band midpoint (real IV movement per day)
      var bandMid={LOW:11,NORMAL:13.5,ELEVATED:17.5,HIGH:22.5}[str.range];
      var credit=str.netCredit*(vix/bandMid);
      // Partial time decay: theta for ~6.5h hold out of the 7-day weekly option life
      var thetaLost=credit*(6.5/24)*(1/7);
      var entryInt=icIntrinsic(entrySpot);
      var exitInt=icIntrinsic(exitSpot);
      var pnl=Math.round((credit-thetaLost-(exitInt-entryInt))*lotSize);
      // Exit conditions: VIX spike >5%, 2k loss, EOD 3:20 PM
      var exited=false,exitReason='';
      if(vc!=null&&vc>5){exited=true;exitReason='VIX spike';pnl=-2000*lotSize;}
      else if(pnl<-2000*lotSize){exited=true;exitReason='2k loss';pnl=-2000*lotSize;}
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
  el.innerHTML='<h3 style="margin:0 0 0.4rem">AI Suggested Iron Condor</h3><div class="status">Running…</div>';
  backtestVix(60).then(function(r){
    if(!r||!r.trades.length){if(el)el.innerHTML='<h3 style="margin:0 0 0.4rem">AI Suggested Iron Condor</h3><div class="status">Insufficient data</div>';return;}
    r.trades.sort(function(a,b){return b.date<a.date?-1:b.date>a.date?1:0;});
    var pnlColor=r.totalPnl>=0?'#15803d':'#dc2626';
    var opts=r.trades.map(function(t,i){return '<option value="'+i+'">'+t.date.slice(5)+' · '+t.str+' · ±'+t.strikeDist+' (entry '+Math.round(t.entrySpot)+')</option>';}).join('');
    var rows=r.trades.map(function(t,i){
      var pc=t.pnl>=0?'#15803d':'#dc2626';
      var sign=t.pnl>0?'+':'';
      return '<tr class="bt-row" data-idx="'+i+'" onclick="window.__btSel&&window.__btSel('+i+')">'
        +'<td>'+t.date.slice(5)+'</td>'
        +'<td>'+t.vix.toFixed(1)+'</td>'
        +'<td>'+Math.round(t.entrySpot)+'</td>'
        +'<td>'+Math.round(t.exitSpot)+'</td>'
        +'<td>'+t.str+'</td>'
        +'<td style="text-align:right;color:'+pc+';font-weight:700;font-variant-numeric:tabular-nums">'+sign+(t.pnl).toLocaleString('en-IN')+'</td>'
        +'<td>'+(t.exited?'<span class="bt-exit" style="color:#b45309">'+t.exitReason+'</span>':'—')+'</td>'
        +'</tr>';
    }).join('');
    el.innerHTML='<h3 style="margin:0 0 0.4rem">AI Suggested Iron Condor</h3>'
      +'<div class="bt-styles"><style>'
      +'#strategy-card .bt-table{width:100%;border-collapse:collapse;font-size:0.73rem}'
      +'#strategy-card .bt-table thead th{position:sticky;top:0;background:#0f172a;color:#e2e8f0;font-weight:600;text-align:right;padding:5px 8px;white-space:nowrap;z-index:2}'
      +'#strategy-card .bt-table thead th:first-child{text-align:left}'
      +'#strategy-card .bt-table td{padding:4px 8px;border-top:1px solid #e2e8f0;white-space:nowrap;font-variant-numeric:tabular-nums}'
      +'#strategy-card .bt-table td:first-child{text-align:left}'
      +'#strategy-card .bt-table td:nth-child(5){text-align:center}'
      +'#strategy-card .bt-table td:last-child{text-align:left}'
      +'#strategy-card .bt-table tbody tr:nth-child(even){background:#f8fafc}'
      +'#strategy-card .bt-table tbody tr:hover,.bt-sel{background:#eff6ff !important;cursor:pointer}'
      +'</style></div>'
      +'<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin:0.4rem 0">'
      +'<span class="badge" style="background:#0ea5e920;color:#0ea5e9">Entry 9:30 → Exit 15:20 IST</span>'
      +'<span class="badge" style="background:#15803d20;color:#15803d">Total: ₹'+r.totalPnl.toLocaleString('en-IN')+'</span>'
      +'<span class="badge" style="background:#1d4ed820;color:#1d4ed8">Win Rate: '+r.winRate.toFixed(1)+'%</span>'
      +'<span class="badge" style="background:#a1620720;color:#a16207">Trades: '+r.totalTrades+'</span>'
      +'<span class="badge" style="background:#c2410c20;color:#c2410c">Max DD: ₹'+r.maxDrawdown.toLocaleString('en-IN')+'</span>'
      +'</div>'
      +'<div style="display:flex;align-items:center;gap:0.5rem;margin:0.4rem 0 0.2rem;font-size:0.75rem;color:#475569">'
      +'<span style="white-space:nowrap">Payoff:</span><select id="bt-select" style="flex:1;min-width:0;padding:4px 6px;font-size:0.75rem;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:#0f172a">'+opts+'</select></div>'
      +'<canvas id="bt-payoff" style="width:100%;height:220px;display:block;margin-bottom:0.3rem"></canvas>'
      +'<div style="max-height:240px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;margin-top:0.2rem">'
      +'<table class="bt-table"><thead><tr><th>Date</th><th>VIX</th><th>Entry·9:30</th><th>Exit·15:20</th><th>Range</th><th>P&L (₹)</th><th>Exit</th></tr></thead>'
      +'<tbody>'+rows+'</tbody></table></div>'
      +'<div style="margin-top:0.4rem;font-size:0.7rem;color:#64748b">Entry 9:30 IST · Exit 15:20 IST · last 60 sessions · intrinsic + partial theta · lot 65 · credit scaled by daily VIX</div>';
    var sel=document.getElementById('bt-select');
    function renderSel(i){
      var t=r.trades[i];
      drawPayoff('bt-payoff',vixStrategy(t.vix),t.entrySpot);
      var rows=el.querySelectorAll('.bt-row');
      for(var j=0;j<rows.length;j++)rows[j].classList.toggle('bt-sel',j===i);
    }
    sel.addEventListener('change',function(){renderSel(+sel.value);});
    window.__btSel=function(i){sel.value=i;renderSel(i);};
    renderSel(0);
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