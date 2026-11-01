# Phase 5.4 — Trade Store Audit

## 1. Schema Comparison

### paper_trades (Live Paper Trades)

| Column | Type | Constraints | Used By |
|--------|------|-------------|---------|
| trade_id | TEXT | PRIMARY KEY | All |
| instrument_id | TEXT | NOT NULL | All |
| scenario | TEXT | | HLC (SCALP_HLC), CPR |
| strategy | TEXT | | HLC (Scalp HLC 3-bar), CPR |
| objective | TEXT | | SCALP, DIRECTIONAL |
| direction | TEXT | | BULL/BEAR |
| legs | TEXT | | JSON array |
| strikes | TEXT | | JSON array |
| expiry | TEXT | | Options expiry |
| entry | REAL | | Entry price |
| stop | REAL | | Stop level |
| target | REAL | | Target level |
| max_risk | REAL | | Risk % |
| expected_reward | REAL | | Reward % |
| entry_time | TEXT | | Entry candle timestamp |
| exit_time | TEXT | | Exit candle timestamp |
| exit_price | REAL | | Exit price |
| exit_reason | TEXT | | STOP/TARGET/EOD |
| paper_pnl | REAL | | P&L in rupees |
| mfe | REAL | | Max favorable excursion |
| mae | REAL | | Max adverse excursion |
| holding_time | TEXT | | Duration |
| status | TEXT | NOT NULL DEFAULT 'OPEN' | ACTIVE/OPEN/CLOSED |
| qualification_evidence | TEXT | | JSON evidence |
| created_at | TEXT | NOT NULL | Insert timestamp |
| updated_at | TEXT | NOT NULL | Update timestamp |

### paper_scalp (EOD Backtest Trades)

| Column | Type | Constraints | Used By |
|--------|------|-------------|---------|
| session_date | TEXT | NOT NULL | Backtest |
| instrument_id | TEXT | NOT NULL | Backtest |
| direction | TEXT | | BULL/BEAR |
| level | TEXT | | H1_UP/H1_DOWN |
| entry_price | REAL | | Entry price |
| exit_price | REAL | | Exit price |
| exit_reason | TEXT | | STOP/TARGET/EOD |
| r_multiple | REAL | | R-multiple |
| result | TEXT | | WIN/LOSS/FLAT |
| points | REAL | | Points |
| created_at | TEXT | NOT NULL | Insert timestamp |
| entry_time | TEXT | | Entry candle timestamp |
| exit_time | TEXT | | Exit candle timestamp |
| PRIMARY KEY | (session_date, instrument_id) | | One trade per session per instrument |

## 2. Writers and Readers

