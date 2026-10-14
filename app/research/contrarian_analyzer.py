"""ContrarianMarketAnalyzer (shadow-only, removable, pure research module).

Investigates whether price-action evidence -- failed breakouts/breakdowns,
CPR rejection/acceptance, gap reversal vs continuation, trapped momentum --
adds measurable value beyond TradingAI.in's existing CPR-based decisions.

Contract
--------
* PURE: no I/O, no network, no DB. Imports only the standard library.
  It never imports or calls trading / alert / paper / qualification /
  loss-learning / mutation workflows and never triggers notifications.
* READ-ONLY: never mutates the supplied decision snapshot or candle data.
* CAUSAL: an assessment at time T uses only candles that COMPLETE on or
  before T (a 5m candle [open, open+5m) completes at open+5m).
* DEFENSIVE: missing or malformed fields yield explicit unavailable or
  insufficient-data states; nothing is fabricated.
* DETERMINISTIC: identical inputs produce identical output.

The analyzer does NOT recompute CPR. It consumes existing authoritative CPR,
pivot, gap and regime values via the supplied canonical decision snapshot
(decision['cpr'] etc.), read from the canonical payload by the caller.

Output is a research verdict only: it is not investment advice, not a
prediction, and not a retail-positioning signal. Results are index-point
evidence, never options P&L.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

METHODOLOGY_VERSION = "contrarian-analyzer-v1"

VALID_INSTRUMENTS = ("NIFTY", "BANKNIFTY")

IST = timezone(timedelta(hours=5, minutes=30))
CANDLE_MINUTES = 5

# ---- Research parameters (Phase 2 defaults). Assumptions, not established
# truths. Explicit and reproducible; never tuned against the holdout. ----
CLOSE_IN = 6          # (context length reserved by the Phase 2 design)
SUSTAIN = 2           # consecutive completes beyond the buffered level
CONFIRM = 1           # completed candle required to confirm an attempt
RECLAIM = 3           # max bars after the last beyond-close to call a failed move
GAP_FIRST_BARS = 4    # first session 5m bars used for the gap-continuation test
FIRST_HOUR_END = "10:30"      # latest COMPLETION time for the gap-reversal window
SESSION_OPEN_HM = "09:15"     # exchange session open (bar open timestamps)
GAP_WINDOW_END_HM = "09:30"   # last 5m bar open timestamp in the 4-bar gap window
FIRST_REVERSAL_HM = "09:20"   # earliest COMPLETION time for the gap-reversal window
MIN_BARS = 4          # minimum usable completed candles for any assessment
ACCEPT_FRAC = 0.15    # acceptance buffer = ACCEPT_FRAC * CPR width
XEXT = 1.2            # extension scale = level +- XEXT * CPR width

# NSE equity-index sessions: 09:15 to 15:30 IST, candles open-timestamped.
OPEN_MIN_HM = "09:20"
OPEN_EOD_HM = "15:20"
LAST_BAR_HM = "15:25"

BULLISH_CONTRARIAN = "BULLISH_CONTRARIAN"
BEARISH_CONTRARIAN = "BEARISH_CONTRARIAN"
CONTINUATION = "CONTINUATION"
INDETERMINATE = "INDETERMINATE"
NEUTRAL = "NEUTRAL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUSES = (
    BULLISH_CONTRARIAN, BEARISH_CONTRARIAN, CONTINUATION,
    INDETERMINATE, NEUTRAL, INSUFFICIENT_DATA,
)

ALIGN_AGREE = "AGREE"
ALIGN_DISAGREE = "DISAGREE"
ALIGN_NEUTRAL = "NEUTRAL"
ALIGN_INSUFFICIENT = "INSUFFICIENT"

_ALWAYS_UNAVAILABLE = ("PCR", "OI", "MAX_PAIN", "IV", "EXPECTED_MOVE")
VIX_MAX_AGE_MIN = 60  # INDIA VIX evidence is usable only within this age window

_PARAM_SPEC = {
    "CLOSE_IN": int, "SUSTAIN": int, "CONFIRM": int, "RECLAIM": int,
    "GAP_FIRST_BARS": int, "MIN_BARS": int,
    "ACCEPT_FRAC": float, "XEXT": float,
    "FIRST_HOUR_END": str, "SESSION_OPEN_HM": str, "GAP_WINDOW_END_HM": str,
}


def _num(value: Any) -> Optional[float]:
    """Defensive numeric coercion. None/''/malformed -> None (no fabrication)."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(f):
        return f
    return None


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse a timestamp to an aware IST datetime, or None when malformed.

    Naive datetimes are assumed to be IST (server convention).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


