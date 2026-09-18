from __future__ import annotations

"""Options Normalizer - Chain data processing using frozen OptionsEngine.

Uses backend/options.py (frozen) for computation.
Provides:
- ATM strike identification
- CE/PE chain separation
- OI summaries
- Evidence/uncertainty generation
"""
import sys
import os
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from options import OptionsEngine
from options_state import OptionsState, _describe_evidence, _describe_uncertainty


def _find_atm_strike(chain: List[Dict], spot: float) -> Optional[float]:
    """Find ATM strike (closest to spot)."""
    if not chain or spot <= 0:
        return None
    valid = [c for c in chain if (c.get("strike") or 0) > 0]
    if not valid:
        return None
    return min(valid, key=lambda c: abs(c["strike"] - spot))["strike"]


def _build_chain_summary(chain: List[Dict], symbol: str) -> Dict[str, Any]:
    """Build summary from a CE or PE chain."""
    if not chain:
        return {"total_oi": 0, "strikes": 0, "max_oi_strike": None, "max_oi": 0}
    total_oi = sum(c.get("open_interest", 0) for c in chain)
    strikes = len(set(c.get("strike") or 0 for c in chain if (c.get("strike") or 0) > 0))
    by_oi = sorted(
        [c for c in chain if (c.get("open_interest") or 0) > 0],
        key=lambda c: c["open_interest"],
        reverse=True,
    )
    max_oi_strike = by_oi[0]["strike"] if by_oi else None
    max_oi = by_oi[0]["open_interest"] if by_oi else 0
    return {
        "total_oi": total_oi,
        "strikes": strikes,
        "max_oi_strike": max_oi_strike,
        "max_oi": max_oi,
    }


def build_options_state(symbol: str, chain: List[Dict], spot: float,
                          expiry: Optional[str] = None,
                          data_quality: str = "LIVE") -> Optional[OptionsState]:
    """Build complete OptionsState from option chain and spot price.

    Uses frozen OptionsEngine for all computations.
    """
    if not chain or spot <= 0:
        return OptionsState(
            symbol=symbol, timestamp="", spot=spot,
            atm_strike=None, expiry=expiry, dte=None,
            pcr=None, pe_oi=None, ce_oi=None, total_oi=None,
            max_pain=None, iv_atm=None, iv_rank=None,
            expected_move=None, bias="NEUTRAL", confidence=0,
            evidence=[], uncertainty=["No option chain data available"],
            data_quality=data_quality,
        )

    engine = OptionsEngine()
    ce_chain = [c for c in chain if c.get("option_type") == "CE"]
    pe_chain = [c for c in chain if c.get("option_type") == "PE"]

    ce_oi = sum(c.get("open_interest") or 0 for c in ce_chain)
    pe_oi = sum(c.get("open_interest") or 0 for c in pe_chain)
    total_oi = ce_oi + pe_oi

    pcr = engine.calculate_pcr(ce_oi, pe_oi) if (ce_oi or 0) > 0 else None
    max_pain_result = engine.calculate_max_pain(chain)
    max_pain = max_pain_result.get("max_pain") if isinstance(max_pain_result, dict) else None
    iv_stats = engine.calculate_iv_stats(chain)
    atm_strike = _find_atm_strike(chain, spot)
    dte = None
    if expiry:
        from datetime import datetime as _dt, timezone as _tz
        try:
            expiry_date = _dt.strptime(str(expiry), "%Y-%m-%d")
            dte = (expiry_date.date() - _dt.now(_tz.utc).date()).days
        except Exception:
            dte = None

    expected_move_result = engine.compute_expected_move(chain, spot, expiry) if expiry else None
    expected_move = expected_move_result.get("expected_move") if isinstance(expected_move_result, dict) else None

    bias_result = engine.derive_options_bias(
        max_pain, spot, pcr,
        {"call_total": ce_oi, "put_total": pe_oi, "total_oi": total_oi},
    )
    bias = bias_result.get("options_bias", "NEUTRAL") if isinstance(bias_result, dict) else "NEUTRAL"
    confidence = bias_result.get("options_confidence", 0) if isinstance(bias_result, dict) else 0

    confirmation_result = engine.compute_confirmation(
        market_bias=bias, market_confidence=confidence,
        options_bias=bias_result.get("options_bias", "NEUTRAL") if isinstance(bias_result, dict) else "NEUTRAL",
        options_confidence=confidence,
        pcr_value=pcr, max_pain_strike=max_pain, spot=spot,
        expected_move_points=expected_move.get("points") if isinstance(expected_move, dict) else None,
        oi_concentration=engine.compute_oi_concentration(chain) if chain else {},
    )

    evidence = _describe_evidence(chain, symbol)
    uncertainty = _describe_uncertainty(OptionsState(
        symbol=symbol, timestamp="", spot=spot,
        atm_strike=atm_strike, expiry=expiry, dte=dte,
        pcr=pcr, pe_oi=pe_oi, ce_oi=ce_oi, total_oi=total_oi,
        max_pain=max_pain, iv_atm=iv_stats.get("avg_iv"), iv_rank=iv_stats.get("iv_rank"),
        expected_move=expected_move, bias=bias, confidence=confidence,
        evidence=[], uncertainty=[], data_quality=data_quality,
    ))

    return OptionsState(
        symbol=symbol, timestamp="", spot=spot,
        atm_strike=atm_strike, expiry=expiry, dte=dte,
        pcr=pcr, pe_oi=pe_oi, ce_oi=ce_oi, total_oi=total_oi,
        max_pain=max_pain, iv_atm=iv_stats.get("avg_iv"), iv_rank=iv_stats.get("iv_rank"),
        expected_move=expected_move, bias=bias, confidence=confidence,
        evidence=evidence, uncertainty=uncertainty,
        data_quality=data_quality,
        ce_chain=_build_chain_summary(ce_chain, symbol),
        pe_chain=_build_chain_summary(pe_chain, symbol),
    )
