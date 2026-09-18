import sqlite3
c = sqlite3.connect("/opt/tradingai/database/tradingai.db")
rows = c.execute("SELECT COUNT(*) FROM price_1m").fetchone()[0]
latest = c.execute("SELECT symbol, timestamp FROM price_1m ORDER BY timestamp DESC LIMIT 5").fetchall()
print(f"price_1m: {rows} rows")
for r in latest: print(f"  {r[0]}: {r[1]}")
print()
rows = c.execute("SELECT COUNT(*) FROM price_5m").fetchone()[0]
latest = c.execute("SELECT symbol, timestamp FROM price_5m ORDER BY timestamp DESC LIMIT 5").fetchall()
print(f"price_5m: {rows} rows")
for r in latest: print(f"  {r[0]}: {r[1]}")
print()
rows = c.execute("SELECT COUNT(*) FROM live_quotes").fetchone()[0]
latest = c.execute("SELECT symbol, timestamp FROM live_quotes ORDER BY timestamp DESC LIMIT 5").fetchall()
print(f"live_quotes: {rows} rows")
for r in latest: print(f"  {r[0]}: {r[1]}")
print()
for t in ["nifty_outlook", "banknifty_outlook", "finnifty_outlook", "sensex_outlook"]:
    try:
        rows = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {rows} rows")
    except: print(f"{t}: NO TABLE")
print()
print("paper_trades:", c.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0])
print("integrity:", c.execute("PRAGMA integrity_check").fetchone()[0])
