from __future__ import annotations

"""Daily dated market pages: numbers from SQLite, words around them.

- `morning [YYYY-MM-DD]` -> market/nifty-outlook-<date>.html  (run ~09:35 IST)
- `close [YYYY-MM-DD]`   -> market/nifty-close-<date>.html    (run ~15:35 IST)

Static HTML with full meta/OG/canonical + Article JSON-LD. After writing,
run sitemap_gen.py --webroot so search engines discover the new URL.
Usage: python3 daily_page.py morning | close [--date 2026-09-10] [--webroot /var/www/tradingai.in/html]
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
SYMBOL = "NIFTY"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _num(v, dec: int = 2) -> str:
    try:
        return f"{float(v):,.{dec}f}"
    except Exception:
        return "—"


def _fetch_day(conn: sqlite3.Connection, date_str: str) -> dict:
    """Everything the article needs, all from the database."""
    d: dict = {"date": date_str}
    candles = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM price_1m WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp",
        (SYMBOL, f"{date_str}%")).fetchall()
    d["candles"] = [dict(r) for r in candles]
    if candles:
        d.update(open=candles[0]["open"], high=max(r["high"] for r in candles),
                 low=min(r["low"] for r in candles), close=candles[-1]["close"],
                 volume=sum(r["volume"] or 0 for r in candles))
    ind = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (SYMBOL,)).fetchone()
    d["indicators"] = dict(ind) if ind else {}
    try:
        d["support_resistance"] = json.loads(d["indicators"].get("support_resistance") or "{}")
    except Exception:
        d["support_resistance"] = {}
    reg = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (SYMBOL,)).fetchone()
    d["regime"] = dict(reg) if reg else {}
    strat = conn.execute("SELECT * FROM daily_strategy WHERE symbol=? AND date=?", (SYMBOL, date_str)).fetchone()
    if not strat:
        strat = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (SYMBOL,)).fetchone()
        d["strategy_locked"] = False
    else:
        d["strategy_locked"] = True
    d["strategy"] = dict(strat) if strat else {}
    try:
        legs = json.loads(d["strategy"].get("legs") or "{}")
        d["strategy_list"] = legs.get("all_strategies", []) if isinstance(legs, dict) else []
    except Exception:
        d["strategy_list"] = []
    vix = conn.execute("SELECT * FROM vix_data WHERE date(timestamp)=? OR substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1", (date_str, date_str)).fetchone()
    d["vix"] = dict(vix) if vix else {}
    hist = conn.execute("SELECT * FROM history WHERE symbol=? AND date=?", (SYMBOL, date_str)).fetchone()
    d["pnl"] = dict(hist) if hist else {}
    exp = conn.execute("SELECT expiry FROM option_expiries WHERE symbol=? AND expiry>=? ORDER BY expiry LIMIT 3", (SYMBOL, date_str)).fetchall()
    d["expiries"] = [r["expiry"] for r in exp]
    return d


def _head(title: str, desc: str, url: str) -> str:
    ld = {"@context": "https://schema.org", "@type": "Article",
          "headline": title, "description": desc,
          "author": {"@type": "Organization", "name": "TradingAI"},
          "publisher": {"@type": "Organization", "name": "TradingAI"}}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{json.dumps(ld)}</script>
<link rel="stylesheet" href="../assets/css/main.css">
</head>"""


def _nav() -> str:
    return """<body>
<header>
  <h1>TradingAI</h1>
  <p class="tagline">Market Intelligence Platform</p>
  <nav>
    <a href="../index.html">Home</a>
    <a href="../market.html">Market</a>
    <a href="../indices/nifty.html">NIFTY</a>
    <a href="../indices/banknifty.html">Bank NIFTY</a>
    <a href="../scanner.html">Scanner</a>
    <a href="../strategies.html">Strategies</a>
    <a href="../strategy-builder.html">Builder</a>
    <a href="../strategies-guide.html">Guide</a>
    <a href="../history.html">History</a>
  </nav>
</header>
<main>"""


def _foot() -> str:
    return """  <footer>
    <p>AI-generated market analysis based on current market data. Defined-risk strategy analysis. Not financial advice — markets can move unexpectedly; users are responsible for their trading decisions.</p>
  </footer>
</main>
</body>
</html>"""


def _why(reg: dict, ind: dict, vix: dict, quote_close: float) -> list[str]:
    out = []
    vwap = ind.get("vwap") or 0
    if vwap and quote_close:
        out.append(f"Price {'above' if quote_close >= vwap else 'below'} VWAP ({_num(vwap)})")
    rsi = ind.get("rsi")
    if rsi is not None:
        out.append(f"RSI {rsi:.0f} ({'healthy momentum' if 50 <= rsi <= 70 else 'oversold' if rsi < 30 else 'overbought' if rsi > 75 else 'neutral'})")
    adx = ind.get("adx")
    if adx is not None:
        out.append(f"ADX {adx:.0f} ({'trending' if adx > 25 else 'range-like'})")
    if vix.get("close"):
        out.append(f"India VIX {vix['close']:.1f}")
    return out


