"""Rebuild the homepage signal-replay animation from the latest classified record.

Presentation only: reads the latest signal per instrument with full context from
data/tg_alerts_archive.jsonl plus that day's 5-minute candles from the
database, then replaces the section between <!--TAIHOW-START--> and
<!--TAIHOW-END--> in frontend/index.html. Changes no trading logic.

Safe for cron after market close (16:05 IST weekdays). If no classified
record exists, the page is left untouched.
"""
import io
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse as up
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = '/opt/tradingai'
IST = ZoneInfo('Asia/Kolkata')
ARCHIVE = os.path.join(BASE, 'data', 'tg_alerts_archive.jsonl')
DB = os.path.join(BASE, 'database', 'tradingai.db')
PAGE = os.path.join(BASE, 'frontend', 'index.html')
START = '<!--TAIHOW-START-->'
END = '<!--TAIHOW-END-->'

W, H, L, R, T, B = 600, 300, 56, 16, 14, 30
X0, X1 = L, W - R


def fmt(x):
    try:
        return '{:,.2f}'.format(float(str(x).replace(',', '')))
    except (ValueError, TypeError):
        return None


def parse_zone(structure):
    m = re.search(r'CPR\s*([0-9,.]+)\s*[–—-]\s*([0-9,.]+)', structure or '')
    if not m:
        return None, None
    return fmt(m.group(1)), fmt(m.group(2))


def fnum(x):
    return float(str(x).replace(',', ''))


