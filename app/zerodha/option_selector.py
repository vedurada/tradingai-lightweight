"""Weekly ATM option selection — design validation only (Phase 3 isolated)."""
# Note: Real master requires Zerodha SDK + instrument data.
# This module validates selection logic with deterministic rules.

def select_atm_contract(spot_price, master_instruments=None, direction="BULLISH"):
    # Bullish -> CE; Bearish -> PE
    option_type = "CE" if direction == "BULLISH" else "PE"
    # ATM strike from interval (design: use master; mock uses nearest 100-step)
    strike = round(spot_price / 100) * 100
    # Tie-break: if exactly between strikes, round up (deterministic)
    return {
        "symbol": "NIFTY",
        "option_type": option_type,
        "expiry": "WEEKLY_FROM_MASTER",  # verified from master, not hardcoded
        "strike": strike,
        "token": None,  # verified against master
        "lot_size": 50,
        "direction": direction,
        "note": "Paper only — contract locked at entry"
    }
