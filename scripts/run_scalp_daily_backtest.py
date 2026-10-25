#!/usr/bin/env python3
"""Apply ScanLP scalp logic (connected HLC 3-bar alignment) to daily candles."""
import csv

PATH = "/Users/satya/research/nifty_daily_multiyear_2007_2026/daily_feature_dataset.csv"
STOP = 1.0
TARGET_R = 1.5
MAX_RISK = 40.0

rows = []
with open(PATH, newline="") as f:
    for d in csv.DictReader(f):
        rows.append({
            "date": d["date"],
            "open": float(d["O"]),
            "high": float(d["H"]),
            "low": float(d["L"]),
            "close": float(d["C"]),
        })

print("rows loaded:", len(rows), "first:", rows[0]["date"], "last:", rows[-1]["date"])


def scan(candles):
    sigs = []
    for i in range(2, len(candles)):
        p, c = candles[i - 1], candles[i]
        up = (c["high"] - p["high"]) > 0 and (c["low"] - p["low"]) > 0 and (c["close"] - p["close"]) > 0
        down = (c["high"] - p["high"]) < 0 and (c["low"] - p["low"]) < 0 and (c["close"] - p["close"]) < 0
        if not (up or down):
            continue
        sigs.append((i, "BULL" if up else "BEAR"))
    return sigs


trades = []
for i, direction in scan(rows):
    if i + 1 >= len(rows):
        continue
    nc = rows[i + 1]
    if direction == "BULL":
        entry = nc["open"]
        stop = rows[i]["low"] - STOP
        risk = entry - stop
        target = entry + risk * TARGET_R
    else:
        entry = nc["open"]
        stop = rows[i]["high"] + STOP
        risk = stop - entry
        target = entry - risk * TARGET_R
    if risk <= 0 or risk > MAX_RISK:
        continue
    bar = rows[i + 1]
    if direction == "BULL":
        hit_stop = bar["low"] <= stop
        hit_target = bar["high"] >= target
    else:
        hit_stop = bar["high"] >= stop
        hit_target = bar["low"] <= target
    if hit_stop and hit_target:
        exit_px, exit_reason = stop, "STOP (both same candle)"
    elif hit_stop:
        exit_px, exit_reason = stop, "STOP"
    elif hit_target:
        exit_px, exit_reason = target, "TARGET"
    else:
        exit_px, exit_reason = bar["close"], "EOD"
    gross = (exit_px - entry) if direction == "BULL" else (entry - exit_px)
    r_mult = gross / risk if risk else 0.0
    trades.append({
        "trade_date": nc["date"], "direction": direction, "level": "H1_UP" if direction == "BULL" else "H1_DOWN",
        "entry": round(entry, 2), "exit": round(exit_px, 2), "exit_reason": exit_reason,
        "r_multiple": round(r_mult, 3), "win_loss": "WIN" if r_mult > 0 else ("LOSS" if r_mult < 0 else "FLAT"),
    })

rs = [t["r_multiple"] for t in trades]
n = len(rs)
w = sum(1 for t in trades if (t["r_multiple"] or 0) > 0)
print("TRADES:", n, "WINS:", w, "WIN_RATE%:", round(100 * w / n, 1) if n else 0)
print("TOTAL_R:", round(sum(rs), 2) if n else 0, "AVG_R:", round(sum(rs) / n, 3) if n else 0)
print("LOSSES:", sum(1 for t in trades if (t["r_multiple"] or 0) < 0))
print("FIRST 20 TRADES:")
for t in trades[:20]:
    print(t)