def load_signals():
    recs = []
    try:
        with io.open(ARCHIVE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    outs = []
    for r in recs:
        if r.get('type') != 'signal' or r.get('source') == 'ledger-backfill':
            continue
        ctx = r.get('ctx') or {}
        if (ctx.get('direction') or '').upper() not in ('BEAR', 'BULL'):
            continue
        if fmt(ctx.get('trigger')) is None:
            continue
        outs.append(r)
    outs.sort(key=lambda r: (r.get('date') or '', r.get('ts_ist') or ''))
    return recs, outs


def find_outcome(recs, key):
    for r in recs:
        if r.get('type') == 'update' and r.get('key') == key:
            oc = r.get('outcome') or {}
            if oc.get('reason'):
                return oc
    return None


def day_candles(inst, date):
    c = sqlite3.connect(DB)
    try:
        rows = c.execute(
            "SELECT timestamp, open, high, low, close FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp LIKE ? ORDER BY timestamp",
            (inst, date + '%')).fetchall()
        prev = c.execute(
            "SELECT close FROM market_candles_5m WHERE instrument_id=? AND timestamp < ? "
            "ORDER BY timestamp DESC LIMIT 1", (inst, date + 'T00:00:00+05:30')).fetchone()
    finally:
        c.close()
    return rows, (prev[0] if prev else None)


def tmins(ts):
    m = re.search(r'T(\d{2}):(\d{2})', ts or '')
    if not m:
        return None
    return (int(m.group(1)) - 9) * 60 + int(m.group(2)) - 15


def build_section(sig, outcome, candles, prev_close):
    ctx = sig.get('ctx') or {}
    inst = sig.get('inst') or 'NIFTY'
    direction = ctx['direction'].upper()
    bear = direction == 'BEAR'
    trig = fnum(ctx['trigger'])
    inv = fnum(ctx['invalidation']) if fmt(ctx.get('invalidation')) else None
    tgt = fnum(ctx['target']) if fmt(ctx.get('target')) else None
    bc_s, tc_s = parse_zone(ctx.get('structure'))
    bc, tc = (fnum(bc_s) if bc_s else None), (fnum(tc_s) if tc_s else None)
    cpr_type = (ctx.get('cpr_type') or '').strip()
    qt = re.search(r'T(\d{2}:\d{2})', ctx.get('quote_timestamp') or '')
    qt = qt.group(1) if qt else ''
    strat = ctx.get('strategy') or ('Bear Call Spread' if bear else 'Bull Put Spread')
    try:
        day = datetime.strptime(sig.get('date'), '%Y-%m-%d').strftime('%d %b %Y')
    except (ValueError, TypeError):
        day = sig.get('date') or ''

    closes = [(tmins(ts), c) for ts, o, h, l, c in candles if tmins(ts) is not None and 0 <= tmins(ts) <= 380]
    if len(closes) < 5:
        return None
    prices = [c for _, c in closes]
    lo, hi = min(prices), max(prices)
    for v in [trig, inv, tgt, bc, tc]:
        if v is not None:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad

    def X(m):
        return X0 + max(0, min(375, m)) / 375.0 * (X1 - X0)

    def Y(v):
        return T + (hi - v) / (hi - lo) * (H - T - B)

    step = max(1, len(closes) // 10)
    sampled = closes[::step]
    if sampled[-1] != closes[-1]:
        sampled.append(closes[-1])
    path = 'M' + ' L'.join('%.1f,%.1f' % (X(m), Y(c)) for m, c in sampled)
    x_trig = X(tmins(ctx.get('quote_timestamp')) or sampled[0][0])

    gap_txt = ''
    if closes and prev_close:
        gp = closes[0][1] - prev_close
        gap_txt = 'Gap %s%.2f (%s)' % ('+' if gp >= 0 else '\u2212', abs(gp),
                                       'bullish' if gp >= 0 else 'bearish')

    if outcome and outcome.get('reason'):
        oc = 'Outcome recorded: %s at %s (%s).' % (
            outcome.get('reason'), outcome.get('exit'),
            outcome.get('points_text') or 'points n/a')
    else:
        oc = 'Outcome posts to the archive after the session boundary.'

    pos_word = 'below' if bear else 'above'
    lvl = bc_s if (bear and bc_s) else (tc_s if (not bear and tc_s) else '')
    c1 = ('<b>1 \u00b7 Yesterday settles.</b> Previous high, low and close build today\u2019s CPR zone%s%s.'
          % ((' \u2014 top central %s, bottom central %s' % (tc_s, bc_s)) if bc_s and tc_s else '',
             (' (%s width)' % cpr_type.lower()) if cpr_type else ''))
    c2 = ('<b>2 \u00b7 Morning gap.</b> %s opens%s \u2014 %s.' % (inst, ' at %s' % fmt(closes[0][1]),
                                     gap_txt.lower() if gap_txt else 'session begins'))
    c3 = '<b>3 \u00b7 Five-minute candles watch.</b> Each completed candle is tested against the CPR zone from 09:15.'
    c4 = ('<b>4 \u00b7 Trigger: %s %s.</b> The %s candle accepts %s the %s CPR boundary \u2014 session classifies %s.'
          % (pos_word, 'bottom central' if bear else 'top central', qt or 'trigger',
             'below' if bear else 'above', 'lower' if bear else 'upper', direction))
    c5 = ('<b>5 \u00b7 Reference levels set.</b> Trigger %s%s%s \u2014 studied as a %s.'
          % (fmt(trig), ('; invalidation %s' % fmt(inv)) if inv else '',
             ('; reference target %s' % fmt(tgt)) if tgt else '', strat))
    c6 = ('<b>6 \u00b7 Outcome recorded.</b> Record closes at the session boundary and lands in the archive \u2014 win or lose. %s' % oc)
    caps = [c1, c2, c3, c4, c5, c6]

    inv_svg = tgt_svg = ''
    if inv is not None:
        inv_svg = ('<line x1="%.1f" y1="%.1f" x2="%d" y2="%.1f" stroke="#b91c1c" stroke-width="1.5" '
                   'stroke-dasharray="6,3" opacity="0" id="taiHowInv"/>'
                   '<text x="%d" y="%.1f" font-size="11" fill="#b91c1c" text-anchor="end" opacity="0" '
                   'id="taiHowInvL">Invalidation %s</text>'
                   % (x_trig, Y(inv), X1, Y(inv), X1 - 10, Y(inv) + 3, fmt(inv)))
    if tgt is not None:
        tgt_svg = ('<line x1="%.1f" y1="%.1f" x2="%d" y2="%.1f" stroke="#15803d" stroke-width="1.5" '
                   'stroke-dasharray="6,3" opacity="0" id="taiHowTgt"/>'
                   '<text x="%d" y="%.1f" font-size="11" fill="#15803d" text-anchor="end" opacity="0" '
                   'id="taiHowTgtL">Ref target %s</text>'
                   % (x_trig, Y(tgt), X1, Y(tgt), X1 - 10, Y(tgt) + 3, fmt(tgt)))
    eod_x, eod_y = X(sampled[-1][0]), Y(sampled[-1][1])
    trig_colour = '#b91c1c' if bear else '#15803d'
    svg = (
        '<svg viewBox="0 0 600 300" role="img" aria-hidden="true">'
        '<rect x="56" y="14" width="528" height="242" fill="#f8fafc" rx="8"/>'
        '<text x="56" y="270" font-size="11" fill="#64748b">09:15</text>'
        '<text x="540" y="270" font-size="11" fill="#64748b">15:30</text>'
        '<rect x="56" y="%.1f" width="528" height="%.1f" fill="#dbeafe" opacity="0" id="taiHowCpr"/>'
        '<line x1="56" y1="%.1f" x2="584" y2="%.1f" stroke="#2563eb" stroke-width="1.5" '
        'stroke-dasharray="5,3" opacity="0" id="taiHowTc"/>'
        '<line x1="56" y1="%.1f" x2="584" y2="%.1f" stroke="#2563eb" stroke-width="1.5" '
        'stroke-dasharray="5,3" opacity="0" id="taiHowBc"/>'
        '<text x="578" y="%.1f" font-size="11" fill="#1d4ed8" text-anchor="end" opacity="0" id="taiHowTcL">TC %s</text>'
        '<text x="578" y="%.1f" font-size="11" fill="#1d4ed8" text-anchor="end" opacity="0" id="taiHowBcL">BC %s</text>'
        '<line x1="56" y1="%.1f" x2="120" y2="%.1f" stroke="#94a3b8" stroke-width="1.5" '
        'stroke-dasharray="2,3" opacity="0" id="taiHowPc"/>'
        '<text x="60" y="%.1f" font-size="11" fill="#64748b" opacity="0" id="taiHowPcL">Prev close %s</text>'
        '<path d="%s" fill="none" stroke="#0b1e3a" stroke-width="3" stroke-linejoin="round" opacity="0" id="taiHowPath"/>'
        '<circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="#fff" stroke-width="2" opacity="0" id="taiHowTrig"/>'
        '<text x="%.1f" y="%.1f" font-size="11" font-weight="700" fill="%s" text-anchor="middle" opacity="0" '
        'id="taiHowTrigL">%s %s</text>'
        '%s%s'
        '<circle cx="%.1f" cy="%.1f" r="6" fill="#0b1e3a" stroke="#fff" stroke-width="2" opacity="0" id="taiHowEod"/>'
        '<text x="%.1f" y="%.1f" font-size="11" font-weight="700" fill="#0b1e3a" text-anchor="end" opacity="0" '
        'id="taiHowEodL">Session close recorded</text>'
        '<text x="100" y="%.1f" font-size="11" font-weight="700" fill="#64748b" opacity="0" id="taiHowGap">%s</text>'
        '</svg>'
        % (Y(tc) if tc else T, ((Y(bc) - Y(tc)) if (bc and tc) else 0),
           Y(tc) if tc else T, Y(tc) if tc else T, Y(bc) if bc else T, Y(bc) if bc else T,
           (Y(tc) - 5) if tc else T, tc_s or '', (Y(bc) + 15) if bc else T, bc_s or '',
           Y(prev_close) if prev_close else T, Y(prev_close) if prev_close else T,
           (Y(prev_close) - 5) if prev_close else T, fmt(prev_close) if prev_close else '',
           path, x_trig, Y(trig), trig_colour, x_trig, Y(trig) - 18, trig_colour, direction, qt,
           inv_svg, tgt_svg, eod_x, eod_y, eod_x, eod_y - 26, Y(sampled[0][1]) + 22,
           (gap_txt or 'Session replay')))
    return day, inst, direction, svg, caps


SHELL = """<section class="sec" id="see-it-work"><h2>See how a signal is born (20 seconds)</h2>
<p class="tai-how-sub">Illustrative replays sketched from classified records — teaching sketches, not live data. <a href="/signal-flow.html">Full rulebook: signal flow</a>.</p>
__BLOCKS__
<div class="tai-how-card"><h3>How to read this replay</h3>
<p class="tai-how-sub">Each replay compresses one classified session into six steps. Press play on a card, or jump with the numbered dots.</p>
<ul>
<li><b>Yesterday settles</b> — the blue band is the Central Pivot Range (top/bottom central) computed from the previous session only.</li>
<li><b>Morning gap</b> — where the index opened versus the previous close, and which way the gap leaned.</li>
<li><b>Five-minute candles watch</b> — the dark line is the session price path, sampled from recorded 5-minute closes starting 09:15.</li>
<li><b>Trigger</b> — the candle that accepted beyond a CPR boundary and classified the session (BEAR below support, BULL above resistance).</li>
<li><b>Reference levels</b> — the dashed lines the rules attached to the record: trigger, invalidation, reference target, and the spread studied.</li>
<li><b>Outcome</b> — how the record closed at the session boundary, kept in the <a href="/alerts.html">alerts archive</a> win or lose.</li>
</ul>
<p class="tai-how-sub">Levels are rounded for display and the path is simplified; exact figures live on the record cards in the archive. Replays refresh every trading evening. Educational sketches only — never investment advice.</p>
</div>
</section>
<style>
#see-it-work .tai-how-sub{font-size:.85rem;color:#475569;margin:.2rem 0 .7rem}
#see-it-work .tai-how-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:.9rem 1.1rem;margin-bottom:.75rem}
#see-it-work .tai-how-card h3{font-size:1.02rem;margin-bottom:.2rem}
#see-it-work .tai-how-card .meta{font-size:.78rem;color:#64748b;margin-bottom:.5rem}
.tai-how-stage{border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;background:#fff}
.tai-how-stage svg{display:block;width:100%;height:auto}
.tai-how-stage svg line,.tai-how-stage svg rect,.tai-how-stage svg text,.tai-how-stage svg circle,.tai-how-stage svg path{transition:opacity .6s ease}
.tai-how-cap{font-size:.9rem;color:#334155;min-height:3.2em;margin:.7rem 0 .4rem}
.tai-how-ctrl{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.tai-how-ctrl button{border:1px solid #1e3a8a;border-radius:8px;background:#0b1e3a;color:#fff;padding:.45rem .9rem;font:700 .8rem Arial,sans-serif;cursor:pointer}
.tai-how-ctrl button:hover{filter:brightness(1.2)}
.tai-how-dots{display:inline-flex;gap:.35rem;margin-left:.3rem}
.tai-how-dots button{width:26px;height:26px;border-radius:50%;border:1px solid #94a3b8;background:#fff;color:#475569;padding:0;font-size:.72rem}
.tai-how-dots button.on{background:#0b1e3a;border-color:#0b1e3a;color:#fff}
.tai-how-stage{position:relative}
.tai-how-fab{position:absolute;top:10px;right:10px;width:36px;height:36px;border-radius:50%;border:1px solid #0b1e3a;background:rgba(11,30,58,.88);color:#fff;display:grid;place-items:center;cursor:pointer;opacity:0;transition:opacity .25s ease;z-index:3;padding:0}
.tai-how-fab svg{width:18px;height:18px;fill:currentColor}
.tai-how-stage:hover .tai-how-fab,.tai-how-stage:focus-within .tai-how-fab{opacity:1}
.tai-how-fab:focus-visible{opacity:1;outline:2px solid #2563eb;outline-offset:2px}
@media(hover:none){.tai-how-fab{opacity:1}}
.tai-how-share-row{position:absolute;left:8px;right:8px;bottom:8px;display:flex;gap:6px;justify-content:center;flex-wrap:wrap;background:rgba(255,255,255,.96);border:1px solid #e2e8f0;border-radius:999px;padding:6px 8px;z-index:3}
.tai-how-share-row[hidden]{display:none}
.tai-how-sh{width:32px;height:32px;border-radius:50%;display:inline-grid;place-items:center;color:#fff;border:1px solid transparent;cursor:pointer;padding:0}
.tai-how-sh svg{width:16px;height:16px;fill:currentColor}
.tai-how-sh-x{background:#000;border-color:#000}
.tai-how-sh-facebook{background:#1877f2;border-color:#1877f2}
.tai-how-sh-whatsapp{background:#25d366;border-color:#25d366}
.tai-how-sh-linkedin{background:#0a66c2;border-color:#0a66c2}
.tai-how-sh-telegram{background:#229ed9;border-color:#229ed9}
.tai-how-sh-ig{background:linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888);border-color:#cc2366}
.tai-how-sh-copy,.tai-how-sh-more{background:#0f172a;border-color:#0f172a}
@media(prefers-reduced-motion:reduce){.tai-how-stage svg line,.tai-how-stage svg rect,.tai-how-stage svg text,.tai-how-stage svg circle,.tai-how-stage svg path{transition:none}}
</style>
<script>
function taiHowBoot(P,caps){
var stage=document.getElementById("taiHowStage"+P);
if(!stage||stage.getAttribute("data-boot"))return;
stage.setAttribute("data-boot","1");
var K=["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Path","Trig","TrigL","Inv","InvL","Tgt","TgtL","Eod","EodL","Gap"];
var E=K.map(function(k){return "taiHow"+P+k;});
function grp(g){return g.map(function(k){return "taiHow"+P+k;});}
var steps=[grp(["Cpr","Tc","Bc","TcL","BcL"]),grp(["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Gap"]),grp(["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Path"]),grp(["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Path","Trig","TrigL"]),grp(["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Path","Trig","TrigL","Inv","InvL","Tgt","TgtL"]),grp(["Cpr","Tc","Bc","TcL","BcL","Pc","PcL","Path","Trig","TrigL","Inv","InvL","Tgt","TgtL","Eod","EodL"])];
var i=0,timer=null,playing=true;
var cap=document.getElementById("taiHowCap"+P),dots=document.getElementById("taiHowDots"+P),playBtn=document.getElementById("taiHowPlay"+P);
var reduced=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function show(n){
i=(n+steps.length)%steps.length;
var on={};steps[i].forEach(function(id){on[id]=1;});
E.forEach(function(id){var el=document.getElementById(id);if(el)el.setAttribute("opacity",on[id]?"1":"0");});
cap.innerHTML=caps[i];
var ds=dots.children;
for(var k=0;k<ds.length;k++){ds[k].className=k===i?"on":"";ds[k].setAttribute("aria-selected",k===i?"true":"false");}
}
for(var d=0;d<steps.length;d++)(function(n){var b=document.createElement("button");b.type="button";b.textContent=String(n+1);b.setAttribute("role","tab");b.setAttribute("aria-label","Go to step "+(n+1));b.addEventListener("click",function(){stop();show(n);});dots.appendChild(b);})(d);
function tick(){show(i+1);}
function stop(){playing=false;if(timer){clearInterval(timer);timer=null;}playBtn.textContent="Play";playBtn.setAttribute("aria-label","Play animation");}
function start(){playing=true;playBtn.textContent="Pause";playBtn.setAttribute("aria-label","Pause animation");if(timer)clearInterval(timer);timer=setInterval(tick,3200);}
playBtn.addEventListener("click",function(){if(playing){stop();}else{start();}});
document.getElementById("taiHowReplay"+P).addEventListener("click",function(){show(0);start();});
var shareBtn=document.getElementById("taiHowShare"+P);
if(shareBtn){var row=document.getElementById("taiHowShareRow"+P);
shareBtn.addEventListener("click",function(){var open=row.hasAttribute("hidden");if(open){row.removeAttribute("hidden");shareBtn.setAttribute("aria-expanded","true");}else{row.setAttribute("hidden","");shareBtn.setAttribute("aria-expanded","false");}});
row.addEventListener("click",function(ev){var t=ev.target.closest("a[data-sh],button[data-sh]");if(!t||!row.contains(t))return;var k=t.getAttribute("data-sh");var url=t.getAttribute("data-url")||"";try{if(window.gtag)window.gtag("event","share",{event_label:"Replay "+k});}catch(e){}
if(k==="copy"){ev.preventDefault();copyUrl(url);}
else if(k==="instagram"){ev.preventDefault();copyUrl(url);try{window.open("https://www.instagram.com/","_blank","noopener");}catch(e){}}
else if(k==="native"&&navigator.share){ev.preventDefault();navigator.share({title:document.title,text:t.getAttribute("data-text")||"",url:url}).catch(function(){});}});
function copyUrl(u){function done(){shareBtn.setAttribute("aria-label","Link copied");setTimeout(function(){shareBtn.setAttribute("aria-label","Share this replay");},2000);}if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(done,function(){fallback();});}else{fallback();}function fallback(){try{var ta=document.createElement("textarea");ta.value=u;ta.style.position="fixed";ta.style.opacity="0";document.body.appendChild(ta);ta.select();document.execCommand("copy");document.body.removeChild(ta);done();}catch(e){}}}}
if("IntersectionObserver" in window){new IntersectionObserver(function(es){es.forEach(function(en){if(!playing)return;if(en.isIntersecting){if(!timer)timer=setInterval(tick,3200);}else{if(timer){clearInterval(timer);timer=null;}}});},{threshold:.2}).observe(stage);}
if(reduced){show(steps.length-1);stop();}else{show(0);start();}
}
__BOOTS__
</script>"""

BLOCK = """<div class="tai-how-card"><h3>__INST__ — __DAY__ (__DIR__)</h3><div class="meta">Reference trigger __TRIG__ · __STRAT__ · teaching replay</div>
<div class="tai-how-stage" id="taiHowStage__P__" aria-label="Animated __INST__ signal walkthrough">
__SVG__
<button type="button" class="tai-how-fab" id="taiHowShare__P__" aria-expanded="false" aria-controls="taiHowShareRow__P__" aria-label="Share this replay"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92c0-1.61-1.31-2.92-2.92-2.92z"/></svg></button><div class="tai-how-share-row" id="taiHowShareRow__P__" hidden><a class="tai-how-sh tai-how-sh-x" href="__HX__" target="_blank" rel="noopener nofollow" data-sh="x" title="Share on X" aria-label="Share on X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.5 3h3.1l-6.8 7.8L21.8 21h-6.3l-4.9-6.4L5 21H1.9l7.3-8.3L2.2 3h6.4l4.4 5.9L17.5 3zm-1.1 16.1h1.7L7.7 4.8H5.9l10.5 14.3z"/></svg></a><a class="tai-how-sh tai-how-sh-facebook" href="__HFB__" target="_blank" rel="noopener nofollow" data-sh="facebook" title="Share on Facebook" aria-label="Share on Facebook"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 21v-7h2.4l.4-3h-2.8V9.1c0-.9.3-1.5 1.6-1.5h1.3V4.9c-.3 0-1.1-.1-2.1-.1-2.1 0-3.6 1.3-3.6 3.7V11H8.3v3h2.4v7h2.8z"/></svg></a><a class="tai-how-sh tai-how-sh-whatsapp" href="__HWA__" target="_blank" rel="noopener nofollow" data-sh="whatsapp" title="Share on WhatsApp" aria-label="Share on WhatsApp"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3zm0 1.8a7.2 7.2 0 1 1-3.7 13.4l-.3-.2-2.7.7.7-2.6-.2-.3A7.2 7.2 0 0 1 12 4.8zm-3 3.3c-.2 0-.5 0-.7.3-.2.3-.9.9-.9 2.1s.9 2.5 1 2.6c.1.1 1.9 3 4.6 4.1 2.3.9 2.8.7 3.3.7.5-.1 1.6-.7 1.9-1.3.2-.6.2-1.1.2-1.3-.1-.1-.3-.2-.6-.3l-2-1c-.3-.1-.5-.2-.7 0l-.9 1.1c-.2.2-.3.2-.6.1a7.6 7.6 0 0 1-2.2-1.4 8.2 8.2 0 0 1-1.5-1.9c-.2-.3 0-.4.1-.6l.5-.6c.1-.2.2-.3.3-.5.1-.2 0-.4 0-.5L9.3 8c-.2-.4-.4-.4-.6-.4H9z"/></svg></a><a class="tai-how-sh tai-how-sh-linkedin" href="__HLI__" target="_blank" rel="noopener nofollow" data-sh="linkedin" title="Share on LinkedIn" aria-label="Share on LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.9 8.6H4V20h2.9V8.6zM5.4 3.5a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 0 0 0-3.4zM10 20v-6c0-1.5.8-2.6 2.3-2.6 1.4 0 2 1 2 2.6v6h2.9v-6.4c0-3-1.6-4.4-3.8-4.4-1.7 0-2.6 1-3 1.7V8.6H7.5V20H10z"/></svg></a><a class="tai-how-sh tai-how-sh-telegram" href="__HTG__" target="_blank" rel="noopener nofollow" data-sh="telegram" title="Share on Telegram" aria-label="Share on Telegram"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 4 3.5 11.1c-.7.3-.7 1.2.1 1.4l4.4 1.4 1.7 5.3c.3.8 1.3.9 1.8.2l2.5-2.9 4.7 3.5c.6.4 1.5.1 1.7-.6L21.9 5c.2-.9-.5-1.3-.9-1zM8.6 13.1l9.5-7.5c.1-.1.3 0 .2.2l-7.8 7.4-.3 3-1.6-3.1z"/></svg></a><button type="button" class="tai-how-sh tai-how-sh-ig" data-sh="instagram" data-url="__EURL__" title="Share on Instagram" aria-label="Share on Instagram"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4c-2.7 0-3 0-4.1.1-1.1 0-1.8.2-2.4.5-.6.2-1.1.6-1.6 1.1-.5.5-.9 1-1.1 1.6-.3.6-.5 1.3-.5 2.4.1 1.1.1 1.4.1 2.3s0 1.2-.1 2.3c0 1.1-.2 1.8-.5 2.4-.2.6-.6 1.1-1.1 1.6-.5.5-1 .9-1.6 1.1-.6.3-1.3.5-2.4.5C9 20 9.3 20 12 20s3 0 4.1-.1c1.1 0 1.8-.2 2.4-.5.6-.2 1.1-.6 1.6-1.1.5-.5.9-1 1.1-1.6.3-.6.5-1.3.5-2.4.1-1.1.1-1.4.1-2.3s0-1.2-.1-2.3c0-1.1-.2-1.8-.5-2.4-.2-.6-.6-1.1-1.1-1.6-.5-.5-1-.9-1.6-1.1-.6-.3-1.3-.5-2.4-.5C15 4 14.7 4 12 4zm0 1.8c2.6 0 3 0 4 .1 1 0 1.5.2 1.9.3.5.2.8.4 1.1.7.3.3.5.6.7 1.1.1.4.3.9.3 1.9.1 1 .1 1.4.1 2.1s0 1-.1 2.1c0 1-.2 1.5-.3 1.9-.2.5-.4.8-.7 1.1-.3.3-.6.5-1.1.7-.4.1-.9.3-1.9.3-1 .1-1.4.1-4 .1s-3 0-4-.1c-1 0-1.5-.2-1.9-.3-.5-.2-.8-.4-1.1-.7-.3-.3-.5-.6-.7-1.1-.1-.4-.3-.9-.3-1.9C4 13.1 4 12.7 4 12s0-1.1.1-2.1c0-1 .2-1.5.3-1.9.2-.5.4-.8.7-1.1.3-.3.6-.5 1.1-.7.4-.1.9-.3 1.9-.3 1-.1 1.4-.1 4-.1zm0 3.1a5.1 5.1 0 1 0 0 10.2 5.1 5.1 0 0 0 0-10.2zm0 8.4a3.3 3.3 0 1 1 0-6.6 3.3 3.3 0 0 1 0 6.6zm5.3-8.6a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0z"/></svg></button><button type="button" class="tai-how-sh tai-how-sh-copy" data-sh="copy" data-url="__EURL__" title="Copy replay link" aria-label="Copy replay link"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 9h9v11H9zM6 4h9v2H8v7H6z" fill-rule="evenodd"/><path d="M9 9h9v11H9V9zm1.5 1.5v8h6v-8h-6zM6 4h9v2H8v7H6V4z"/></svg></button><button type="button" class="tai-how-sh tai-how-sh-more" data-sh="native" data-url="__EURL__" data-text="__ETEXT__" title="More share options" aria-label="More share options"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5.5A1.8 1.8 0 1 0 12 9a1.8 1.8 0 0 0 0-3.5zm0 5.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6zm0 5.3a1.8 1.8 0 1 0 0 3.5 1.8 1.8 0 0 0 0-3.5zM18.5 7.5l-5 2.6.7 1.4 5-2.6-.7-1.4zM18.5 16.5l-5-2.6.7-1.4 5 2.6-.7 1.4zM5.5 7.5l5 2.6-.7 1.4-5-2.6.7-1.4zm0 9l5-2.6-.7-1.4-5 2.6.7 1.4z"/></svg></button></div>
</div>
<p class="tai-how-cap" id="taiHowCap__P__" aria-live="polite">__CAP0__</p>
<div class="tai-how-ctrl">
<button type="button" id="taiHowPlay__P__" aria-label="Pause animation">Pause</button>
<button type="button" id="taiHowReplay__P__" aria-label="Replay animation">Replay</button>
<span class="tai-how-dots" id="taiHowDots__P__" role="tablist" aria-label="Animation steps"></span>
</div>
</div>"""


def render_block(sig, outcome, candles, prev_close, prefix):
    out = build_section(sig, outcome, candles, prev_close)
    if not out:
        return None, None
    day, inst, direction, svg, caps = out
    ctx = sig.get('ctx') or {}
    svg = svg.replace('id="taiHow', 'id="taiHow' + prefix)
    share_url = 'https://tradingai.in/#see-it-work'
    share_text = '%s %s (%s) session replay \u2014 TradingAI.in (educational market analytics, not investment advice)' % (inst, day, direction)
    eu = up.quote(share_url, safe='')
    et = up.quote(share_text, safe='')
    hrefs = {
        '__HX__': 'https://twitter.com/intent/tweet?text=' + et + '&url=' + eu,
        '__HFB__': 'https://www.facebook.com/sharer/sharer.php?u=' + eu,
        '__HWA__': 'https://wa.me/?text=' + up.quote(share_text + ' ' + share_url, safe=''),
        '__HLI__': 'https://www.linkedin.com/sharing/share-offsite/?url=' + eu,
        '__HTG__': 'https://t.me/share/url?url=' + eu + '&text=' + et,
        '__EURL__': share_url,
        '__ETEXT__': share_text,
    }
    block = (BLOCK.replace('__P__', prefix).replace('__INST__', inst)
             .replace('__DAY__', day).replace('__DIR__', direction)
             .replace('__TRIG__', fmt(ctx.get('trigger')) or '')
             .replace('__STRAT__', ctx.get('strategy') or '')
             .replace('__SVG__', svg).replace('__CAP0__', caps[0]))
    for k, v in hrefs.items():
        block = block.replace(k, v)
    boot = 'taiHowBoot("%s",%s);' % (prefix, json.dumps(caps))
    return block, boot


def main():
    recs, sigs = load_signals()
    if not sigs:
        print('no classified signal on record; page untouched')
        return
    latest_day = max(r.get('date') or '' for r in sigs)
    blocks, boots, made = [], [], []
    for inst, prefix in (('NIFTY', 'N'), ('BANKNIFTY', 'B')):
        day_sigs = [r for r in sigs if r.get('date') == latest_day and (r.get('inst') or '') == inst]
        if not day_sigs:
            continue
        sig = day_sigs[-1]
        candles, prev_close = day_candles(inst, latest_day)
        if len(candles) < 5:
            print('insufficient candles for %s %s; skipped' % (inst, latest_day))
            continue
        block, boot = render_block(sig, find_outcome(recs, sig.get('key')), candles, prev_close, prefix)
        if block:
            blocks.append(block)
            boots.append(boot)
            made.append('%s %s' % (latest_day, inst))
    if not blocks:
        print('could not build any replay; page untouched')
        return
    section = SHELL.replace('__BLOCKS__', '\n'.join(blocks)).replace('__BOOTS__', '\n'.join(boots))
    p = PAGE
    s = io.open(p, encoding='utf-8').read()
    if START not in s or END not in s:
        print('markers missing in index.html; page untouched')
        return
    pre, rest = s.split(START, 1)
    _, post = rest.split(END, 1)
    s = pre + START + '\n' + section + '\n' + END + post
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix='.index-', suffix='.html')
    try:
        with io.open(fd, 'w', encoding='utf-8') as f:
            f.write(s)
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print('replay rebuilt for: %s' % '; '.join(made))


if __name__ == '__main__':
    main()
