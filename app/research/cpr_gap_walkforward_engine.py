"""CPR + gap 09:45 walk-forward credit-spread backtest (READ-ONLY).

Validated NIFTY 09:45 short-credit strategy over stored 5m candles. The
rules are the CPR + daily-gap walk-forward decision published in
LEVEL_RESEARCH_REPORT.md (fade/bias classification over a trailing 20-session
window of CPR width and gap size):

- first-30m (5m buckets 09:15..09:40) defines the observation; entry is the
  close of the 09:40 bucket (09:45 NIFTY price).
- large gap up holding above TC for the first 30m -> A_BULL_PUT; large gap
  down holding below BC -> A_BEAR_CALL (cushioned strikes, 100-pt width).
- price above CPR with positive first 30m -> B_BULL_PUT; below CPR with
  negative first 30m -> B_BEAR_CALL.
- otherwise -> wider iron condor (neutral/inside/wide CPR variants).
- win = neither short strike is touched after entry (trigger-hit rule);
  separate 15:15-exit win = price at the 15:15 open resolves on the short
  side correctly, mirroring a flat-at-15:15 exit.

Points = EXACT index move for the directional legs, not assumed credit:
- BULL (bull put): points = exit_price - entry_price (15:15 open minus 09:45)
- BEAR (bear call): points = entry_price - exit_price
- NEUTRAL (iron condor): points = -|exit_price - entry_price| (any large
  move is adverse for the neutral position)
Actual candle prices only; no premium assumption (historical option chains
unavailable -> documented SPOT-R limitation). A bull-put win can therefore
show small negative points if the index eased below entry but never hit the
short strike; P/L should be read alongside the touch/exit win flags.

Cross-checked against the local 15m yfinance walk-forward: identical setup,
touch and exit results on every shared trade date (38/38), entry/exit price
diff = 0.000 pts (see outputs/vm5m_vs_local15m.csv). Validated for NIFTY
only; BANKNIFTY/INDIA_VIX lack the 50-pt strike calibration.

SELECT-only against market_candles_5m via get_conn (no writes). Shared by:
- POST /api/backtest/cpr-walkforward (date-range backtest)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app.core.db import get_conn

VALID = ('NIFTY',)

STRIKE_STEP = 50
SPREAD_WIDTH = 100

_IST_BUCKET15 = pd.Timestamp("09:45").time()
_IST_BUCKET1515 = pd.Timestamp("15:15").time()


@dataclass(frozen=True)
class Config:
    lookback_days: int = 20
    narrow_q: float = 0.25
    wide_q: float = 0.75
    large_gap_q: float = 0.70
    small_gap_q: float = 0.35
    a_cushion_pct: float = 0.0025
    b_cushion_pct: float = 0.0035
    neutral_cushion_pct: float = 0.0045
    a_credit_pts: float = 25.0
    b_credit_pts: float = 18.0
    iron_condor_credit_pts: float = 30.0


def _round_down(value):
    return int(math.floor(value / STRIKE_STEP) * STRIKE_STEP)


def _round_up(value):
    return int(math.ceil(value / STRIKE_STEP) * STRIKE_STEP)


def _clean(value):
    """Pandas/NaN/NA -> None-safe Python scalar for JSON serialization."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _load_candles(instrument):
    conn = get_conn()
    try:
        rows = conn.execute(
            'SELECT timestamp, open, high, low, close FROM market_candles_5m '
            'WHERE instrument_id=? ORDER BY timestamp',
            (instrument,)).fetchall()
    finally:
        conn.close()
    frame = pd.DataFrame([dict(r) for r in rows])
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.set_index("timestamp")
    frame.columns = [c.lower() for c in frame.columns]
    return frame


