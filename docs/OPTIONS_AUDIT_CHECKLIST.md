# TradingAI Options Trading Engine — Audit Checklist

**Version:** 1.0  
**Date:** 2026-11-02  
**Scope:** Options module (options_trading_engine.py + tests + validation)  
**Status:** Pre-live audit — must pass all checks before VM integration

---

## A. Design Review

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| A1 | SHADOW mode hard-enforced (`LIVE_EXECUTION_AUTHORIZED = False`) | | `options_trading_engine.py` line ~100 |
| A2 | No `place_order()` or broker order calls in engine | | Source code grep |
| A3 | No fabricated option premiums — all from Zerodha API | | Code review |
| A4 | Weekly expiry only (NIFTY Thursdays) | | `get_option_chain()` |
| B5 | ATM strike = nearest strike to spot | | `select_atm_contract()` |
| A6 | BULL → buy ATM CE; BEAR → buy ATM PE | | `on_signal()` logic |
| A7 | Single open position per instrument (Mode C) | | `has_open_position()` |
| A8 | Stop/target based on underlying spot, not premium | | `check_exits()` |
| A9 | EOD exit at 15:25 IST | | `EOD_EXIT` constant |
| A10 | Option data unavailable → degrade to spot-only (no trade) | | `on_signal()` fallback |

---

## B. Implementation Review

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| B1 | `paper_option_trades` table created with all required columns | | `init_option_trades_table()` |
| B2 | Zerodha credentials loaded from `.env.zerodha` (not hardcoded) | | `_load_zerodha_env()` |
| B3 | Access token used from env (no secrets in code) | | `_kite_client()` |
| B4 | Spot price fetched via `kc.quote("NSE:NIFTY")` | | `get_spot_price()` |
| B5 | Option chain fetched via `kc.instruments("NFO")` | | `get_option_chain()` |
| B6 | Contract premium fetched via `kc.quote("NFO:<symbol>")` | | `get_contract_quote()` |
| B7 | Trade recorded in SQLite with audit timestamps | | INSERT in `on_signal()` |
| B8 | Exit updates DB with premium_exit, pnl, status='CLOSED' | | UPDATE in `check_exits()` |
| B9 | Open positions tracked in memory + DB | | `self.open_positions` dict |
| B10 | CLI smoke test (`_demo()`) runs without errors | | `python options_trading_engine.py` |

---

## C. Test Coverage

| # | Test | Status | Result |
|---|------|--------|--------|
| C1 | ATM CE selection for BULL signal | | `TestATMSelection.test_select_atm_ce_bull` |
| C2 | ATM PE selection for BEAR signal | | `TestATMSelection.test_select_atm_pe_bear` |
| C3 | No contract → returns None | | `TestATMSelection.test_no_contract_returns_none` |
| C4 | DB table creation | | `TestEngineInit.test_init_creates_table` |
| C5 | BULL signal creates CE trade | | `TestSignalProcessing.test_bull_signal_creates_trade` |
| C6 | BEAR signal creates PE trade | | `TestSignalProcessing.test_bear_signal_creates_pe` |
| C7 | Mode C — second signal rejected | | `TestSignalProcessing.test_no_open_position_when_already_open` |
| C8 | No Zerodha client → NO_TRADE | | `TestSignalProcessing.test_no_kite_client_degrades` |
| C9 | Bull target exit → P&L calculated | | `TestExitLogic.test_bull_target_exit` |
| C10 | Bear stop exit → P&L calculated | | `TestExitLogic.test_bear_stop_exit` |
| C11 | SHADOW enforcement blocks live mode | | `TestShadowEnforcement.test_live_execution_blocked` |

**Run tests:** `cd /Users/satya/tradingai_sync && python3 tests/test_options_trading_engine.py`

---

## D. Validation Coverage

| # | Check | Status | Result |
|---|-------|--------|--------|
| D1 | Design principles verified in source | | `validate_options_integration.py` |
| D2 | No place_order in engine source | | `validate_options_integration.py` |
| D3 | BULL → CE, ATM strike correct | | `validate_options_integration.py` |
| D4 | Mode C — position blocking works | | `validate_options_integration.py` |
| D5 | Target exit P&L points + rupees correct | | `validate_options_integration.py` |
| D6 | Error handling: no client, no spot, no chain | | `validate_options_integration.py` |
| D7 | Audit trail: all fields in DB | | `validate_options_integration.py` |

**Run validation:** `cd /Users/satya/tradingai_sync && python3 scripts/validate_options_integration.py`

---

## E. Pre-Live Integration Gates (VM Only — After All Above Pass)

| # | Gate | Status | Owner |
|---|------|--------|-------|
| E1 | All unit tests pass locally | | — |
| E2 | All validation checks pass locally | | — |
| E3 | Zerodha access token valid on VM | | Run `refresh_zerodha_token.py` |
| E4 | `paper_option_trades` table created on VM DB | | Run engine once on VM |
| E5 | Option chain fetchable from VM (Zerodha API reachable) | | Test `get_option_chain()` on VM |
| E6 | SHADOW mode confirmed on VM (`LIVE_EXECUTION_AUTHORIZED = False`) | | Check `/opt/tradingai/app/zerodha/config.py` |
| E7 | Integrate `on_signal()` into `paper_scalp_live.py` on VM | | — |
| E8 | Integrate `check_exits()` into exit monitor on VM | | — |
| E9 | Dashboard reads `paper_option_trades` | | `live_dashboard_worker.py` update |
| E10 | Telegram alerts for option trades | | `tg_alerts.py` update |

---

## F. Files in This Module

| File | Purpose |
|------|---------|
| `docs/OPTIONS_TRADING_DESIGN.md` | Design specification |
| `scripts/options_trading_engine.py` | Core engine implementation |
| `tests/test_options_trading_engine.py` | Unit test suite |
| `scripts/validate_options_integration.py` | End-to-end validation |
| `docs/OPTIONS_AUDIT_CHECKLIST.md` | This audit checklist |

---

## G. Sign-Off

| Reviewer | Role | Date | Signature |
|----------|------|------|-----------|
| | Developer | | |
| | Quant/Strategy | | |
| | Risk/Compliance | | |

**DO NOT integrate with live VM until all rows above are checked PASS.**