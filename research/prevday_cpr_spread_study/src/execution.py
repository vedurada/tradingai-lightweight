"""Entry / stop / target / exit simulation at INDEX level (spec.md §4).

Conservative rules:
  * entry = open of the bar AFTER the signal bar;
  * a bar that contains both the stop and the target is resolved as STOP first;
  * a bar that OPENS beyond the stop is filled at the OPEN (gap-through);
  * the EOD exit is the 15:20 OPEN (production convention).
"""
from datetime import datetime

BULL, BEAR = "BULLISH", "BEARISH"

TIME_EXIT_BARS = {"EOD": "15:20", "13:30": "13:30", "14:00": "14:00",
                  "14:30": "14:30"}


def _stop_price(ctx, sig, entry, dirn, stop_cfg):
    kind = stop_cfg.get("type", "PCT")
    if kind == "PCT":
        dist = entry * float(stop_cfg.get("value", 0.005))
        return entry - dirn * dist, dist
    base = stop_cfg.get("level") or sig.get("invalidation")
    if base is None:
        dist = entry * 0.005
        return entry - dirn * dist, dist
    if kind == "ATR":
        atr = ctx.get("prev_atr5m") or 0.0
        buf = float(stop_cfg.get("mult", 1.0)) * atr
    else:
        buf = float(stop_cfg.get("buffer_pts", 10.0))
        buf = max(buf, entry * float(stop_cfg.get("buffer_pct", 0.0)))
    stop = float(base) - dirn * buf
    dist = abs(entry - stop)
    if dist <= 0:
        dist = entry * 0.005
        stop = entry - dirn * dist
    return stop, dist


def _target_price(entry, dirn, stop_dist, target_cfg):
    kind = target_cfg.get("type", "R")
    if kind == "R":
        return entry + dirn * float(target_cfg.get("value", 1.0)) * stop_dist
    lvl = target_cfg.get("level")
    if lvl is None:
        return entry + dirn * stop_dist
    return float(lvl)


def simulate(ctx, sig, stop_cfg, target_cfg, time_exit="EOD", cost_r=0.0):
    """Simulate one signal. Returns a trade dict, or None if not executable."""
    bars = ctx["bars"]
    ei = sig.get("entry_bar_idx")
    if ei is None or ei >= len(bars):
        return None
    entry = bars[ei]["o"]
    dirn = 1 if sig["direction"] == BULL else -1
    stop, stop_dist = _stop_price(ctx, sig, entry, dirn, stop_cfg)
    target = _target_price(entry, dirn, stop_dist, target_cfg)
    if dirn * (target - entry) <= 0:
        target = entry + dirn * stop_dist          # target must be directional

    exit_bar_hhmm = TIME_EXIT_BARS.get(time_exit or "EOD", "15:20")
    mfe_r = 0.0
    mae_r = 0.0
    exit_price = None
    exit_reason = None
    exit_idx = None
    exit_ts = None
    gap_fill = False
    missing_exit_bar = False

    exit_bar_present = any(b["hhmm"] == exit_bar_hhmm for b in bars)
    for j in range(ei, len(bars)):
        b = bars[j]
        if b["hhmm"] == exit_bar_hhmm:
            # flat at the OPEN of the exit bar: the bar's own range is never used
            gapped = (b["o"] <= stop) if dirn == 1 else (b["o"] >= stop)
            exit_price = b["o"]
            exit_reason = "STOP_GAP" if gapped else "TIME_EXIT"
            gap_fill = gapped
            exit_idx, exit_ts = j, b["ts"]
            break
        # excursions up to this bar
        if dirn == 1:
            mfe_r = max(mfe_r, (b["h"] - entry) / stop_dist)
            mae_r = min(mae_r, (b["l"] - entry) / stop_dist)
            stop_hit = b["l"] <= stop
            target_hit = b["h"] >= target
            gap_stop = b["o"] <= stop
        else:
            mfe_r = max(mfe_r, (entry - b["l"]) / stop_dist)
            mae_r = min(mae_r, (entry - b["h"]) / stop_dist)
            stop_hit = b["h"] >= stop
            target_hit = b["l"] <= target
            gap_stop = b["o"] >= stop
        if gap_stop:
            exit_price = b["o"]
            exit_reason = "STOP_GAP"
            exit_idx, exit_ts = j, b["ts"]
            gap_fill = True
            break
        if stop_hit:                      # conservative: stop before target
            exit_price = stop
            exit_reason = "STOP"
            exit_idx, exit_ts = j, b["ts"]
            break
        if target_hit:
            exit_price = target
            exit_reason = "TARGET"
            exit_idx, exit_ts = j, b["ts"]
            break
    if exit_price is None:
        # the exit bar was missing (2026-09-21 / 2026-10-15) -> flagged, never hidden
        last = bars[-1]
        exit_price = last["c"]
        exit_reason = "EOD_LAST_CLOSE"
        exit_idx, exit_ts = len(bars) - 1, last["ts"]
        missing_exit_bar = True
    if not exit_bar_present:
        missing_exit_bar = True

    pts = dirn * (exit_price - entry)
    r = pts / stop_dist
    r_net = r - float(cost_r or 0.0)
    hold_bars = (exit_idx - ei + 1) if exit_idx is not None else 0
    hold_min = 0.0
    if exit_ts is not None:
        hold_min = (exit_ts - bars[ei]["ts"]).total_seconds() / 60.0
    return {
        "session_date": ctx["session_date"],
        "model": sig["model"], "direction": sig["direction"],
        "setup_type": sig.get("setup_type"),
        "level": sig.get("level"),
        "reason": sig.get("reason"),
        "signal_ts": sig.get("signal_ts"), "signal_hhmm": sig.get("signal_hhmm"),
        "entry_ts": bars[ei]["ts"].isoformat(), "entry_price": entry,
        "stop_price": stop, "stop_dist": stop_dist, "target_price": target,
        "exit_ts": exit_ts.isoformat() if exit_ts else None,
        "exit_price": exit_price, "exit_reason": exit_reason,
        "r": r, "r_net": r_net, "points": pts,
        "mfe_r": mfe_r, "mae_r": mae_r,
        "hold_bars": hold_bars, "hold_minutes": hold_min,
        "gap_fill": gap_fill, "missing_exit_bar": missing_exit_bar,
        "result": "WIN" if pts > 0 else "LOSS" if pts < 0 else "BE",
    }