def _intraday_feature_rows(candles):
    """Per-session 5m stats + per-session daily OHLC/CPR derived from 5m runs."""
    sessions = []
    daily_rows = []
    for date, bars in candles.groupby(candles.index.date, sort=True):
        session = bars.between_time("09:15", "15:30")
        if len(session) < 10:
            continue
        first30 = session[session.index.time < _IST_BUCKET15]
        post_entry = session[(session.index.time >= _IST_BUCKET15)
                             & (session.index.time < _IST_BUCKET1515)]
        exit_candidates = session[session.index.time >= _IST_BUCKET1515]
        if len(exit_candidates):
            exit_price = float(exit_candidates["open"].iloc[0])
        else:
            exit_price = float(session[session.index.time < _IST_BUCKET1515]["close"].iloc[-1])
        sessions.append({
            "date": pd.Timestamp(date),
            "entry_time_ist": "09:45",
            "exit_time_ist": "15:15",
            "open": float(session["open"].iloc[0]),
            "high": float(session["high"].max()),
            "low": float(session["low"].min()),
            "close": float(session["close"].iloc[-1]),
            "first30_open": float(first30["open"].iloc[0]),
            "first30_high": float(first30["high"].max()),
            "first30_low": float(first30["low"].min()),
            "first30_close": float(first30["close"].iloc[-1]),
            "entry_price": float(first30["close"].iloc[-1]),
            "exit_price": exit_price,
            "post_entry_high": float(post_entry["high"].max()),
            "post_entry_low": float(post_entry["low"].min()),
        })
        daily_rows.append({"date": pd.Timestamp(date), "open": float(session["open"].iloc[0]),
                           "high": float(session["high"].max()),
                           "low": float(session["low"].min()),
                           "close": float(session["close"].iloc[-1])})

    session_df = pd.DataFrame(sessions).sort_values("date").reset_index(drop=True)
    daily = pd.DataFrame(daily_rows).sort_values("date").reset_index(drop=True)
    daily["prev_high"] = daily["high"].shift(1)
    daily["prev_low"] = daily["low"].shift(1)
    daily["prev_close"] = daily["close"].shift(1)
    daily["pivot"] = (daily["prev_high"] + daily["prev_low"] + daily["prev_close"]) / 3
    bc_raw = (daily["prev_high"] + daily["prev_low"]) / 2
    tc_raw = 2 * daily["pivot"] - bc_raw
    daily["bc"] = pd.concat([bc_raw, tc_raw], axis=1).min(axis=1)
    daily["tc"] = pd.concat([bc_raw, tc_raw], axis=1).max(axis=1)
    daily["cpr_width_pct"] = (daily["tc"] - daily["bc"]) / daily["prev_close"]
    keep = ["date", "prev_high", "prev_low", "prev_close", "pivot", "bc", "tc", "cpr_width_pct"]
    merged = session_df.merge(daily[keep], on="date", how="left")
    merged["gap_pct"] = (merged["open"] - merged["prev_close"]) / merged["prev_close"]
    merged["first30_return_pct"] = (
        (merged["first30_close"] - merged["first30_open"]) / merged["first30_open"]
    )
    merged["day_range_pct"] = (merged["high"] - merged["low"]) / merged["prev_close"]
    return merged.dropna(subset=["prev_close", "bc", "tc", "gap_pct"]).reset_index(drop=True)


def _choose_trade(row, cpr_class, gap_class, cfg):
    above_cpr = row["first30_close"] > row["tc"]
    below_cpr = row["first30_close"] < row["bc"]
    inside_cpr = row["bc"] <= row["first30_close"] <= row["tc"]
    first30_green = row["first30_close"] >= row["first30_open"]
    first30_red = row["first30_close"] <= row["first30_open"]
    large_gap_go_up = (gap_class == "gap_up" and row["open"] > row["tc"]
                       and row["first30_low"] > row["tc"] and first30_green)
    large_gap_go_down = (gap_class == "gap_down" and row["open"] < row["bc"]
                         and row["first30_high"] < row["bc"] and first30_red)

    if cpr_class != "wide" and large_gap_go_up:
        reference = min(row["first30_low"], row["tc"], row["prev_close"])
        short_put = _round_down(reference * (1 - cfg.a_cushion_pct))
        return {"setup": "A_BULL_PUT", "signal": "BULL_PUT_CREDIT_SPREAD",
                "direction": "BULL", "short_put": short_put,
                "long_put": short_put - SPREAD_WIDTH, "short_call": None,
                "long_call": None, "credit_pts": cfg.a_credit_pts,
                "reason": "A setup: large gap up held above TC for first 30m"}

    if cpr_class != "wide" and large_gap_go_down:
        reference = max(row["first30_high"], row["bc"], row["prev_close"])
        short_call = _round_up(reference * (1 + cfg.a_cushion_pct))
        return {"setup": "A_BEAR_CALL", "signal": "BEAR_CALL_CREDIT_SPREAD",
                "direction": "BEAR", "short_put": None, "long_put": None,
                "short_call": short_call, "long_call": short_call + SPREAD_WIDTH,
                "credit_pts": cfg.a_credit_pts,
                "reason": "A setup: large gap down held below BC for first 30m"}

    if above_cpr and first30_green:
        reference = min(row["first30_low"], row["tc"])
        short_put = _round_down(reference * (1 - cfg.b_cushion_pct))
        return {"setup": "B_BULL_PUT", "signal": "BULL_PUT_CREDIT_SPREAD",
                "direction": "BULL", "short_put": short_put,
                "long_put": short_put - SPREAD_WIDTH, "short_call": None,
                "long_call": None, "credit_pts": cfg.b_credit_pts,
                "reason": "B setup: price above CPR with positive first 30m"}

    if below_cpr and first30_red:
        reference = max(row["first30_high"], row["bc"])
        short_call = _round_up(reference * (1 + cfg.b_cushion_pct))
        return {"setup": "B_BEAR_CALL", "signal": "BEAR_CALL_CREDIT_SPREAD",
                "direction": "BEAR", "short_put": None, "long_put": None,
                "short_call": short_call, "long_call": short_call + SPREAD_WIDTH,
                "credit_pts": cfg.b_credit_pts,
                "reason": "B setup: price below CPR with negative first 30m"}

    put_reference = min(row["first30_low"], row["prev_low"], row["bc"])
    call_reference = max(row["first30_high"], row["prev_high"], row["tc"])
    short_put = _round_down(put_reference * (1 - cfg.neutral_cushion_pct))
    short_call = _round_up(call_reference * (1 + cfg.neutral_cushion_pct))
    neutral_label = "C_NEUTRAL_IC"
    reason = "C setup: mixed CPR/gap structure, default to wider iron condor"
    if inside_cpr:
        neutral_label = "C_INSIDE_CPR_IC"
        reason = "C setup: first 30m closed inside CPR, wider iron condor"
    elif cpr_class == "wide":
        neutral_label = "C_WIDE_CPR_IC"
        reason = "C setup: wide CPR, reduced conviction wider iron condor"

    return {"setup": neutral_label, "signal": "IRON_CONDOR", "direction": "NEUTRAL",
            "short_put": short_put, "long_put": short_put - SPREAD_WIDTH,
            "short_call": short_call, "long_call": short_call + SPREAD_WIDTH,
            "credit_pts": cfg.iron_condor_credit_pts, "reason": reason}


