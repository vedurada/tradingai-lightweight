from __future__ import annotations

"""Backfill ~1 year of daily candles for tracked stocks into price_1d (gap-fill via yfinance).

Idempotent (INSERT OR IGNORE on unique symbol+date). Run after deploy, then weekly via cron.
Usage: python3 backfill_yearly.py
"""

import os
import sqlite3
import time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol, yfinance_symbol FROM symbols WHERE active=1 AND type='stock' AND yfinance_symbol IS NOT NULL"
    ).fetchall()
    yf_map = {r["yfinance_symbol"]: r["symbol"] for r in rows}
    if not yf_map:
        print("no stock yfinance symbols to backfill")
        conn.close()
        return

    existing = {(r["symbol"], str(r["timestamp"])[:10]) for r in conn.execute("SELECT symbol, timestamp FROM price_1d")}
    t0 = time.time()
    try:
        import yfinance as yf

        df = yf.download(list(yf_map.keys()), period="1y", interval="1d",
                         group_by="ticker", auto_adjust=False, progress=False, threads=True)
    except Exception as e:
        print(f"download failed: {e}")
        conn.close()
        return

    inserted = skipped = 0
    for yf_sym, sym in yf_map.items():
        try:
            sub = df[yf_sym].dropna(how="all") if hasattr(df[yf_sym], "dropna") else df[yf_sym]
            if sub is None or len(sub) == 0:
                continue
            for idx, row in sub.iterrows():
                ts = str(idx.date())
                if (sym, ts) in existing:
                    skipped += 1
                    continue
                o, h, l, cl = row["Open"], row["High"], row["Low"], row["Close"]
                if any(v is None for v in (o, h, l, cl)):
                    continue
                vol = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
                conn.execute(
                    "INSERT OR IGNORE INTO price_1d (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sym, ts, float(o), float(h), float(l), float(cl), vol),
                )
                inserted += 1
        except Exception as e:
            print(f"ERR {sym}: {e}")
    conn.commit()
    conn.close()
    print(f"backfill_yearly done in {time.time()-t0:.1f}s inserted={inserted} skipped={skipped}")


if __name__ == "__main__":
    main()