def _completion(bar_ts: datetime) -> datetime:
    """A candle with OPEN timestamp t completes at t + 5m (engine convention)."""
    return bar_ts + timedelta(minutes=CANDLE_MINUTES)


def _hm(ts: datetime) -> str:
    return ts.strftime("%H:%M")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def normalize_candles(candles: Any) -> Dict[str, Any]:
    """Normalize raw candle rows into a deterministic sorted bar list.

    Returns dict with keys: bars (sorted list of dicts with aware 'ts' and
    float OHLCV + is_complete), duplicates (dropped count, last wins),
    excluded (count of malformed rows), received (raw row count).
    Never raises on malformed rows. Out-of-order inputs are sorted.
    """
    received = 0
    excluded = 0
    by_ts: Dict[datetime, dict] = {}
    for c in candles if isinstance(candles, (list, tuple)) else []:
        received += 1
        if not isinstance(c, dict):
            excluded += 1
            continue
        ts = _parse_ts(c.get("timestamp"))
        o = _num(c.get("open"))
        h = _num(c.get("high"))
        lo = _num(c.get("low"))
        cl = _num(c.get("close"))
        if ts is None or o is None or h is None or lo is None or cl is None:
            excluded += 1
            continue
        by_ts[ts] = {
            "ts": ts,
            "open": o, "high": h, "low": lo, "close": cl,
            "volume": _num(c.get("volume")) or 0.0,
            "is_complete": bool(c.get("is_complete")),
        }
    bars = sorted(by_ts.values(), key=lambda r: r["ts"])
    return {
        "bars": bars,
        "received": received,
        "excluded": excluded,
        "duplicates": received - excluded - len(bars),
    }


def usable_bars(bars: List[dict], assessment_ts: datetime) -> List[dict]:
    """Bars that have fully completed on or before assessment_ts (causal)."""
    return [b for b in bars if _completion(b["ts"]) <= assessment_ts]


def resolve_assessment_ts(
    bars: List[dict],
    provided: Any = None,
    decision_ts: Any = None,
) -> Optional[datetime]:
    """Resolve the assessment instant from explicit input or data bounds.

    The assessment can never be later than the latest completed candle, so a
    future-dated decision payload cannot leak future bars in.
    """
    candidate = _parse_ts(provided)
    if candidate is None:
        candidate = _parse_ts(decision_ts)
    latest = _completion(bars[-1]["ts"]) if bars else None
    if candidate is not None and latest is not None:
        return min(candidate, latest)
    if candidate is not None:
        return candidate
    return latest