### paper_trades writers
- `paper_scalp_live.py:try_create_trade()` → `PaperTradeEngine.create_paper_trade()`
- `tg_alerts.py:do_watch()` → `PaperTradeEngine.create_paper_trade()` (only if trade doesn't exist)
- `PaperTradeEngine.create_paper_trade()` → INSERT with deterministic ID

### paper_trades readers
- `app/api/app.py` → `/api/paper/scalp` (read-only, 500 rows)
- `app/paper_trade/engine.py:monitor()` → exit evaluation
- `app/decision/view.py` → active paper trade display
- `app/paper_trade/performance.py` → performance aggregation
- `tg_alerts.py:do_watch()` → DB check before alerting
- `tg_alerts.py:do_reconcile()` → exit reconciliation
- `scripts/paper_scalp_live.py:has_open_position()` → Mode C check

### paper_scalp writers
- Backtest scripts (run_backtest.py, run_scalp_1m_backtest.py, etc.)
- `paper_confluence.py` (topup mode)
- Manual backtest runs

### paper_scalp readers
- `app/api/app.py` → `/api/paper/scalp/eod` (read-only)
- `tg_alerts.py:do_reconcile()` → legacy CPR key resolution
- `scalp_reconcile.py:reconcile()` → matches live vs EOD trades

## 3. Status and Lifecycle Fields

### paper_trades status
- `ACTIVE` — trade just created, being monitored
- `OPEN` — trade is open (legacy, same as ACTIVE)
- `CLOSED` — trade has exited (STOP/TARGET/EOD)

### paper_scalp status
- No explicit status field; uses `result` (WIN/LOSS/FLAT) and `exit_reason`

## 4. Signal Identifiers and Idempotency

### paper_trades
- `trade_id` = PRIMARY KEY
- Deterministic ID: `PT-` + sha1(link_key)[:10].upper()
- `link_key` = `scalp|{inst}|{trade_date}|{direction}|{signal_time}`
- Idempotent: `INSERT` + `IntegrityError` catch returns existing ID

### paper_scalp
- PRIMARY KEY = `(session_date, instrument_id)`
- One trade per session per instrument
- No idempotency mechanism (INSERT OR REPLACE)

### scalp_signals
- `signal_id` = `SS-` + sha1(instrument|candle_ts|direction|level)[:12]
- UNIQUE constraint on `(instrument_id, source_candle_ts, direction)`
- Status: NEW → TRADED / EXPIRED / IGNORED

## 5. Entry, Stop, Target, Exit Representation

### paper_trades
- Entry: `entry` (REAL), `entry_time` (TEXT, ISO 8601)
- Stop: `stop` (REAL)
- Target: `target` (REAL)
- Exit: `exit_price` (REAL), `exit_time` (TEXT), `exit_reason` (TEXT)
- P&L: `paper_pnl` (REAL, in rupees)

### paper_scalp
- Entry: `entry_price` (REAL), `entry_time` (TEXT)
- Exit: `exit_price` (REAL), `exit_time` (TEXT), `exit_reason` (TEXT)
- Performance: `r_multiple` (REAL), `result` (TEXT), `points` (REAL)

## 6. Daily Trade-Count Queries

### paper_trades
```sql
SELECT COUNT(*) FROM paper_trades
WHERE instrument_id=? AND substr(entry_time,1,10)=? AND scenario='SCALP_HLC'
```

### paper_scalp
```sql
SELECT COUNT(*) FROM paper_scalp
WHERE instrument_id=? AND session_date=?
```

## 7. Dashboard and Performance Endpoint Dependencies

| Endpoint | Table | Query |
|----------|-------|-------|
| `/api/paper/scalp` | paper_trades | `WHERE scenario='SCALP_HLC' OR qualification_evidence LIKE '%SCALP_HLC%'` |
| `/api/paper/scalp/eod` | paper_scalp | `WHERE session_date=?` |
| `/api/performance/live` | paper_trades | Via `get_performance()` |
| `/api/paper/spread/today` | cpr_trigger_engine | Today's CPR trigger state |

## 8. Open-Position and Stale-Trade Handling

### paper_trades
- Open positions: `status IN ('ACTIVE', 'OPEN')`
- Mode C: `has_open_position()` checks for ACTIVE/OPEN SCALP_HLC trades
- Stale trades: `status` remains OPEN until monitor() evaluates exit
- Stale detection: `is_stale()` checks if entry_time is >20 min old

### paper_scalp
- No explicit status field
- Uses `result` (WIN/LOSS/FLAT) and `exit_reason` for lifecycle
- EOD flat at 15:20 open if neither stop nor target hit

## 9. Recommendation: Least Risky Path to Consistency

**Option A (Recommended): Keep both stores, unify reporting**

- `paper_trades` remains the authoritative live store
- `paper_scalp` remains for EOD backtest comparison
- `scalp_reconcile.py` already matches live vs EOD trades
- No schema changes needed

**Option B (Higher risk): Merge into one store**

- Would require schema migration
- Would break existing API endpoints
- Would require updating all queries
- NOT recommended

**Recommendation: Option A** — Keep both stores, unify reporting via `scalp_reconcile.py`.

---

## 10. No Schema Changes Made

This audit is read-only. No database schema changes were proposed or implemented.
