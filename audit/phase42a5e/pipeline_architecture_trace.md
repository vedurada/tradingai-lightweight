# Pipeline Architecture Trace

## Data Source Tracing (NIFTY, BANKNIFTY)

### 1-MINUTE - NIFTY
- **timestamp**: 2026-09-18 10:29:00
- **price**: 23346.4
- **source**: yfinance/NSE (via data_fetcher_db.py)
- **fetch_process**: data_fetcher_db.py (cron: * 9-15 * * 1-5)
- **data_quality**: STALE
- **notes**: Latest 1m at 2026-09-18 10:29:00, market closed

### 5-MINUTE CANDLE - NIFTY
- **timestamp**: 2026-09-18T04:25:00+00:00
- **price**: 23346.400390625
- **open**: 23341.849609375
- **high**: 23346.400390625
- **low**: 23341.849609375
- **volume**: 0
- **source**: aggregate.py (1m→5m aggregation)
- **fetch_process**: aggregate.py sweep (cron: */15 9-15)
- **data_quality**: STALE
- **notes**: Latest 5m candle at 2026-09-18 09:55:00 IST

### MARKET SNAPSHOT - NIFTY
- **timestamp**: 2026-09-18T10:29:26.068125+00:00
- **value**: 23346.4
- **source**: market_snapshots table
- **fetch_process**: aggregate.py / data_fetcher_db.py
- **data_quality**: FRESH
- **notes**: Snapshot contains multi-index data

### MARKET STATE/REGIME - NIFTY
- **timestamp**: 2026-09-18T10:29:04.459Z
- **regime**: BEARISH
- **trend**: BEARISH
- **confidence**: 75.0
- **source**: market_regime table (deterministic engine)
- **fetch_process**: generate_json.py / aggregate.py
- **data_quality**: FRESH
- **notes**: regime=BEARISH, trend=BEARISH

### AI OUTLOOK - NIFTY
- **timestamp**: 2026-09-18 09:30:10
- **value**: {"date": "2026-09-18", "symbol": "NIFTY", "as_of_ist": "2026-09-18 09:30 IST", "regime": {"primary":
- **source**: market_outlooks table (AI generated via outlook.py)
- **fetch_process**: outlook.py (cron: 30 9 * * 1-5, 0 19 * * 1-5)
- **data_quality**: FRESH
- **notes**: AI outlook from outlook.py

### 1-MINUTE - BANKNIFTY
- **timestamp**: 2026-09-18 10:29:00
- **price**: 56358.7
- **source**: yfinance/NSE (via data_fetcher_db.py)
- **fetch_process**: data_fetcher_db.py (cron: * 9-15 * * 1-5)
- **data_quality**: STALE
- **notes**: Latest 1m at 2026-09-18 10:29:00, market closed

### 5-MINUTE CANDLE - BANKNIFTY
- **timestamp**: 2026-09-18T04:25:00+00:00
- **price**: 56358.69921875
- **open**: 56360.19921875
- **high**: 56360.19921875
- **low**: 56358.69921875
- **volume**: 0
- **source**: aggregate.py (1m→5m aggregation)
- **fetch_process**: aggregate.py sweep (cron: */15 9-15)
- **data_quality**: STALE
- **notes**: Latest 5m candle at 2026-09-18 09:55:00 IST

### MARKET SNAPSHOT - BANKNIFTY
- **timestamp**: 2026-09-18T10:29:26.068125+00:00
- **value**: 56358.7
- **source**: market_snapshots table
- **fetch_process**: aggregate.py / data_fetcher_db.py
- **data_quality**: FRESH
- **notes**: Snapshot contains multi-index data

### MARKET STATE/REGIME - BANKNIFTY
- **timestamp**: 2026-09-18T10:29:05.127Z
- **regime**: BEARISH
- **trend**: BEARISH
- **confidence**: 70.0
- **source**: market_regime table (deterministic engine)
- **fetch_process**: generate_json.py / aggregate.py
- **data_quality**: FRESH
- **notes**: regime=BEARISH, trend=BEARISH

### AI OUTLOOK - BANKNIFTY
- **timestamp**: 2026-09-18 09:30:19
- **value**: {"date": "2026-09-18", "symbol": "BANKNIFTY", "as_of_ist": "2026-09-18 09:30 IST", "regime": {"prima
- **source**: market_outlooks table (AI generated via outlook.py)
- **fetch_process**: outlook.py (cron: 30 9 * * 1-5, 0 19 * * 1-5)
- **data_quality**: FRESH
- **notes**: AI outlook from outlook.py