def render_morning(d: dict, date_str: str) -> str:
    pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y")
    title = f"NIFTY Market Outlook — {pretty}"
    desc = (f"NIFTY outlook for {pretty}: regime {(d['regime'].get('regime',''))}, "
            f"support/resistance, expected range, VIX and intraday strategy conditions.")
    url = f"https://tradingai.in/market/nifty-outlook-{date_str}.html"
    reg, ind, vix = d["regime"], d["indicators"], d["vix"]
    sr = d["support_resistance"]
    sup, res = sr.get("support", []), sr.get("resistance", [])
    why = _why(reg, ind, vix, d.get("close", 0))
    exp = ", ".join(d["expiries"][:3]) or "—"
    h = [_head(title, desc, url), _nav(),
         f"<div class='updated-bar'><span>Published {pretty} ~09:35 IST</span></div>",
         f"<h2>NIFTY MARKET OUTLOOK — {pretty.upper()}</h2>",
         f"<div class='card'><div class='status'>Previous close: {_num(d.get('close'))} | Day range so far: {_num(d.get('low'))} – {_num(d.get('high'))}</div>"
         f"<div class='status'>Market regime: <strong>{reg.get('regime','N/A')}</strong> ({reg.get('confidence',0)}%)</div>"
         f"<div class='status'>India VIX: {_num(vix.get('close'),1) if vix.get('close') else '—'}</div></div>",
         "<div class='card'><h3>Trend</h3>"
         f"<div class='status'>VWAP: {_num(ind.get('vwap'))} | EMA20: {_num(ind.get('ema20'))} | EMA50: {_num(ind.get('ema50'))} | RSI: {ind.get('rsi','—')} | ADX: {ind.get('adx','—')}</div></div>",
         "<div class='card'><h3>Support &amp; Resistance</h3>"
         f"<div class='status'>Support: {', '.join(_num(x) for x in sup) or '—'}</div>"
         f"<div class='status'>Resistance: {', '.join(_num(x) for x in res) or '—'}</div>"
         f"<div class='status'>Expected range: {( _num(sup[0])+' – '+_num(res[0])) if sup and res else '—'}</div></div>",
         "<div class='card'><h3>Options positioning</h3>"
         f"<div class='status'>Upcoming expiries: {exp}</div>"
         "<div class='status'>PCR / OI concentration: unavailable — Yahoo carries no NSE option chain.</div></div>",
         "<div class='card'><h3>Why this view?</h3>" + "".join(f"<div class='status'>✓ {w}</div>" for w in why) + "</div>",
         f"<div class='card'><h3>Intraday plan</h3><div class='status'>Strategy locks at the 9:30 AM outlook — see <a href='../strategies.html'>Strategy Intelligence</a> and <a href='../indices/nifty.html'>live NIFTY dashboard</a>.</div></div>",
         _foot()]
    return "\n".join(h)


def render_close(d: dict, date_str: str) -> str:
    pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y")
    title = f"NIFTY Market Analysis — {pretty}"
    pnl = d.get("pnl", {})
    pts = pnl.get("points")
    pts_txt = f"{pts:+.2f} pts {pnl.get('result','')}" if pts is not None else "—"
    desc = f"NIFTY market close report for {pretty}: session range, close { _num(d.get('close'))}, paper P&L {pts_txt}."
    url = f"https://tradingai.in/market/nifty-close-{date_str}.html"
    candles = d.get("candles", [])
    day_open = candles[0]["open"] if candles else 0
    h = [_head(title, desc, url), _nav(),
         f"<div class='updated-bar'><span>Published {pretty} ~15:35 IST</span></div>",
         f"<h2>NIFTY TODAY — {pretty.upper()}</h2>",
         f"<div class='card'><h3>Market summary</h3><div class='status'>Open {_num(day_open)} | High {_num(d.get('high'))} | Low {_num(d.get('low'))} | Close {_num(d.get('close'))}</div>"
         f"<div class='status'>Regime: <strong>{d['regime'].get('regime','N/A')}</strong> | VIX: {_num(d['vix'].get('close'),1) if d['vix'].get('close') else '—'}</div></div>",
         f"<div class='card'><h3>Paper trade (9:30 → 3:20)</h3><div class='status'>Entry {pnl.get('entry_time','09:30')} @ {_num(pnl.get('locked_price'))} → Exit {pnl.get('exit_time','15:20')} @ {_num(pnl.get('closed_price'))} = <strong>{pts_txt}</strong> ({pnl.get('direction','')} {pnl.get('strategy','')})</div>"
         f"<div class='status'>Full record: <a href='../history.html'>P&amp;L history</a></div></div>",
         f"<div class='card'><h3>Levels for tomorrow</h3><div class='status'>Support: {', '.join(_num(x) for x in d['support_resistance'].get('support',[])) or '—'} | Resistance: {', '.join(_num(x) for x in d['support_resistance'].get('resistance',[])) or '—'}</div></div>",
         f"<div class='card'><h3>Morning outlook</h3><div class='status'><a href='nifty-outlook-{date_str}.html'>Read the morning outlook for {pretty} →</a></div></div>",
         _foot()]
    return "\n".join(h)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("morning", "close") else "morning"
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    webroot = None
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            date_str = args[i + 1]
            i += 2
        elif args[i] == "--webroot" and i + 1 < len(args):
            webroot = args[i + 1]
            i += 2
        else:
            i += 1
    conn = _db()
    d = _fetch_day(conn, date_str)
    conn.close()
    html = render_morning(d, date_str) if mode == "morning" else render_close(d, date_str)
    name = f"nifty-{'outlook' if mode == 'morning' else 'close'}-{date_str}.html"
    outdir = os.path.join(webroot, "market") if webroot else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "market")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, name), "w") as f:
        f.write(html)
    print(f"wrote {name} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
