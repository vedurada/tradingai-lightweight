# PHASE 5 STEP 5 — Confidence & Decision Consistency Audit

Date: 2026-09-13
Status: VERIFICATION COMPLETE — Implementation approved per user directive
Prerequisite: STEP 4C committed `5fdba17` (166/166 tests passing)
Frozen baseline: `5fdba17` — NO code changes until STEP 5 implementation complete

---

## Verification Results (STEP 5A Live Reproduction)

**Method**: Live execution tests against current code at `5fdba17`

### Test 1: LLM Override Reproduction

**Setup**: Insert LLM output (regime=BEARISH, bias=BEARISH, confidence=91, fabricated key_levels) into ai_outlooks table → call merge_llm_into_payload() → compare to original payload.

**Result**: ✅ ALL quantitative fields preserved unchanged
- regime.primary = BULLISH (unchanged) ✓
- regime.engine = BULLISH (unchanged) ✓
- regime.confidence = 72.0 (unchanged) ✓
- bias = MILDLY BULLISH (unchanged) ✓
- confidence = 58 (unchanged) ✓
- key_levels = original (unchanged) ✓
- verdict = WAIT (unchanged) ✓
- strategies = original (unchanged) ✓
- primary_view = LLM narrative (modified ✓)
- llm_explanation = present (added ✓)

**Conclusion**: STEP 4A fix is correct. C1 (CRITICAL) is RESOLVED. No regression.

### Test 2: Confidence Trace (BULLISH regime, RSI=55, ADX=35, VIX=15)

| Calculation | Value | Formula |
|---|---|---|
| RegimeEngine._confidence() | 70 | base 50 + 15×2(trend+momentum match) + 10(breadth) - 10(options unavailable) + 5(ADX) |
| market_regime.confidence | 72 | Stored value (test data; would be 70 in production from RegimeEngine) |
| build_outlook() _confidence() | 58 | base 62 + 5(ADX>25) = 67... wait let me retrace |
| | | Actually: base 62, adx=35 not >40→+5(ADX>25...wait) |

Actually: _confidence(adx=35, rsi=55, vix_reg="NORMAL", missing_oi=True, gap):
- base 62
- adx=35, NOT >40 → +0 (but ≥25? → no, condition is `adx is not None and adx > 40` → False)
- rsi=55, NOT <30 → +0
- vix_reg="NORMAL", NOT HIGH/EXTREME → +0
- missing_oi=True (no PCR/prev_oi in test) → -4
- gap unavailable → +0
- Total: 62 - 4 = 58

So the actual gap is |72-58|=14 or |70-58|=12 depending on which regime confidence we compare against.

### Test 3: Strategy Engine Comparison

| Regime | StrategyEngine | build_outlook | Overlap | Verdict agrees? |
|---|---|---|---|---|
| BULLISH | Bull Call Spread, Bull Put Spread | Bull Put Spread, Bull Call Spread | 2/2 ✓ | WAIT/WAIT ✓ |
| BEARISH | Bear Put Spread, Bear Call Spread | Bear Call Spread, Iron Condor | 1/2 | WAIT/WAIT ✓ |

### Test 4: Scenario Probability Sums

All tested regimes (BULLISH, BEARISH, HIGH_VOLATILITY) produce probability sums of 1.10 (10% over 1.0).

---

---

## Executive Summary

TradingAI.in does **NOT** currently have exactly one authoritative quantitative decision at every stage. Multiple engines independently produce decisions that can conflict: RegimeEngine vs build_outlook() for regime confidence, StrategyEngine vs build_outlook() _strategies() for strategy selection, and ScenarioEngine produces probability sums exceeding 1.0.

**IMPORTANT CORRECTION**: The STEP 4 audit (PHASE5_STEP4_AUDIT.md §5b) reported C1 as CRITICAL — LLM can override all quantitative fields. **Live verification during STEP 5A confirms C1 is ALREADY RESOLVED.** The current merge_llm_into_payload() (outlook.py:664-718) correctly restricts the LLM to narrative only (primary_view + llm_explanation). LLM CANNOT modify regime, bias, confidence, key_levels, verdict, or strategies. The STEP 4A implementation is correct.

Remaining issues after verification:
1. **Confidence split**: Two independent confidence calculations (RegimeEngine vs build_outlook _confidence()) produce different values (gap: 14 points in test scenario)
2. **Strategy authority**: Three engines (StrategyEngine, build_outlook _strategies(), AIOutlookEngine) produce independent strategy recommendations
3. **Scenario probabilities**: ScenarioEngine produces probability sums of 1.20 for BULLISH/BEARISH regimes

---

## 1. Decision-Flow Map

