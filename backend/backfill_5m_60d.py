#!/usr/bin/env python3
"""Backfill true 5m candles for last 60d via yfinance (no synthetic)."""
import os, sqlite3, time
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

def main():
    import yfinance as yf
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    rows=conn.execute("SELECT symbol, yfinance_symbol FROM symbols WHERE yfinance_symbol IS NOT NULL AND symbol IN ('NIFTY','BANKNIFTY','FINNIFTY','SENSEX')").fetchall()
    yf_map={r["yfinance_symbol"]: r["symbol"] for r in rows}
    print("tickers", yf_map)
    # yfinance 5m period 60d
    try:
        df=yf.download(list(yf_map.keys()), period="60d", interval="5m", group_by="ticker", auto_adjust=False, progress=False, threads=True, timeout=60)
    except Exception as e:
        print("download failed", e)
        return
    # need to handle df structure
    inserted=0
    for yf_sym, sym in yf_map.items():
        try:
            sub=df[yf_sym] if yf_sym in df.columns.get_level_values(0) else df
            if sub is None or len(sub)==0:
                continue
            # drop NaN
            sub=sub.dropna(how="all")
            for idx, row in sub.iterrows():
                # idx is Timestamp with tz
                try:
                    ts = idx.tz_convert('UTC').strftime("%Y-%m-%d %H:%M:%S")
                except:
                    ts = str(idx)[:19]
                # check if already exists
                exists=conn.execute("SELECT 1 FROM price_5m WHERE symbol=? AND timestamp=? LIMIT 1", (sym, ts)).fetchone()
                if exists:
                    continue
                o,h,l,c,vol = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"), row.get("Volume")
                if any(v!=v for v in (o,h,l,c)): # NaN
                    continue
                try:
                    o,h,l,c=float(o),float(h),float(l),float(c)
                    vol=int(vol) if vol==vol else 0
                except:
                    continue
                conn.execute("INSERT OR IGNORE INTO price_5m (symbol, timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                             (sym, ts, o,h,l,c,vol))
                inserted+=1
        except Exception as e:
            print(f"ERR {sym}: {e}")
            import traceback; traceback.print_exc()
    conn.commit()
    conn.close()
    print(f"5m backfill done inserted {inserted}")

if __name__=="__main__":
    main()
