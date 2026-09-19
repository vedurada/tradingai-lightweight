CREATE TABLE instruments (
    instrument_id TEXT PRIMARY KEY, symbol TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    exchange TEXT NOT NULL, instrument_type TEXT NOT NULL, timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE trading_sessions (
    session_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, date TEXT NOT NULL,
    open_time TEXT NOT NULL, close_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'COMPLETED',
    total_candles INTEGER NOT NULL DEFAULT 0, open_price REAL, high_price REAL, low_price REAL, close_price REAL,
    range REAL, gap REAL, trend TEXT, volatility REAL, vwap REAL, cpr_pivot REAL, cpr_r1 REAL, cpr_r2 REAL, cpr_s1 REAL, cpr_s2 REAL,
    created_at TEXT NOT NULL, FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id));
CREATE TABLE market_candles_5m (
    candle_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, data_state TEXT NOT NULL DEFAULT 'LIVE',
    ingested_at TEXT NOT NULL, session_id TEXT, is_complete INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id));
CREATE TABLE market_snapshots (
    snapshot_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    price REAL, change REAL, change_pct REAL, vwap REAL, ema20 REAL, ema200 REAL, rsi REAL,
    adx REAL, macd REAL, macd_signal REAL, atr REAL, cpr_pivot REAL, cpr_r1 REAL, cpr_r2 REAL,
    cpr_s1 REAL, cpr_s2 REAL, india_vix REAL, trend TEXT, vwap_relation TEXT, momentum TEXT,
    volatility TEXT, structure TEXT, opening_behavior TEXT, data_state TEXT NOT NULL DEFAULT 'LIVE',
    created_at TEXT NOT NULL, FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id));
CREATE TABLE market_levels (
    level_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    prev_close REAL, prev_high REAL, prev_low REAL, day_high REAL, day_low REAL, vwap REAL,
    pivot REAL, r1 REAL, r2 REAL, s1 REAL, s2 REAL, support1 REAL, support2 REAL,
    resistance1 REAL, resistance2 REAL, created_at TEXT NOT NULL);
CREATE TABLE volatility_snapshots (
    vol_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    implied_volatility REAL, historical_volatility REAL, expected_move REAL, atm_premium REAL,
    pcr REAL, open_interest INTEGER, volume INTEGER, expiry TEXT, data_state TEXT NOT NULL DEFAULT 'LIVE',
    created_at TEXT NOT NULL);
CREATE TABLE historical_sessions (
    session_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, range REAL, gap REAL, trend TEXT, vwap REAL,
    atr REAL, volatility REAL, cpr_pivot REAL, cpr_r1 REAL, cpr_r2 REAL, cpr_s1 REAL, cpr_s2 REAL,
    opening_range REAL, first_15m_change REAL, first_30m_change REAL, first_60m_change REAL,
    high_low_pct REAL, range_pct REAL, vol_rank TEXT, regime TEXT, features TEXT, created_at TEXT NOT NULL);
