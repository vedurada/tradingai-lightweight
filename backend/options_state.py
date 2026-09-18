from __future__ import annotations

"""Options State - per-symbol options intelligence state.

Composed from:
- Option chain data (CE/PE strikes, OI, IV, volume)
- PCR (put-call ratio)
- Max Pain
- Expected Move (from IV and DTE)
- Evidence/unertainty descriptions (NOT simplistic OI claims)

Principles:
- NEVER synthesize values — only observed, cached, derived, or unavailable
- Evidence describes what data shows, not what it guarantees
- Uncertainty is explicit when data is incomplete
- Mobile-first: structured for progressive disclosure
"""
import json
from typing import Any, Dict, List, Optional


class OptionsState:
    """Per-symbol options intelligence state.

    Immutable snapshot: once created, never modified.
    """

    def __init__(self, symbol: str, timestamp: str, *,
                 spot: Optional[float],
                 atm_strike: Optional[float],
                 expiry: Optional[str],
                 dte: Optional[int],
                 pcr: Optional[float],
                 pe_oi: Optional[int],
                 ce_oi: Optional[int],
                 total_oi: Optional[int],
                 max_pain: Optional[float],
                 iv_atm: Optional[float],
                 iv_rank: Optional[float],
                 expected_move: Optional[Dict[str, Any]],
                 bias: Optional[str],
                 confidence: Optional[int],
                 evidence: List[str],
                 uncertainty: List[str],
                 data_quality: str,
                 ce_chain: List[Dict] = None,
                 pe_chain: List[Dict] = None,
                 oi_buildup: Optional[Dict] = None):
        self.symbol = symbol
        self.timestamp = timestamp
        self.spot = spot
        self.atm_strike = atm_strike
        self.expiry = expiry
        self.dte = dte
        self.pcr = pcr
        self.pe_oi = pe_oi
        self.ce_oi = ce_oi
        self.total_oi = total_oi
        self.max_pain = max_pain
        self.iv_atm = iv_atm
        self.iv_rank = iv_rank
        self.expected_move = expected_move
        self.bias = bias
        self.confidence = confidence
        self.evidence = sorted(evidence or [])
        self.uncertainty = sorted(uncertainty or [])
        self.data_quality = data_quality
        self.ce_chain = ce_chain or []
        self.pe_chain = pe_chain or []
        self.oi_buildup = oi_buildup

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "spot": self.spot,
            "atm_strike": self.atm_strike,
            "expiry": self.expiry,
            "dte": self.dte,
            "pcr": self.pcr,
            "pe_oi": self.pe_oi,
            "ce_oi": self.ce_oi,
            "total_oi": self.total_oi,
            "max_pain": self.max_pain,
            "iv_atm": self.iv_atm,
            "iv_rank": self.iv_rank,
            "expected_move": self.expected_move,
            "bias": self.bias,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "data_quality": self.data_quality,
            "ce_chain": self.ce_chain,
            "pe_chain": self.pe_chain,
            "oi_buildup": self.oi_buildup,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def mobile_summary(self) -> dict[str, Any]:
        """Mobile-first summary: bias + key levels + options snapshot."""
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "bias": self.bias or "NEUTRAL",
            "confidence": self.confidence,
            "key_levels": {
                "support": None,
                "resistance": None,
                "max_pain": self.max_pain,
                "expected_range": self.expected_move,
            },
            "options": {
                "pcr": self.pcr,
                "atm": self.atm_strike,
                "iv": self.iv_atm,
                "max_pain": self.max_pain,
            },
            "data_quality": self.data_quality,
        }


def _describe_evidence(chain: List[Dict], symbol: str) -> List[str]:
    """Generate evidence descriptions from option chain data.

    Describes what the data shows, NOT what it guarantees.
    """
    evidence = []
    if not chain:
        return evidence

    total_oi = sum(c.get("open_interest") or 0 for c in chain)
    if (total_oi or 0) > 0:
        evidence.append(f"Total {symbol} OI: {total_oi:,} across {len(chain)} strikes")

    # Identify highest OI strikes
    sorted_by_oi = sorted(
        [c for c in chain if (c.get("open_interest") or 0) > 0],
        key=lambda c: c["open_interest"],
        reverse=True,
    )
    if sorted_by_oi:
        top = sorted_by_oi[0]
        side = "CE" if top.get("option_type") == "CE" else "PE"
        evidence.append(f"Highest {side} OI at strike {top['strike']}: {top['open_interest']:,}")

    # IV evidence
    ivs = [c.get("implied_volatility", 0) for c in chain if (c.get("implied_volatility") or 0) > 0]
    if ivs:
        avg_iv = sum(ivs) / len(ivs)
        evidence.append(f"ATM IV: {avg_iv:.2f}% across {len(ivs)} strikes with IV")

    return evidence


def _describe_uncertainty(state: OptionsState) -> List[str]:
    """Generate uncertainty descriptions based on data completeness."""
    uncertainty = []
    if state.iv_atm is None:
        uncertainty.append("IV unavailable: expected move estimate unavailable")
    if state.max_pain is None:
        uncertainty.append("Max Pain unavailable: insufficient chain data")
    if state.pcr is None:
        uncertainty.append("PCR unavailable: OI data incomplete")
    if state.dte is None or state.dte <= 0:
        uncertainty.append("Expiry unclear: time decay cannot be computed")
    if state.ce_oi is None and state.pe_oi is None:
        uncertainty.append("No OI data available for bias determination")
    if state.data_quality in ("DATA UNAVAILABLE", "STALE"):
        uncertainty.append(f"Data quality: {state.data_quality}")
    return uncertainty
