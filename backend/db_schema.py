from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    yfinance_symbol TEXT,
    type TEXT CHECK(type IN ('index', 'stock', 'etf', 'vix')),
    category TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT,
    lot_size INTEGER,
    lot_source TEXT,
    lot_as_of TEXT
);

CREATE TABLE IF NOT EXISTS price_1m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price1m_symbol_ts ON price_1m(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_price1m_ts ON price_1m(timestamp DESC);

CREATE TABLE IF NOT EXISTS price_5m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price5m_symbol_ts ON price_5m(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS price_15m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price15m_symbol_ts ON price_15m(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS price_1d (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adjusted_close REAL,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price1d_symbol_ts ON price_1d(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS vix_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    change REAL,
    change_pct REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_vix_ts ON vix_data(timestamp DESC);

CREATE TABLE IF NOT EXISTS option_expiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    expiry TEXT,
    fetched_at TEXT,
    UNIQUE(symbol, expiry)
);

CREATE TABLE IF NOT EXISTS option_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    expiry TEXT,
    strike REAL,
    option_type TEXT,
    last_price REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    open_interest INTEGER,
    change_in_oi INTEGER,
    implied_volatility REAL,
    bid_size INTEGER,
    ask_size INTEGER,
    fetched_at TEXT,
    UNIQUE(symbol, expiry, strike, option_type)
);
CREATE INDEX IF NOT EXISTS idx_opt_chain_symbol_expiry ON option_chain(symbol, expiry);
CREATE INDEX IF NOT EXISTS idx_opt_chain_strike ON option_chain(symbol, strike);

CREATE TABLE IF NOT EXISTS live_quotes (
    symbol TEXT PRIMARY KEY,
    timestamp TEXT,
    price REAL,
    open REAL,
    high REAL,
    low REAL,
    previous_close REAL,
    change REAL,
    change_pct REAL,
    volume INTEGER,
    source TEXT
);

CREATE TABLE IF NOT EXISTS index_breadth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name TEXT,
    timestamp TEXT,
    last REAL,
    change_pct REAL,
    advances INTEGER,
    declines INTEGER,
    unchanged INTEGER,
    open REAL,
    high REAL,
    low REAL,
    prev_close REAL,
    UNIQUE(index_name, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_idxbreadth_name_ts ON index_breadth(index_name, timestamp DESC);

CREATE TABLE IF NOT EXISTS market_breadth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    advances INTEGER,
    declines INTEGER,
    unchanged INTEGER,
    advance_decline_ratio REAL,
    pct_above_ema20 REAL,
    pct_above_ema50 REAL,
    pct_above_ema200 REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_breadth_ts ON market_breadth(timestamp DESC);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    nifty REAL,
    banknifty REAL,
    finnifty REAL,
    sensex REAL,
    vix REAL,
    vix_change_pct REAL,
    nifty_regime TEXT,
    banknifty_regime TEXT,
    breadth REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON market_snapshots(timestamp DESC);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    ema9 REAL,
    ema20 REAL,
    ema50 REAL,
    ema100 REAL,
    ema200 REAL,
    sma20 REAL,
    sma50 REAL,
    sma200 REAL,
    vwap REAL,
    rsi REAL,
    macd REAL,
    macd_signal REAL,
    macd_histogram REAL,
    atr REAL,
    adx REAL,
    di_plus REAL,
    di_minus REAL,
    bollinger_upper REAL,
    bollinger_middle REAL,
    bollinger_lower REAL,
    bollinger_width REAL,
    pivot REAL,
    r1 REAL, s1 REAL, r2 REAL, s2 REAL, r3 REAL, s3 REAL,
    cpr_classification TEXT,
    day_high REAL,
    day_low REAL,
    prev_day_high REAL,
    prev_day_low REAL,
    prev_day_close REAL,
    open_range_high REAL,
    open_range_low REAL,
    support_resistance TEXT DEFAULT '{}',
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ind_symbol_ts ON indicators(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    bullish_trigger TEXT,
    bullish_confirmation TEXT,
    bullish_target TEXT,
    bullish_invalidation TEXT,
    bearish_trigger TEXT,
    bearish_confirmation TEXT,
    bearish_target TEXT,
    bearish_invalidation TEXT,
    range_condition TEXT,
    range_strategy TEXT,
    range_invalidation TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_scen_symbol_ts ON scenarios(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    strategy TEXT,
    market_condition TEXT,
    expiry TEXT,
    legs TEXT,
    entry_trigger TEXT,
    maximum_profit TEXT,
    maximum_loss TEXT,
    breakeven TEXT,
    stop_loss TEXT,
    target TEXT,
    adjustment TEXT,
    exit TEXT,
    time_based_exit TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_strat_symbol_ts ON strategies(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS ai_outlooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    outlook TEXT,
    data_quality TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_outlook_symbol_ts ON ai_outlooks(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    alert_type TEXT,
    message TEXT,
    read INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol_ts ON alerts(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS market_regime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    regime TEXT,
    confidence REAL,
    trend TEXT,
    momentum TEXT,
    volatility TEXT,
    breadth TEXT,
    vix_regime TEXT,
    evidence TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_regime_symbol_ts ON market_regime(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    data TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_fund_symbol_ts ON fundamentals(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    symbol TEXT,
    headline TEXT,
    publisher TEXT,
    url TEXT,
    UNIQUE(timestamp, symbol, headline)
);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(timestamp DESC);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    action_type TEXT,
    value REAL,
    UNIQUE(symbol, timestamp, action_type)
);

CREATE TABLE IF NOT EXISTS data_status (
    symbol TEXT PRIMARY KEY,
    last_fetch TEXT,
    last_1m_fetch TEXT,
    last_5m_fetch TEXT,
    last_15m_fetch TEXT,
    last_options_fetch TEXT,
    last_breadth_fetch TEXT,
    last_vix_fetch TEXT,
    status TEXT,
    error_count INTEGER DEFAULT 0
);

-- B6.7: source-grained fetch health (the API-side _record_fetch_result writer
-- targets this table; the fetcher-side per-symbol data_status table is untouched).
CREATE TABLE IF NOT EXISTS fetch_health (
    source TEXT PRIMARY KEY,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    last_error TEXT,
    last_ok_at TEXT
);

CREATE TABLE IF NOT EXISTS etf_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    close REAL,
    change_pct REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_etf_symbol_ts ON etf_data(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS oi_top_strikes (
    symbol TEXT,
    expiry TEXT,
    side TEXT CHECK(side IN ('CE','PE')),
    rank INTEGER,
    strike REAL,
    open_interest INTEGER,
    fetched_at TEXT,
    PRIMARY KEY (symbol, expiry, side, rank)
);
CREATE INDEX IF NOT EXISTS idx_oi_symbol_expiry ON oi_top_strikes(symbol, expiry);

CREATE TABLE IF NOT EXISTS pcr_history (
    symbol TEXT,
    date TEXT,
    expiry TEXT,
    pcr REAL,
    max_pain REAL,
    pe_oi INTEGER,
    ce_oi INTEGER,
    total_oi INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_pcr_hist_sym_date ON pcr_history(symbol, date);

CREATE TABLE IF NOT EXISTS market_outlooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    symbol TEXT DEFAULT 'NIFTY',
    payload TEXT NOT NULL,
    created_at TEXT,
    UNIQUE(date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_market_outlooks_date ON market_outlooks(date DESC);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    date TEXT,
    locked_price REAL,
    closed_price REAL,
    entry_time TEXT DEFAULT '09:30',
    exit_time TEXT DEFAULT '15:20',
    direction TEXT DEFAULT 'LONG',
    points REAL,
    result TEXT,
    strategy TEXT,
    market_regime TEXT,
    directional_bias TEXT,
    confidence REAL,
    market_summary TEXT,
    evidence_strength REAL DEFAULT 0,
    volatility_classification TEXT,
    market_structure TEXT,
    no_trade_conditions TEXT,
    strategy_environment TEXT,
    invalidation TEXT,
    entry_outlook TEXT,
    created_at TEXT,
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_history_symbol_date ON history(symbol, date DESC);

CREATE TABLE IF NOT EXISTS investment_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    date TEXT,
    horizon TEXT CHECK(horizon IN ('SHORT', 'LONG')),
    rating TEXT,
    target_price REAL,
    stop_price REAL,
    fair_value REAL,
    reason TEXT,
    confidence REAL,
    score REAL,
    created_at TEXT,
    UNIQUE(symbol, date, horizon)
);
CREATE INDEX IF NOT EXISTS idx_invest_symbol_date ON investment_views(symbol, date DESC);

CREATE TABLE IF NOT EXISTS daily_strategy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    date TEXT,
    strategy_json TEXT,
    regime TEXT,
    confidence REAL,
    bias TEXT,
    locked_at TEXT DEFAULT '09:30',
    created_at TEXT,
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_dailystrat_symbol_date ON daily_strategy(symbol, date DESC);

CREATE TABLE IF NOT EXISTS history_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    date TEXT,
    locked_price REAL,
    closed_price REAL,
    entry_time TEXT DEFAULT '09:30',
    exit_time TEXT DEFAULT '15:20',
    direction TEXT DEFAULT 'LONG',
    points REAL,
    result TEXT,
    strategy TEXT,
    market_regime TEXT,
    directional_bias TEXT,
    confidence REAL,
    market_summary TEXT,
    entry_outlook TEXT,
    created_at TEXT,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    strategy TEXT,
    entry_price REAL,
    quantity INTEGER,
    direction TEXT,
    entry_date TEXT,
    exit_price REAL,
    exit_date TEXT,
    points REAL,
    result TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS mf_schemes (
    scheme_code TEXT PRIMARY KEY,
    scheme_name TEXT,
    fund_house TEXT,
    scheme_type TEXT,
    scheme_setting TEXT,
    is_direct INTEGER DEFAULT 0,
    category TEXT,
    amfi_category TEXT,
    nav REAL,
    nav_date TEXT,
    imported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mf_schemes_category ON mf_schemes(category, is_direct);

CREATE TABLE IF NOT EXISTS mf_returns (
    scheme_code TEXT PRIMARY KEY,
    scheme_name TEXT,
    fund_house TEXT,
    category TEXT,
    nav REAL,
    nav_date TEXT,
    ret_1y REAL,
    ret_3y REAL,
    ret_5y REAL,
    ret_days_1y INTEGER,
    expected_from TEXT,
    computed_at TEXT
);

CREATE TABLE IF NOT EXISTS etf_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    holding_symbol TEXT,
    holding_name TEXT,
    pct REAL,
    fetch_date TEXT,
    UNIQUE(symbol, holding_symbol)
);
CREATE INDEX IF NOT EXISTS idx_etf_holdings_symbol ON etf_holdings(symbol, pct DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT DEFAULT 'global',
    username TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT DEFAULT 'user' CHECK(kind IN ('user','system','alert')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_channel_created ON chat_messages(channel, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at DESC);

CREATE TABLE IF NOT EXISTS market_change_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    state TEXT NOT NULL,
    material_change INTEGER DEFAULT 0,
    changes TEXT DEFAULT '[]',
    UNIQUE(symbol, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_mkt_change_sym_ts ON market_change_snapshots(symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS ai_outlooks_5m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outlook_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    candle_timestamp TEXT,
    generated_at TEXT,
    model TEXT,
    model_version TEXT,
    prompt_version TEXT,
    data_snapshot_id TEXT,
    bias TEXT,
    confidence INTEGER DEFAULT 0,
    market_regime TEXT,
    summary TEXT,
    evidence_json TEXT DEFAULT '[]',
    watch_levels_json TEXT DEFAULT '[]',
    confirmation_json TEXT DEFAULT '[]',
    invalidation_json TEXT DEFAULT '[]',
    risk_json TEXT DEFAULT '[]',
    trade_state TEXT DEFAULT 'NO_TRADE',
    expected_horizon_minutes INTEGER DEFAULT 30,
    material_changes_json TEXT DEFAULT '[]',
    data_state TEXT DEFAULT 'UNAVAILABLE',
    created_at TEXT,
    UNIQUE(outlook_id)
);
CREATE INDEX IF NOT EXISTS idx_ai5m_instrument_ts ON ai_outlooks_5m(instrument, candle_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ai5m_generated ON ai_outlooks_5m(generated_at DESC);

CREATE TABLE IF NOT EXISTS ai_outcome_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outlook_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_price REAL,
    reference_price REAL,
    horizon_minutes INTEGER,
    future_return_pct REAL,
    correct BOOLEAN,
    mfe_pct REAL,
    mae_pct REAL,
    bias TEXT,
    recorded_at TEXT,
    evaluated_at TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outcome_outlook ON ai_outcome_predictions(outlook_id);
CREATE INDEX IF NOT EXISTS idx_outcome_symbol ON ai_outcome_predictions(symbol, recorded_at DESC);

CREATE TABLE IF NOT EXISTS market_snapshots_5m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    candle_timestamp TEXT NOT NULL,
    snapshot_time TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    vwap REAL,
    ema9 REAL,
    ema21 REAL,
    ema20 REAL,
    ema200 REAL,
    rsi REAL,
    rsi_14 REAL,
    macd REAL,
    macd_signal REAL,
    adx REAL,
    atr REAL,
    cpr_upper REAL,
    cpr_lower REAL,
    pivot REAL,
    support REAL,
    resistance REAL,
    prev_day_high REAL,
    prev_day_low REAL,
    price_vs_vwap TEXT,
    trend_state TEXT,
    volatility_state TEXT,
    regime TEXT,
    vix REAL,
    pcr REAL,
    call_oi REAL,
    put_oi REAL,
    expected_move REAL,
    max_pain REAL,
    data_state TEXT DEFAULT 'LIVE',
    data_timestamp TEXT,
    created_at TEXT,
    UNIQUE(symbol, candle_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_snap5m_sym_ts ON market_snapshots_5m(symbol, candle_timestamp DESC);
 """

def init_database(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript(SCHEMA)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    # Migrate existing DBs: add columns introduced after initial schema.
    try:
        c.execute("PRAGMA table_info(symbols)")
        sym_cols = {row[1] for row in c.fetchall()}
        if "lot_size" not in sym_cols:
            c.execute("ALTER TABLE symbols ADD COLUMN lot_size INTEGER")
        if "lot_source" not in sym_cols:
            c.execute("ALTER TABLE symbols ADD COLUMN lot_source TEXT")
        if "lot_as_of" not in sym_cols:
            c.execute("ALTER TABLE symbols ADD COLUMN lot_as_of TEXT")
        c.execute("PRAGMA table_info(indicators)")
        ind_cols = {row[1] for row in c.fetchall()}
        if "support_resistance" not in ind_cols:
            c.execute("ALTER TABLE indicators ADD COLUMN support_resistance TEXT DEFAULT '{}'")
        c.execute("PRAGMA table_info(history)")
        hist_cols = {row[1] for row in c.fetchall()}
        if "entry_time" not in hist_cols:
            c.execute("ALTER TABLE history ADD COLUMN entry_time TEXT DEFAULT '09:30'")
        if "exit_time" not in hist_cols:
            c.execute("ALTER TABLE history ADD COLUMN exit_time TEXT DEFAULT '15:20'")
        if "direction" not in hist_cols:
            c.execute("ALTER TABLE history ADD COLUMN direction TEXT DEFAULT 'LONG'")
        if "entry_outlook" not in hist_cols:
            c.execute("ALTER TABLE history ADD COLUMN entry_outlook TEXT")
        c.execute("PRAGMA table_info(history_archive)")
        arch_cols = {row[1] for row in c.fetchall()}
        if "entry_time" not in arch_cols:
            c.execute("ALTER TABLE history_archive ADD COLUMN entry_time TEXT DEFAULT '09:30'")
        if "exit_time" not in arch_cols:
            c.execute("ALTER TABLE history_archive ADD COLUMN exit_time TEXT DEFAULT '15:20'")
        if "direction" not in arch_cols:
            c.execute("ALTER TABLE history_archive ADD COLUMN direction TEXT DEFAULT 'LONG'")
        if "entry_outlook" not in arch_cols:
            c.execute("ALTER TABLE history_archive ADD COLUMN entry_outlook TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")

if __name__ == "__main__":
    init_database()
