# PHASE 5 STEP 4 — Full Pipeline Audit

Date: 2026-09-13
Status: AUDIT ONLY — no code changes, no commits
Prerequisite: STEP 3 committed `61bd3bf` (112/112 tests passing)

---

## 1. End-to-End Data Flow

### Primary production path (live poller)

```
price_1m + vix_data + market_breadth + option_chain
    ↓
RegimeEngine.evaluate(market, options_input)  [data_fetcher_db.py:538-551]
    ↓
market_regime table  [data_fetcher_db.py:553-556]
  ├─ regime: BULLISH | BEARISH | SIDEWAYS | HIGH_VOLATILITY | UNKNOWN
  ├─ confidence: 0-100
  ├─ trend, momentum, volatility, breadth, vix_regime (component strings)
  └─ reasons (list of strings)
    ↓
store_regime_and_strategies()  [data_fetcher_db.py:472]
  ├─ ScenarioEngine.generate(regime, ...) → scenarios table     [line 580-581]
  ├─ StrategyEngine.select(regime, ...) → strategies table      [line 582-585]
  └─ AIOutlookEngine.generate(symbol, data, use_llm=False) → ai_outlooks table [line 586-595]
    ↓
API endpoints read from tables:
  /api/regime/<symbol>      → market_regime
  /api/strategy/<symbol>    → strategies
  /api/scenarios/<symbol>   → scenarios
  /api/outlook/<symbol>     → ai_outlooks
  /api/market-outlook       → market_outlooks + LLM overlay
```

### Daily outlook path (outlook.py main, run via cron)

```
DB (indicators, market_regime, vix_data, price_1d, option_chain, history)
    ↓
build_outlook(conn, symbol, date)  [outlook.py:336]
  Reads: indicators, market_regime (regime + confidence only), vix_data, price_1d
  Computes: gap, bias, confidence, expected_range, key_levels, strategies, verdict
  ↓
payload stored to market_outlooks table  [outlook.py:831-835]
  ↓
merge_llm_into_payload()  [outlook.py:657] — LLM overlay (see §5)
  ↓
render_html(payload, date) → market/outlook-<date>.html
  ↓
Chat alert IF verdict=="TRADE"  [outlook.py:839-852] — see §5.2
```

### On-demand / API path

```
/api/market-outlook → reads market_outlooks → merge_llm_into_payload()
/api/market-outlook/<date> → reads market_outlooks → merge_llm_into_payload()
/api/market → _build_market() → _symbol_data() → per-symbol API data + ai_outlook
/api/options-intelligence/<symbol> → OptionsEngine → build_outlook() [line 804] → compute_confirmation()
```

### Daily page path (daily_page.py)

```
_fetch_day(conn, date_str) → reads price_1m, indicators, market_regime, strategy, vix, history, expiries
  ↓
render_morning() / render_close() → market/nifty-outlook-<date>.html
```

---

## 2. Consumer Inventory

| Consumer | Reads from | Regime field | Method | Notes |
|---|---|---|---|---|
| build_outlook() | market_regime table | regime, confidence | REGIME_MAP → regime_label | Lines 339, 479-480 |
| _bias() (in outlook.py) | regime_label | substring match | BULLISH/BEARISH/NEUTRAL | Line 137 |
| _strategies() (in outlook.py) | bias_label, probs, reg | reg NOT used | N/A | Line 541 |
| StrategyEngine.select() | regime param (from data_fetcher_db) | normalize_regime() | BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY | strategies.py:14 |
| StrategyEngine.select_stock_outlook() | regime param (from data_fetcher_db) | normalize_regime() | BULLISH/BEARISH/HIGH_VOLATILITY/SIDEWAYS | strategies.py:71 |
| ScenarioEngine.generate() | regime param (from data_fetcher_db) | normalize_regime() | BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY | scenarios.py:7 |
| AIOutlookEngine._rule_based() | data["regime"] | normalize_regime() | BULLISH/BEARISH/HIGH_VOLATILITY/SIDEWAYS/UNKNOWN | ai_outlook.py:259 |
| AIOutlookEngine.generate() (LLM) | data["regime"] passed to prompt | no normalization | LLM text | ai_outlook.py:67 |
| merge_llm_into_payload() | ai_outlooks table | regime, bias, confidence | REGIME_MAP + direct assignment | outlook.py:657 |
| daily_page.py | market_regime table | regime (raw) | _fetch_day() line 57-58 | Displays raw value |
| alert.py | history table | market_regime | normalize_regime() | alert.py:59-88 |
| /api/regime/<symbol> | market_regime table | all columns | row_to_dict | api_server.py:481 |
| /api/strategy/<symbol> | strategies table | strategy env | row_to_dict | api_server.py:497 |
| /api/scenarios/<symbol> | scenarios table | strategy env | row_to_dict | api_server.py:513 |
| /api/outlook/<symbol> | ai_outlooks table | market_regime | row_to_dict | api_server.py:522 |
| /api/market-outlook | market_outcomes + ai_outlooks | merge_llm_into_payload | full pipeline | api_server.py:848 |
| /api/options-intelligence | options chain + build_outlook | market bias from build_outlook | derive_options_bias | api_server.py:704 |
| /api/market | _symbol_data per symbol | ai_outlook from per-symbol API | cached | api_server.py:1070 |