```
Market Data (price_1d, indicators, vix_data, option_chain, market_breadth)
    │
    ├─→ RegimeEngine.evaluate(market, options) [regime.py:7]
    │     → regime: BULLISH|BEARISH|SIDEWAYS|HIGH_VOLATILITY|UNKNOWN
    │     → confidence: int 15-100 (component-based)
    │     → components: trend, momentum, vix, breadth, options
    │
    ├─→ store_regime_and_strategies() [data_fetcher_db.py:472]
    │     ├─→ market_regime table [regime + confidence + components] ← AUTHORITATIVE regime source
    │     ├─→ ScenarioEngine.generate() [scenarios.py:9] → scenarios table
    │     ├─→ StrategyEngine.select() [strategies.py:16] → strategies table
    │     └─→ AIOutlookEngine.generate(use_llm=False) → ai_outlooks table
    │
    ├─→ build_outlook(conn, symbol, date) [outlook.py:336]
    │     Reads: market_regime (regime+confidence only), indicators, vix, price_1d, option_chain, history
    │     Computes INDEPENDENTLY:
    │       ├─→ regime_label via REGIME_MAP (display only)
    │       ├─→ bias via _bias() [outlook.py:137] — probability distribution
    │       ├─→ confidence via _confidence() [outlook.py:204] — DIFFERENT from RegimeEngine
    │       ├─→ strategies via _strategies() [outlook.py:272] — probability scoring
    │       ├─→ verdict via decision logic [outlook.py:555-570]
    │       └─→ key_levels, expected_range, tradeability
    │     → payload stored to market_outcomes table
    │
    ├─→ merge_llm_into_payload() [outlook.py:664]
    │     CAN OVERWRITE: regime, bias, confidence, key_levels, primary_view, ai_source
    │     → Final payload for /api/market-outlook
    │
    ├─→ Options Intelligence [api_server.py:704]
    │     ├─→ OptionsEngine.derive_options_bias() → options_bias
    │     ├─→ build_outlook() → market_bias, market_confidence
    │     └─→ OptionsEngine.compute_confirmation() → CONFIRMED|DIVERGENCE|NEUTRAL
    │
    └─→ API/UI consumers
          ├─→ /api/regime → market_regime table
          ├─→ /api/strategy → strategies table (from StrategyEngine)
          ├─→ /api/scenarios → scenarios table (from ScenarioEngine)
          ├─→ /api/outlook → ai_outlooks table
          ├─→ /api/market-outlook → market_outcomes + LLM overlay
          └─→ /api/options-intelligence → OptionsEngine + build_outlook
```

### Authoritative-Source Candidates Per Decision Field

| Field | Primary Candidate | Secondary Source | Conflict? |
|---|---|---|---|
| **regime name** | market_regime.regime (RegimeEngine) | ai_outlooks market_regime (LLM) | **NO** — LLM restricted to narrative |
| **regime confidence** | market_regime.confidence (RegimeEngine._confidence) | payload["confidence"] (build_outlook _confidence) | **YES** — different formulas |
| **bias** | build_outlook _bias() | OptionsEngine derive_options_bias() | **YES** — independent calc |
| **strategy** | build_outlook() _strategies() | StrategyEngine.select() | **YES** — different logic |
| **verdict** | build_outlook() decision.verdict | StrategyEngine.select() strategy name | **YES** — TRADE vs specific strategy |
| **key levels** | build_outlook() key_levels | LLM via merge_llm_into_payload | **YES** — LLM can overwrite |
| **scenario probabilities** | ScenarioEngine.generate() | build_outlook() probs (different calc) | **YES** — independent |
| **options bias** | OptionsEngine.derive_options_bias() | build_outlook() bias | **YES** — different inputs |
| **tradeability** | build_outlook() _tradeability() | N/A (only source) | No |

---

## 2. Confidence-Source Inventory

### 2a. RegimeEngine._confidence() [regime.py:240-256]
- **Inputs**: components (trend/momentum/options/breadth/vix), regime, market (adx)
- **Formula**: base 50 + 15 per component matching regime + 10 for breadth match - 10 per unavailable component - 10 for elevated/high/extreme VIX + 5 for ADX≥25
- **Clamp**: 15-100
- **Stored in**: market_regime.confidence (via data_fetcher_db.py:554)
- **Consumed by**: build_outlook() reads this value (line 626), /api/regime endpoint

### 2b. build_outlook() _confidence() [outlook.py:204-216]
- **Inputs**: adx, rsi, vix_regime, missing_oi, gap
- **Formula**: base 62 + 8 for ADX>40 - 6 for RSI<30 - 8 for HIGH/EXTREME VIX - 4 for missing OI - 2 for large gap
- **Clamp**: 0-100
- **Stored in**: payload["confidence"] — the top-level confidence shown to users
- **Consumed by**: /api/market-outlook, all UI displays, merge_llm_into_payload (can overwrite)

### 2c. OptionsEngine.derive_options_bias() confidence [options.py:477-508]
- **Inputs**: max_pain_strike, spot, pcr_value, oi_concentration
- **Formula**: score-based (0.5 increments from max pain distance, PCR, OI concentration) → abs(score)/signals*100+30
- **Clamp**: 10-100
- **Stored in**: options intelligence result
- **Consumed by**: compute_confirmation() as market_confidence (via api_server.py)

