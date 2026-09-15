# PHASE 5 STEP 1 — Audit Report

Date: 2026-09-13
Status: Complete
Frozen baseline: 7cd3813 → cf851b4 (39/39 tests passing)

---

## 1. build_outlook() Audit (outlook.py, 938 lines)

### Structure
`build_outlook(conn, symbol, date)` is a 660-line pipeline with ~50 sub-calculations spanning:
- Gap analysis, VIX regime, bias probabilities, tradeability, confidence
- PCR, CE wall, prev-day strikes, OI trend, market-open delta
- Feature engine (prev-day candles, past confirmation, hierarchy)
- 11 strategy scoring formulas, verdict logic, narrative generation
- Historical fallback synthesis (SMA/RSI/regime/VIX from price_1d)

### Key Finding: build_outlook() is 100% deterministic
- **Zero LLM calls inside the function**
- LLM influence flows exclusively through external path: `refresh_ai_outlook()` → DB (`ai_outlooks`) → `merge_llm_into_payload()`
- The LLM overlay modifies: primary_view, regime, bias, confidence, key_levels, ai_source

### Dead Code in outlook.py
| Item | Lines | Severity |
|------|-------|----------|
| `_pcr_read(pcr)` — never called | 274-283 | Medium |
| `from daily_page import _foot, _head, _nav` — unused import | 22 | Low |
| `oi_signal = "MIXED"` — overwritten immediately at next line | 593 | Low |
| Broad `except: pass` blocks | 257, 269, 404, 483, 529 | Low |
| Unnecessary `locals()` check for `past_confirms_bias` | 657 | Low |
| `open_vs_prev_high/low` computed but analytically unused | 484-488 | Low |

### Duplicated Calculations (outlook.py overlaps)
| Calculation | outlook.py | Also in |
|-------------|------------|---------|
| PCR rounding | `_pcr_info()` rounds to **2** decimals | `options.calculate_pcr()` rounds to **3** |
| Max Pain | `_prev_day_top_strikes()` finds highest OI | `options.calculate_max_pain()` (different algorithm) |
| Expected range | `_expected_range(pivot, atr)` ATR-based | `options.compute_expected_move()` IV-based (different methodology) |
| Bias | `_bias(regime, rsi, gap)` | `options.derive_options_bias()` (different inputs) |
| Confidence | `_confidence(adx, rsi, vix)` | `options.compute_confirmation()` (different inputs) |

**Critical**: No shared helper calls between outlook.py and options.py — they independently solve overlapping conceptual problems with different data inputs.

---

## 2. OptionsEngine Audit (options.py, 687 lines)

### Public Methods (7) — all deterministic, self-contained
| Method | What it does | Status |
|--------|-------------|--------|
| `calculate_pcr(call_oi, put_oi)` | PE/CE ratio, 3 decimals | Used by analyze_options internally |
| `calculate_max_pain(contracts)` | Aggregate intrinsic-payout method | Used by api_server |
| `calculate_iv_stats(contracts)` | Avg/min/max IV, IV rank | Used by api_server |
| `compute_expected_move(contracts, price, expiry)` | ATM IV × √(DTE/365) × Spot | Used by api_server |
| `compute_oi_concentration(contracts)` | OI totals, changes, zones, concentration | Used by api_server |
| `compute_confirmation(...)` | Market vs options alignment | Used by api_server |
| `derive_options_bias(...)` | Max Pain + PCR + OI → bias | Used by api_server |

### Dead Code (~135 lines, 19.6% of file)
| Item | Lines | Severity |
|------|-------|----------|
| Cache infra (`_cache`, `_cache_time`, `_cached`, `_set_cache`, `_cache_ttl`) — never called | 13-25 | High |
| Unreachable block in `compute_expected_move()` (copy of `compute_oi_concentration` body) | 215-340 | High |
| `analyze_options()` — no external callers | 660-687 | Medium |

### Duplicated Calculations (options.py overlaps)
| Calculation | options.py | Also in |
|-------------|------------|---------|
| Max Pain algorithm | `_max_pain_aggregate_payout()` (lines 32-83) | `fo_fetcher.py:157-198` (inline), `api_server.py:596-643` (inline) |
| PCR | `calculate_pcr()` rounds to 3 | `outlook.py:_pcr_info()` rounds to 2 (inconsistent) |
| OI by strike grouping | Inside `compute_oi_concentration()` | `fo_fetcher.py`, `api_server.py` |

### Bugs Found
| # | Issue | Severity |
|---|-------|----------|
| 1 | 126 lines unreachable in `compute_expected_move()` | High |
| 2 | Cache mechanism non-functional (no callers) | Medium |
| 3 | `points` return type inconsistent (float vs "DATA TEMPORARILY UNAVAILABLE" string) | Medium |
| 4 | Logger defined but never used | Low |
| 5 | O(n^2) Max Pain algorithm (acceptable for 50-200 strikes) | Low |

---

## 3. Market Data Inputs Audit

### Database Schema: 37 tables
- **2 dead tables**: `signals`, `sector_data` (schema exists, no data ever written, no consumers)
- **Data flow**: NSE API → option_chain/live_quotes/index_breadth; yfinance → price_1m/vix_data; fo_fetcher → pcr_history/oi_top_strikes; Internal engines → indicators/market_regime/strategies