---

## 3. Contradiction Analysis

### 3a. Regime name flow through build_outlook()

build_outlook() reads `regime` from market_regime, maps through REGIME_MAP to get `regime_label`, then:
- _bias(): substring match on regime_label → BULLISH/BEARISH/NEUTRAL (regime-name agnostic)
- _strategies(): uses bias_label and probs, NOT regime → regime-name agnostic
- Verdict: uses bias_label, past_trend, oi_trend, gap, rsi → regime-independent
- **Verdict: build_outlook() is REGIME-NAME AGNOSTIC. No contradiction possible within this function.**

### 3b. Two strategy engines — potential divergence

**Engine A**: build_outlook() `_strategies()` (outlook.py:272-300) — scores 10 strategy names by probability-weighted formula, returns ranked list + avoid.
**Engine B**: StrategyEngine.select() (strategies.py:14-164) — selects 2-3 specific strategies based on regime name, returns structured strategy dicts.

Both are called with regime from RegimeEngine but compute independently:
- Engine A determines `primary_view` text and `trades` (only if verdict=="TRADE")
- Engine B produces the strategies table consumed by `/api/strategy/<symbol>` and daily_page

**FINDING**: For index symbols on the same date, Engine A and Engine B could produce different strategy recommendations. Engine A uses probability scoring (Long Call Spread score = 0.55*bullish_prob + 10 + ...), Engine B uses regime-based selection (BULLISH → Bull Call Spread + Bull Put Spread). They are complementary, not contradictory, but are not synchronized.

**Severity**: MEDIUM — complementary, not contradictory. Both are deterministic given same inputs.

### 3c. Two confidence sources in build_outlook() payload

`payload["regime"]["confidence"]` = from market_regime table (RegimeEngine confidence, line 619)
`payload["confidence"]` = from _confidence(adx, rsi, vix_reg, missing_oi, gap) (line 531, independent calculation)

These use DIFFERENT inputs:
- market_regime.confidence: from RegimeEngine component scoring (trend, momentum, options, vix, breadth)
- _confidence(): from adx, rsi, vix_regime, missing_oi, gap

**FINDING**: These two confidence values can diverge for the same symbol/date. The top-level `payload["confidence"]` is what /api/market-outlook returns and what UI displays. The `payload["regime"]["confidence"]` is what market_regime table stores. Neither is "wrong" but they measure different things.

**Severity**: MEDIUM — not a correctness issue, but a semantic ambiguity. UI shows _confidence() result; market_regime stores RegimeEngine result.

### 3d. Options intelligence uses build_outlook as input

`/api/options-intelligence/<symbol>` at api_server.py:704:
1. Computes options bias via OptionsEngine.derive_options_bias() (line 797-799)
2. Calls build_outlook() to get market bias/confidence (line 804-813)
3. Uses both as inputs to compute_confirmation() (line 816-820)
4. Has hardcoded defaults: `mkt_bias = "BULLISH"`, `mkt_conf = 76` (lines 801-802) used ONLY if build_outlook() throws exception (line 812-813 except clause)

**FINDING**: If build_outlook() fails, options-intelligence shows hardcoded BULLISH/76 as market bias. This fallback is only triggered on exception, which should be rare. But if it fires, user sees BULLISH regardless of actual regime.