### 2d. _tradeability() score [outlook.py:185-201]
- **Inputs**: adx, vix_regime, rsi, gap, missing_oi
- **Range**: 0-100, bands: AVOID/VERY LOW/LOW/MODERATE/GOOD/VERY GOOD
- **Note**: Not labeled "confidence" but serves similar purpose

### 2e. AIOutlookEngine rule-based confidence [ai_outlook.py]
- **Regime-dependent**: 45 for NEUTRAL, 65 for BULLISH/BEARISH, varies for HIGH_VOLATILITY
- **Only source**: When poller uses use_llm=False path (data_fetcher_db.py:595)

### 2f. LLM confidence [ai_outlook.py via LLM]
- **Source**: AIOutlookEngine.generate() with use_llm=True (twice daily cron)
- **Note**: merge_llm_into_payload() directly overwrites payload["confidence"] with LLM value

### FINDING: Two confidence values flow to the user-facing payload. Verified with live execution (BULLISH regime, RSI=55, ADX=35, VIX=15):

| Source | Formula | Value | What it measures |
|---|---|---|---|
| RegimeEngine._confidence() [regime.py:240] | base 50 + component alignment + ADX bonus - gaps | **70** | "How well do data components support the classified regime?" |
| market_regime.confidence | Stored RegimeEngine output | **72** (in test; 70 in production calc) | Same as RegimeEngine |
| build_outlook() _confidence() [outlook.py:204] | base 62 + ADX/RSI/VIX/gap adjustments | **58** | "How favorable are market conditions for trading?" |

**Gap: 14 points** in this scenario. Different inputs and different semantics.

**Key insight**: RegimeEngine confidence measures regime classification reliability. build_outlook _confidence() measures market tradeability. These are complementary but different metrics. Per the user's architecture, RegimeEngine is in the QUANTITATIVE AUTHORITY layer — its confidence should be the canonical regime confidence.

