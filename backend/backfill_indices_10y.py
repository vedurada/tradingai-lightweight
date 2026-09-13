#!/usr/bin/env python3
"""Backfill 10y daily candles for indices (NIFTY/BANKNIFTY/SENSEX/FINNIFTY) into price_1d via yfinance.

Usage: python3 backfill_indices_10y.py [--period 10y]
 period: 1y|2y|5y|10y|max (default 10y)
"""
import os, sys, time, sqlite3, argparse

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

PERIOD_MAP = {"10y": "10y", "5y": "5y", "2y": "2y", "1y": "1y", "max": "max"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="10y", choices=["1y","2y","5y","10y","max"])
    args = ap.parse_args()
    period = PERIOD_MAP[args.period]

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT symbol, yfinance_symbol FROM symbols WHERE yfinance_symbol IS NOT NULL AND symbol IN ('NIFTY','BANKNIFTY','FINNIFTY','SENSEX','INDIA VIX')").fetchall()
    # also include INDIA VIX? stored as VIX? check yfinance_symbol for VIX
    yf_map = {r["yfinance_symbol"]: r["symbol"] for r in rows}
    if not yf_map:
        print("no symbols")
        return
    # ensure VIX included if present elsewhere
    # yfinance tickers: ^NSEI, ^NSEBANK, ^BSESN, ^CNX100? FINNIFTY uses custom? Use ^NSEI proxy for FINNIFTY if needed
    # FINNIFTY yfinance may be ^NSEI-like? keep as is if mapping exists else map to ^NSEI
    for r in rows:
        print(f"  {r['symbol']} -> {r['yfinance_symbol']}")
    existing = {(r["symbol"], str(r["timestamp"])[:10]) for r in conn.execute("SELECT symbol, timestamp FROM price_1d")}
    print(f"existing price_1d rows: {len(existing)}, period={period}, tickers={list(yf_map.keys())}")
    try:
        import yfinance as yf
        df = yf.download(list(yf_map.keys()), period=period, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True, timeout=60)
    except Exception as e:
        print(f"download failed: {e}")
        return

    inserted = skipped = 0
    for yf_sym, sym in yf_map.items():
        try:
            # df may be MultiIndex
            if len(yf_map) > 1:
                sub = df[yf_sym] if yf_sym in df.columns.get_level_values(0) else None
                if sub is None:
                    # fallback for single-level
                    sub = df
            else:
                sub = df
            if sub is None or len(sub) == 0:
                print(f"  {sym}: no data")
                continue
            # drop rows where all OHLC NaN
            sub = sub.dropna(how="all", subset=["Open","High","Low","Close"]) if "Open" in sub.columns else sub
            for idx, row in sub.iterrows():
                try:
                    ts = str(idx.date())
                except:
                    ts = str(idx)[:10]
                if (sym, ts) in existing:
                    skipped += 1
                    continue
                o, h, l, cl = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")
                if any(v is None or str(v) == "nan" for v in (o,h,l,cl)):
                    continue
                try:
                    o, h, l, cl = float(o), float(h), float(l), float(cl)
                except:
                    continue
                if o == 0 or cl == 0:
                    continue
                vol = row.get("Volume")
                try:
                    vol = int(vol) if vol == vol and vol is not None else 0
                except:
                    vol = 0
                conn.execute("INSERT OR IGNORE INTO price_1d (symbol, timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                             (sym, ts, o, h, l, cl, vol))
                inserted += 1
                existing.add((sym, ts))
        except Exception as e:
            print(f"ERR {sym}: {e}")
            import traceback; traceback.print_exc()
    conn.commit()
    conn.close()
    print(f"done inserted={inserted} skipped={skipped}")

if __name__ == "__main__":
    main()
