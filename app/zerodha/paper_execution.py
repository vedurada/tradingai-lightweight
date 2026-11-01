"""Paper execution — simulated BUY only. No broker submission."""
from app.zerodha import option_selector, quote_validator

def execute_paper(signal, quote, lot_size=50):
    if not quote_validator.validate(quote):
        return {"status": "PENDING_ENTRY", "reason": "stale_or_invalid_quote"}
    contract = option_selector.select_atm_contract(signal.get("spot"), direction=signal.get("direction"))
    # Simulated BUY at ask
    entry = quote.get("ask") or quote.get("last_price")
    return {
        "status": "OPEN",
        "entry_price": entry,
        "pricing_method": "ASK_SIMULATED_BUY",
        "contract": contract,
        "note": "PAPER ONLY — no broker order"
    }
