#!/usr/bin/env python3
import yfinance as yf

START = "2026-10-16"
END = "2026-10-23"
print("fetching ^NSEI 1m candles...")
t = yf.Ticker("^NSEI")
h = t.history(start=START, end=END, interval="1m")
print("fetched:", len(h))
rows = []
for _, r in h.iterrows():
    ts = r.name
    rows.append({
        "timestamp": str(ts),
        "open": float(r["Open"]),
        "high": float(r["High"]),
        "low": float(r["Low"]),
        "close": float(r["Close"]),
        "date": str(ts.date()),
    })
print("rows:", len(rows), rows[0]["timestamp"] if rows else None, rows[-1]["timestamp"] if rows else None)

STOP = 1.0
TARGET_R = 1.5
MAX_RISK = 40.0
trades = []
for i in range(2, len(rows)):
    if i + 1 >= len(rows):
        break
    p, c = rows[i - 1], rows[i]
    up = (c["high"] - p["high"]) > 0 and (c["low"] - p["low"]) > 0 and (c["close"] - p["close"]) > 0
    down = (c["high"] - p["high"]) < 0 and (c["low"] - p["low"]) < 0 and (c["close"] - p["close"]) < 0
    if not (up or down):
        continue
    nc = rows[i + 1]
    if up:
        entry = nc["open"]; stop = rows[i]["low"] - STOP; risk = entry - stop; target = entry + risk * TARGET_R
    else:
        entry = nc["open"]; stop = rows[i]["high"] + STOP; risk = stop - entry; target = entry - risk * TARGET_R
    if risk <= 0 or risk > MAX_RISK:
        continue
    bar = rows[i + 1]
    if up:
        hit_stop = bar["low"] <= stop; hit_target = bar["high"] >= target
    else:
        hit_stop = bar["high"] >= stop; hit_target = bar["low"] <= target
    if hit_stop and hit_target: exit_px, exit_reason = stop, "STOP (both same candle)"
    elif hit_stop: exit_px, exit_reason = stop, "STOP"
    elif hit_target: exit_px, exit_reason = target, "TARGET"
    else: exit_px, exit_reason = bar["close"], "EOD"
    gross = (exit_px - entry) if up else (entry - exit_px)
    r_mult = gross / risk if risk else 0.0
    trades.append({
        "trade_date": nc["date"], "direction": "BULL" if up else "BEAR",
        "entry": round(entry, 2), "exit": round(exit_px, 2), "exit_reason": exit_reason,
        "r_multiple": round(r_mult, 3), "win_loss": "WIN" if r_mult > 0 else ("LOSS" if r_mult < 0 else "FLAT"),
    })
rs = [t["r_multiple"] for t in trades]
n = len(rs)
w = sum(1 for t in trades if (t["r_multiple"] or 0) > 0)
print("1m TRADES:", n, "WINS:", w, "WIN_RATE%:", round(100 * w / n, 1) if n else 0)
print("TOTAL_R:", round(sum(rs), 2) if n else 0, "AVG_R:", round(sum(rs) / n, 3) if n else 0)
print("LOSSES:", sum(1 for t in trades if (t["r_multiple"] or 0) < 0))