CREATE TABLE scenario_definitions (
    definition_id TEXT PRIMARY KEY, scenario_type TEXT NOT NULL, description TEXT NOT NULL,
    required_conditions TEXT NOT NULL, confirmation_conditions TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL, expiry_conditions TEXT, direction TEXT, objective TEXT,
    active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE scenario_candidates (
    candidate_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, session_id TEXT,
    scenario_type TEXT NOT NULL, historical_context TEXT, required_conditions TEXT,
    confirmation_conditions TEXT, invalidation_conditions TEXT, status TEXT NOT NULL DEFAULT 'NOT_ACTIVE',
    evidence TEXT, confidence REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE scenario_matches (
    match_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, instrument_id TEXT NOT NULL,
    timestamp TEXT NOT NULL, match_state TEXT NOT NULL DEFAULT 'WATCH', evidence TEXT, confidence REAL,
    confirmation_evidence TEXT, invalidation_evidence TEXT, created_at TEXT NOT NULL);
CREATE TABLE option_contracts (
    contract_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, expiry TEXT NOT NULL,
    strike REAL NOT NULL, option_type TEXT NOT NULL, last_price REAL, bid REAL, ask REAL,
    volume INTEGER, open_interest INTEGER, implied_volatility REAL, delta REAL, gamma REAL,
    theta REAL, vega REAL, premium_per_lot REAL, max_risk REAL, max_reward REAL,
    distance_from_spot REAL, liquidity TEXT, data_state TEXT NOT NULL DEFAULT 'LIVE', created_at TEXT NOT NULL);
CREATE TABLE option_snapshots (
    snapshot_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    atm_strike REAL, atm_premium REAL, atm_iv REAL, expected_move REAL, pcr REAL,
    total_oi INTEGER, total_volume INTEGER, data_state TEXT NOT NULL DEFAULT 'LIVE', created_at TEXT NOT NULL);
CREATE TABLE trade_candidates (
    candidate_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, timestamp TEXT NOT NULL,
    scenario TEXT, scenario_status TEXT, strategy TEXT, objective TEXT, direction TEXT,
    legs TEXT, strikes TEXT, expiry TEXT, entry REAL, stop REAL, target REAL,
    max_risk REAL, expected_reward REAL, risk_reward REAL, qualification_status TEXT NOT NULL DEFAULT 'PENDING',
    qualification_reasons TEXT, data_quality TEXT, created_at TEXT NOT NULL);
CREATE TABLE qualified_trades (
    trade_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, date TEXT NOT NULL, timestamp TEXT NOT NULL,
    scenario TEXT NOT NULL, strategy TEXT NOT NULL, objective TEXT NOT NULL, direction TEXT NOT NULL,
    legs TEXT, strikes TEXT, expiry TEXT, entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
    max_risk REAL NOT NULL, expected_reward REAL NOT NULL, risk_reward REAL, qualification_evidence TEXT,
    status TEXT NOT NULL DEFAULT 'QUALIFIED', daily_lock_consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX idx_daily_trade_lock ON qualified_trades(instrument_id, date);
CREATE TABLE daily_trade_locks (
    lock_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'AVAILABLE',
    trade_id TEXT, locked_at TEXT, consumed_at TEXT, created_at TEXT NOT NULL, UNIQUE(instrument_id, date));
CREATE TABLE paper_trades (
    trade_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, scenario TEXT, strategy TEXT, objective TEXT,
    direction TEXT, legs TEXT, strikes TEXT, expiry TEXT, entry REAL, stop REAL, target REAL, max_risk REAL,
    expected_reward REAL, entry_time TEXT, exit_time TEXT, exit_price REAL, exit_reason TEXT, paper_pnl REAL,
    mfe REAL, mae REAL, holding_time TEXT, status TEXT NOT NULL DEFAULT 'OPEN', qualification_evidence TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE paper_trade_events (
    event_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, timestamp TEXT NOT NULL, event_type TEXT NOT NULL, price REAL,
    scenario_status TEXT, risk_status TEXT, target_status TEXT, stop_status TEXT, evidence TEXT, created_at TEXT NOT NULL);
CREATE TABLE backtest_runs (
    run_id TEXT PRIMARY KEY, instrument TEXT NOT NULL, date_start TEXT NOT NULL, date_end TEXT NOT NULL,
    candle_timeframe TEXT NOT NULL DEFAULT '5m', scenario_filter TEXT, strategy_filter TEXT, objective_filter TEXT,
    strategy_version TEXT, scenario_version TEXT, config_version TEXT, data_source TEXT, total_sessions INTEGER,
    qualified_trades INTEGER, no_trade_days INTEGER, runs_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'COMPLETED', notes TEXT);
CREATE TABLE backtest_decisions (
    decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_date TEXT NOT NULL, instrument TEXT NOT NULL,
    timestamp TEXT NOT NULL, market_state TEXT, scenario TEXT, scenario_status TEXT, confirmation TEXT,
    options_valid INTEGER DEFAULT 0, risk_accepted INTEGER DEFAULT 0, decision TEXT NOT NULL, decision_reasons TEXT,
    latest_allowed_data TEXT, actual_latest_data TEXT, lookahead_check TEXT NOT NULL DEFAULT 'PASS', created_at TEXT NOT NULL);
CREATE TABLE backtest_trades (
    trade_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_date TEXT NOT NULL, instrument TEXT NOT NULL,
    scenario TEXT, strategy TEXT, objective TEXT, direction TEXT, entry REAL, stop REAL, target REAL, exit REAL,
    exit_reason TEXT, paper_pnl REAL, mfe REAL, mae REAL, holding_time TEXT, created_at TEXT NOT NULL);
CREATE TABLE backtest_outcomes (
    outcome_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, total_trades INTEGER, wins INTEGER, losses INTEGER,
    breakeven INTEGER, win_rate REAL, avg_outcome REAL, median_outcome REAL, profit_factor REAL, max_drawdown REAL,
    avg_holding_time TEXT, target_exits INTEGER, stop_exits INTEGER, invalidation_exits INTEGER, eod_exits INTEGER, created_at TEXT NOT NULL);
CREATE TABLE ai_explanations (
    explanation_id TEXT PRIMARY KEY, instrument_id TEXT, timestamp TEXT NOT NULL, prompt TEXT, response TEXT,
    model TEXT, provider TEXT, status TEXT NOT NULL DEFAULT 'SUCCESS', error TEXT, agreement_status TEXT,
    latency_ms INTEGER, token_usage INTEGER, created_at TEXT NOT NULL);
CREATE TABLE data_quality_events (
    event_id TEXT PRIMARY KEY, instrument_id TEXT, timestamp TEXT NOT NULL, check_type TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL);
CREATE TABLE pipeline_runs (
    run_id TEXT PRIMARY KEY, pipeline_name TEXT NOT NULL, instrument_id TEXT, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL DEFAULT 'RUNNING', records_processed INTEGER DEFAULT 0, errors TEXT, created_at TEXT NOT NULL);
CREATE TABLE system_health (
    check_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, component TEXT NOT NULL, status TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL);
CREATE TABLE research_daily_decisions (
    decision_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, date TEXT NOT NULL, timestamp TEXT NOT NULL,
    market_state TEXT, scenario TEXT, scenario_status TEXT, options_state TEXT, qualification_status TEXT NOT NULL,
    qualification_reasons TEXT, trade_id TEXT, created_at TEXT NOT NULL);