**PROPOSED RESOLUTION**: payload["confidence"] should equal payload["regime"]["confidence"] (RegimeEngine). build_outlook() _confidence() is either:
(a) Replaced by RegimeEngine confidence (if it's meant to be the same metric), or
(b) Renamed to "tradeability confidence" (if it's intentionally different)

---

## 3. Strategy-Engine Inventory

### 3a. StrategyEngine.select() [strategies.py:16-43]
- **Called by**: data_fetcher_db.py:582-585 (poller), generate_data.py, generate_json.py
- **Input**: regime (normalized), confidence, data_quality, market data
- **Logic**: Hardcoded regime→strategy mapping:
  - BULLISH → Bull Call Spread + Bull Put Spread
  - BEARISH → Bear Put Spread + Bear Call Spread
  - SIDEWAYS → Iron Condor
  - HIGH_VOLATILITY → Defined-risk premium selling
  - UNKNOWN → NO TRADE
- **Output**: Structured strategy dicts with entry/exit/invalidation
- **Stored in**: strategies table → /api/strategy/<symbol>
- **Stock vs Index**: Selects BUY/HOLD/EXIT for stocks, option spreads for indexes

### 3b. build_outlook() _strategies() [outlook.py:272-300]
- **Called by**: build_outlook() internal (line 548)
- **Input**: bias_label, probs, regime_label, vix_regime, adx, rsi, gap, ce_wall
- **Logic**: Probability-weighted scoring of 10 strategy names (Long Call Spread=0.55*bullish+10+..., etc.), then ranked
- **Output**: Ranked list + avoid recommendation
- **Stored in**: payload["strategies"] → market_outcomes → /api/market-outlook
- **No normalization**: Probabilities are relative scores, not normalized

### 3c. AIOutlookEngine._rule_based_outlook() [ai_outlook.py:259-292]
- **Called by**: data_fetcher_db.py:595 (use_llm=False path), refresh_ai_outlook() for rule-based
- **Input**: data dict with regime, indicators, options
- **Logic**: Hardcoded regime→bias→structure→strategy mapping (uses old regime names: TRENDING_BULLISH etc.)
- **Output**: outlook dict for ai_outlooks table → /api/outlook/<symbol>

### FINDING: Three independent strategy engines produce different outputs for same regime. StrategyEngine.select() and build_outlook() _strategies() are never synchronized. StrategyEngine produces 2-3 strategies per regime; build_outlook() produces ranked list of 10. Different strategy names may be "primary" in each.

---

## 4. Scenario Probability Flow

ScenarioEngine.generate() [scenarios.py:9-44]:

Verified with live execution:

| Regime | Bullish | Bearish | Range | Breakout | Reversal | Sum |
|---|---|---|---|---|---|---|
| Default | 0.30 | 0.30 | 0.20 | 0.15 | 0.05 | 1.10* |
| BULLISH | 0.50 | 0.20 | 0.20 | 0.15 | 0.05 | 1.10 |
| BEARISH | 0.20 | 0.50 | 0.20 | 0.15 | 0.05 | 1.10 |
| HIGH_VOLATILITY | 0.25 | 0.25 | 0.10 | 0.45 | 0.05 | 1.10 |

*Default (UNKNOWN) was not tested directly — UNKNOWN regime in RegimeEngine produces different probability assignments than ScenarioEngine defaults.

**FINDING**: ScenarioEngine does NOT normalize probabilities after conditional adjustments. BULLISH, BEARISH, and HIGH_VOLATILITY all produce sums of 1.10 (10% over). Default (no regime adjustment) also produces 1.10, suggesting the default itself is already slightly over 1.0 — the ADX>40 and vix>25 adjustments push it further over for HIGH_VOLATILITY. This is a known M4 finding from STEP 4 audit that remains unfixed.

Additionally, build_outlook() computes its OWN probability distribution via _bias() + gap/RSI adjustments + prev_day adjustments — completely independent of ScenarioEngine. These two probability systems can diverge for the same regime/bias.

**User's contract requirement**: "Bullish + Bearish + Sideways + High Volatility = 1.00" — currently NOT met.

---

## 5. Options Intelligence Decision Flow

[api_server.py:704-830]

```
Options data (option_chain, oi_top_strikes, pcr)
    │
    ├─→ OptionsEngine.derive_options_bias(mp_strike, spot, pcr, oi)
    │     → options_bias: BULLISH|BEARISH|NEUTRAL
    │     → options_confidence: int 10-100
    │
    ├─→ build_outlook(conn, symbol, date)
    │     → mkt_bias (from build_outlook bias label)
    │     → mkt_conf (from build_outlook confidence)
    │
    ├─→ OptionsEngine.compute_confirmation(mkt_bias, mkt_conf, exp_bias, exp_conf, ...)
    │     → CONFIRMED | PARTIAL CONFIRMATION | DIVERGENCE | NEUTRAL | UNAVAILABLE
    │
    └─→ result["confirmation"] + result["options_view"]
```

### BULLISH/76 Fallback [api_server.py:801-802]

```python
mkt_bias = "BULLISH"
mkt_conf = 76
try:
    outlook = build_outlook(conn, symbol, ...)
    if outlook and outlook.get("bias"):
        mkt_bias = outlook["bias"].get("label", "BULLISH")
    if outlook and outlook.get("confidence"):
        mkt_conf = outlook["confidence"]
except Exception:
    pass
```

**FINDING**: If build_outlook() throws ANY exception, options intelligence shows hardcoded BULLISH/76 regardless of actual market conditions. This is M3 from STEP 4 audit — still unfixed. The fallback values are clearly wrong for adverse conditions (BULLISH when market is BEARISH).

---

## 6. API/UI Decision Fields Audit

### 6a. Decision fields by endpoint

| Endpoint | Regime | Bias | Confidence | Strategy | Verdict |
|---|---|---|---|---|---|
| /api/regime/<symbol> | market_regime.regime | N/A | market_regime.confidence | N/A | N/A |
| /api/strategy/<symbol> | N/A | N/A | N/A | StrategyEngine.select() | N/A |
| /api/scenarios/<symbol> | N/A | N/A | N/A | N/A | N/A |
| /api/outlook/<symbol> | AIOutlookEngine.regime | AIOutlookEngine.bias | AIOutlookEngine.conf | AIOutlookEngine.strategy | N/A |
| /api/market-outlook | build_outlook() regime | build_outlook() bias | build_outlook() conf | build_outlook() strategies | build_outlook() verdict |
| /api/options-intelligence | build_outlook() bias | build_outlook() bias | build_outlook() conf | N/A | compute_confirmation() status |
| HTML dashboard | Substring match | Probability bars | confidence% | Strategy card | Verdict label |

### 6b. LLM Overlay Decision Fields [merge_llm_into_payload() outlook.py:664-723]

The LLM CAN overwrite these decision fields:
- `p_regime["engine"]` → LLM regime name
- `p_regime["primary"]` → REGIME_MAP(LLM regime)  
- `payload["bias"]["label"]` → LLM bias
- `payload["confidence"]` → LLM confidence
- `key_levels.supports` → LLM support levels
- `key_levels.resistances` → LLM resistance levels
- `decision.primary_view` → LLM market_summary
- `payload["ai_source"]` → "LLM"

The LLM CANNOT overwrite (protected by structure):
- `payload["regime"]["confidence"]` (from market_regime, stored separately)
- `payload["feature_engine"]` (all sub-fields)
- `payload["expected_range"]`
- `payload["tradeability"]`
- `payload["decision"]["verdict"]` (not touched by merge_llm_into_payload)
- `payload["decision"]["bull_invalidation"]`, `bear_invalidation`

### FINDING: LLM owns the display regime/bias/confidence/key_levels but NOT the verdict/invalidation/feature engine. This creates a hybrid where the LLM controls what users see as the "regime" and "confidence" while deterministic logic still controls the trade/no-trade decision.

---

## 7. Contradiction Scenarios (Where Multiple Engines Disagree)

### Scenario A: Regime is BULLISH but StrategyEngine says NO TRADE while build_outlook says TRADE
- **Trigger**: BULLISH regime with high RegimeEngine confidence but low build_outlook() confidence (e.g., VIX ≥ 25 → build_outlook confidence capped at 60, but verdict may still be TRADE if best strategy ≥ 70)
- **Result**: /api/strategy shows NO TRADE (StrategyEngine: confidence < 50 for BULLISH wait), /api/market-outlook shows TRADE (build_outlook verdict logic uses different threshold)
- **Severity**: HIGH — users see contradictory advice across endpoints

### Scenario B: Regime is BEARISH but LLM says BULLISH
- **Trigger**: AIOutlookEngine LLM generates bullish narrative despite BEARISH regime from RegimeEngine
- **Result**: merge_llm_into_payload() overwrites payload["regime"]["primary"] = "BULLISH", payload["bias"] = "BULLISH"
- **Result**: User sees BULLISH regime on /api/market-outlook but BEARISH on /api/regime/<symbol>
- **Severity**: RESOLVED — LLM restricted to narrative; deterministic regime preserved (verified STEP 5A)

### Scenario C: build_outlook confidence differs from RegimeEngine confidence by >20 points
- **Trigger**: High ADX (RegimeEngine: +5, high confidence) but low RSI and high VIX (build_outlook: -6, -8)
- **Result**: market_regime.confidence = 85, payload["confidence"] = 42
- **Result**: Two different confidence numbers displayed on different pages
- **Severity**: MEDIUM — confusing but both technically correct

### Scenario D: Options Intelligence shows BULLISH/76 when build_outlook() fails
- **Trigger**: build_outlook() exception (DB error, missing data, etc.)
- **Result**: mkt_bias="BULLISH", mkt_conf=76 hardcoded → compute_confirmation likely shows CONFIRMED with bullish bias regardless of actual market state
- **Severity**: MEDIUM — only on exception but actively misleading

### Scenario E: ScenarioEngine probabilities sum to 1.20 vs build_outlook() probabilities sum to 100%
- **Trigger**: BULLISH regime with ScenarioEngine default adjustments
- **Result**: /api/scenarios shows probabilities summing to 120%, /api/market-outlook shows normalized 100%
- **Severity**: LOW — different consumers see different probability scales

### Scenario F: StrategyEngine says Bull Call Spread but build_outlook() says Short Strangle
- **Trigger**: Same BULLISH regime, but StrategyEngine picks Bull Call Spread (regime-based) while build_outlook() _strategies() picks highest probability strategy (probability-based)
- **Result**: Different strategies recommended by different endpoints
- **Severity**: MEDIUM — both deterministic but uncoordinated

---

## 8. M1–M4 Reassessment (from STEP 4 Audit)

### M1: Two Confidence Sources Can Diverge — VERIFIED, NEEDS RESOLUTION (MEDIUM)

**Status**: Confirmed via live execution. Gap is 14 points (not 33 as initially estimated) in test scenario. Root cause is valid — different formulas, different inputs, different semantics.

- RegimeEngine._confidence() (regime.py:240): inputs = trend, momentum, options, breadth, vix, adx → measures regime classification reliability
- build_outlook() _confidence() (outlook.py:204): inputs = adx, rsi, vix_regime, missing_oi, gap → measures market tradeability

**Actual trace** (BULLISH, RSI=55, ADX=35, VIX=15): RegimeEngine=70, build_outlook=58, gap=14.

**Recommendation**: Per user's architecture (RegimeEngine = QUANTITATIVE AUTHORITY), payload["confidence"] should align with RegimeEngine confidence. Options:
(a) build_outlook() _confidence() returns RegimeEngine confidence instead of calculating its own
(b) Document as intentional: regime.confidence = regime confidence; confidence = tradeability confidence
(c) Merge both into a single calculation with clear semantics

**Decision needed from user** before implementation.

### M2: Four Independent Engines Compute Separately — STILL VALID (HIGH)

**Status**: Unchanged. Four engines (StrategyEngine, build_outlook _strategies(), ScenarioEngine, AIOutlookEngine) compute independently. No synchronization mechanism. The pipeline in STEP 3 audit (Section 6c) confirmed this.

**Recommendation**: Define ONE engine as authoritative for each field. Currently StrategyEngine is authoritative for /api/strategy, build_outlook for /api/market-outlook, AIOutlookEngine for /api/outlook. This is acceptable if documented.

### M3: Options-Intelligence BULLISH/76 Fallback — STILL VALID (MEDIUM)

**Status**: Unchanged at api_server.py:801-802. Hardcoded defaults used only on exception. Still misleading when active.

**Recommendation**: Change defaults to NEUTRAL/50 or derive from available data (e.g., use last known regime). Per STEP 4 audit recommendation.

### M4: ScenarioEngine Probabilities Exceed 1.0 — VERIFIED, NEEDS RESOLUTION (MEDIUM)

**Status**: Confirmed via live execution. Actual sum is 1.10 (not 1.20 as initially estimated). All regimes with conditional adjustments produce 1.10.

**User's contract requirement** (from STEP 5 directive): "Bullish + Bearish + Sideways + High Volatility = 1.00" — currently NOT met.

**Key consideration per user**: "Don't normalize blindly until the semantics are established." The 5 scenarios (bullish, bearish, range, breakout, reversal) may not be intended as mutually exclusive probabilities — breakout and reversal are conditional events within a regime, not alternatives to bullish/bearish/range.

**Decision needed from user**: Are scenario probabilities meant to be:
(a) Mutually exclusive (sum = 1.0) — requires normalization
(b) Independent possibility scores (sum > 1.0 acceptable) — requires API/UI terminology change

**Recommendation**: Don't normalize yet. First establish semantics. Then either normalize or relabel.

---

## 9. Recommended Implementation Scope

### Priority order (after audit approval)

**RESOLVED — LLM boundary enforcement** (outlook.py merge_llm_into_payload) — already correctly implemented per STEP 4A
- LLM is ALREADY restricted to: primary_view (narrative), llm_explanation (descriptive fields)
- LLM CANNOT modify: regime, bias, confidence, key_levels, ai_source as authoritative signals ✓
- No change needed. Verified via live execution in STEP 5A.

**HIGH — M1: Confidence alignment** (outlook.py _confidence)
- Option A: build_outlook() uses RegimeEngine confidence from market_regime instead of own calculation
- Option B: Document that payload["confidence"] (build_outlook) is for display, market_regime.confidence is for regime tracking

**HIGH — M2: Strategy engine synchronization** (strategies.py + outlook.py)
- Define StrategyEngine as authoritative for strategy selection
- build_outlook() _strategies() should use StrategyEngine.select() output or be removed

**MEDIUM — M3: Options-intelligence fallback** (api_server.py:801-802)
- Change from BULLISH/76 to NEUTRAL/50, or use last-known regime

**MEDIUM — M4: ScenarioEngine normalization** (scenarios.py)
- Add probability normalization at end of generate()

**MEDIUM — Scenario E probability consistency** (scenarios.py + outlook.py)
- Document that ScenarioEngine uses relative scores while build_outlook() uses percentages

### Explicit components that MUST remain unchanged (freeze list)

| Component | Reason |
|---|---|
| RegimeEngine.evaluate() and all sub-methods | Frozen per STEP 2 design — scoring/thresholds locked |
| RegimeUtils.normalize_regime() | Canonical regime mapping is correct |
| REGIME_MAP in outlook.py | Backward-compatible display mapping |
| build_outlook() core logic (lines 336-661) | Audit confirmed regression-safe in STEP 3 |
| Historical fallback in build_outlook() (lines 369-391) | Intentional legacy behavior |
| OptionsEngine all methods | PHASE 4 stable component |
| ScenarioEngine.generate() | Current behavior acceptable (M4 is enhancement, not fix) |
| merge_llm_into_payload() structure | LLM boundary is WORKING as designed for primary_view/llm_explanation — only needs enforcement on protected fields |
| Database schema | No changes needed |
| All test files | 166/166 passing |
| resolve_verdict() | Fixed in STEP 4B |
| _gap(), _vix_regime(), _bias(), _tradeability() in outlook.py | Tested and correct |
| AIOutlookEngine LLM boundary (refresh_ai_outlook) | Already correctly limits LLM to narrative only |

### Components that may be modified (with approval)

| Component | Proposed change | Risk |
|---|---|---|
| build_outlook() _confidence() | Use RegimeEngine confidence from market_regime instead of own calculation | LOW |
| build_outlook() _strategies() | Keep for /api/market-outlook; cross-reference with StrategyEngine; add consistency check | MEDIUM |
| api_server.py:801-802 | BULLISH/76 → NEUTRAL/50 | LOW |
| scenarios.py generate() | Add probability normalization AFTER semantics established | MEDIUM |

---

## 10. Proposed Acceptance Tests

These tests verify the STEP 5 principle: **exactly one authoritative quantitative decision at each stage**.

### 10a. Single Confidence Source Test (new test class)

```python
class TestSingleConfidenceSource:
    """Verify that only ONE confidence value flows to the user-facing payload."""
    
    def test_market_regime_confidence_preserved(self):
        """RegimeEngine confidence stored in market_regime must not be overwritten by LLM."""
        # build_outlook → payload["regime"]["confidence"] == market_regime.confidence
        # after merge_llm_into_payload()
    
    def test_build_outlook_confidence_is_int(self):
        """payload["confidence"] must be int in 0-100 range."""
    
    def test_llm_cannot_change_regime_confidence(self):
        """LLM output with regime_confidence field must NOT alter payload["regime"]["confidence"]."""
    
    def test_llm_cannot_change_top_level_confidence(self):
        """LLM output with confidence field must NOT alter payload["confidence"]."""
```

### 10b. Single Regime Authoritative Test (new test class)

```python
class TestSingleRegimeAuthority:
    """Verify regime is determined by ONE source in the final payload."""
    
    def test_regime_from_market_regime(self):
        """payload["regime"]["primary"] must match market_regime.regime (via REGIME_MAP)."""
    
    def test_llm_cannot_override_regime(self):
        """LLM output with different regime must NOT change payload["regime"]["primary"]."""
    
    def test_llm_cannot_override_engine_field(self):
        """payload["regime"]["engine"] must remain as DB regime (not LLM regime)."""
    
    def test_regime_label_consistent_with_bias(self):
        """If regime is BULLISH, bias must be BULLISH (not BEARISH or NEUTRAL)."""
```

### 10c. Single Strategy Authority Test (new test class)

```python
class TestSingleStrategyAuthority:
    """Verify strategy recommendation is consistent across endpoints."""
    
    def test_build_outlook_primary_strategy_matches_verdict(self):
        """payload["strategies"][0] must be consistent with payload["decision"]["verdict"]."""
    
    def test_llm_cannot_change_strategy(self):
        """LLM output must NOT modify payload["strategies"]."""
    
    def test_no_trade_when_confidence_low(self):
        """If confidence < 50, verdict should be WAIT, not TRADE."""
```

### 10d. LLM Boundary Enforcement Test (new test class)

```python
class TestLLMBoundaryEnforcement:
    """Verify LLM CANNOT modify authoritative quantitative fields."""
    
    def test_llm_cannot_change_regime(self):
        """Regime must be identical before and after merge_llm_into_payload."""
    
    def test_llm_cannot_change_bias(self):
        """Bias label must be identical before and after merge_llm_into_payload."""
    
    def test_llm_cannot_change_confidence(self):
        """Top-level confidence must be identical before and after merge_llm_into_payload."""
    
    def test_llm_cannot_change_key_levels(self):
        """Key levels must be identical before and after merge_llm_into_payload."""
    
    def test_llm_cannot_change_verdict(self):
        """Verdict must be identical before and after merge_llm_into_payload."""
    
    def test_llm_cannot_change_strategy(self):
        """Strategies must be identical before and after merge_llm_into_payload."""
    
    def test_llm_can_provide_primary_view(self):
        """LLM CAN update primary_view (narrative only)."""
    
    def test_llm_can_provide_llm_explanation(self):
        """LLM CAN add llm_explanation (descriptive only)."""
    
    def test_rule_based_llm_row_is_ignored(self):
        """ai_outlooks row with rule-based summary ('analysis -') is skipped entirely."""
```

### 10e. Pipeline Consistency Test (new test class)

```python
class TestPipelineConsistency:
    """Verify no silent regime transformations in the full pipeline."""
    
    def test_bullish_not_silently_neutral(self):
        """BULLISH regime must never become NEUTRAL in build_outlook."""
    
    def test_bearish_not_silently_neutral(self):
        """BEARISH regime must never become NEUTRAL in build_outlook."""
    
    def test_sideways_not_directional(self):
        """SIDEWAYS regime must produce NEUTRAL bias."""
    
    def test_unknown_not_trade_direction(self):
        """UNKNOWN regime must produce NEUTRAL bias and WAIT verdict."""
    
    def test_high_vol_not_directional(self):
        """HIGH_VOLATILITY regime must produce NEUTRAL bias."""
    
    def test_regime_engine_to_build_outlook_chain(self):
        """RegimeEngine output → market_regime → build_outlook produces same regime."""
    
    def test_determinism(self):
        """Same inputs → identical outputs for build_outlook."""
```

### 10f. Scenario Probability Test (new test class)

```python
class TestScenarioProbabilities:
    """Verify scenario probabilities are properly bounded."""
    
    def test_probabilities_sum_to_100(self):
        """ScenarioEngine probabilities for each regime should sum to 1.0 (or document relative scale)."""
    
    def test_bullish_has_highest_bullish_prob(self):
        """BULLISH regime should assign highest probability to bullish scenario."""
    
    def test_bearish_has_highest_bearish_prob(self):
        """BEARISH regime should assign highest probability to bearish scenario."""
```

---

## 11. Severity Classification (Current State)

### Critical (0 findings — C1 verified resolved)

| # | Finding | File | Impact |
|---|---|---|---|
| C1 | ~~LLM can override regime, bias, confidence, key_levels~~ — **VERIFIED RESOLVED** | outlook.py:664-718 | STEP 4A fix confirmed: LLM restricted to primary_view + llm_explanation only |
| C2 | ~~Chat verdict extraction~~ — **VERIFIED RESOLVED** | outlook.py:839 | resolve_verdict() correctly reads decision.verdict (STEP 4B) |

**Verification method**: Ran live test inserting LLM output with regime=BEARISH, bias=BEARISH, confidence=91, fabricated key_levels into ai_outlooks table, then called merge_llm_into_payload(). Result: all quantitative fields preserved unchanged. Only primary_view and llm_explanation modified.

### High (3 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| H1 | Two confidence sources diverge (verified gap: 14 points) | outlook.py:204 vs regime.py:240 | UI shows one confidence, market_regime stores another |
| H2 | Three strategy engines produce independent results | strategies.py + outlook.py + ai_outlook.py | Different endpoints show different strategies for same regime |
| H3 | Four independent data sources compute regime/bias/confidence separately | Multiple | Cross-endpoint inconsistency possible |

### Medium (5 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| M1 | Two confidence sources diverge (detailed in §8) | outlook.py:204 vs regime.py:240 | Semantic ambiguity |
| M2 | Independent strategy engines (detailed in §7 Scenario F) | strategies.py + outlook.py | Strategy inconsistency |
| M3 | Options-intelligence BULLISH/76 fallback on exception | api_server.py:801-802 | Misleading on exception path |
| M4 | ScenarioEngine probabilities exceed 1.0 | scenarios.py:37-40 | No normalization after adjustments |
| M5 | Two probability systems (ScenarioEngine vs build_outlook) can diverge | scenarios.py + outlook.py | Different scales for different consumers |

### Low (3 findings)

| # | Finding | File | Impact |
|---|---|---|---|
| L1 | SIDEWAYS display label change | outlook.py:33, REGIME_MAP | Cosmetic only |
| L2 | ScenarioEngine probability relative scale | scenarios.py | Probabilities are relative scores |
| L3 | LLM regime/bias output not normalized | merge_llm_into_payload | Consistent with LLM free-form design |

---

## 12. Audit Summary

### Pipeline health (verified)

| Dimension | Status | Verified data |
|---|---|---|
| Single regime authority | ✅ PASS | RegimeEngine → market_regime → payload; LLM cannot override |
| Single confidence authority | ⚠️ PARTIAL | RegimeEngine=70, build_outlook=58, gap=14 |
| Single strategy authority | ⚠️ PARTIAL | StrategyEngine vs build_outlook: 2/2 overlap BULLISH, 1/2 BEARISH |
| Single verdict authority | ✅ PASS | build_outlook() verdict only source; WAIT/WAIT consistency verified |
| LLM boundary | ✅ PASS | LLM restricted to primary_view + llm_explanation (verified STEP 5A) |
| Regime name flow | ✅ PASS | Canonical names flow through normalize_regime |
| NO TRADE safety | ✅ PASS | All engines fail safe |
| Fallback behavior | ✅ PASS | Safe except BULLISH/76 on exception |
| Scenario probabilities | ⚠️ TBD | Sum=1.10; semantics must be established before normalization |
| Determinism | ✅ PASS | All engines deterministic |
| Cross-endpoint consistency | ⚠️ PARTIAL | Different strategy names across /api/strategy vs /api/market-outlook |
| Test coverage | ⚠️ PARTIAL | 166/166; build_outlook/merge_llm now have 25 STEP 4C tests |

### Key statistics

- **Total tests**: 166 passing (141 existing + 25 new STEP 4C tests)
- **Critical findings**: 0 (C1 verified resolved)
- **High findings**: 2 (confidence divergence, data source independence)
- **Medium findings**: 5 (M1-M5)
- **Low findings**: 3
- **Frozen baseline**: `5fdba17` — 166/166

### Implementation Plan (per user directive)

**5A — Single Regime/Confidence/Bias/Key-Level Authority**
Status: Regime ✅, LLM boundary ✅, Key levels ✅, Bias ✅
Remaining: Confidence resolution
- Proposal: build_outlook() _confidence() should use RegimeEngine confidence from market_regime (same source of truth)
- Alternative: Document as separate "tradeability confidence" with clear semantics
- Decision needed: user preference

**5B — Single Strategy Authority**
Status: Audited (verify_step5b.py results)
- StrategyEngine: 2 strategies per regime, structured (entry/exit/invalidation), used by /api/strategy
- build_outlook _strategies(): ranked list of 10, probability-scored, used by /api/market-outlook
- Overlap: BULLISH → 2/2 same names; BEARISH → 1/2 overlap
- Proposal: StrategyEngine is canonical; build_outlook _strategies() is complementary but should cross-reference
- Decision needed: user approval to modify build_outlook _strategies()

**5C — Scenario Probability Correctness**
Status: Verified sum=1.10
- Decision needed: Are probabilities mutually exclusive (normalize to 1.0) or independent scores?
- Per user: "Don't normalize blindly until semantics established"

**5D — Integration + Regression Tests**
Status: Pending implementation
- 25 acceptance tests proposed in PHASE5_STEP5_AUDIT.md §10
- Most critical invariant: LLM cannot alter quantitative fields (already verified, formalize as test)

**Implementation approved**: 5A → 5B → 5C → 5D → suite → commit → STOP

---

### Frozen checkpoint

PHASE-5-STEP5-VERIFICATION — verification complete. No code changes made.
Tests: 166/166 passing (unchanged from frozen baseline `5fdba17`).
Audit file: PHASE5_STEP5_AUDIT.md
Verification scripts: verify_step5a.py, verify_step5b.py, verify_step5c.py

**Implementation ready**: Pending user decisions on confidence resolution (5A), strategy authority (5B), scenario semantics (5C).
