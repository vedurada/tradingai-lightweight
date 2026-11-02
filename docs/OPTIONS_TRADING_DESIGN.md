# TradingAI Options Trading Module — Design Document

**Version:** 1.0  
**Date:** 2026-11-02  
**Status:** DESIGN (pre-implementation)  
**Scope:** NIFTY weekly options — ATM CE/PE buying on HLC 3-bar signals  
**Mode:** SHADOW (paper trading only, no live orders)

---

## 1. Objective

Extend the existing HLC 3-Bar shadow engine to trade NIFTY weekly options:

| Signal | Action | Instrument |
|--------|--------|------------|
| BULL (H1_UP) | Buy ATM CE | Nearest weekly expiry |
| BEAR (H1_DOWN) | Buy ATM PE | Nearest weekly expiry |

Option premium is captured at signal generation time. Entry/exit is tracked via underlying spot movement (stop/target in points translates to option premium P&L). All trading is paper/SHADOW only.

---

## 2. Design Principles

1. **No fabricated data** — All premiums, strikes, IVs come from Zerodha API only
2. **SHADOW enforced** — `LIVE_EXECUTION_AUTHORIZED = False`, no broker orders
3. **Weekly expiry only** — NIFTY weekly options expire every Thursday
4. **ATM selection** — Nearest strike to spot price at signal time
5. **Read-only DB** — Option snapshots stored but never modify existing trades table
6. **Fail-safe** — If option data unavailable, signal falls back to spot-only (no trade)

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  HLC 3-Bar Signal (paper_scalp_live.py)                     │
│  - Detects H1_UP / H1_DOWN on 5m candles                    │
└──────────────────┬──────────────────────────────────────────┘
                   │ signal generated
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Options Trading Engine (options_trading_engine.py)         │
│  1. Fetch spot price from Zerodha                           │
│  2. Fetch option chain (weekly expiry)                      │
│  3. Select ATM strike                                       │
│  4. Select CE (BULL) or PE (BEAR)                           │
│  5. Capture premium at signal time                          │
│  6. Record paper option trade                               │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Exit Monitor                                               │
│  - Stop hit (spot ≤ stop) → exit option at current premium  │
│  - Target hit (spot ≥ target) → exit option                 │
│  - EOD (15:25 IST) → exit at closing premium                │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Data Model

### Option Trade Record (`paper_option_trades` table)

| Field | Type | Description |
|-------|------|-------------|
| trade_id | TEXT PK | Unique trade ID |
| signal_id | TEXT | Link to scalp_signals entry |
| instrument | TEXT | NIFTY |
| direction | TEXT | BULL / BEAR |
| option_type | TEXT | CE / PE |
| expiry | TEXT | Weekly expiry date (YYYY-MM-DD) |
| strike | REAL | ATM strike price |
| spot_at_signal | REAL | NIFTY spot at signal time |
| premium_entry | REAL | Option premium at entry |
| stop_spot | REAL | Stop loss in spot points |
| target_spot | REAL | Target in spot points |
| premium_exit | REAL | Option premium at exit |
| exit_reason | TEXT | TARGET / STOP / EOD / EXPIRED |
| pnl_points | REAL | P&L in option points |
| pnl_rupees | REAL | P&L in rupees (premium × lot_size) |
| status | TEXT | OPEN / CLOSED / EXPIRED |
| created_at | TEXT | Timestamp |
| updated_at | TEXT | Timestamp |

### NIFTY Lot Size: 50 (standard)

---

## 5. ATM Strike Selection Algorithm

```
1. Get spot price S from Zerodha quote
2. Get weekly expiry dates from option chain
3. Select nearest expiry (this Thursday)
4. Get all strikes for that expiry
5. ATM strike = strike closest to S (round to nearest 50 for NIFTY)
6. Select CE if BULL, PE if BEAR
7. Capture last_price (premium) from option contract
```

---

## 6. Exit Logic

| Condition | Action |
|-----------|--------|
| Spot hits target | Exit option, record premium_exit |
| Spot hits stop | Exit option, record premium_exit |
| 15:25 IST (EOD) | Exit option at closing premium |
| Option data unavailable | Hold until data returns or EOD |

---

## 7. Risk Rules

- Max 1 open option position per instrument at a time (Mode C)
- No averaging, no martingale
- Premium paid is max loss (option buying)
- Stop/target based on underlying spot, not premium

---

## 8. Integration Points (VM Only — After Local Validation)

1. `paper_scalp_live.py` → calls `options_trading_engine.on_signal()`
2. `live_dashboard_worker.py` → reads `paper_option_trades` for display
3. `tg_alerts.py` → sends option trade alerts

---

## 9. Safety Guardrails

- [ ] Zerodha access token must be valid (daily refresh required)
- [ ] Option chain must be fetchable before any trade
- [ ] If API fails, signal degrades to spot-only (no option trade)
- [ ] SHADOW mode hard-enforced — no `place_order()` calls
- [ ] All premiums logged with source timestamp for audit