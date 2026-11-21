#!/usr/bin/env python3
"""Historical 5-minute replay of all eight paper-only scanners.

IMPORTANT LIMITATION
--------------------
mStock supplies per-instrument 5-minute OHLCV history, not historical 5-second
quote snapshots.  The live scanners enter and exit on sampled quote LTP; the
HIGH scanners use LTP > previous high as an entry predicate; trail/stop state
ratchets on every poll.  An exact replay of the live 5-second paper behaviour
is therefore impossible from this data alone.

This harness is an explicitly labelled 5-minute rule simulation.  It imports
the real strategy engines and reuses their evaluate/trail/stop/close code.
Fill and ATM proxies are conservative and documented in the output report:

  * entry fill = signal candle open
  * exit fill  = adverse 5m bar extreme when a stop/trail is hit
  * ATM strike inferred from CE/PE parity, anchored by NIFTY futures
  * spot OHLC for regime/pattern logic reconstructed from CE/PE parity

No broker order API is used.  Results are points only; no lot size, capital,
target, or brokerage is invented.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("BROKER_GATEWAY_SCANNER", "api")

IST_OFFSET = timedelta(hours=5, minutes=30)
ENTRY_START = time(9, 20)
ENTRY_END = time(15, 15)
MARKET_CLOSE = time(15, 30)
FIRST_CANDLE_START = time(9, 15)
STRIKE_STEP = 50.0


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif hasattr(value, "isoformat"):
        dt = datetime.fromisoformat(str(value))
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST_OFFSET)
    return dt


def iso(value: datetime | date | Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def floor_5m(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def round_to_strike(value: float, step: float = STRIKE_STEP) -> float:
    return float(math.floor(float(value) / step + 0.5) * step)


def normalize_bars(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in raw or []:
        start_raw = row.get("start", row.get("date"))
        if start_raw is None:
            continue
        out.append({
            "start": parse_dt(start_raw),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row.get("volume") or 0),
        })
    out.sort(key=lambda r: r["start"])
    return out


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compare_expiry(value: Any) -> date:
    dt = parse_dt(value) if not isinstance(value, date) else value
    return dt.date() if isinstance(dt, datetime) else dt


def expiry_text(value: Any) -> str:
    d = compare_expiry(value)
    return d.isoformat()


def in_entry_window(ts: datetime) -> bool:
    return ENTRY_START <= ts.time() < ENTRY_END


# ---------------------------------------------------------------------------
# Data access (gateway only; broker-agnostic at the scanner boundary)
# ---------------------------------------------------------------------------
class HistoryFetcher:
    def __init__(self, kite, cache_dir: Path):
        self.kite = kite
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, token: int, start: datetime, end: datetime) -> list[dict]:
        key = f"{int(token)}_{start.strftime('%Y%m%dT%H%M')}_{end.strftime('%Y%m%dT%H%M')}_5minute.json"
        path = self.cache_dir / key
        if path.exists():
            return normalize_bars(json.loads(path.read_text()))
        raw = self.kite.historical_data(int(token), start, end, "5minute")
        bars = normalize_bars(raw)
        path.write_text(json.dumps(bars, default=iso))
        return bars


def fetch_instruments(kite) -> list[dict]:
    return kite.instruments("NFO") or []


def pick_futures(instruments: list[dict], session_start: date) -> dict:
    futures = [
        r for r in instruments
        if str(r.get("name", "")).upper() == "NIFTY"
        and str(r.get("instrument_type", "")).upper() == "XX"
        and float(r.get("strike") or 0) == 0
        and r.get("expiry")
        and compare_expiry(r["expiry"]) >= session_start
    ]
    if not futures:
        raise RuntimeError("no NIFTY futures instrument found for backtest window")
    futures.sort(key=lambda r: (compare_expiry(r["expiry"]), int(r["instrument_token"])))
    return futures[0]


def option_universe(instruments: list[dict], start: date, lo: float, hi: float) -> dict:
    """Map (expiry, strike, option_type) -> instrument row."""
    rows: dict[tuple[str, float, str], dict] = {}
    for r in instruments:
        otype = str(r.get("instrument_type", "")).upper()
        if otype not in ("CE", "PE") or not r.get("expiry"):
            continue
        if str(r.get("name", "")).upper() != "NIFTY":
            continue
        if compare_expiry(r["expiry"]) < start:
            continue
        strike = float(r.get("strike") or 0)
        if not (lo <= strike <= hi):
            continue
        rows[(expiry_text(r["expiry"]), strike, otype)] = r
    return rows


# ---------------------------------------------------------------------------
# Parity-derived spot and ATM
# ---------------------------------------------------------------------------
def build_parity_series(option_series, futures_bars, universe):
    """Return (atm_by_ts, spot_bars, ce_pe_index).

    For each 5m timestamp, use the NIFTY futures close to anchor the strike
    search.  CE - PE + K approximates the underlying forward at that strike.
    The chosen strike is the one whose implied forward is closest to futures.
    Spot OHLC is reconstructed with parity-friendly extremes:
      high ~= K + CE.high - PE.low, low ~= K + CE.low - PE.high.
    """
    fut_index = {b["start"]: b for b in futures_bars}
    expiries = sorted({k[0] for k in option_series})
    strikes = sorted({k[1] for k in option_series})

    atm_by_ts: dict[datetime, float] = {}
    spot_by_ts: dict[datetime, dict] = {}
    ce_pe_index: dict[datetime, tuple[str, float]] = {}

    for ts, fut_bar in sorted(fut_index.items()):
        # Live scanners pick the nearest NIFTY expiry that has not expired.
        eligible_expiries = [e for e in expiries
                             if datetime.fromisoformat(e).date() >= ts.date()]
        if not eligible_expiries:
            continue
        nearest_expiry = min(eligible_expiries)

        best: tuple[float, str, float, dict, dict] | None = None
        for exp in (nearest_expiry,):
            for strike in strikes:
                ce = option_series.get((exp, strike, "CE", ts))
                pe = option_series.get((exp, strike, "PE", ts))
                if not ce or not pe:
                    continue
                if ce["close"] <= 0 and pe["close"] <= 0:
                    continue
                forward = strike + ce["close"] - pe["close"]
                score = abs(forward - fut_bar["close"])
                if best is None or score < best[0]:
                    best = (score, exp, forward, ce, pe)
        if best is None:
            continue

        _, exp, forward, ce, pe = best
        atm = round_to_strike(forward)
        if (exp, atm, "CE") not in universe or (exp, atm, "PE") not in universe:
            available = [s for s in strikes if (exp, s, "CE") in universe and (exp, s, "PE") in universe]
            if not available:
                continue
            atm = min(available, key=lambda s: abs(s - atm))

        ce_bar = option_series.get((exp, atm, "CE", ts)) or ce
        pe_bar = option_series.get((exp, atm, "PE", ts)) or pe
        spot_open = atm + ce_bar["open"] - pe_bar["open"]
        spot_close = atm + ce_bar["close"] - pe_bar["close"]
        spot_high = atm + ce_bar["high"] - pe_bar["low"]
        spot_low = atm + ce_bar["low"] - pe_bar["high"]
        spot_high = max(spot_high, spot_open, spot_close)
        spot_low = min(spot_low, spot_open, spot_close)

        atm_by_ts[ts] = float(atm)
        ce_pe_index[ts] = (exp, float(atm))
        spot_by_ts[ts] = {
            "start": ts,
            "timestamp": ts.isoformat(),
            "session_date": ts.date().isoformat(),
            "open": round(spot_open, 2),
            "high": round(spot_high, 2),
            "low": round(spot_low, 2),
            "close": round(spot_close, 2),
            "volume": int(fut_bar.get("volume") or 0),
        }
    return atm_by_ts, spot_by_ts, ce_pe_index


# ---------------------------------------------------------------------------
# Regime gate for sma9_atr (mirrors live compute_spot_regime)
# ---------------------------------------------------------------------------
def ema_values(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    out = [sum(values[:period]) / period]
    k = 2.0 / (period + 1.0)
    for value in values[period:]:
        out.append(float(value) * k + out[-1] * (1.0 - k))
    return out


def spot_regime(spot_bars: list[dict], now: datetime, period: int = 9) -> str | None:
    completed = [r for r in spot_bars if r["start"] < floor_5m(now)]
    session = [r for r in completed if r["start"].date() == now.date()]
    if not session or len(completed) < period + 1:
        return None
    closes = [float(r["close"]) for r in completed]
    emas = ema_values(closes, period)
    if len(emas) < 2:
        return None
    price, ema_now, ema_prev = closes[-1], emas[-1], emas[-2]
    session_closes = [float(r["close"]) for r in session]
    volumes = [float(r.get("volume") or 0) for r in session]
    if sum(volumes) > 0:
        vwap = sum(c * v for c, v in zip(session_closes, volumes)) / sum(volumes)
    else:
        vwap = sum((r["high"] + r["low"] + r["close"]) / 3.0 for r in session) / len(session)
    if price > vwap and price > ema_now and ema_now > ema_prev:
        return "CE"
    if price < vwap and price < ema_now and ema_now < ema_prev:
        return "PE"
    return None


# ---------------------------------------------------------------------------
# Premium scanner replay
# ---------------------------------------------------------------------------
SCANNER_SPECS = [
    {"key": "sma9", "path": "sma9_scanner/app/sma9_engine.py", "family": "sma", "atr": False, "regime": False},
    {"key": "sma9_high", "path": "sma9_high_scanner/app/sma9_high_engine.py", "family": "high", "atr": False, "regime": False},
    {"key": "sma9_trail", "path": "sma9_trail_scanner/app/sma9_trail_engine.py", "family": "fixed_trail", "atr": False, "regime": False},
    {"key": "sma9_high_trail", "path": "sma9_high_trail_scanner/app/sma9_high_trail_engine.py", "family": "high_fixed_trail", "atr": False, "regime": False},
    {"key": "sma9_atr", "path": "sma9_atr_scanner/app/sma9_atr_engine.py", "family": "atr", "atr": True, "regime": True},
    {"key": "sma9_5s_atr", "path": "sma9_5s_atr_scanner/app/sma9_5s_atr_engine.py", "family": "atr", "atr": True, "regime": False},
    {"key": "sma9_1min_poll", "path": "sma9_1min_poll_scanner/app/sma9_1min_poll_engine.py", "family": "atr", "atr": True, "regime": False},
]


def exit_premium_position(sm, bar: dict, is_atr: bool) -> dict | None:
    """Conservative OHLC stop/trail processing for one open premium position."""
    low, high = bar["low"], bar["high"]
    candidates: list[tuple[float, str]] = []

    sl = sm.check_stop_loss(low)
    if sl is not None:
        candidates.append((float(sl), "STOP_LOSS_ATR" if is_atr else "STOP_LOSS_5PCT"))

    trail = sm.update_trail(high)
    if trail is not None:
        candidates.append((float(trail), "TRAIL_STOP_EXIT"))
    trail = sm.update_trail(low)
    if trail is not None:
        candidates.append((float(trail), "TRAIL_STOP_EXIT"))

    if not candidates:
        return None
    exit_px, reason = min(candidates, key=lambda item: item[0])
    end = bar["start"] + timedelta(minutes=5)
    return sm.close(end, exit_px, reason, candle_high=high, candle_low=low)


def replay_premium_scanner(spec, root: Path, universe, series, timestamps,
                           atm_by_ts, spot_by_ts, ce_pe_index, end_ts) -> list[dict]:
    module = load_module(root / spec["path"], f"bt_{spec['key']}")
    trades: list[dict] = []
    machines = {otype: module.OptionStateMachine(otype) for otype in ("CE", "PE")}
    spot_sequence: list[dict] = []

    for ts in timestamps:
        if ts in spot_by_ts:
            spot_sequence.append(spot_by_ts[ts])
        exp, atm = ce_pe_index.get(ts, ("", 0.0))
        if not exp or atm <= 0:
            continue

        for otype in ("CE", "PE"):
            sm = machines[otype]
            key = (exp, atm, otype)
            instrument = universe.get(key)
            if not instrument:
                continue
            bars = series.get((key[0], key[1], key[2]), [])
            history = [b for b in bars if b["start"] <= ts]
            if not history or history[-1]["start"] != ts:
                continue

            if sm.position is not None:
                trade = exit_premium_position(sm, history[-1], bool(spec["atr"]))
                if trade:
                    trade["scanner"] = spec["key"]
                    trades.append(trade)
                continue

            if not in_entry_window(ts):
                continue

            if spec["regime"]:
                allowed = spot_regime(spot_sequence, ts)
                if allowed != otype:
                    continue

            ev = module.evaluate_option(history, otype, ltp=history[-1]["open"])
            market_close = ts.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute,
                                      second=0, microsecond=0)
            kwargs = {}
            if spec["atr"]:
                kwargs["atr"] = module.premium_atr(history)
            sm.try_entry(
                ev, ts, atm, exp,
                int(instrument["instrument_token"]),
                str(instrument["tradingsymbol"]),
                market_close, **kwargs,
            )

    for otype, sm in machines.items():
        if sm.position is None:
            continue
        key = (sm.position.expiry, sm.position.strike, otype)
        bars = series.get(key, [])
        last = bars[-1] if bars else None
        if last is None:
            continue
        trade = sm.close(last["start"] + timedelta(minutes=5), last["close"],
                         "BACKTEST_END", candle_high=last["high"], candle_low=last["low"])
        if trade:
            trade["scanner"] = spec["key"]
            trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Pattern scanner replay
# ---------------------------------------------------------------------------
def pattern_atr_list(candles: list[dict]) -> list[float | None]:
    if len(candles) < 2:
        return [None] * len(candles)
    trs = []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    period = 14
    atrs: list[float | None] = [None]
    for i in range(len(trs)):
        if i < period - 1:
            atrs.append(None)
        elif i == period - 1:
            atrs.append(sum(trs[:period]) / period)
        else:
            prev_atr = atrs[-1] or (sum(trs[-period:]) / period)
            atrs.append((prev_atr * (period - 1) + trs[i]) / period)
    return atrs


def replay_pattern_scanner(root: Path, universe, series, spot_by_ts,
                           ce_pe_index, timestamps, end_ts) -> list[dict]:
    module = load_module(root / "app/research/pattern_scanner.py", "bt_pattern_engine")
    positions: dict[str, Any] = {}
    position_keys: dict[str, tuple[str, float, str]] = {}
    trades: list[dict] = []
    spot_sequence: list[dict] = []

    for ts in timestamps:
        spot = spot_by_ts.get(ts)
        if not spot:
            continue
        spot_sequence.append(spot)
        atrs = pattern_atr_list(spot_sequence)
        atr = atrs[-1]

        if ts.time() < module.NO_NEW_ENTRY_AFTER:
            try:
                results = (module.detect_bullish_patterns(spot_sequence, len(spot_sequence) - 1, atr)
                           + module.detect_bearish_patterns(spot_sequence, len(spot_sequence) - 1, atr))
            except Exception as exc:  # detector failures are reported, never fatal
                print(f"[pattern] detector error at {ts.isoformat()}: {exc}", file=sys.stderr)
                results = []
            for res in results or []:
                direction = res.get("direction")
                if direction not in ("BULLISH", "BEARISH"):
                    continue
                otype = "CE" if direction == "BULLISH" else "PE"
                # Use the same parity-derived expiry/ATM pair as premium replay.
                exp, atm = ce_pe_index.get(ts, ("", 0.0))
                key = (exp, atm, otype)
                if key not in universe:
                    candidates = [k for k in universe if k[0] == exp and k[2] == otype]
                    if not candidates:
                        continue
                    key = min(candidates, key=lambda k: abs(k[1] - atm))
                instrument = universe[key]
                option_bars = [b for b in series.get(key, []) if b["start"] <= ts]
                if not option_bars or option_bars[-1]["start"] != ts:
                    continue
                entry_px = option_bars[-1]["open"]
                symbol = str(instrument["tradingsymbol"])
                pattern = res.get("pattern_name", "unknown")
                pos_key = f"{pattern}:{symbol}"
                if pos_key in positions:
                    continue
                option_atr = module.premium_atr(option_bars)
                positions[pos_key] = module.OptionPosition(
                    trade_id=f"BT-PAT-{ts.strftime('%Y%m%d%H%M')}-{symbol}",
                    pattern_name=pattern,
                    instrument=symbol,
                    direction=direction,
                    entry_price=float(entry_px),
                    entry_spot=float(spot["close"]),
                    entry_ts=ts.isoformat(),
                    session_date=spot["start"].date().isoformat(),
                    atr=option_atr,
                )
                position_keys[pos_key] = key

        for pos_key, pos in list(positions.items()):
            if pos.entry_ts and parse_dt(pos.entry_ts) >= ts:
                continue  # never apply an entry bar's own extreme as a lookahead exit
            key = position_keys.get(pos_key)
            bars = [b for b in series.get(key, []) if b["start"] <= ts] if key else []
            if not bars or bars[-1]["start"] != ts:
                continue
            opt = bars[-1]
            bar_end = (opt["start"] + timedelta(minutes=5)).isoformat()
            pos.update_mfe_mae(opt["high"], opt["low"])

            # Conservative 5m premium-exit proxy: ratchet the ATR trail on the
            # bar high, then check both the ratcheted trail and the initial
            # ATR stop against the bar low. Fill at the adverse extreme.
            trail_hit = pos.update_trail(opt["high"], ts.isoformat())
            if trail_hit is None and pos.hwm > pos.entry_price \
                    and opt["low"] <= pos.stop_loss:
                trail_hit = round(pos.stop_loss, 2)
            sl_hit = pos.check_stop_loss(opt["low"])

            candidates: list[tuple[float, str]] = []
            if trail_hit is not None:
                candidates.append((float(trail_hit), "TRAIL_STOP_EXIT"))
            if sl_hit is not None:
                candidates.append((float(sl_hit), "STOP_LOSS_ATR"))
            if not candidates:
                continue
            exit_px, reason = min(candidates, key=lambda item: item[0])
            pos.close(reason, bar_end, exit_price=exit_px)
            trades.append(_pattern_trade(pos, "pattern_scanner", key))
            del positions[pos_key]

    for pos_key, pos in list(positions.items()):
        key = position_keys.get(pos_key)
        bars = series.get(key, []) if key else []
        if not bars:
            continue
        pos.close("BACKTEST_END", bars[-1]["start"].isoformat(), exit_price=bars[-1]["close"])
        trades.append(_pattern_trade(pos, "pattern_scanner", key))
    return trades


def _pattern_trade(pos, scanner: str, key) -> dict:
    return {
        "scanner": scanner,
        "trade_id": getattr(pos, "trade_id", ""),
        "strategy_id": "pattern_scanner",
        "instrument": getattr(pos, "instrument", ""),
        "option_type": "CE" if getattr(pos, "direction", "BULLISH") == "BULLISH" else "PE",
        "strike": key[1] if key else 0,
        "expiry": key[0] if key else "",
        "signal_timestamp": getattr(pos, "entry_ts", ""),
        "entry_timestamp": getattr(pos, "entry_ts", ""),
        "entry_price": round(float(getattr(pos, "entry_price", 0)), 2),
        "exit_timestamp": getattr(pos, "exit_ts", ""),
        "exit_price": round(float(getattr(pos, "exit_price", 0)), 2),
        "exit_reason": getattr(pos, "exit_reason", ""),
        "atr_at_entry": getattr(pos, "atr_at_entry", None),
        "stop_price": getattr(pos, "stop_price", None),
        "trail_distance": getattr(pos, "trail_distance", None),
        "stop_distance_pct": getattr(pos, "stop_distance_pct", None),
        "stop_source": getattr(pos, "stop_source", None),
        "pnl_points": round(float(getattr(pos, "pnl_points", 0)), 2),
        "status": getattr(pos, "status", "CLOSED"),
        "direction": getattr(pos, "direction", ""),
        "pattern_name": getattr(pos, "pattern_name", ""),
        "dataset": "BACKTEST_5M_PARITY",
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def summarize(scanner: str, trades: list[dict]) -> dict:
    pnls = [float(t.get("pnl_points") or 0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    total = round(sum(pnls), 2)
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
    reasons: dict[str, int] = defaultdict(int)
    for t in trades:
        reasons[str(t.get("exit_reason") or "UNKNOWN")] += 1
    return {
        "scanner": scanner,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "flat": len(trades) - wins - losses,
        "win_rate_pct": round(100.0 * wins / len(trades), 2) if trades else 0.0,
        "total_points": total,
        "avg_points": round(total / len(trades), 2) if trades else 0.0,
        "best_trade_points": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade_points": round(min(pnls), 2) if pnls else 0.0,
        "max_drawdown_points": round(max_dd, 2),
        "exit_reasons": dict(sorted(reasons.items())),
    }


def write_outputs(out_dir: Path, summaries: list[dict], all_trades: list[dict],
                  meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps({
        "meta": meta,
        "scanners": summaries,
    }, indent=2, default=iso))

    fields = sorted({k for t in all_trades for k in t.keys()})
    with (out_dir / "trades.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for trade in sorted(all_trades, key=lambda t: (t.get("scanner", ""), str(t.get("exit_timestamp", "")))):
            writer.writerow({k: trade.get(k, "") for k in fields})

    lines = [
        "# Historical scanner backtest (5m rule simulation)",
        "",
        "> **Not an exact 5-second paper replay.** mStock supplies 5-minute OHLCV,",
        "> not historical 5-second quotes. Live entry/exit fills use sampled LTP;",
        "> this report uses the conservative proxies below.",
        "",
        "## Assumptions",
        "",
        f"- Window: `{meta['window']['start']}` to `{meta['window']['end']}`",
        "- Entry fill: signal candle open",
        "- Exit fill: adverse 5m extreme when a stop/trail is hit",
        "- ATM: CE/PE parity anchored by NIFTY futures, rounded to 50",
        "- Spot OHLC for regime/pattern: reconstructed from CE/PE parity",
        "- Pattern exits: premium ATR(14) only (0.70xATR, 5-30% clamp, 10% fallback)",
        "- PnL: premium points only; no lot size, capital, target, or brokerage",
        "- Broker: gateway identity `api` (mapped to mStock in this deployment)",
        "",
        "## Results",
        "",
        "| Scanner | Trades | Win % | Total pts | Avg pts | Max DD pts |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['scanner']} | {s['trades']} | {s['win_rate_pct']:.2f} | "
            f"{s['total_points']:.2f} | {s['avg_points']:.2f} | {s['max_drawdown_points']:.2f} |"
        )
    lines += ["", "## Exit reasons", ""]
    for s in summaries:
        lines.append(f"- {s['scanner']}: `{json.dumps(s['exit_reasons'], sort_keys=True)}`")
    lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/opt/tradingai", help="deployment root containing scanner apps")
    parser.add_argument("--start", default="2026-11-05", help="backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-11-20", help="backtest end date (YYYY-MM-DD)")
    parser.add_argument("--out", default="", help="output directory")
    parser.add_argument("--cache", default="/tmp/tradingai_backtest_cache", help="history cache directory")
    args = parser.parse_args()

    root = Path(args.root)
    start = datetime.fromisoformat(f"{args.start}T09:15:00+05:30")
    end = datetime.fromisoformat(f"{args.end}T15:30:00+05:30")
    out_dir = Path(args.out or f"/opt/tradingai/backtests/{args.start}_to_{args.end}")
    fetcher = HistoryFetcher(None, Path(args.cache))

    from kiteconnect import KiteConnect
    fetcher.kite = KiteConnect(api_key="gateway")

    instruments = fetch_instruments(fetcher.kite)
    fut = pick_futures(instruments, start.date())
    fut_bars = fetcher.fetch(int(fut["instrument_token"]), start, end)
    if not fut_bars:
        raise RuntimeError("no futures history in window")

    lo = math.floor((min(b["low"] for b in fut_bars) - 600) / STRIKE_STEP) * STRIKE_STEP
    hi = math.ceil((max(b["high"] for b in fut_bars) + 600) / STRIKE_STEP) * STRIKE_STEP
    quote = fetcher.kite.quote(["NSE:NIFTY 50"]) or {}
    spot_now = float(next(iter(quote.values())).get("last_price") or 0)
    if spot_now:
        lo = min(lo, round_to_strike(spot_now - 1000))
        hi = max(hi, round_to_strike(spot_now + 1000))

    universe = option_universe(instruments, start.date(), lo, hi)
    print(f"[fetch] futures={fut['tradingsymbol']} strikes={len({k[1] for k in universe})} "
          f"tokens={len(universe)} range={lo:.0f}-{hi:.0f}", file=sys.stderr)

    series: dict[tuple[str, float, str], list[dict]] = {}
    for key, row in universe.items():
        bars = fetcher.fetch(int(row["instrument_token"]), start, end)
        if bars:
            series[key] = bars
    if not series:
        raise RuntimeError("no option history fetched")

    option_index: dict[tuple[str, float, str, datetime], dict] = {}
    for key, bars in series.items():
        for bar in bars:
            option_index[(*key, bar["start"])] = bar

    atm_by_ts, spot_by_ts, ce_pe_index = build_parity_series(option_index, fut_bars, universe)
    timestamps = sorted(set(ce_pe_index))
    print(f"[fetch] option tokens with history={len(series)} aligned_timestamps={len(timestamps)}",
          file=sys.stderr)

    all_trades: list[dict] = []
    for spec in SCANNER_SPECS:
        trades = replay_premium_scanner(spec, root, universe, series, timestamps,
                                        atm_by_ts, spot_by_ts, ce_pe_index, timestamps[-1])
        all_trades.extend(trades)
    all_trades.extend(replay_pattern_scanner(root, universe, series, spot_by_ts,
                                             ce_pe_index, timestamps, timestamps[-1]))

    keys = [s["key"] for s in SCANNER_SPECS] + ["pattern_scanner"]
    summaries = [summarize(key, [t for t in all_trades if t.get("scanner") == key]) for key in keys]
    meta = {
        "fidelity": "5m_rule_simulation_not_exact_5s_replay",
        "window": {"start": args.start, "end": args.end},
        "broker_gateway_identity": os.environ.get("BROKER_GATEWAY_SCANNER"),
        "instrument": "NIFTY",
        "underlying_anchor": fut.get("tradingsymbol"),
        "strike_range": [lo, hi],
        "aligned_5m_timestamps": len(timestamps),
        "atm_source": "CE/PE parity anchored by NIFTY futures; rounded to 50",
        "fill_policy": "entry at signal candle open; exit at adverse 5m extreme on stop/trail",
        "pattern_exit_model": "premium_atr_14_only",
        "paper_only": True,
    }
    write_outputs(out_dir, summaries, all_trades, meta)
    print(json.dumps({"out": str(out_dir), "scanners": summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
