# Phase 5.5 — Trade Store and Lifecycle Audit

## 1. Trade Store Comparison

### paper_trades (Live Paper Trades)

| Column | Type | Constraints |
|--------|------|-------------|
| trade_id | TEXT | PRIMARY KEY |
| instrument_id | TEXT | NOT NULL |
| scenario | TEXT | SCALP_HLC, etc. |
| strategy | TEXT | Scalp HLC 3-bar, etc. |
| direction | TEXT | BULL/BEAR |
| entry | REAL | Entry price |
| stop | REAL | Stop level |
| target | REAL | Target level |
| entry_time | TEXT | Entry candle timestamp |
| exit_time | TEXT | Exit candle timestamp |
| exit_price | REAL | Exit price |
| exit_reason | TEXT | STOP/TARGET/EOD |
| status | TEXT | ACTIVE/OPEN/CLOSED |
| qualification_evidence | TEXT | JSON evidence |
| created_at | TEXT | NOT NULL |
| updated_at | TEXT | NOT NULL |

### paper_scalp (EOD Backtest Trades)

| Column | Type | Constraints |
|--------|------|-------------|
| session_date | TEXT | NOT NULL |
| instrument_id | TEXT | NOT NULL |
| direction | TEXT | BULL/BEAR |
| level | TEXT | H1_UP/H1_DOWN |
| entry_price | REAL | Entry price |
| exit_price | REAL | Exit price |
| exit_reason | TEXT | STOP/TARGET/EOD |
| r_multiple | REAL | R-multiple |
| result | TEXT | WIN/LOSS/FLAT |
| points | REAL | Points |
| created_at | TEXT | NOT NULL |
| entry_time | TEXT | Entry candle timestamp |
| exit_time | TEXT | Exit candle timestamp |
| PRIMARY KEY | (session_date, instrument_id) | |

## 2. Writers and Readers

### paper_trades
- Writers: paper_scalp_live.py, tg_alerts.py
- Readers: API (/api/paper/scalp), monitor, tg_alerts, performance, decision view

### paper_scalp
- Writers: Backtest scripts, paper_confluence.py
- Readers: API (/api/paper/scalp/eod), reconcile

## 3. Lifecycle Transitions

```
1. Signal detected (scalp_engine._scan_signals)
   └── Signal recorded (scalp_signal_store.record_signal)
       └── Entry-time guard evaluated (_entry_time_guard)
           └── If OK: try_create_trade()
               └── Mode C check (has_open_position)
                   └── PaperTradeEngine.create_paper_trade()
                       └── INSERT INTO paper_trades (trade_id = PK)
                       └── mark_traded(conn, sid, tid)
                           └── UPDATE scalp_signals SET status='TRADED'
               └── PaperTradeEngine.monitor()
                   └── SELECT ACTIVE/OPEN trades
                   └── exits_opens() → stop/target evaluation
                   └── If hit: _exit_trade() → UPDATE status='CLOSED'
                   └── record_performance() → INSERT into paper_trade_events
               └── tg_alerts.py:do_watch()
                   └── SELECT trade_id FROM paper_trades WHERE trade_id=?
                   └── If exists: tg('sendMessage', ...) → alert
                   └── log_alert() → append to tg_alerts_archive.jsonl
```

## 4. Idempotency Verification

| Mechanism | Status | Evidence |
|-----------|--------|----------|
| Deterministic trade_id (SHA-1 of link_key) | PASS | `paper_scalp_live.py:25-32` |
| trade_id is PRIMARY KEY | PASS | `schema.sql:81` |
| INSERT + IntegrityError catch prevents duplicates | PASS | `paper_trade/engine.py:105-123` |
| Signal UNIQUE constraint | PASS | `scalp_signal_store.py:13` — UNIQUE(instrument_id, source_candle_ts, direction) |
| tg_alerts dedup via fired key | PASS | `tg_alerts.py:399` |

## 5. No Schema Changes Made

This audit is read-only. No database schema changes were proposed or implemented.
