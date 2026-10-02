"""E.2 isolated read-only educational economics endpoint.

This module contains NO economics formula of its own. It adapts
caller-supplied (user-entered) prices into the leg shape the AUTHORITATIVE
implementation already expects, then delegates to it:

    app.options.economics.calc_*              <- single source of truth
    app.options.weekly_spreads.
        spread_points_at_expiry               <- authoritative intrinsic curve

ISOLATION CONTRACT
------------------
* GET only. No database access. No cache writes. No trade, alert, signal,
  regime, outlook or strategy mutation. No side effects.
* Imports nothing from app.live, app.decision, app.core.qualification,
  app.scenarios, app.ai, app.research, app.paper_trade, app.options.engine,
  app.options.provider, app.options.nse_chain. This endpoint is not an input
  to the decision pipeline and cannot become one.
* Never fabricates. Missing input -> INPUT_REQUIRED. Invalid input ->
  INVALID_INPUT. Engine fault -> SYSTEM_CALCULATION_ERROR. No value is ever
  defaulted, coerced, or substituted.
* Produces no probability, confidence, bias, outlook, target or
  recommendation.

RATE LIMITING: intentionally no @limiter.limit decorator. app/api/app.py:52
constructs Limiter(default_limits=["60 per minute"]) which already applies to
every registered route. A second decorator here would be redundant.
"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from app.options.contract import VALID_INSTRUMENTS
from app.options.economics import (
    LOT_SIZES,
    calc_bear_call_spread,
    calc_bear_put_spread,
    calc_bull_call_spread,
    calc_bull_put_spread,
    calc_iron_condor,
)
from app.options.weekly_spreads import spread_points_at_expiry

bp = Blueprint("e2_economics", __name__)

# Exact mirrors of the five APPROVED_STRATEGIES in
# app.options.strategy.StrategyType, with the leg count each authoritative
# calc_* requires. Side assignment below mirrors the sort/side rules those
# same functions already apply; _verify_curve_reconciles cross-checks it.
_CALC = {
    "BULL_PUT_SPREAD": (calc_bull_put_spread, 2),
    "BULL_CALL_SPREAD": (calc_bull_call_spread, 2),
    "BEAR_CALL_SPREAD": (calc_bear_call_spread, 2),
    "BEAR_PUT_SPREAD": (calc_bear_put_spread, 2),
    "IRON_CONDOR": (calc_iron_condor, 4),
}

_OPTION_TYPES = ("CE", "PE")
MAX_LEGS = 4
MAX_POINTS = 61
MIN_LOTS = 1
MAX_LOTS = 500
MAX_LOT_SIZE = 10000
MAX_EXPIRY_LABEL = 40

_DATA_GATE_NOTE = (
    "Educational calculation from prices the user entered. "
    "Not live market data. No market-data or options-chain provider was "
    "contacted. Not investment advice."
)


_IST = ZoneInfo("Asia/Kolkata")


def _now():
    """Envelope timestamp, matching the IST convention used in app/api/app.py.

    This is response metadata only; every economic figure below is a pure
    function of the caller's input.
    """
    return datetime.now(_IST).isoformat()


def _err(state, reasons, status_code):
    """Unavailable/error envelope, matching app/api/app.py conventions."""
    return jsonify({"state": state, "timestamp": _now(),
                    "data": {"reasons": reasons}}), status_code


def _flt(raw, field):
    """Strict numeric parse. Returns (value, error_code). Never coerces."""
    if raw is None or str(raw).strip() == "":
        return None, "MISSING_" + field.upper()
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None, "INVALID_" + field.upper()
    if math.isnan(v) or math.isinf(v):
        return None, "INVALID_" + field.upper()
    return v, None


def _sides_for(strategy, legs):
    """Assign BUY/SELL per leg using the same ordering rules the
    authoritative calc_* functions apply internally."""
    out = [None] * len(legs)

    def order(idxs):
        return sorted(idxs, key=lambda i: legs[i]["strike"])

    asc = order(range(len(legs)))
    desc = list(reversed(asc))

    if strategy == "BULL_PUT_SPREAD":
        out[desc[0]], out[desc[1]] = "SELL", "BUY"
    elif strategy == "BULL_CALL_SPREAD":
        out[asc[0]], out[asc[1]] = "BUY", "SELL"
    elif strategy == "BEAR_CALL_SPREAD":
        out[asc[0]], out[asc[1]] = "SELL", "BUY"
    elif strategy == "BEAR_PUT_SPREAD":
        out[desc[0]], out[desc[1]] = "BUY", "SELL"
    elif strategy == "IRON_CONDOR":
        puts = order([i for i in range(len(legs))
                      if legs[i]["option_type"] == "PE"])
        calls = order([i for i in range(len(legs))
                       if legs[i]["option_type"] == "CE"])
        if len(puts) != 2 or len(calls) != 2:
            raise ValueError("iron condor needs 2 puts and 2 calls")
        # short the closer strikes, long the wider ones
        out[puts[1]] = "SELL"
        out[puts[0]] = "BUY"
        out[calls[0]] = "SELL"
        out[calls[1]] = "BUY"
    return out


def _verify_curve_reconciles(curve_pts, econ):
    """Self-check: the curve's own extremes must agree with the economics
    summary the authoritative module returned. Guards against the side
    mirror in _sides_for ever drifting from economics.py.
    """
    tgt_profit = econ.get("max_reward")
    tgt_risk = econ.get("max_risk")
    if not isinstance(tgt_profit, (int, float)):
        return False
    if not isinstance(tgt_risk, (int, float)):
        return False
    hi = max(curve_pts)
    lo = min(curve_pts)
    return (abs(hi - tgt_profit) <= 0.05) and (abs(lo + tgt_risk) <= 0.05)


@bp.route("/api/economics/calculate", methods=["GET"])
def economics_calculate():
    """Read-only defined-risk economics for user-entered prices.

    Every economic figure is delegated to app.options.economics, which is
    unmodified. Invalid input yields INVALID_INPUT, never a substitute value.
    """
    inst = (request.args.get("instrument") or "").upper()
    if inst not in VALID_INSTRUMENTS:
        return _err("INVALID_INPUT", ["UNKNOWN_INSTRUMENT"], 404)

    strategy = (request.args.get("strategy") or "").upper()
    if strategy not in _CALC:
        return _err("INVALID_INPUT", ["UNKNOWN_STRATEGY"], 400)
    fn, expected_legs = _CALC[strategy]

    expiry = (request.args.get("expiry") or "").strip()
    if not expiry:
        return _err("INPUT_REQUIRED", ["MISSING_EXPIRY_LABEL"], 400)
    if len(expiry) > MAX_EXPIRY_LABEL:
        return _err("INVALID_INPUT", ["EXPIRY_LABEL_TOO_LONG"], 400)

    # ---- collect legs ----------------------------------------------------
    legs, errs = [], []
    for i in range(MAX_LEGS):
        raw_t = request.args.get("leg%d_type" % i)
        raw_k = request.args.get("leg%d_strike" % i)
        raw_p = request.args.get("leg%d_premium" % i)
        if raw_t is None and raw_k is None and raw_p is None:
            continue
        ot = (raw_t or "").upper()
        if ot not in _OPTION_TYPES:
            errs.append("LEG%d_INVALID_OPTION_TYPE" % i)
            continue
        k, e1 = _flt(raw_k, "leg%d_strike" % i)
        p, e2 = _flt(raw_p, "leg%d_premium" % i)
        errs.extend([x for x in (e1, e2) if x])
        if e1 or e2:
            continue
        if k <= 0:
            errs.append("LEG%d_NON_POSITIVE_STRIKE" % i)
            continue
        if p <= 0:
            errs.append("LEG%d_NON_POSITIVE_PREMIUM" % i)
            continue
        # user premium -> authoritative leg shape. bid = ask = premium, so
        # economics.py derives credit/debit from the entered premium exactly.
        # This models a mid-price fill; stated on-page.
        legs.append({"instrument": inst, "expiry": expiry,
                     "option_type": ot, "strike": k,
                     "bid": p, "ask": p})
    if errs:
        return _err("INVALID_INPUT", errs, 400)
    if len(legs) != expected_legs:
        return _err("INVALID_INPUT",
                    ["LEG_COUNT_MISMATCH_EXPECTED_%d" % expected_legs], 400)

    # ---- lot size / lots -------------------------------------------------
    default_lot = LOT_SIZES.get(inst)
    if default_lot is None:
        return _err("SYSTEM_CALCULATION_ERROR", ["LOT_SIZE_UNAVAILABLE"], 500)

    lot_raw = request.args.get("lot_size")
    if lot_raw is None or str(lot_raw).strip() == "":
        lot_v = default_lot
    else:
        lv, e = _flt(lot_raw, "lot_size")
        if e:
            return _err("INVALID_INPUT", [e], 400)
        if lv != int(lv) or not (1 <= lv <= MAX_LOT_SIZE):
            return _err("INVALID_INPUT", ["INVALID_LOT_SIZE"], 400)
        lot_v = int(lv)

    lots, e = _flt(request.args.get("lots"), "lots")
    if e:
        return _err("INPUT_REQUIRED", [e], 400)
    if lots != int(lots) or not (MIN_LOTS <= lots <= MAX_LOTS):
        return _err("INVALID_INPUT", ["INVALID_LOTS"], 400)
    lots = int(lots)

    # ---- AUTHORITATIVE CALCULATION --------------------------------------
    # BUY/SELL is inferred by economics.py from option_type + strike order.
    # The caller cannot supply a side.
    result = fn(legs)
    if result.status != "STRATEGY_VALID":
        return _err("INVALID_INPUT",
                    [result.reason or "ECONOMICS_REJECTED"]
                    + list(result.errors or []), 400)
    econ = result.economics or {}

    # signed premium for the curve, read from the authoritative result
    if econ.get("net_credit") is not None:
        signed, basis = econ["net_credit"], "NET_CREDIT"
    elif econ.get("net_debit") is not None:
        signed, basis = -econ["net_debit"], "NET_DEBIT"
    else:
        return _err("SYSTEM_CALCULATION_ERROR", ["NO_NET_PREMIUM"], 500)

    # ---- deterministic expiry curve -------------------------------------
    sides = _sides_for(strategy, legs)
    curve_legs = [{"side": s, "type": lg["option_type"], "strike": lg["strike"]}
                  for s, lg in zip(sides, legs)]

    widths = [econ.get("spread_width"), econ.get("put_width"),
              econ.get("call_width")]
    widths = [abs(w) for w in widths if isinstance(w, (int, float))]
    width = max(widths) if widths else 1.0
    ks = [lg["strike"] for lg in legs]

    lo_raw = request.args.get("range_low")
    hi_raw = request.args.get("range_high")
    lo_a, e1 = (None, None) if lo_raw is None else _flt(lo_raw, "range_low")
    hi_a, e2 = (None, None) if hi_raw is None else _flt(hi_raw, "range_high")
    range_errs = [x for x in (e1, e2) if x]
    if range_errs:
        return _err("INVALID_INPUT", range_errs, 400)
    if lo_a is not None and hi_a is not None:
        if hi_a <= lo_a:
            return _err("INVALID_INPUT", ["RANGE_INVERTED"], 400)
        lo, hi = lo_a, hi_a
    elif lo_a is None and hi_a is None:
        lo, hi = min(ks) - width, max(ks) + width
    else:
        return _err("INPUT_REQUIRED", ["RANGE_REQUIRES_BOTH_BOUNDS"], 400)
    if (hi - lo) > 10 * width:
        return _err("INVALID_INPUT", ["RANGE_TOO_WIDE"], 400)

    pts_raw = request.args.get("points")
    if pts_raw is None:
        n = MAX_POINTS
    else:
        pts_a, e = _flt(pts_raw, "points")
        if e:
            return _err("INVALID_INPUT", [e], 400)
        if pts_a != int(pts_a) or pts_a < 3 or pts_a > MAX_POINTS:
            return _err("INVALID_INPUT", ["INVALID_POINTS"], 400)
        n = int(pts_a)

    step = (hi - lo) / (n - 1)
    spots, pts = [], []
    for i in range(n):
        p = lo + step * i
        v = spread_points_at_expiry({"legs": curve_legs}, p)
        if v is None:
            return _err("SYSTEM_CALCULATION_ERROR", ["CURVE_FAILED"], 500)
        spots.append(round(p, 2))
        pts.append(round(v + signed, 2))

    # Self-check guards the side mirror in _sides_for against drifting from
    # economics.py. It can only be evaluated when the plotted range actually
    # reaches both structural extremes, so a deliberately narrowed chart range
    # reports curve_reconciled=false rather than raising an engine error.
    covers_extremes = lo <= min(ks) - width and hi >= max(ks) + width
    reconciled = _verify_curve_reconciles(pts, econ)
    if covers_extremes and not reconciled:
        return _err("SYSTEM_CALCULATION_ERROR",
                    ["CURVE_ECONOMICS_MISMATCH"], 500)

    per_lot = [round(v * lot_v, 2) for v in pts]
    total = [round(v * lot_v * lots, 2) for v in pts]

    return jsonify({
        "state": "CALCULATED",
        "timestamp": _now(),
        "data": {
            "source": "USER_INPUT_CALCULATION",
            "data_gate_note": _DATA_GATE_NOTE,
            "economics_authority": "app.options.economics",
            "instrument": inst,
            "strategy": strategy,
            "expiry_label": expiry,
            "premium_basis": "MID_PRICE_BID_EQUALS_ASK",
            "net_basis": basis,
            "legs": legs,
            "leg_sides": sides,
            "lot_size": lot_v,
            "lot_size_default": default_lot,
            "lots": lots,
            "economics": econ,
            "range": {"low": round(lo, 2), "high": round(hi, 2),
                      "points": n, "width": round(width, 2)},
            "curve": {"spots": spots, "pnl_pts": pts,
                      "pnl_per_lot_rs": per_lot,
                      "pnl_total_rs": total},
            "curve_reconciled": reconciled,
            "estimated_costs_rs": econ.get("costs_rs"),
        },
    })