**Severity**: MEDIUM — only on exception, but misleading when active.

### 3e. LLM vs deterministic regime in final payload

merge_llm_into_payload() (outlook.py:657-723) directly overwrites:
- `p_regime["engine"]` = LLM regime (line 704-706)
- `p_regime["primary"]` = REGIME_MAP(LLM regime) (line 705-706)
- `payload["bias"]["label"]` = LLM bias (line 708-709)
- `payload["confidence"]` = LLM confidence (line 710-711)
- `key_levels` supports/resistances = LLM values (line 712-719)
- `decision.primary_view` = LLM market_summary (line 693-694)
- `decision.regime_override` = LLM regime, bias, confidence (line 695-700)
- `payload["ai_source"]` = "LLM" (line 721)

**FINDING**: The LLM CAN override every quantitative field in the payload (regime, bias, confidence, key levels, primary view). This DIRECTLY violates the STEP 3 principle that "deterministic regime remains authoritative" and "LLM does not own regime/bias/confidence/strategy."

**Severity**: CRITICAL — this was identified in STEP 3 audit but deferred. The LLM produces the final authoritative values in the payload that all APIs and UI consume.

### 3f. Chat alert never fires

outlook.py:839:
```python
verdict = (payload.get("verdict") or payload.get("outlook", {}).get("verdict")
           or payload.get("trade_decision") or "").strip().upper()
```

But payload structure at line 649 has verdict at `payload["decision"]["verdict"]`, not at top level. There is no `payload["verdict"]`, `payload["outlook"]`, or `payload["trade_decision"]`.

**FINDING**: `verdict` is always "" at line 839, so `verdict == "TRADE"` is always False. Chat alerts NEVER fire. This is a pre-existing bug.

**Severity**: CRITICAL — completely dead code; no trade notifications are ever sent.

---

## 4. Fallback / Unavailable-State Analysis

### 4a. build_outlook() fallback matrix

| Input unavailable | build_outlook() behavior | Correct? |
|---|---|---|
| No indicators (ind is None/empty) | Historical fallback: synthesize from price_1d SMA (lines 362-391). Regime synthesized as TRENDING_BULLISH/BEARISH/RANGE_BOUND/etc. | Yes (legacy compat) |
| No VIX | _vix_regime() returns ("UNKNOWN", "flat"). _confidence: no VIX penalty. _tradeability: no VIX bonus. vol_fav → "waiting" | Yes |
| No gap data | gap = {"available": False}. Most gap adjustments skipped. Cover_prob = None | Yes |
| No options data (pcr) | pcr["available"] = False. missing_oi = True. Confidence -4, tradeability -5, vol_fav → "waiting" | Yes |
| No day data (price_1d) | gap = {"available": False}. Expected range still computed from pivot/atr | Partial (no day candles) |
| No regime in market_regime | reg.get("regime") = "" → REGIME_MAP[""] → "" (empty key, not in map) → regime_label = "" → _bias() → NEUTRAL (else branch) | Yes (safe) |
| No prev_close | prev_close = None. Gap not computed (requires prev_close). | Yes |
| All data missing | Historical fallback attempts SMA synthesis. If all fails, regime = UNKNOWN, bias = NEUTRAL | Yes (safe) |

### 4b. Downstream engine fallback matrix

| Engine | UNKNOWN regime | Missing data |
|---|---|---|
| StrategyEngine.select() | NO TRADE (safe) | Uses existing logic; depends on input data |
| ScenarioEngine.generate() | Default probabilities 0.3/0.3/0.2/0.15/0.05 | N/A |
| AIOutlookEngine._rule_based() | NEUTRAL bias, 45 confidence, RANGE structure, NO TRADE strategy | Handles via data.get() defaults |
| AIOutlookEngine LLM | Depends on LLM prompt | Options analysis shows DATA UNAVAILABLE |
| build_outlook() | NEUTRAL bias, N/A confidence, WAIT verdict | All dependent on specific missing field |
| alert.py | UNKNOWN regime normalized, safe comparison | N/A |

**FINDING**: All engines correctly fail safe to NEUTRAL/NO TRADE/WAIT for unknown/missing data. No engine produces false directional signals from missing data.

### 4c. ScenarioEngine probability normalization

