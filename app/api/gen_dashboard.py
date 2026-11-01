import sqlite3
from datetime import datetime
conn = sqlite3.connect("file:/opt/tradingai/database/tradingai.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT signal_id, trade_date, instrument_id, strategy, direction, signal_type, source_candle_ts, reference_price, reference_stop, reference_target FROM scalp_signals WHERE trade_date >= date('now','-1 days') ORDER BY trade_date DESC, source_candle_ts DESC LIMIT 30").fetchall()
html = '<html><head><meta charset="utf-8"><title>TradingAI Live Dashboard</title><style>body{font-family:sans-serif;background:#0b0c15;color:#eaeaea;padding:2rem}h1{color:#00e5ff}table{border-collapse:collapse;width:100%;font-size:0.85rem}th{background:#161b2e;color:#00e5ff;padding:.6rem;text-align:left}td{padding:.5rem;border-bottom:1px solid #2a2f3f}tr:hover{background:#161b2e}.scalp{color:#ffb400}</style></head><body>'
html += f"<h1>TradingAI.in — Live Shadow / Paper Trades (HLC 3-Bar)</h1><p>DB: /opt/tradingai/database/tradingai.db | Table: scalp_signals | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M IST')}</p>"
html += '<table><tr><th>Signal ID</th><th>Date</th><th>Instrument</th><th>Dir</th><th>Signal Time</th><th>Ref Price (Signal)</th><th>Stop</th><th>Target</th><th>Strategy</th><th>State</th></tr>'
for r in rows:
    html += f"<tr><td>{r['signal_id'][:8]}...</td><td>{r['trade_date']}</td><td>{r['instrument_id']}</td><td>{r['direction']}</td><td>{(r["source_candle_ts"] or "").replace("+05:30","")}}</td><td>{r['reference_price'] or '-'}</td><td>{r['reference_stop'] or '-'}</td><td>{r['reference_target'] or '-'}</td><td class='scalp'>{r['strategy'] or '-'}</td><td>OPEN / SIGNAL</td></tr>"
html += '</table><p><b>Rule (HLC 3-Bar):</b> Signal = 3 consecutive 5m bars H/L/C aligned; Entry = next candle open; Stop = signal candle low/high ±1pt; Target = 1.5R.</p>'
html += '<p><a href="https://tradingai.in/live.dashboard">Deploy to /opt/tradingai/app/api/live.dashboard.html + nginx/reverse-proxy to expose at https://tradingai.in/live.dashboard</a></p></body></html>'
with open("/tmp/live.dashboard.html","w") as f: f.write(html)
print("rows:", len(rows))
