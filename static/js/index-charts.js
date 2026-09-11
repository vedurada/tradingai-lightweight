/* Shared charting for index pages: candlestick intraday chart with max-pain overlay,
 * multi-day PCR-history bars, and a live OPTIONS INTELLIGENCE box (PCR / max pain / OI).
 * Uses the page-globals API_BASE ('..') and SYM (symbol) where present.
 */
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
  if(step<3){drawArea(id,rows,mn,mx,maxPain);return;}   // too dense for candles
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

window.TAIcharts={drawCandles:drawCandles,drawPcrHistory:drawPcrHistory,loadOptionsBox:loadOptionsBox,currentExpiry:currentExpiry,pcrLabel:pcrLabel,pcrColor:pcrColor,fmt:fmt};
})();