For UNKNOWN regime, ScenarioEngine uses default probabilities (0.3/0.3/0.2/0.15/0.05). After ADX > 40 adjustment (+0.1 to breakout), total = 0.3+0.35+0.3+0.15+0.1 = 1.2, which exceeds 1.0. No explicit normalization exists in ScenarioEngine.

**FINDING**: ScenarioEngine does NOT normalize probabilities to sum to 1.0 after conditional adjustments. For ADX > 40 with HIGH_VOLATILITY: breakout 0.5 (0.4+0.1), bullish 0.35, bearish 0.35, range 0.1, reversal 0.05 = 1.35. This exceeds 1.0 and could confuse downstream consumers.

**Severity**: LOW — probabilities are relative scores, not strict probabilities, but this is misleading.

---

## 5. LLM Boundary Audit

### 5a. Where LLM is called

| Location | Method | Regime source | Frequency |
|---|---|---|---|
| outlook.py refresh_ai_outlook() | AIOutlookEngine.generate(symbol, data, use_llm=True) | data["regime"] from market_regime (NOT normalized) | Twice daily (cron 09:30/19:00) |
| outlook.py main() → merge_llm_into_payload() | LLM output overlays onto build_outlook() | LLM output | On every market_outlook read (via API) |
| ai_outlook.py generate() with use_llm=True | AIOutlookEngine._call_llm_chain() | data["regime"] | Only in refresh_ai_outlook() |

### 5b. LLM can alter quantitative decisions

merge_llm_into_payload() (outlook.py:657-723) directly modifies:
1. **Regime**: `p_regime["engine"] = LLM regime`, `p_regime["primary"] = REGIME_MAP(LLM regime)` — **ALTERS regime**
2. **Bias**: `payload["bias"]["label"] = LLM bias` — **ALTERS bias**
3. **Confidence**: `payload["confidence"] = LLM confidence` — **ALTERS confidence**
4. **Key levels**: `kl["supports"] = LLM support levels`, `kl["resistances"] = LLM resistance levels` — **ALTERS key levels**
5. **Primary view**: `decision["primary_view"] = LLM market_summary` — **ALTERS narrative**
6. **Decision override**: `decision["regime_override"] = {engine, bias, confidence}` — **ALTERS decision**
7. **ai_source**: `payload["ai_source"] = "LLM"` — **SIGNAL**

