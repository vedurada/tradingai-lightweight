"""SQL guard — prevents SQL injection via f-string table names."""

ALLOWED_TABLES = {
    "price_1m", "price_1d", "price_5m", "price_15m",
    "vix_data", "vix_daily", "option_chain", "option_expiries",
    "live_quotes", "portfolio", "alerts", "chat_messages",
    "regime_data", "strategy_data", "scenarios", "outlook_data",
    "symbols", "market_data", "data_status", "indicators",
    "users", "api_keys",
    # B6.5: tables legitimately queried via dynamic names elsewhere.
    "market_outlooks", "market_snapshots", "market_regime", "strategies",
    "market_breadth", "index_breadth", "fundamentals", "etf_data",
    # Phase 9: Trade Journal
    "trade_journal", "trade_journal_events", "user_feedback",
}


def assert_table_name(table: str) -> None:
    assert table in ALLOWED_TABLES, f"Disallowed table: {table}"