### Data Classification
| State | Sources |
|-------|---------|
| LIVE | NSE live chain, NSE API quotes, yfinance 1m candles |
| STORED | DB tables (indicators, regime, strategies, AI outlooks, etc.) |
| CONDITIONALLY LIVE | NSE live chain (only when NSE API responds), 1m candles (only during market hours) |
| UNAVAILABLE | signals table, sector_data table |

### API Contracts: 61 endpoints
- ~20+ have no frontend usage (internal/monitoring/cron)
- All frontend API calls resolve to existing endpoints (no broken links)
- Workhorse endpoints: `/api/<symbol>` (aggregated), `/api/market` (cached 20s, 20+ pages)
- Options endpoints: `/api/pcr`, `/api/maxpain`, `/api/oi-concentration`, `/api/expected-move`, `/api/options-intelligence` (all PHASE 4 additions)

---

## 4. Duplication Summary

| Calculation | Locations | Severity |
|-------------|-----------|----------|
| **Max Pain** | options.py, fo_fetcher.py, api_server.py — 3 identical | High |
| **PCR** | options.py, fo_fetcher.py, api_server.py, outlook.py — 4 implementations, inconsistent rounding (2 vs 3 decimals) | High |
| **OI by strike** | options.py, fo_fetcher.py, api_server.py — 3 implementations | Medium |
| **Quote building** | api_server.py, data_fetcher_db.py — 2-3 implementations | Medium |
| **Change/percentage** | Inline in 5+ locations | Low |

---

## 5. Unused Code Summary

### Functions with no callers
| Function | File | Notes |
|----------|------|-------|
| `_pcr_read(pcr)` | outlook.py | Completely dead |
| `analyze_options(chain, price)` | options.py | No external callers |
| `_foot`, `_head`, `_nav` | outlook.py | Unused import |
| ~40 API route handlers | api_server.py | No frontend consumer (may serve external/backend) |

### Dead database tables
| Table | Status |
|-------|--------|
| `signals` | Schema exists, no data, no fetcher, no consumer |
| `sector_data` | Schema exists, no data, no fetcher, no consumer |

---

## 6. Test Baseline

### Current State
| Metric | Value |
|--------|-------|
| Test file | `tests/test_max_pain.py` (only file) |
| Test functions defined | 39 |
| Tests executed | 38 |
| Tests passed | 38/38 (100%) |
| Dead stubs | 1 (`test_multiple_expiries` — pass statement) |
| Test framework | Raw asserts + print (no pytest config) |
| CI configuration | None |
| PHASE 5 test file | None |

### Coverage Gaps
| Uncovered | Details |
|-----------|---------|
| OptionsEngine methods | `_cached`, `_set_cache`, `calculate_pcr` (public), `calculate_max_pain` (public), `calculate_iv_stats`, `analyze_options` (6 methods) |
| API endpoints tested | 3 of 61 (<5%) |
| fo_fetcher functions | 0 of 11 |
| Other backend modules | regime.py, aggregate.py, all others |

### Untested Code Paths
- Max Pain tie-breaking (identical minimum payout)
- Expected Move DTE=0 path
- Expected Move date format fallback
- compute_confirmation with "NEUTRAL" string (not None)
- All-negative OI change scenario

---

## 7. Key Findings for PHASE 5 Planning

### What Already Exists (can be leveraged)
1. **`build_outlook()`**: Comprehensive deterministic engine covering regime, bias, confidence, strategies, key levels, verdict
2. **`OptionsEngine`**: 7 public methods for all options calculations
3. **Market regime data**: `market_regime` table populated by existing fetcher
4. **Strategies table**: `strategies` table with AI-selected strategies
5. **Historical data**: `price_1d`, `history`, `market_regime` for backtesting

### What Needs to Be Built (PHASE 5)
1. **Market Regime Engine** (STEP 2): Deterministic regime classification (Bullish/Bearish/Sideways/High-volatility) — partially exists in `build_outlook()` but needs standalone extraction
2. **Intraday Market Outlook** (STEP 3): Daily intelligence layer — overlaps with `build_outlook()`; needs consolidation
3. **Strategy Mapping Engine** (STEP 4): Market condition → defined-risk strategy mapping — partially exists in `_strategies()` in outlook.py
4. **Historical Validation** (STEP 5): Signal tracking with actual outcomes — entirely new
5. **Daily Intelligence Dashboard** (STEP 6): User-facing UI — new frontend section

### Architectural Constraints (preserved)
1. Backend is single source of truth for all calculations
2. No calculation refactoring into frontend
3. Deterministic outputs not altered casually
4. Additive, isolated changes per step
5. LLM remains explanatory, never becomes source of quantitative values
6. `build_outlook()` remains untouched
7. All new code goes through OptionsEngine or new backend engine

### Immediate Risks for PHASE 5
1. **build_outlook() vs new engine overlap**: Need clear boundary to avoid duplicating regime/bias/confidence logic
2. **OptionsEngine dead code**: 135 lines should be cleaned before adding new methods
3. **PCR rounding inconsistency**: Must standardize before building on top
4. **Max Pain duplication**: 3 implementations should converge to options.py
5. **Test coverage**: Only 38 tests, mostly for options.py; need PHASE 5 test infrastructure

---

## 8. PHASE 5 STEP 1 Audit — Complete

Ready for STEP 2 (Market Regime Engine) planning.

Next action: Define deterministic regime classification inputs, formula, and test plan before implementing.