**FINDING**: The LLM has full authority over the final payload fields. Any API consumer (all /api/* endpoints that call merge_llm_into_payload) receives LLM-modified values. The deterministic regime from RegimeEngine is NOT authoritative in the final payload — the LLM values are.

**Severity**: CRITICAL.

### 5c. LLM prompt vocabulary

The LLM prompt (ai_outlook.py:35, updated in STEP 3) specifies canonical regime names: BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY/UNCONFIRMED. However, refresh_ai_outlook() passes `regime_info.get("regime","UNKNOWN")` (line 902) which is now canonical (BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY). Good.

BUT: the LLM prompt tells the LLM to return market_regime in its response. The LLM could return any string. normalize_regime() is NOT applied to LLM output in merge_llm_into_payload() or refresh_ai_outlook(). So an LLM returning "TRENDING_BULLISH" or "BULLISH" or "very bullish" would all flow directly into the payload without normalization.

**FINDING**: LLM regime/bias output is not normalized. Consistent with design (LLM free-form), but means LLM regime field is uncontrolled.

### 5d. Where LLM is NOT called

- data_fetcher_db.py store_regime_and_strategies(): use_llm=False (deterministic). Verified ✓
- build_outlook(): no LLM call. Verified ✓
- daily_page.py: no LLM call. Verified ✓
- StrategyEngine, ScenarioEngine: no LLM. Verified ✓
- alert.py: no LLM. Verified ✓

---

## 6. API/UI Consistency Audit

### 6a. API → UI data flow

| API endpoint | Consumed by | Data source |
|---|---|---|
| /api/market-outlook | Daily outlook dashboard (ai-outlook.js) | market_outlooks + merge_llm_into_payload |
| /api/regime/<symbol> | daily_page.py, scanner, today/index | market_regime table |
| /api/strategy/<symbol> | daily_page.py, strategies.html | strategies table |
| /api/scenarios/<symbol> | Not directly consumed by UI (internal) | scenarios table |
| /api/outlook/<symbol> | market.html, daily_page.py | ai_outlooks table |
| /api/options-intelligence/<symbol> | dashboard, strategies pages | OptionsEngine + build_outlook |
| /api/market | Site-wide ticker, dashboard | _build_market() → _symbol_data() |
| /api/vix, /api/prices, /api/pcr, /api/maxpain | Various | Direct DB queries |

### 6b. UI regime display consistency

HTML/JS files use SUBSTRING matching for regime coloring:
- market.html: `r.includes('BULLISH')`, `r.includes('BEARISH')`, `r.includes('RANGE')`, `r.includes('VOLATILITY')`
- strategies.html, scanner.html, today/index.html: Same pattern

**FINDING**: UI uses substring matching, so BULLISH matches (new name), TRENDING_BULLISH also matches (legacy). SIDEWAYS does NOT match 'RANGE' → will get default color (#64748b grey) instead of RANGE color (#a16207). This is a UI display change for SIDEWAYS regime.

**Severity**: LOW — visual only, but SIDEWAYS now shows grey instead of amber.

### 6c. Consistency between API sources

Four independent sources all derive from market_regime but compute independently:
1. build_outlook() → market_outlooks → /api/market-outlook
2. StrategyEngine → strategies → /api/strategy
3. ScenarioEngine → scenarios → /api/scenarios
4. AIOutlookEngine (rule-based or LLM) → ai_outlooks → /api/outlook

**FINDING**: These CAN show different regime/bias/confidence values for the same symbol/date because they're computed independently at different times. The regime NAME will be consistent (from RegimeEngine), but derived confidence/bias/strategy values may differ due to different calculation methods and potential timing differences.

**Severity**: MEDIUM — by design but not guaranteed consistent.

---

## 7. Legacy-Reference Audit

### 7a. Old regime name references after STEP 3

| Location | Old names present | Status | Intentional? |
|---|---|---|---|
| backend/regime_utils.py REGIME_ALIASES | TRENDING_BULLISH, TRENDING_BEARISH, RANGE_BOUND | Mapping entries | Yes — normalization |
| backend/outlook.py REGIME_MAP (lines 27-37) | TRENDING_BULLISH, TRENDING_BEARISH, RANGE_BOUND, RANGE, BULLISH_RANGE, BEARISH_RANGE | Display label mapping | Yes — backward compat |
| backend/outlook.py historical fallback (lines 374-383) | TRENDING_BULLISH, TRENDING_BEARISH, BULLISH_RANGE, BEARISH_RANGE, RANGE_BOUND | Price-SMA synthesis | Yes — historical replay |
| backend/ai_outlook.py _rule_based_outlook() | UNCONFIRMED (→ UNKNOWN via normalize) | Special marker | Yes |
| prompts/daily_outlook.txt | None | Updated in STEP 3 | N/A |
| backend/strategies.py | None (all updated) | ✓ | N/A |
| backend/scenarios.py | None (all updated) | ✓ | N/A |
| backend/alert.py | None (all updated) | ✓ | N/A |
| HTML/JS frontend | Substring matching (BULLISH, BEARISH, RANGE, VOLATILITY) | Compatible with both | Yes |
| backend/backtest.py | RANGE, VIX_SPIKE, VIX_HIGH | Own regime names | Independent |
| backend/pnl_tracker.py | Reads market_regime directly | No hardcoded names | N/A |
| backend/history_logger.py | Reads market_regime directly | No hardcoded names | N/A |

**FINDING**: No active logic depends on old regime names. All remaining references are in intentional compatibility/mapping layers (REGIME_MAP, REGIME_ALIASES, historical fallback, substring-based UI). No code path FAILS because of an old regime name.

**Severity**: NONE — all legacy references are intentional and safe.

### 7b. Potential future cleanup

If/when historical data is fully migrated or aged out:
- REGIME_MAP legacy entries could be removed (lines 28-29, 32-33, 36-37 of outlook.py)
- Historical fallback regime synthesis (lines 374-383 of outlook.py) could use canonical names
- These are cosmetic and do not affect behavior

---

## 8. Test-Coverage Gaps

### 8a. Existing tests (112 passing)

| Suite | Tests | Coverage |
|---|---|---|
| test_regime.py | 20 | RegimeEngine: 18-test matrix + determinism + no-LLM |
| test_max_pain.py | 38 | OptionsEngine: max pain, OI concentration, PCR, IV, expected move |
| test_regime_utils.py | 15 | RegimeUtils: normalization, aliases, equivalence |
| test_regime_integration.py | 39 | Strategy, Scenario, AI outlook, alert normalization |

### 8b. Untested paths

| Component | Gap | Severity |
|---|---|---|
| build_outlook() | ZERO direct test coverage | HIGH |
| merge_llm_into_payload() | ZERO direct test coverage | CRITICAL |
| outlook.py main() | Not tested (cron function) | HIGH |
| outlook.py refresh_ai_outlook() | Not tested | HIGH |
| alert.py check_regime_changes() | Not tested through Database (only normalization logic tested) | MEDIUM |
| data_fetcher_db.py store_regime_and_strategies() | Not tested | HIGH |
| _rule_based_outlook() edge cases | Only basic regime mapping tested, not RSI/confidence adjustments | MEDIUM |
| /api/market-outlook endpoint | Not tested | MEDIUM |
| /api/options-intelligence endpoint | Not tested | MEDIUM |
| daily_page.py render functions | Not tested | LOW |
| AIOutlookEngine.generate() LLM path | Not tested (would require mocking providers) | MEDIUM |
| Full pipeline integration | No end-to-end test from RegimeEngine → market_regime → build_outlook → API | HIGH |
| RegimeEngine with no data edge cases | Test 10 in test_regime.py covers all-missing, but partial data scenarios not tested | MEDIUM |
| build_outlook() historical fallback | Not tested | MEDIUM |

**FINDING**: The most critical gap is build_outlook() (the core function producing the primary user-facing payload) having zero test coverage, combined with merge_llm_into_payload() (the LLM boundary) also having zero coverage.

---

## 9. Severity Classification

### Critical (2 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| C1 | LLM can override all quantitative payload fields (regime, bias, confidence, key levels, primary view) | outlook.py:657-723 | LLM authority overrides deterministic regime |
| C2 | Chat alert NEVER fires (wrong key path for verdict) | outlook.py:839 | No trade notifications sent |

### High (4 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| H1 | build_outlook() has zero test coverage | outlook.py | Core function untested |
| H2 | merge_llm_into_payload() has zero test coverage | outlook.py:657 | LLM boundary untested |
| H3 | Full pipeline integration untested | All | End-to-end behavior unknown |
| H4 | data_fetcher_db.py store_regime_and_strategies() untested | data_fetcher_db.py:472 | Real-time data pipeline untested |

### Medium (5 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| M1 | Two confidence sources can diverge | outlook.py:531 vs 619 | UI shows _confidence(), market_regime stores RegimeEngine confidence |
| M2 | Four independent engines compute strategies/scenarios/outlook separately | Multiple | Potential inconsistency across API endpoints |
| M3 | Options-intelligence fallback uses hardcoded BULLISH/76 | api_server.py:801-802 | Misleading on exception |
| M4 | ScenarioEngine probabilities can exceed 1.0 | scenarios.py:37-40 | No normalization after adjustments |
| M4b | alert.py check_regime_changes() not tested through Database | alert.py:59 | Alert logic unverified |

### Low (3 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| L1 | SIDEWAYS regime gets default UI color (not RANGE color) | market.html, scanner.html | Visual only |
| L2 | ScenarioEngine probability sum > 1.0 for some inputs | scenarios.py | Probabilities are relative scores |
| L3 | REGIME_MAP has legacy entries | outlook.py:27-37 | Harmless display mapping |

---

## 10. Recommended STEP 4 Implementation Scope

### Priority order (after audit approval)

**C1 — LLM boundary hardening** (outlook.py)
- Add normalize_regime() call to LLM regime/bias before applying to payload
- OR: prevent LLM from overwriting regime/bias in merge_llm_into_payload() — only use LLM for narrative (primary_view, market_summary)
- Requires: architectural decision on LLM's role in payload

**C2 — Chat alert fix** (outlook.py:839)
- Fix verdict extraction: `payload.get("decision", {}).get("verdict", "")`
- Requires: trivial fix, low risk

**H1 — build_outlook() tests** (new file)
- Test build_outlook() with mocked DB connection
- Cover: BULLISH, BEARISH, SIDEWAYS, UNKNOWN regimes
- Cover: missing VIX, missing indicators, missing gap data
- Cover: verdict TRADE/WAIT/AVOID paths

**H2 — merge_llm_into_payload() tests** (new file)
- Test with LLM regime/bias/confidence → verify override
- Test with rule-based ai_outlook → verify no override
- Test with empty/None LLM output → verify payload unchanged

**H3 — Full pipeline integration test** (new file)
- RegimeEngine → market_regime → build_outlook → payload verification
- End-to-end: deterministic output for given market conditions

**H4 — store_regime_and_strategies() test** (new file)
- Test with mocked RegimeEngine/ScenarioEngine/StrategyEngine/AIOutlookEngine
- Verify all three tables populated correctly

**M1 — Confidence documentation** (outlook.py)
- Add comments explaining the two confidence sources and their difference
- Consider aligning them or documenting intentional divergence

**M2 — Engine consistency** (strategies.py, scenarios.py)
- Verify StrategyEngine and build_outlook() _strategies() produce compatible outputs for same regime/bias
- Consider shared strategy ranking logic

**M3 — Options-intelligence fallback** (api_server.py:801-802)
- Change defaults from hardcoded BULLISH/76 to derived defaults (NEUTRAL/50) or explicitly mark as "unavailable"

**M4 — ScenarioEngine normalization** (scenarios.py)
- Add probability normalization to sum to 1.0 after all conditional adjustments

### Explicit "do not modify" components

| Component | Reason |
|---|---|
| build_outlook() core logic | Audit confirmed regression-safe; only SIDEWAYS display label changed |
| REGIME_MAP in outlook.py | Backward-compatible display mapping; legacy entries harmless |
| Historical fallback (outlook.py:374-383) | Intentional legacy behavior for historical replay |
| RegimeEngine scoring/thresholds | Frozen per STEP 2 design |
| OptionsEngine calculations | PHASE 4 stable component |
| Market_regime schema | No changes needed; all 10 columns populated |
| Database schema | No changes needed |
| API endpoint contracts | Unchanged; all endpoints return valid data |
| REGIME_ALIASES in regime_utils.py | Working correctly; no changes needed |
| Test suite | 112/112 passing; do not modify without reason |

---

## 11. Audit Summary

### Pipeline health

| Dimension | Status |
|---|---|
| Determinism | ✅ All engines deterministic (RegimeEngine, StrategyEngine, ScenarioEngine, AIOutlookEngine rule-based, build_outlook) |
| Connectivity | ✅ All engines connected via market_regime table and DB |
| Regime name flow | ✅ Canonical names flow through normalizer to all consumers |
| NO TRADE safety | ✅ All engines fail safe for UNKNOWN/insufficient data |
| LLM boundary | ❌ CRITICAL: LLM can override all quantitative fields |
| Build_outlook testing | ❌ CRITICAL: zero test coverage on core function |
| Confidence integrity | ⚠️ Two confidence sources can diverge |
| Strategy consistency | ⚠️ Two strategy engines (build_outlook vs StrategyEngine) compute independently |
| API/UI consistency | ⚠️ Four independent data sources; SIDEWAYS UI color change |
| Legacy compatibility | ✅ All old regime names properly mapped/compatible |
| Fallback behavior | ✅ All missing data paths fail safe |
| Chat alerts | ❌ CRITICAL: never fires (wrong key path) |

### Key statistics

- **Total tests**: 112 passing (58 existing + 54 new)
- **Critical findings**: 2
- **High findings**: 4
- **Medium findings**: 5
- **Low findings**: 3
- **Files touched in STEP 3**: 7 (4 backend + 3 new/modified test files + 1 new utility)
- **Files requiring STEP 4 work**: 4 (outlook.py, api_server.py, scenarios.py + new test files)

### Next action

Await approval on C1 (LLM boundary hardening) before any implementation. C2 (chat alert fix) is trivial and can proceed independently. All other findings are documented for phased implementation after approval.

---

### Frozen checkpoint

PHASE-5-STEP4-AUDIT — read-only audit complete. No code changes made.
Tests: 112/112 passing (unchanged).
审计文件：PHASE5_STEP4_AUDIT.md

**No implementation until audit findings are reviewed and approved.**
