from __future__ import annotations

from typing import Any


class OptionsEngine:
    def __init__(self) -> None:
        pass

    def calculate_pcr(self, call_oi: float, put_oi: float) -> float:
        if call_oi == 0:
            return 0.0
        return round(put_oi / call_oi, 3)

    def _max_pain_aggregate_payout(self, contracts: list[dict]) -> dict[str, Any]:
        """
        Calculate Max Pain strike: the strike that minimizes the aggregate
        intrinsic payout of all options at expiration.

        For each candidate settlement strike K:
        - Calls: max(K - strike, 0) × Call OI
        - Puts: max(strike - K, 0) × Put OI
        Max Pain = K producing the minimum aggregate payout.
        """
        if not contracts:
            return {"max_pain": None, "pain_details": {}, "min_payout": None}

        # Group open interest by strike and option type
        calls_by_strike = {}
        puts_by_strike = {}
        for c in contracts:
            strike = c.get("strike", 0)
            oi = c.get("open_interest", 0)
            opt_type = c.get("option_type", "")
            if strike <= 0 or oi <= 0:
                continue
            if opt_type == "CE":
                calls_by_strike[strike] = calls_by_strike.get(strike, 0) + oi
            elif opt_type == "PE":
                puts_by_strike[strike] = puts_by_strike.get(strike, 0) + oi

        # Get all unique strikes
        all_strikes = sorted(list(set(list(calls_by_strike.keys()) + list(puts_by_strike.keys()))))

        # Calculate aggregate payout for each candidate settlement strike
        pain_details = {}
        for settlement in all_strikes:
            total_payout = 0.0
            # Call payouts: max(settlement - strike, 0) × Call OI
            for strike, call_oi in calls_by_strike.items():
                total_payout += max(settlement - strike, 0) * call_oi
            # Put payouts: max(strike - settlement, 0) × Put OI
            for strike, put_oi in puts_by_strike.items():
                total_payout += max(strike - settlement, 0) * put_oi
            pain_details[settlement] = total_payout

        if not pain_details:
            return {"max_pain": None, "pain_details": {}, "min_payout": None}

        # Max Pain = strike with minimum aggregate payout
        max_pain_strike = min(pain_details, key=pain_details.get)
        return {
            "max_pain": max_pain_strike,
            "pain_details": pain_details,
            "min_payout": pain_details[max_pain_strike],
        }

    def calculate_max_pain(self, contracts: list[dict]) -> dict[str, Any]:
        """
        Public API: calculate Max Pain strike from options contracts.
        Returns the strike producing the minimum aggregate option-holder payout.
        """
        result = self._max_pain_aggregate_payout(contracts)
        # Return a simple dict for backward compatibility with existing callers
        return {"max_pain": result["max_pain"]}

    def calculate_iv_stats(self, contracts: list[dict]) -> dict[str, Any]:
        ivs = [c.get("implied_volatility", 0) for c in contracts if c.get("implied_volatility")]
        if not ivs:
            return {"avg_iv": 0, "min_iv": 0, "max_iv": 0, "iv_rank": 0}
        avg_iv = sum(ivs) / len(ivs)
        return {"avg_iv": round(avg_iv, 2), "min_iv": round(min(ivs), 2), "max_iv": round(max(ivs), 2), "iv_rank": round(((avg_iv - min(ivs)) / (max(ivs) - min(ivs)) * 100) if max(ivs) > min(ivs) else 50, 1)}

    def compute_expected_move(self, contracts: list[dict], underlying_price: float, expiry: str) -> dict[str, Any]:
        if not contracts or underlying_price <= 0 or not expiry:
            return {
                "expected_move": {
                    "type": None,
                    "points": "DATA TEMPORARILY UNAVAILABLE",
                    "lower": "DATA TEMPORARILY UNAVAILABLE",
                    "upper": "DATA TEMPORARILY UNAVAILABLE",
                    "methodology": None,
                    "expiry": expiry,
                    "atm_strike": None,
                    "data_quality": "DATA TEMPORARILY UNAVAILABLE",
                }
            }

        ce_atm_iv = None
        pe_atm_iv = None
        atm_strike = None

        ce_contracts = [c for c in contracts if c.get("option_type") == "CE" and c.get("strike", 0) > 0]
        pe_contracts = [c for c in contracts if c.get("option_type") == "PE" and c.get("strike", 0) > 0]

        if ce_contracts:
            atm_ce = min(ce_contracts, key=lambda c: abs(c["strike"] - underlying_price))
            atm_strike = atm_ce["strike"]
            ce_atm_iv = atm_ce.get("implied_volatility")
            if ce_atm_iv is not None and ce_atm_iv <= 0:
                ce_atm_iv = None

        if pe_contracts:
            atm_pe = min(pe_contracts, key=lambda c: abs(c["strike"] - underlying_price))
            if atm_strike is None or abs(atm_pe["strike"] - underlying_price) < abs(atm_strike - underlying_price):
                atm_strike = atm_pe["strike"]
            pe_atm_iv = atm_pe.get("implied_volatility")
            if pe_atm_iv is not None and pe_atm_iv <= 0:
                pe_atm_iv = None

        if atm_strike is None:
            return {
                "expected_move": {
                    "type": "options_implied",
                    "points": "DATA TEMPORARILY UNAVAILABLE",
                    "lower": "DATA TEMPORARILY UNAVAILABLE",
                    "upper": "DATA TEMPORARILY UNAVAILABLE",
                    "methodology": "ATF strike could not be determined from available option chain",
                    "expiry": expiry,
                    "atm_strike": None,
                    "data_quality": "DATA TEMPORARILY UNAVAILABLE",
                }
            }

        atm_iv = None
        if ce_atm_iv is not None and pe_atm_iv is not None:
            atm_iv = (ce_atm_iv + pe_atm_iv) / 2
        elif ce_atm_iv is not None:
            atm_iv = ce_atm_iv
        elif pe_atm_iv is not None:
            atm_iv = pe_atm_iv

        if atm_iv is None or atm_iv <= 0:
            return {
                "expected_move": {
                    "type": "options_implied",
                    "points": "DATA TEMPORARILY UNAVAILABLE",
                    "lower": "DATA TEMPORARILY UNAVAILABLE",
                    "upper": "DATA TEMPORARILY UNAVAILABLE",
                    "methodology": "ATM implied volatility unavailable for expected move calculation",
                    "expiry": expiry,
                    "atm_strike": atm_strike,
                    "data_quality": "DATA TEMPORARILY UNAVAILABLE",
                }
            }

        from datetime import datetime as _dt, timezone as _tz
        try:
            expiry_date = _dt.strptime(str(expiry), "%Y-%m-%d")
        except Exception:
            expiry_date = _dt.strptime(str(expiry), "%d-%b-%Y")
        today = _dt.now(_tz.utc).date()
        if isinstance(expiry_date, _dt):
            expiry_date = expiry_date.date()
        dte = (expiry_date - today).days

        if dte <= 0:
            return {
                "expected_move": {
                    "type": "options_implied",
                    "points": "DATA TEMPORARILY UNAVAILABLE",
                    "lower": "DATA TEMPORARILY UNAVAILABLE",
                    "upper": "DATA TEMPORARILY UNAVAILABLE",
                    "methodology": "Expiry date is today or in the past; cannot compute time decay",
                    "expiry": expiry,
                    "atm_strike": atm_strike,
                    "data_quality": "DATA TEMPORARILY UNAVAILABLE",
                }
            }

        expected_points = atm_iv / 100 * (dte / 365) ** 0.5 * underlying_price
        expected_points = round(expected_points, 2)
        lower = round(underlying_price - expected_points, 2)
        upper = round(underlying_price + expected_points, 2)

        return {
            "expected_move": {
                "type": "options_implied",
                "points": expected_points,
                "lower": lower,
                "upper": upper,
                "methodology": "ATM IV × sqrt(DTE/365) × Spot Price (1 standard deviation expected move)",
                "expiry": expiry,
                "atm_strike": atm_strike,
                "data_quality": "LIVE",
            }
        }

    def compute_oi_concentration(self, contracts: list[dict]) -> dict[str, Any]:
        if not contracts:
            return {
                "call_oi": 0, "put_oi": 0, "total_oi": 0,
                "call_oi_change": "DATA TEMPORARILY UNAVAILABLE",
                "put_oi_change": "DATA TEMPORARILY UNAVAILABLE",
                "oi_change_available": False,
                "highest_call_oi": None,
                "highest_put_oi": None,
                "oi_concentration": {},
                "major_call_zones": [],
                "major_put_zones": [],
                "strikes": [],
            }

        call_oi_by_strike = {}
        put_oi_by_strike = {}
        call_oi_change_by_strike = {}
        put_oi_change_by_strike = {}
        for c in contracts:
            strike = c.get("strike", 0)
            oi = c.get("open_interest", 0)
            opt_type = c.get("option_type", "")
            coi = c.get("change_in_oi", 0)
            if strike <= 0:
                continue
            if opt_type == "CE":
                call_oi_by_strike[strike] = call_oi_by_strike.get(strike, 0) + oi
                call_oi_change_by_strike[strike] = call_oi_change_by_strike.get(strike, 0) + coi
            elif opt_type == "PE":
                put_oi_by_strike[strike] = put_oi_by_strike.get(strike, 0) + oi
                put_oi_change_by_strike[strike] = put_oi_change_by_strike.get(strike, 0) + coi

        call_oi = sum(call_oi_by_strike.values())
        put_oi = sum(put_oi_by_strike.values())
        total_oi = call_oi + put_oi

        all_strikes = sorted(set(list(call_oi_by_strike.keys()) + list(put_oi_by_strike.keys())))

        all_change = list(call_oi_change_by_strike.values()) + list(put_oi_change_by_strike.values())
        oi_change_available = any(c > 0 for c in all_change) if all_change else False

        call_oi_change = "DATA TEMPORARILY UNAVAILABLE"
        put_oi_change = "DATA TEMPORARILY UNAVAILABLE"
        if oi_change_available:
            call_oi_change = sum(v for v in call_oi_change_by_strike.values() if v > 0) or 0
            put_oi_change = sum(v for v in put_oi_change_by_strike.values() if v > 0) or 0

        highest_call = None
        if call_oi_by_strike:
            top_strike = max(call_oi_by_strike, key=call_oi_by_strike.get)
            highest_call = {
                "strike": top_strike,
                "oi": call_oi_by_strike[top_strike],
                "pct_of_call_oi": round(call_oi_by_strike[top_strike] / call_oi * 100, 2) if call_oi else 0,
            }

        highest_put = None
        if put_oi_by_strike:
            top_strike = max(put_oi_by_strike, key=put_oi_by_strike.get)
            highest_put = {
                "strike": top_strike,
                "oi": put_oi_by_strike[top_strike],
                "pct_of_put_oi": round(put_oi_by_strike[top_strike] / put_oi * 100, 2) if put_oi else 0,
            }

        top_call_pct = round(max(call_oi_by_strike.values()) / call_oi * 100, 2) if call_oi else 0
        top_put_pct = round(max(put_oi_by_strike.values()) / put_oi * 100, 2) if put_oi else 0

        top3_call_strikes = sorted(call_oi_by_strike, key=call_oi_by_strike.get, reverse=True)[:3]
        top3_call_total = sum(call_oi_by_strike[s] for s in top3_call_strikes)
        top3_call_pct = round(top3_call_total / call_oi * 100, 2) if call_oi else 0

        top3_put_strikes = sorted(put_oi_by_strike, key=put_oi_by_strike.get, reverse=True)[:3]
        top3_put_total = sum(put_oi_by_strike[s] for s in top3_put_strikes)
        top3_put_pct = round(top3_put_total / put_oi * 100, 2) if put_oi else 0

        major_call_zones = []
        if call_oi > 0:
            for strike in sorted(call_oi_by_strike, key=call_oi_by_strike.get, reverse=True):
                pct = call_oi_by_strike[strike] / call_oi * 100
                if pct >= 10:
                    major_call_zones.append({"strike": strike, "oi": call_oi_by_strike[strike], "pct": round(pct, 2)})
                else:
                    break

        major_put_zones = []
        if put_oi > 0:
            for strike in sorted(put_oi_by_strike, key=put_oi_by_strike.get, reverse=True):
                pct = put_oi_by_strike[strike] / put_oi * 100
                if pct >= 10:
                    major_put_zones.append({"strike": strike, "oi": put_oi_by_strike[strike], "pct": round(pct, 2)})
                else:
                    break

        strike_data = []
        for strike in all_strikes:
            co = call_oi_by_strike.get(strike, 0)
            po = put_oi_by_strike.get(strike, 0)
            strike_data.append({
                "strike": strike,
                "call_oi": co,
                "put_oi": po,
                "total_oi": co + po,
                "call_pct": round(co / call_oi * 100, 2) if call_oi else 0,
                "put_pct": round(po / put_oi * 100, 2) if put_oi else 0,
            })

        return {
            "call_oi": call_oi,
            "put_oi": put_oi,
            "total_oi": total_oi,
            "call_oi_change": call_oi_change,
            "put_oi_change": put_oi_change,
            "oi_change_available": oi_change_available,
            "highest_call_oi": highest_call,
            "highest_put_oi": highest_put,
            "oi_concentration": {
                "top_call_strike_pct": top_call_pct,
                "top_put_strike_pct": top_put_pct,
                "top3_call_pct": top3_call_pct,
                "top3_put_pct": top3_put_pct,
            },
            "major_call_zones": major_call_zones,
            "major_put_zones": major_put_zones,
            "strikes": strike_data,
        }

    def compute_confirmation(self, market_bias: str, market_confidence: int,
                             options_bias: str, options_confidence: int,
                             pcr_value: float = None, max_pain_strike: float = None,
                             spot: float = None, expected_move_points: float = None,
                             oi_concentration: dict = None) -> dict[str, Any]:
        reasons = []
        data_quality = "LIVE"

        if market_bias is None and options_bias is None:
            return {
                "confirmation": {
                    "status": "UNAVAILABLE",
                    "market_bias": market_bias,
                    "options_bias": options_bias,
                    "market_confidence": market_confidence,
                    "options_confidence": options_confidence,
                    "reasons": ["Both market and options data unavailable"],
                    "data_quality": "UNAVAILABLE",
                }
            }

        directional_market = market_bias in ("BULLISH", "BEARISH") if market_bias else False
        directional_options = options_bias in ("BULLISH", "BEARISH") if options_bias else False

        if not directional_market and not directional_options:
            return {
                "confirmation": {
                    "status": "NEUTRAL",
                    "market_bias": market_bias,
                    "options_bias": options_bias,
                    "market_confidence": market_confidence,
                    "options_confidence": options_confidence,
                    "reasons": ["Neither market nor options side has sufficient directional evidence"],
                    "data_quality": data_quality,
                }
            }

        if not directional_options:
            return {
                "confirmation": {
                    "status": "UNAVAILABLE" if options_bias is None else "PARTIAL CONFIRMATION",
                    "market_bias": market_bias,
                    "options_bias": options_bias,
                    "market_confidence": market_confidence,
                    "options_confidence": options_confidence,
                    "reasons": (["Options data unavailable, cannot confirm market view"]
                                if options_bias is None
                                else ["Options view is NEUTRAL, market view directional but not confirmed"]),
                    "data_quality": data_quality,
                }
            }

        if not directional_market:
            return {
                "confirmation": {
                    "status": "PARTIAL CONFIRMATION",
                    "market_bias": market_bias,
                    "options_bias": options_bias,
                    "market_confidence": market_confidence,
                    "options_confidence": options_confidence,
                    "reasons": ["Market view is NEUTRAL, options view directional but not confirmed"],
                    "data_quality": data_quality,
                }
            }

        mkt = market_bias.upper()
        opt = options_bias.upper()

        if mkt == opt:
            agreement_strength = min(market_confidence, options_confidence) / 100
            status = "CONFIRMED" if agreement_strength >= 0.6 else "PARTIAL CONFIRMATION"
            if status == "CONFIRMED":
                reasons.append(f"Market {mkt} (confidence {market_confidence}/100) aligns with options {opt} (confidence {options_confidence}/100)")
            else:
                reasons.append(f"Market {mkt} and options {opt} agree but confidence is moderate ({market_confidence}/{options_confidence})")
        else:
            status = "DIVERGENCE"
            reasons.append(f"Market {mkt} (confidence {market_confidence}/100) diverges from options {opt} (confidence {options_confidence}/100)")

        if pcr_value is not None and pcr_value > 0:
            if pcr_value > 1.5:
                reasons.append(f"PCR {pcr_value:.2f} indicates put-dominated positioning")
            elif pcr_value < 0.7:
                reasons.append(f"PCR {pcr_value:.2f} indicates call-dominated positioning")
            else:
                reasons.append(f"PCR {pcr_value:.2f} indicates balanced positioning")

        if max_pain_strike is not None and spot and spot > 0:
            distance = (max_pain_strike - spot) / spot * 100
            if abs(distance) < 1:
                reasons.append(f"Max Pain {max_pain_strike} near spot {spot:.2f} (within 1%)")
            elif distance > 0:
                reasons.append(f"Max Pain {max_pain_strike} is {distance:.1f}% above spot {spot:.2f}")
            else:
                reasons.append(f"Max Pain {max_pain_strike} is {abs(distance):.1f}% below spot {spot:.2f}")

        if expected_move_points is not None and isinstance(expected_move_points, (int, float)) and expected_move_points > 0:
            reasons.append(f"Options implied expected move ±{expected_move_points:.0f} points")

        if oi_concentration:
            top_call = oi_concentration.get("highest_call_oi")
            top_put = oi_concentration.get("highest_put_oi")
            if top_call and top_call.get("pct_of_call_oi", 0) >= 30:
                reasons.append(f"Call OI concentrated at strike {top_call['strike']} ({top_call['pct_of_call_oi']:.1f}% of total)")
            if top_put and top_put.get("pct_of_put_oi", 0) >= 30:
                reasons.append(f"Put OI concentrated at strike {top_put['strike']} ({top_put['pct_of_put_oi']:.1f}% of total)")

        return {
            "confirmation": {
                "status": status,
                "market_bias": market_bias,
                "options_bias": options_bias,
                "market_confidence": market_confidence,
                "options_confidence": options_confidence,
                "reasons": reasons,
                "data_quality": data_quality,
            }
        }

    def derive_options_bias(self, max_pain_strike: float, spot: float, pcr_value: float = None,
                            oi_concentration: dict = None) -> dict[str, Any]:
        if max_pain_strike is None or spot is None or spot <= 0:
            return {
                "options_bias": None,
                "options_confidence": 0,
                "data_quality": "DATA TEMPORARILY UNAVAILABLE",
                "reasons": ["Max Pain or spot unavailable, cannot derive options bias"],
            }

        score = 0.0
        reasons = []
        signals = 0

        distance_pct = (max_pain_strike - spot) / spot * 100
        signals += 1
        if abs(distance_pct) < 1:
            score += 0
            reasons.append(f"Max Pain {max_pain_strike} near spot {spot:.0f} — neutral positioning")
        elif distance_pct > 0:
            score -= min(distance_pct / 5, 1)
            reasons.append(f"Max Pain {max_pain_strike} {distance_pct:.1f}% above spot → bearish lean")
        else:
            score += min(abs(distance_pct) / 5, 1)
            reasons.append(f"Max Pain {max_pain_strike} {abs(distance_pct):.1f}% below spot → bullish lean")

        if pcr_value is not None and pcr_value > 0:
            signals += 1
            if pcr_value > 1.5:
                score -= 0.5
                reasons.append(f"PCR {pcr_value:.2f} put-dominated → bearish")
            elif pcr_value < 0.7:
                score += 0.5
                reasons.append(f"PCR {pcr_value:.2f} call-dominated → bullish")
            else:
                reasons.append(f"PCR {pcr_value:.2f} balanced")

        if oi_concentration:
            top_call = oi_concentration.get("highest_call_oi")
            top_put = oi_concentration.get("highest_put_oi")
            if top_call and top_put:
                signals += 1
                call_pct = top_call.get("pct_of_call_oi", 0)
                put_pct = top_put.get("pct_of_put_oi", 0)
                if call_pct >= put_pct * 1.5:
                    score += 0.5
                    reasons.append(f"Call concentration ({call_pct:.1f}%) exceeds put ({put_pct:.1f}%) → bullish")
                elif put_pct >= call_pct * 1.5:
                    score -= 0.5
                    reasons.append(f"Put concentration ({put_pct:.1f}%) exceeds call ({call_pct:.1f}%) → bearish")

        if score > 0.5:
            bias = "BULLISH"
        elif score < -0.5:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        if signals == 0:
            confidence = 0
        else:
            confidence = round(abs(score) / signals * 100 + 30, 0)
            confidence = max(10, min(100, confidence))

        return {
            "options_bias": bias,
            "options_confidence": int(confidence),
            "data_quality": "LIVE",
            "reasons": reasons,
        }