def _cpr_block(decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Authoritative CPR/pivot/gap values from the canonical decision snapshot."""
    cpr = decision.get("cpr")
    if isinstance(cpr, dict) and cpr.get("available") is not False:
        return cpr
    return None


def _direction(value: Any) -> Optional[str]:
    """Normalize a BULLISH/BEARISH/BULL/BEAR directional label to uniform form."""
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    if v in ("BULLISH", "BULL"):
        return "BULLISH"
    if v in ("BEARISH", "BEAR"):
        return "BEARISH"
    if v in ("NEUTRAL", "FLAT", "RANGING", "NONE"):
        return None
    return None


def _decision_payload_fields(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Defensively extract the authoritative fields we are allowed to consume.

    Missing values become None / empty; nothing is invented.
    """
    cpr = _cpr_block(decision)
    get = lambda key: _num((cpr or {}).get(key)) if cpr else None  # noqa: E731
    tc = get("tc")
    bc = get("bc")
    pp = get("pp") if get("pp") is not None else get("pivot")
    if pp is None and tc is not None and bc is not None:
        pp = (tc + bc) / 2.0  # CPR midline; derived from authoritative TC/BC only
    r1, r2 = get("r1"), get("r2")
    s1, s2 = get("s1"), get("s2")
    pdh, pdl = get("prev_high"), get("prev_low")
    prev_close = get("prev_close")
    if prev_close is None:
        prev_close = _num(decision.get("prev_close"))
    day_open = get("day_open")
    gap_points = get("gap_points")
    if gap_points is None:
        gap_points = _num(decision.get("gap_points"))
    gap_direction = None
    gdir_raw = (cpr or {}).get("gap_direction") if cpr else None
    if gdir_raw is None:
        gdir_raw = decision.get("gap_direction")
    if isinstance(gdir_raw, str):
        g = gdir_raw.strip().upper()
        if g in ("BULLISH", "BEARISH"):
            gap_direction = g
        elif g == "NEUTRAL":
            gap_direction = None

    decision_dir = _direction(
        decision.get("strategy_direction")
        or (decision.get("trade") or {}).get("direction")
        or decision.get("market_bias")
    )
    decision_knowable_at = _parse_ts(
        (decision.get("trade") or {}).get("entry_time") or decision.get("timestamp")
    )
    regime = decision.get("market_regime")
    if isinstance(regime, str):
        regime = regime.strip().upper()
    vol = decision.get("volatility_state")
    if isinstance(vol, str):
        vol = vol.strip().upper()
    atr = _num(decision.get("atr"))
    atr_present = atr is not None
    trade = decision.get("trade")
    return {
        "cpr_available": cpr is not None and tc is not None and bc is not None,
        "tc": tc, "bc": bc, "pp": pp, "r1": r1, "r2": r2, "s1": s1, "s2": s2,
        "pdh": pdh, "pdl": pdl, "prev_close": prev_close, "day_open": day_open,
        "gap_direction": gap_direction, "gap_points": gap_points,
        "cpr_type": (cpr or {}).get("cpr_type") if cpr else None,
        "price_position": (cpr or {}).get("price_position") if cpr else None,
        "virgin": (cpr or {}).get("virgin") if cpr else None,
        "market_regime": regime, "volatility_state": vol,
        "strategy": decision.get("strategy") if isinstance(decision.get("strategy"), str) else "NONE",
        "decision_dir": decision_dir,
        "decision_knowable_at": decision_knowable_at,
        "decision_trade_level": trade.get("level") if isinstance(trade, dict) else None,
        "atr_present": atr_present,
    }


def _canonical_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate/merge research parameters. Unknown or wrong-typed keys raise."""
    merged = {
        "CLOSE_IN": CLOSE_IN, "SUSTAIN": SUSTAIN, "CONFIRM": CONFIRM,
        "RECLAIM": RECLAIM, "GAP_FIRST_BARS": GAP_FIRST_BARS,
        "MIN_BARS": MIN_BARS, "ACCEPT_FRAC": ACCEPT_FRAC, "XEXT": XEXT,
        "FIRST_HOUR_END": FIRST_HOUR_END, "SESSION_OPEN_HM": SESSION_OPEN_HM,
    }
    if params:
        for k, v in params.items():
            if k not in _PARAM_SPEC:
                raise ValueError(f"UNKNOWN_PARAM:{k}")
            if not isinstance(v, _PARAM_SPEC[k]):
                raise ValueError(f"BAD_PARAM_TYPE:{k}")
            merged[k] = v
    return merged


def _level_universe(fields: Dict[str, Any]) -> Dict[str, float]:
    """Named authoritative levels usable by the level-scan rules."""
    out: Dict[str, float] = {}
    for key in ("tc", "bc", "pp", "r1", "r2", "s1", "s2", "pdh", "pdl"):
        v = fields.get(key)
        if v is not None and math.isfinite(v):
            out[key] = float(v)
    return out


def _scan_level(
    events: List[dict],
    bars: List[dict],
    level: float,
    bu: Optional[float],
    width: float,
    sign: int,
    params: Dict[str, Any],
) -> None:
    """Scan one level on one side for attempt/sustain/extension/failure events.

    sign: +1 tests breakout above `level` (UP), -1 tests breakdown below (DOWN).
    bu:   acceptance buffer (None or <=0 -> side skipped: no valid CPR-width
          scale to quantify acceptance). Events are appended to `events` with
          causal knowable_at = completion of the deciding bar.
    """
    if bu is None or bu <= 0:
        return
    p = params
    lo, hi = level - bu, level + bu
    ext_scale = level + (XEXT * width if sign > 0 else -XEXT * width)

    start: Optional[int] = None
    run_end: Optional[int] = None
    ack_valid = False
    sustained_done = False
    extended_done = False

    n = len(bars)
    idx = 0
    while idx < n:
        b = bars[idx]
        c = b["close"]
        beyond = (c > hi) if sign > 0 else (c < lo)
        in_window = lo <= c <= hi
        if beyond:
            if ack_valid and run_end is not None:
                run_end = idx
            else:
                prior = bars[idx - 1] if idx > 0 else None
                ack_valid = bool(prior is not None and lo <= prior["close"] <= hi)
                if ack_valid:
                    start, run_end = idx, idx
                    sustained_done = False
                    extended_done = False
                else:
                    start = run_end = None
            if ack_valid and run_end is not None:
                completion_ts = _completion(b["ts"])
                if not sustained_done and run_end - start + 1 >= p["SUSTAIN"]:
                    sustained_done = True
                    events.append({
                        "type": "SUSTAINED_ACCEPT",
                        "side": "UP" if sign > 0 else "DOWN",
                        "level": level,
                        "direction_pressure": "BULLISH" if sign > 0 else "BEARISH",
                        "attempt_ts": _iso(_completion(bars[start]["ts"])),
                        "event_ts": _iso(completion_ts),
                        "knowable_at": _iso(completion_ts),
                        "invalidation": "close re-enters the buffered level window",
                        "used_bars": idx + 1,
                    })
                if not extended_done and (c > ext_scale if sign > 0 else c < ext_scale):
                    extended_done = True
                    events.append({
                        "type": "EXTENSION",
                        "side": "UP" if sign > 0 else "DOWN",
                        "level": level,
                        "direction_pressure": "BULLISH" if sign > 0 else "BEARISH",
                        "attempt_ts": _iso(_completion(bars[start]["ts"])),
                        "event_ts": _iso(completion_ts),
                        "knowable_at": _iso(completion_ts),
                        "invalidation": "close falls back through the buffered level window",
                        "used_bars": idx + 1,
                    })
            idx += 1
            continue
        # not beyond the buffered level
        if ack_valid and run_end is not None and not sustained_done:
            last_beyond = run_end
            if (idx - last_beyond) <= p["RECLAIM"] and in_window:
                trap = _is_trap(bars, start, idx, sign)
                completion_ts = _completion(b["ts"])
                ev_type = "FAILED_BREAKDOWN" if sign < 0 else "FAILED_BREAKOUT"
                events.append({
                    "type": ev_type,
                    "side": "UP" if sign > 0 else "DOWN",
                    "level": level,
                    "direction_pressure": "BEARISH" if sign > 0 else "BULLISH",
                    "attempt_ts": _iso(_completion(bars[start]["ts"])),
                    "event_ts": _iso(completion_ts),
                    "knowable_at": _iso(completion_ts),
                    "trap": trap,
                    "invalidation": ("close establishes a sustained run beyond "
                                     "the buffered level without reclaim"),
                    "used_bars": idx + 1,
                })
                ack_valid = False
                run_end = None
                start = None
                idx += 1
                continue
            if (idx - last_beyond) > p["RECLAIM"]:
                ack_valid = False
                run_end = None
                start = None
        idx += 1


def _is_trap(bars: List[dict], start: Optional[int], idx: int, sign: int) -> bool:
    """Trapped momentum: the attempt touched a session extreme before failing."""
    if start is None or start < 1:
        return False
    attempt = bars[start]
    prior = bars[:start]
    if not prior:
        return False
    if sign > 0:
        return attempt["high"] >= max(b["high"] for b in prior)
    return attempt["low"] <= min(b["low"] for b in prior)


def _scan_gaps(
    events: List[dict],
    bars: List[dict],
    assessment_ts: datetime,
    fields: Dict[str, Any],
    params: Dict[str, Any],
) -> Tuple[Dict[str, bool], List[str]]:
    """Gap continuation / first-hour reversal tests (informational-at-T only).

    Returns (flag-dict, reasons). Uses only the authoritative gap fields and
    candle behavior inside the session; never notices future bars.
    """
    p = params
    flag = {"gap_continuation": None, "gap_reversal": None}
    reasons: List[str] = []
    prev_close = fields["prev_close"]
    gap_dir = fields["gap_direction"]
    if prev_close is None or gap_dir is None:
        reasons.append("GAP_TEST_SKIPPED_PREV_CLOSE_OR_DIRECTION_MISSING")
        return flag, reasons
    session_date = bars[0]["ts"].date() if bars else None
    if session_date is None:
        reasons.append("GAP_TEST_SKIPPED_NO_SESSION_BARS")
        return flag, reasons

    window = [
        b for b in bars
        if b["ts"].date() == session_date
        and SESSION_OPEN_HM <= _hm(b["ts"]) <= GAP_WINDOW_END_HM
    ]
    if len(window) >= p["GAP_FIRST_BARS"]:
        four_completion = _completion(window[p["GAP_FIRST_BARS"] - 1]["ts"])
        if four_completion <= assessment_ts:
            bull_breached = any(b["low"] < prev_close for b in window)
            bear_breached = any(b["high"] > prev_close for b in window)
            if gap_dir == "BULLISH" and not bull_breached:
                flag["gap_continuation"] = "BULLISH"
                events.append({
                    "type": "GAP_CONTINUATION", "side": None, "level": "PREV_CLOSE",
                    "direction_pressure": "BULLISH", "attempt_ts": None,
                    "event_ts": _iso(four_completion), "knowable_at": _iso(four_completion),
                    "invalidation": "an early bar low breaches prev close",
                    "used_bars": len(bars),
                })
            elif gap_dir == "BEARISH" and not bear_breached:
                flag["gap_continuation"] = "BEARISH"
                events.append({
                    "type": "GAP_CONTINUATION", "side": None, "level": "PREV_CLOSE",
                    "direction_pressure": "BEARISH", "attempt_ts": None,
                    "event_ts": _iso(four_completion), "knowable_at": _iso(four_completion),
                    "invalidation": "an early bar high breaches prev close",
                    "used_bars": len(bars),
                })
    for b in bars:
        if b["ts"].date() != session_date:
            continue
        compl = _completion(b["ts"])
        if compl > assessment_ts:
            break
        if _hm(compl) < FIRST_REVERSAL_HM:
            continue
        if _hm(compl) > p["FIRST_HOUR_END"]:
            break
        if gap_dir == "BULLISH" and b["close"] < prev_close:
            flag["gap_reversal"] = "BEARISH"
            events.append({
                "type": "GAP_REVERSAL", "side": None, "level": "PREV_CLOSE",
                "direction_pressure": "BEARISH", "attempt_ts": None,
                "event_ts": _iso(compl), "knowable_at": _iso(compl),
                "invalidation": "price never closes back across prev close in window",
                "used_bars": len(bars),
            })
            break
        if gap_dir == "BEARISH" and b["close"] > prev_close:
            flag["gap_reversal"] = "BULLISH"
            events.append({
                "type": "GAP_REVERSAL", "side": None, "level": "PREV_CLOSE",
                "direction_pressure": "BULLISH", "attempt_ts": None,
                "event_ts": _iso(compl), "knowable_at": _iso(compl),
                "invalidation": "price never closes back across prev close in window",
                "used_bars": len(bars),
            })
            break
    return flag, reasons


def _prevailing_move(bars: List[dict]) -> str:
    """Direction of the day's closes so far (BULLISH/BEARISH/FLAT)."""
    up = sum(1 for b in bars if b["close"] > b["open"])
    down = sum(1 for b in bars if b["close"] < b["open"])
    if up > down:
        return "BULLISH"
    if down > up:
        return "BEARISH"
    return "FLAT"


def _resolve_status(
    events: List[dict],
    fields: Dict[str, Any],
    bar_count: int,
) -> Tuple[str, Dict[str, int], Dict[str, int], List[str]]:
    """Map evidence to a status. Returns (status, contrarian, continuation, conflicts)."""
    bull_contr = 0
    bear_contr = 0
    for e in events:
        if e["type"] in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN", "GAP_REVERSAL"):
            if e["direction_pressure"] == "BULLISH":
                bull_contr += 1
            else:
                bear_contr += 1
    bull_cont = any(
        e["type"] in ("SUSTAINED_ACCEPT", "EXTENSION", "GAP_CONTINUATION")
        and e["direction_pressure"] == "BULLISH" for e in events
    )
    bear_cont = any(
        e["type"] in ("SUSTAINED_ACCEPT", "EXTENSION", "GAP_CONTINUATION")
        and e["direction_pressure"] == "BEARISH" for e in events
    )
    contrarian = {"bullish": bull_contr, "bearish": bear_contr}
    continuation = {"bullish": 1 if bull_cont else 0, "bearish": 1 if bear_cont else 0}

    conflicts: List[str] = []
    total_bull = bull_contr + (1 if bull_cont else 0)
    total_bear = bear_contr + (1 if bear_cont else 0)
    if total_bull > 0 and total_bear > 0:
        conflicts.append("BULLISH and BEARISH evidence coexist")

    if bar_count < fields["_min_bars"]:
        status = INSUFFICIENT_DATA
    elif not fields["_levels"] and fields["prev_close"] is None:
        status = INSUFFICIENT_DATA
    elif total_bull > 0 and total_bear > 0:
        status = INDETERMINATE
    elif total_bull > 0 and bull_contr > 0 and bear_contr == 0 and not bear_cont:
        status = BULLISH_CONTRARIAN
    elif total_bull > 0 and bull_contr == 0 and bull_cont:
        status = CONTINUATION
    elif total_bear > 0 and bear_contr > 0 and bull_contr == 0 and not bull_cont:
        status = BEARISH_CONTRARIAN
    elif total_bear > 0 and bear_contr == 0 and bear_cont:
        status = CONTINUATION
    else:
        status = NEUTRAL
    return status, contrarian, continuation, conflicts


def _alignment(
    status: str,
    status_bias: Optional[str],
    decision_dir: Optional[str],
    assessment_ts: Optional[datetime],
    decision_knowable_at: Optional[datetime],
) -> str:
    """Causal alignment: the canonical direction counts only when it was
    knowable at the assessment instant (never with future decision info)."""
    if status in (INSUFFICIENT_DATA,):
        return ALIGN_INSUFFICIENT
    if decision_dir is None:
        return ALIGN_INSUFFICIENT
    if decision_knowable_at is None or assessment_ts is None:
        return ALIGN_INSUFFICIENT
    if decision_knowable_at > assessment_ts:
        return ALIGN_INSUFFICIENT
    if status_bias is None:
        return ALIGN_NEUTRAL
    return ALIGN_AGREE if status_bias == decision_dir else ALIGN_DISAGREE


def _candidate_setup(events: List[dict]) -> str:
    labels = []
    if any(e["type"] == "GAP_REVERSAL" for e in events):
        labels.append("GAP_REVERSAL_FADE")
    for e in events:
        if e["type"] == "FAILED_BREAKOUT":
            labels.append("FAILED_BREAKOUT" + ("_TRAPPED" if e.get("trap") else ""))
        elif e["type"] == "FAILED_BREAKDOWN":
            labels.append("FAILED_BREAKDOWN" + ("_TRAPPED" if e.get("trap") else ""))
    if not labels and any(e["type"] in ("SUSTAINED_ACCEPT", "EXTENSION") for e in events):
        labels.append("SUSTAINED_BREAK")
    if not labels and any(e["type"] == "GAP_CONTINUATION" for e in events):
        labels.append("GAP_CONTINUATION")
    return " + ".join(labels) if labels else "NONE"


def _invalidation_conditions(events: List[dict]) -> List[str]:
    seen = set()
    out = []
    for e in events:
        text = e.get("invalidation") or ""
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def analyze(
    instrument: str,
    decision: Any,
    candles: Any,
    assessment_ts: Any = None,
    vix_evidence: Any = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce a versioned, causal ContrarianMarketAnalyzer verdict.

    Pure function: no I/O, no mutation of `decision` or `candles`.
    Raises ValueError for an unsupported instrument or a missing/malformed
    decision snapshot (never returns a fabricated verdict for those).
    """
    inst = (instrument or "").strip().upper()
    if inst not in VALID_INSTRUMENTS:
        raise ValueError(f"UNSUPPORTED_INSTRUMENT:{inst or 'EMPTY'}")
    if not isinstance(decision, dict):
        raise ValueError("DECISION_REQUIRED")

    p = _canonical_params(params)
    fields = _decision_payload_fields(decision)
    norm = normalize_candles(candles)
    bars = norm["bars"]
    ass = resolve_assessment_ts(bars, assessment_ts, decision.get("timestamp"))

    skeleton: Dict[str, Any] = {
        "methodology_version": METHODOLOGY_VERSION,
        "instrument": inst,
        "assessment_ts": _iso(ass) if ass else None,
        "data_timestamp": _iso(bars[-1]["ts"]) if bars else None,
        "bar_count": 0,
        "market_regime_assessment": {},
        "prevailing_move": None,
        "failed_move_evidence": {"failed_breakout": [], "failed_breakdown": [],
                                 "trapped": []},
        "contrarian_bias": None,
        "continuation_bias": None,
        "conflicting_evidence": [],
        "decision": {"alignment": ALIGN_INSUFFICIENT, "direction": fields["decision_dir"],
                     "level": fields["decision_trade_level"]},
        "candidate_setup_type": "NONE",
        "invalidation_conditions": [],
        "risk_notes": [],
        "unavailable_inputs": list(_ALWAYS_UNAVAILABLE),
        "status": INSUFFICIENT_DATA,
        "evidence": [],
        "inputs": {},
    }

    if not bars:
        skeleton["inputs"] = {
            "cpr_available": fields["cpr_available"],
            "gap_reconstructed": False,
            "buffer": None, "width_scale": None,
            "atr_present": fields["atr_present"],
            "vix_present": False,
            "bars_received": norm["received"], "bars_excluded": norm["excluded"],
            "duplicates_dropped": norm["duplicates"],
            "assessment_resolved_from": "none",
        }
        skeleton["risk_notes"].append("No completed candles available; insufficient data.")
        skeleton["unavailable_inputs"].append("CANDLES")
        return skeleton

    usable = usable_bars(bars, ass)
    bar_count = len(usable)
    skeleton["assessment_ts"] = _iso(ass)
    skeleton["data_timestamp"] = _iso(usable[-1]["ts"])
    skeleton["bar_count"] = bar_count

    unavailable = list(_ALWAYS_UNAVAILABLE)
    if not fields["cpr_available"]:
        unavailable.append("CPR")
    if fields["prev_close"] is None:
        unavailable.append("PREV_CLOSE")
    if not fields["atr_present"]:
        unavailable.append("ATR")
    skeleton["unavailable_inputs"] = unavailable

    vix_present, vix_value = False, None
    if isinstance(vix_evidence, dict):
        vts = _parse_ts(vix_evidence.get("timestamp") or vix_evidence.get("ts"))
        vv = _num(vix_evidence.get("value"))
        stale = vts is not None and ass is not None and (
            vts > ass or (ass - vts).total_seconds() / 60.0 > VIX_MAX_AGE_MIN
        )
        if vts is not None and vv is not None and not stale and ass is not None:
            vix_present = True
            vix_value = vv
        else:
            unavailable.append("VIX")
            unavailable.append("VIX_STALE_OR_MALFORMED")
    else:
        unavailable.append("VIX")
    skeleton["unavailable_inputs"] = unavailable

    levels = _level_universe(fields)
    fields["_levels"] = levels
    fields["_min_bars"] = p["MIN_BARS"]

    events: List[dict] = []
    gap_flag, gap_reasons = _scan_gaps(events, usable, ass, fields, p)

    width = (fields["tc"] - fields["bc"]) if (fields["tc"] is not None and fields["bc"] is not None) else None
    buffer = None
    if width is not None and width > 0:
        buffer = round(ACCEPT_FRAC * width, 4)
    scale_valid = buffer is not None and buffer > 0
    if not scale_valid:
        gap_reasons.append("BUFFER_UNAVAILABLE_CPR_WIDTH_INVALID")

    for name, level in sorted(levels.items()):
        _scan_level(events, usable, level, buffer, width or 0.0, 1, p)
        _scan_level(events, usable, level, buffer, width or 0.0, -1, p)

    status, contrarian, continuation, conflicts = _resolve_status(
        events, fields, bar_count
    )
    status_bias = None
    if status == BULLISH_CONTRARIAN:
        status_bias = "BULLISH"
    elif status == BEARISH_CONTRARIAN:
        status_bias = "BEARISH"
    elif status == CONTINUATION:
        status_bias = "BULLISH" if continuation["bullish"] else (
            "BEARISH" if continuation["bearish"] else None
        )
    if status in (INDETERMINATE, NEUTRAL, INSUFFICIENT_DATA):
        status_bias = None

    failed_out = {"failed_breakout": [], "failed_breakdown": [], "trapped": []}
    for e in events:
        if e["type"] == "FAILED_BREAKOUT":
            failed_out["failed_breakout"].append(round(e["level"], 2))
        elif e["type"] == "FAILED_BREAKDOWN":
            failed_out["failed_breakdown"].append(round(e["level"], 2))
        if e.get("trap"):
            failed_out["trapped"].append(round(e["level"], 2))

    skeleton["failed_move_evidence"] = failed_out
    skeleton["evidence"] = events
    skeleton["status"] = status
    skeleton["contrarian_bias"] = (
        "BULLISH" if contrarian["bullish"] and not contrarian["bearish"] else
        "BEARISH" if contrarian["bearish"] and not contrarian["bullish"] else None
    )
    skeleton["continuation_bias"] = (
        "BULLISH" if continuation["bullish"] and not continuation["bearish"] else
        "BEARISH" if continuation["bearish"] and not continuation["bullish"] else None
    )
    skeleton["prevailing_move"] = _prevailing_move(usable)
    skeleton["conflicting_evidence"] = conflicts
    skeleton["candidate_setup_type"] = _candidate_setup(events)
    skeleton["invalidation_conditions"] = _invalidation_conditions(events)
    skeleton["decision"]["alignment"] = _alignment(
        status, status_bias, fields["decision_dir"], ass, fields["decision_knowable_at"]
    )

    regime_assessment = {
        "market_regime": fields["market_regime"] or "UNAVAILABLE",
        "volatility_state": fields["volatility_state"] or "UNAVAILABLE",
        "cpr_type": fields["cpr_type"] or "UNAVAILABLE",
        "cpr_width_pct": None,
        "price_position": fields["price_position"] or "UNAVAILABLE",
        "virgin_cpr": fields["virgin"],
        "strategy": fields["strategy"],
    }
    if fields["cpr_available"]:
        w = fields["tc"] - fields["bc"]
        pp = fields["pp"] or (fields["tc"] + fields["bc"]) / 2.0
        regime_assessment["cpr_width_pct"] = round((w / pp) * 100.0, 6) if pp else None
    skeleton["market_regime_assessment"] = regime_assessment

    risk_notes = [
        "Shadow-only research observation; no trading effect.",
        "Index-point evidence; NOT options P&L.",
        "Costs/slippage are research assumptions (0.10R round trip, 0.05R entry).",
    ]
    if gap_reasons:
        risk_notes.append("Gap context: " + "; ".join(gap_reasons))
    skeleton["risk_notes"] = risk_notes

    skeleton["inputs"] = {
        "cpr_available": fields["cpr_available"],
        "gap_reconstructed": False,
        "buffer": buffer,
        "width_scale": scale_valid,
        "atr_present": fields["atr_present"],
        "vix_present": vix_present,
        "vix_value": vix_value,
        "bars_received": norm["received"],
        "bars_excluded": norm["excluded"],
        "duplicates_dropped": norm["duplicates"],
        "assessment_resolved_from": "provided" if _parse_ts(assessment_ts) is not None
        else ("decision" if _parse_ts(decision.get("timestamp")) is not None else "latest_bar"),
    }
    return skeleton


class ContrarianMarketAnalyzer:
    """Thin stateless wrapper exposing the pure analysis under one name."""

    METHODOLOGY_VERSION = METHODOLOGY_VERSION
    VALID_INSTRUMENTS = VALID_INSTRUMENTS

    @staticmethod
    def analyze(
        instrument: str,
        decision: Any,
        candles: Any,
        assessment_ts: Any = None,
        vix_evidence: Any = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return analyze(instrument, decision, candles, assessment_ts,
                       vix_evidence, params)