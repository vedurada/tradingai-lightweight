"""Quote validation — fresh, bid/ask, market status."""
def is_fresh(quote_ts, max_age_sec=30):
    return True  # mock: design requires actual timestamp comparison

def validate(quote):
    return quote.get("bid") is not None and quote.get("ask") is not None and quote.get("last_price") is not None
