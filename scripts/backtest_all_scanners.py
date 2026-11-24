#!/usr/bin/env python3
"""Historical 5-minute replay of the nine paper-only scanners.

IMPORTANT LIMITATION
--------------------
mStock supplies per-instrument 5-minute OHLCV history, not historical 5-second
quote snapshots. The scanners enter and exit on sampled quote LTP (the HIGH
scanners use LTP > previous high as an entry predicate; trail/stop state
ratchets on every poll). An exact replay of that live quote-sampled paper
behaviour is therefore impossible from this data alone.

This harness is an explicitly labelled 5-minute rule simulation. It imports
the real strategy engines and reuses their evaluate/trail/stop/close code.
Fill and ATM rules are documented in the output report:

  * exit fill  = adverse 5m bar low for the ATR stop, or the ratcheted stop
                 level when a trail is hit
  * ATM strike = nearest 50 to the completed NIFTY 50 index close (token 26000)
  * spot OHLC for regime logic = real NIFTY 50 index 5m bars (token 26000)

No futures anchor or CE/PE parity is used for underlying spot or ATM selection.

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
NIFTY_INDEX_TOKEN = 26000  # NSE index token used by the live scanners


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
# Real NIFTY index spot and ATM
# ---------------------------------------------------------------------------
def build_index_spot_series(index_bars, option_series, universe):
    """Return (atm_by_ts, spot_bars, ce_pe_index) from real index 5m bars.

    The NIFTY 50 index close is authoritative for both spot OHLC and ATM
    selection. No futures anchor or CE/PE parity is used: the ATM is simply the
    nearest listed 50-point strike to each completed index bar's close.
    """
    index_index = {b["start"]: b for b in index_bars}
    expiries = sorted({k[0] for k in option_series})

    atm_by_ts: dict[datetime, float] = {}
    spot_by_ts: dict[datetime, dict] = {}
    ce_pe_index: dict[datetime, tuple[str, float]] = {}

    for ts, index_bar in sorted(index_index.items()):
        # Live scanners pick the nearest NIFTY expiry that has not expired.
        eligible_expiries = [e for e in expiries
                             if datetime.fromisoformat(e).date() >= ts.date()]
        if not eligible_expiries:
            continue
        nearest_expiry = min(eligible_expiries)

        atm = round_to_strike(index_bar["close"])
        listed_atm = [s for s in {k[1] for k in universe}
                      if (nearest_expiry, s, "CE") in universe
                      and (nearest_expiry, s, "PE") in universe]
        if not listed_atm:
            continue
        if atm not in listed_atm:
            atm = min(listed_atm, key=lambda s: abs(s - atm))

        atm_by_ts[ts] = float(atm)
        ce_pe_index[ts] = (nearest_expiry, float(atm))
        spot_px = round(float(index_bar["close"]), 2)
        spot_by_ts[ts] = {
            "start": ts,
            "timestamp": ts.isoformat(),
            "session_date": ts.date().isoformat(),
            "open": round(float(index_bar["open"]), 2),
            "high": round(float(index_bar["high"]), 2),
            "low": round(float(index_bar["low"]), 2),
            "close": spot_px,
            "volume": int(index_bar.get("volume") or 0),
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
    {"key": "sma9_5min", "path": "sma9_5min_scanner/app/sma9_5min_engine.py", "family": "sma", "atr": False, "regime": False},
    {"key": "sma9_adx", "path": "sma9_adx_scanner/app/sma9_adx_engine.py", "family": "sma_adx", "atr": False, "regime": False},
    {"key": "sma9_high", "path": "sma9_high_scanner/app/sma9_high_engine.py", "family": "high", "atr": False, "regime": False},
    {"key": "sma9_trail", "path": "sma9_trail_scanner/app/sma9_trail_engine.py", "family": "fixed_trail", "atr": False, "regime": False},
    {"key": "sma9_high_trail", "path": "sma9_high_trail_scanner/app/sma9_high_trail_engine.py", "family": "high_fixed_trail", "atr": False, "regime": False},
    {"key": "sma9_atr", "path": "sma9_atr_scanner/app/sma9_atr_engine.py", "family": "atr", "atr": True, "regime": True},
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
        f"# Historical scanner backtest ({meta['fidelity']})",
        "",
        "> **Not an exact 5-second paper replay for the eight 5s scanners.**",
        "> mStock supplies 5-minute OHLCV, not historical 5-second quotes. Their",
        "> live fills use sampled LTP; this report uses conservative proxies below.",
        "",
        "## Assumptions",
        "",
        f"- Window: `{meta['window']['start']}` to `{meta['window']['end']}`",
        "- Exit fill: adverse 5m low for the ATR stop, ratcheted stop level for a trail hit",
        f"- ATM: nearest 50 to completed NIFTY 50 index close (token {NIFTY_INDEX_TOKEN})",
        f"- Spot OHLC for regime: real NIFTY 50 index 5m bars (token {NIFTY_INDEX_TOKEN})",
        "- No futures anchor or CE/PE parity is used for underlying spot/ATM",
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
    index_bars = fetcher.fetch(NIFTY_INDEX_TOKEN, start, end)
    if not index_bars:
        raise RuntimeError(f"no NIFTY index history for token {NIFTY_INDEX_TOKEN} in window")

    lo = math.floor((min(b["low"] for b in index_bars) - 600) / STRIKE_STEP) * STRIKE_STEP
    hi = math.ceil((max(b["high"] for b in index_bars) + 600) / STRIKE_STEP) * STRIKE_STEP
    quote = fetcher.kite.quote(["NSE:NIFTY 50"]) or {}
    spot_now = float(next(iter(quote.values())).get("last_price") or 0)
    if spot_now:
        lo = min(lo, round_to_strike(spot_now - 1000))
        hi = max(hi, round_to_strike(spot_now + 1000))

    universe = option_universe(instruments, start.date(), lo, hi)
    print(f"[fetch] index=NIFTY 50 ({NIFTY_INDEX_TOKEN}) "
          f"strikes={len({k[1] for k in universe})} "
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

    atm_by_ts, spot_by_ts, ce_pe_index = build_index_spot_series(
        index_bars, option_index, universe
    )
    timestamps = sorted(set(ce_pe_index))
    print(f"[fetch] option tokens with history={len(series)} aligned_timestamps={len(timestamps)}",
          file=sys.stderr)

    all_trades: list[dict] = []
    for spec in SCANNER_SPECS:
        trades = replay_premium_scanner(spec, root, universe, series, timestamps,
                                        atm_by_ts, spot_by_ts, ce_pe_index, timestamps[-1])
        all_trades.extend(trades)

    keys = [s["key"] for s in SCANNER_SPECS]
    summaries = [summarize(key, [t for t in all_trades if t.get("scanner") == key]) for key in keys]
    meta = {
        "fidelity": "5m_rule_simulation_not_exact_5s_replay",
        "window": {"start": args.start, "end": args.end},
        "broker_gateway_identity": os.environ.get("BROKER_GATEWAY_SCANNER"),
        "instrument": "NIFTY",
        "underlying_anchor": f"NIFTY 50 index ({NIFTY_INDEX_TOKEN})",
        "spot_source": f"NIFTY 50 index 5m history (token {NIFTY_INDEX_TOKEN})",
        "strike_range": [lo, hi],
        "aligned_5m_timestamps": len(timestamps),
        "atm_source": f"nearest 50 to NIFTY 50 index close (token {NIFTY_INDEX_TOKEN})",
        "futures_anchor_used": False,
        "ce_pe_parity_used": False,
        "fill_policy": (
            "entry at signal candle open; ATR stop fills at adverse 5m low, "
            "trail fills at ratcheted stop level"
        ),
        "premium_spot_model": "real_index_5m_ohlc",
        "paper_only": True,
    }
    write_outputs(out_dir, summaries, all_trades, meta)
    print(json.dumps({"out": str(out_dir), "scanners": summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