def _make_trades(features, cfg):
    """Walk-forward decisions over trailing lookback_days; no forward leakage."""
    rows = []
    for idx, row in features.iterrows():
        prior = features.iloc[:idx].tail(cfg.lookback_days)
        out = row.to_dict()
        if len(prior) < cfg.lookback_days:
            out.update({"setup": "WARMUP", "signal": "NO_TRADE", "direction": None,
                        "reason": "need more walk-forward history",
                        "cpr_class": "insufficient", "gap_class": "insufficient",
                        "short_put": None, "long_put": None, "short_call": None,
                        "long_call": None, "credit_pts": 0.0, "win": None,
                        "exit_price_win": None, "points_pnl": 0.0})
            rows.append(out)
            continue

        narrow_cut = prior["cpr_width_pct"].quantile(cfg.narrow_q)
        wide_cut = prior["cpr_width_pct"].quantile(cfg.wide_q)
        large_gap = prior["gap_pct"].abs().quantile(cfg.large_gap_q)
        small_gap = prior["gap_pct"].abs().quantile(cfg.small_gap_q)

        if row["cpr_width_pct"] <= narrow_cut:
            cpr_class = "narrow"
        elif row["cpr_width_pct"] >= wide_cut:
            cpr_class = "wide"
        else:
            cpr_class = "normal"

        if row["gap_pct"] >= large_gap:
            gap_class = "gap_up"
        elif row["gap_pct"] <= -large_gap:
            gap_class = "gap_down"
        elif abs(row["gap_pct"]) <= small_gap:
            gap_class = "flat"
        elif row["gap_pct"] > 0:
            gap_class = "small_gap_up"
        else:
            gap_class = "small_gap_down"

        trade = _choose_trade(row, cpr_class, gap_class, cfg)
        signal = trade["signal"]
        put_touched = None
        call_touched = None
        if signal in {"BULL_PUT_CREDIT_SPREAD", "IRON_CONDOR"}:
            put_touched = bool(row["post_entry_low"] <= trade["short_put"])
        if signal in {"BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}:
            call_touched = bool(row["post_entry_high"] >= trade["short_call"])

        touched_count = int(put_touched is True) + int(call_touched is True)
        win = touched_count == 0
        direction = trade.get("direction")
        if direction == "BULL":
            points_pnl = row["exit_price"] - row["entry_price"]
        elif direction == "BEAR":
            points_pnl = row["entry_price"] - row["exit_price"]
        else:
            points_pnl = -abs(row["exit_price"] - row["entry_price"])

        if signal == "BULL_PUT_CREDIT_SPREAD":
            buffer_pct = (row["entry_price"] - trade["short_put"]) / row["entry_price"]
            exit_price_win = bool(row["exit_price"] > trade["short_put"])
        elif signal == "BEAR_CALL_CREDIT_SPREAD":
            buffer_pct = (trade["short_call"] - row["entry_price"]) / row["entry_price"]
            exit_price_win = bool(row["exit_price"] < trade["short_call"])
        else:
            put_buffer = (row["entry_price"] - trade["short_put"]) / row["entry_price"]
            call_buffer = (trade["short_call"] - row["entry_price"]) / row["entry_price"]
            buffer_pct = min(put_buffer, call_buffer)
            exit_price_win = bool(trade["short_put"] < row["exit_price"] < trade["short_call"])

        out.update(trade)
        out.update({"cpr_class": cpr_class, "gap_class": gap_class,
                    "put_touched": put_touched, "call_touched": call_touched,
                    "touched_count": touched_count, "win": win,
                    "exit_price_win": exit_price_win, "points_pnl": points_pnl,
                    "buffer_pct": buffer_pct})
        rows.append(out)
    return rows


def _trade_dicts(trades):
    """JSON-safe per-trade records matching the exports used for validation."""
    clean = []
    for t in trades:
        clean.append({
            "trade_date": _clean(t["date"]),
            "setup": t["setup"], "signal": t["signal"], "direction": t.get("direction"),
            "cpr_class": t["cpr_class"], "gap_class": t["gap_class"],
            "entry_time": t.get("entry_time_ist", "09:45"),
            "exit_time": t.get("exit_time_ist", "15:15"),
            "entry_price": _clean(t["entry_price"]),
            "exit_price": _clean(t["exit_price"]),
            "short_put": _clean(t.get("short_put")), "long_put": _clean(t.get("long_put")),
            "short_call": _clean(t.get("short_call")), "long_call": _clean(t.get("long_call")),
            "put_touched": t.get("put_touched"), "call_touched": t.get("call_touched"),
            "touched_count": t.get("touched_count"), "win": t.get("win"),
            "exit_price_win": t.get("exit_price_win"), "points_pnl": _clean(t.get("points_pnl")),
            "buffer_pct": _clean(t.get("buffer_pct")), "reason": t.get("reason"),
        })
    return clean


def _by_setup(trades):
    rows = []
    for setup in sorted({t["setup"] for t in trades}):
        group = [t for t in trades if t["setup"] == setup]
        wins = sum(1 for t in group if t["win"])
        ev = sum(1 for t in group if t["exit_price_win"])
        rows.append({
            "setup": setup, "signal": group[0]["signal"],
            "trades": len(group),
            "wins": int(wins), "win_rate": round(100 * wins / len(group), 1),
            "exit_price_wins": int(ev),
            "exit_price_win_rate": round(100 * ev / len(group), 1),
            "total_points": round(sum(t["points_pnl"] for t in group), 1),
        })
    if rows:
        rows.append({
            "setup": "ALL", "signal": "ALL",
            "trades": len(trades),
            "wins": int(sum(1 for t in trades if t["win"])),
            "win_rate": round(100 * sum(1 for t in trades if t["win"]) / len(trades), 1),
            "exit_price_wins": int(sum(1 for t in trades if t["exit_price_win"])),
            "exit_price_win_rate": round(
                100 * sum(1 for t in trades if t["exit_price_win"]) / len(trades), 1),
            "total_points": round(sum(t["points_pnl"] for t in trades), 1),
        })
    return rows


def run_walkforward(instrument, date_start='', date_end=''):
    """Walk-forward backtest over stored 5m sessions in [start, end] (read-only).

    Features are computed over the full stored history so trailing-window
    percentiles are identical to the validated full-range run; only sessions
    inside [date_start, date_end] are reported. Empty bounds = full range.
    """
    inst = (instrument or '').upper()
    if inst not in VALID:
        return {'error': 'UNKNOWN_INSTRUMENT'}

    candles = _load_candles(inst)
    if candles.empty:
        return {'error': 'NO_DATA'}

    features = _intraday_feature_rows(candles)
    cfg = Config()
    trades = _make_trades(features, cfg)

    first = features["date"].min().date().isoformat()
    last = features["date"].max().date().isoformat()
    d0 = date_start or first
    d1 = date_end or last

    in_range = [t for t in trades if d0 <= t["date"].date().isoformat() <= d1]
    tradable = [t for t in in_range if t["signal"] != "NO_TRADE"]
    wins = sum(1 for t in tradable if t["win"])
    ev_wins = sum(1 for t in tradable if t["exit_price_win"])

    return {
        'instrument': inst,
        'date_start': d0,
        'date_end': d1,
        'sessions': len(features),
        'warmup_days': sum(1 for t in in_range if t["signal"] == "NO_TRADE"),
        'days': len(tradable),
        'signals': len(tradable),
        'no_signal_days': 0,
        'wins': int(wins),
        'losses': len(tradable) - wins,
        'win_rate': round(100 * wins / len(tradable), 1) if tradable else 0,
        'exit_price_wins': int(ev_wins),
        'exit_price_losses': len(tradable) - ev_wins,
        'exit_price_win_rate': round(100 * ev_wins / len(tradable), 1) if tradable else 0,
        'total_points': round(sum(t["points_pnl"] for t in tradable), 1),
        'avg_points': round(sum(t["points_pnl"] for t in tradable) / len(tradable), 2) if tradable else 0,
        'by_setup': _by_setup(tradable) if tradable else [],
        'trades': _trade_dicts(in_range),
    }