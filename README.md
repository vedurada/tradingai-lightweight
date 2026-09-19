# TradingAI.in — Intraday NIFTY & BANKNIFTY Options Intelligence

AI-powered market analysis for NIFTY and BANKNIFTY options traders. Scenario detection, trade qualification, paper trading, and historical research.

## What TradingAI Does

TradingAI analyzes historical and current NIFTY/BANKNIFTY price action to:

1. **Detect scenarios** — What historical pattern does today's market resemble?
2. **Confirm in real-time** — Is the scenario currently confirmed by market data?
3. **Qualify trades** — Is there a valid, risk-appropriate options trade?
4. **Execute one trade per day** — Server-side daily lock prevents over-trading.
5. **Research backtests** — Historical replay with no-look-ahead validation.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run API server
cd /opt/tradingai_new
gunicorn -w 2 --bind 127.0.0.1:8000 app.api.app:app

# Run health check
python3 scripts/health_check.py

# Fetch market data
python3 scripts/fetch_market_data.py

# Run tests
python3 -m unittest discover tests/
```

## Architecture

```
Market Data (yfinance)
    ↓
Deterministic Engine
    ├── Scenario Engine (historical pattern matching)
    ├── Market State (trend, VWAP, momentum, volatility)
    ├── Strategy Engine (strategy selection)
    ├── Risk Engine (entry, stop, target, R:R validation)
    └── Qualification Engine (all conditions check)
    ↓
Decision (QUALIFIED_TRADE or NO_TRADE)
    ↓
AI Explanation (downstream, non-authoritative)
    ↓
Paper Trade (monitoring and exit)
```

## Key Principles

- **Deterministic**: The engine, not AI, makes all trade decisions.
- **No look-ahead**: Backtest enforces data at or before decision time.
- **One trade/day**: Server-side hard limit via daily_trade_locks.
- **NO TRADE is valid**: "No opportunity today" is a successful outcome.
- **No fabricated data**: Unavailable data shows UNAVAILABLE, not 0.

## Project Structure

```
/opt/tradingai_new/
├── app/              Flask API & engines
├── frontend/         Static HTML pages
├── database/         SQLite database
├── config/           JSON config files
├── scripts/          Pipeline scripts
├── data/             Live, historical, generated data
├── tests/            Test suite
└── logs/             Application logs
```

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Home | /index.html | Introduction and links |
| NIFTY | /indices/nifty.html | NIFTY live market and trade intelligence |
| BANKNIFTY | /indices/banknifty.html | BANKNIFTY live market and trade intelligence |
| Backtest | /backtest.html | Historical research and replay |
| Methodology | /methodology.html | How TradingAI works |

## API

See [API.md](API.md) for full API documentation.

## Data Sources

- **Market data**: yfinance (NIFTY, BANKNIFTY, INDIA_VIX)
- **Options data**: Currently unavailable (NO TRADE when required)
- **All timestamps**: Asia/Kolkata (IST)

## Limitations

- Options data not yet available — options-dependent trades are NO TRADE.
- yfinance data may have delays for Indian indices.
- Backtesting uses simulated outcomes based on candle data.
- AI explanations are downstream and cannot override trade decisions.

## Disclaimer

TradingAI provides market analysis for educational and research purposes. Historical results do not guarantee future performance. Paper trades are simulations and are not broker executions. Users are responsible for their own trading decisions and risk.
