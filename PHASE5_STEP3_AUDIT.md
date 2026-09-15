# PHASE 5 STEP 3 — Regime Integration Audit

Date: 2026-09-13
Status: AUDIT ONLY — no code changes
Prerequisite: STEP 2 committed `c615235` (58/58 tests passing)

---

## 1. build_outlook() — What It Produces

`build_outlook(conn, symbol, date)` at `backend/outlook.py:336` is a 938-line function producing a structured dict payload with these top-level fields:

| Field | Description |
|---|---|
| `date`, `symbol`, `as_of_ist` | Identifiers |
| `regime` | `{primary, engine, confidence}` — regime name + display label + DB confidence |
| `bias` | `{label, probs}` — BULLISH/BEARISH/NEUTRAL with probability distribution |
| `confidence` | Overall confidence 0-100 |
| `vix` | VIX value, regime, trend, change |
| `tradeability` | `{score, band}` — AVOID to VERY GOOD |
| `expected_range`, `volatility_favours`, `gap` | Derived from indicators |
| `key_levels`, `indicators`, `expiry`, `options` | Support/resistance, EMA/RSI/MACD, expiry, PCR/OI |
| `feature_engine` | prev_day, market_open, past_confirmation, hierarchy |
| `strategies`, `strategy_to_avoid`, `avoid_reason` | Ranked option strategies |
| `decision` | `{verdict: TRADE/WAIT, primary_view, bull/bear_invalidation}` |
| `trades` | Historical trade records for that date |

---

## 2. Inputs build_outlook() Reads Directly

From DB (all by symbol and/or date):

| Table | Used for | Notes |
|---|---|---|
| `indicators` | RSI, ADX, ATR, EMA20/50/200, VWAP, MACD, support/resistance, pivot | Primary input |
| **`market_regime`** | **regime name, confidence** | **NEW — only 2 fields consumed** |
| `vix_data` | VIX price, regime, trend | Independent of market_regime |
| `price_1d` | OHLCV for gap/pattern analysis | Independent |
| `option_chain`, `oi_top_strikes`, `option_expiries` | PCR, CE wall, strikes | Independent |
| `history` | Past trades for verdict | Independent |

**Critical observation**: build_outlook() reads market_regime at `outlook.py:339` and consumes **exactly 2 fields**: `regime` (string) and `confidence` (number). No other market_regime columns (trend, momentum, volatility, breadth, vix_regime) are read by build_outlook().

---

## 3. How build_outlook() Consumes market_regime

### 3a. Regime Name Resolution (`outlook.py:479-480`)

```python
reg_key = str(reg.get("regime", "")).upper()
regime_label = REGIME_MAP.get(reg_key, reg_key if reg_key else "UNKNOWN")
```

This reads the regime name from market_regime table, uppercases it, then maps through REGIME_MAP.

### 3b. REGIME_MAP Behavior with New Regime Names

| New regime name in DB | REGIME_MAP lookup | regime_label (display) | Old regime_label | Change? |
|---|---|---|---|---|
| BULLISH | REGIME_MAP["BULLISH"] = "BULLISH" | BULLISH | BULLISH | **No** |
| BEARISH | REGIME_MAP["BEARISH"] = "BEARISH" | BEARISH | BEARISH | **No** |
| SIDEWAYS | Not in map → fallback | SIDEWAYS | NEUTRAL / RANGE | **Yes** |
| HIGH_VOLATILITY | REGIME_MAP["HIGH_VOLATILITY"] = "EVENT / ABNORMAL VOLATILITY" | EVENT / ABNORMAL VOLATILITY | EVENT / ABNORMAL VOLATILITY | **No** |

Only SIDEWAYS shows a different display label than the old RANGE_BOUND mapping.

### 3c. Bias Computation (`outlook.py:137-182`)

`_bias(regime_label, rsi, gap)` uses **substring matching** on the regime name:

```python
if "BEARISH" in key:  # BULLISH? No. BEARISH? Yes. SIDEWAYS? No. → NEUTRAL
    ...
elif "BULLISH" in key:  # BULLISH? Yes → BULLISH bias
    ...
else:  # SIDEWAYS → NEUTRAL (same as RANGE_BOUND was)
```

| New regime_label | _bias result | Old regime_label | _bias result | Same? |
|---|---|---|---|---|
| BULLISH | BULLISH bias | BULLISH | BULLISH bias | **Yes** |
| BEARISH | BEARISH bias | BEARISH | BEARISH bias | **Yes** |
| SIDEWAYS | NEUTRAL bias | NEUTRAL / RANGE | NEUTRAL bias | **Yes** |
| EVENT / ABNORMAL VOLATILITY | NEUTRAL bias | EVENT / ABNORMAL VOLATILITY | NEUTRAL bias | **Yes** |

**Verdict**: `_bias()` behavior is **100% preserved** for all new regime names.

### 3d. Strategy Scoring (`outlook.py:272-300`)

`_strategies(bias_label, probs, reg, ...)` — the `reg` parameter (regime name) is **NOT used** in any scoring logic. Only `bias_label` and `probs` matter (line 293):

```python
strong_bias = (p.get("bullish") or 0) >= 40 or (p.get("bearish") or 0) >= 40 or bias_label in (...)
```

**Verdict**: Strategy scoring is **100% preserved** regardless of regime name.

### 3e. Verdict Logic (`outlook.py:547-563`)

Verdict depends on: `bias_label`, `past_trend`, `oi_trend`, `past_confirms_bias`, `rsi_bounce`, `best[1]`, `gap`. None of these depend on regime name.

### 3f. Historical Fallback (`outlook.py:362-391`)

When no indicator/regime exists as of a date (historical replay before market_regime was populated), build_outlook() synthesizes from price_1d SMA using **old regime names**: "TRENDING_BULLISH", "TRENDING_BEARISH", "BULLISH_RANGE", "BEARISH_RANGE", "RANGE_BOUND". These ARE in REGIME_MAP and map correctly. This is a PHASE-3 legacy feature and should remain untouched.

---

## 4. build_outlook() VERDICT

**build_outlook() is REGRESSION-SAFE**. The regime name flows through:
1. REGIME_MAP → display label (BULLISH/BEARISH unchanged; SIDEWAYS is new display name)
2. _bias() → bias probabilities (preserved via substring matching)
3. _strategies() → strategy scoring (regime name not used)
4. Verdict → (preserved)

**The ONLY behavioral change in build_outlook() is**: SIDEWAYS regime now displays as "SIDEWAYS" instead of "NEUTRAL / RANGE". This is cosmetic and does not affect bias, strategy, or verdict computation.

**No code change to build_outlook() is required.**

---

## 5. Consumer-by-Consumer Analysis

### 5a. CRITICAL — strategies.py StrategyEngine.select()

**File**: `backend/strategies.py`
**Called by**: `data_fetcher_db.py:585`, `generate_data.py:83`, `generate_json.py:66`

Hardcoded regime name checks:
- Line 20: `if regime == "TRENDING_BULLISH":` → NEW: "BULLISH" → **WILL NOT MATCH**
- Line 25: `elif regime == "TRENDING_BEARISH":` → NEW: "BEARISH" → **WILL NOT MATCH**
- Line 30: `elif regime == "RANGE_BOUND":` → NEW: "SIDEWAYS" → **WILL NOT MATCH**
- Line 34: `elif regime == "HIGH_VOLATILITY":` → **matches** ✓
- Line 78: `elif regime == "TRENDING_BULLISH" and confidence >= 50:` → **WILL NOT MATCH**
- Line 82: `elif regime == "TRENDING_BEARISH":` → **WILL NOT MATCH**
- Line 86: `elif regime == "HIGH_VOLATILITY":` → **matches** ✓
- Line 90: `elif regime == "RANGE_BOUND":` → **WILL NOT MATCH**

**Impact**: For index symbols, StrategyEngine.select() now returns **NO TRADE** for all regimes except HIGH_VOLATILITY. For stocks, BUY/EXIT logic through TRENDING_BULLISH/TRENDING_BEARISH never triggers. This changes the `strategies` table content and affects `/api/strategy/<symbol>`, daily_page strategy display, and all downstream consumers.

**This is a BEHAVIOR BREAKING CHANGE.**

### 5b. HIGH — scenarios.py ScenarioEngine.generate()

**File**: `backend/scenarios.py`
**Called by**: `data_fetcher_db.py:581`, `generate_data.py:82`, `generate_json.py:65`

Hardcoded regime checks:
- Line 14: `if regime == "TRENDING_BULLISH":` → **WILL NOT MATCH**
- Line 20: `elif regime == "TRENDING_BEARISH":` → **WILL NOT MATCH**
- Line 26: `elif regime == "HIGH_VOLATILITY":` → **matches** ✓
- Line 32: `elif regime == "RANGE_BOUND":` → **WILL NOT MATCH**

**Impact**: Scenario probability adjustments will NOT trigger for BULLISH/BEARISH/SIDEWAYS. All scenarios use default probabilities (0.3/0.3/0.2/0.15/0.05) regardless of regime. Affects `/api/scenarios/<symbol>` and daily page scenario displays.

### 5c. CRITICAL — ai_outlook.py _rule_based_outlook()

**File**: `backend/ai_outlook.py:259-292`
**Called by**: `data_fetcher_db.py:595` (use_llm=False path)

Hardcoded regime checks:
- Line 264: `if regime == "TRENDING_BULLISH":` → **WILL NOT MATCH**
- Line 267: `elif regime == "TRENDING_BEARISH":` → **WILL NOT MATCH**
- Line 278: `structure = "UPTREND" if regime == "TRENDING_BULLISH"` → **WILL NOT MATCH**
- Line 278: `else ("DOWNTREND" if regime == "TRENDING_BEARISH"` → **WILL NOT MATCH**

**Impact**: When the poller falls back to rule-based outlook (not LLM), all index symbols will get NEUTRAL bias with 45 confidence instead of BULLISH/BEARISH with 65 confidence. This affects the `ai_outlooks` table content and all consumers of that table.

### 5d. MEDIUM — ai_outlook.py LLM prompt

**File**: `backend/ai_outlook.py:35`

LLM prompt specifies: `market_regime: TRENDING_BULLISH/TRENDING_BEARISH/RANGE_BOUND/HIGH_VOLATILITY/UNCONFIRMED`

The prompt tells the LLM to return OLD regime names. The rule engine returns NEW names. This is a **prompt inconsistency** that could confuse the LLM or cause it to return names incompatible with downstream processing.

### 5e. MEDIUM — alert.py false regime change alerts

**File**: `backend/alert.py:68-71`

Compares prev/curr regime as strings. When existing data transitions from old regime names ("TRENDING_BULLISH") to new names ("BULLISH") in the database, alerts will fire for regime changes that are semantically identical. This affects the history table data that was populated before STEP 2.

### 5f. LOW — daily_page.py display

**File**: `backend/daily_page.py:165`

Displays `{reg.get('regime','N/A')}` directly from market_regime table. Will now show "BULLISH" instead of "TRENDING_BULLISH", "SIDEWAYS" instead of "RANGE_BOUND". This is expected and correct — it shows the authoritative regime name.

### 5g. LOW — pnl_tracker.py

**File**: `backend/pnl_tracker.py:115,301`

Reads regime/confidence from market_regime for display/reporting. No logic impact.

### 5h. NONE — API endpoints

| Endpoint | Reads from | Impact |
|---|---|---|
| `/api/regime/<symbol>` | market_regime directly | None — returns whatever is in DB |
| `/api/regimes` | market_regime directly | None |
| `/api/market-outlook` | build_outlook() | None — verified regression-safe above |
| `/api/strategy/<symbol>` | strategies table | **Affected** — strategies.py mismatch |
| `/api/scenarios/<symbol>` | scenarios table | **Affected** — scenarios.py mismatch |

### 5i. NONE — backtest.py

Uses its own regime names (RANGE, VIX_SPIKE, VIX_HIGH). Independent of market_regime table. No impact.

### 5j. NONE — historical fallback in build_outlook()

Synthesizes old regime names from price_1d SMA for historical replay. REGIME_MAP handles them correctly. No impact.

---

## 6. Full Pipeline Data Flow (Post-STEP 2)

```
Data fetch → RegimeEngine.evaluate(market, options) → regime_info
  regime_info.regime = "BULLISH" | "BEARISH" | "SIDEWAYS" | "HIGH_VOLATILITY"
  regime_info.confidence = int 0-100

store_regime_and_strategies(conn, symbol):
  1. Save regime_info to market_regime table ✓
  2. ScenarioEngine.generate(regime_info["regime"], ...) ← BREAKS: hardcoded old names
  3. StrategyEngine.select(regime_info["regime"], ...) ← BREAKS: hardcoded old names
  4. AIOutlookEngine.generate(symbol, {...,"regime": regime_info["regime"]}, use_llm=False) ← BREAKS: _rule_based_outlook hardcoded old names
  5. Save results to scenarios, strategies, ai_outlooks tables

build_outlook(conn, symbol, date):
  1. Read market_regime ← OK
  2. REGIME_MAP → display labels ← OK (only SIDEWAYS display changes)
  3. _bias(), _strategies(), verdict ← OK (all regime-name agnostic)
  4. Produce payload ← OK
  5. Save to market_outlooks ← OK

API consumers:
  /api/regime ← reads market_regime ← OK
  /api/market-outlook ← build_outlook() ← OK
  /api/strategy ← strategies table ← BROKEN (strategies.py)
  /api/scenarios ← scenarios table ← BROKEN (scenarios.py)
```

---

## 7. STEP 3 Requirements Assessment

### What build_outlook() requires:
- **Nothing**. It is regression-safe. No code change needed.

### What the PIPELINE requires:
- StrategyEngine, ScenarioEngine, and AIOutlookEngine rule-based path all have hardcoded OLD regime names and WILL BREAK with new regime names from RegimeEngine.
- These engines are called by `data_fetcher_db.py:store_regime_and_strategies()` and `generate_data.py`/`generate_json.py`.

### What STEP 3 needs (per user directive):
1. **Do NOT replace build_outlook()** — it is stable and regression-safe.
2. **Fix engine interface compatibility**: Update StrategyEngine, ScenarioEngine, and AIOutlookEngine._rule_based_outlook() to accept new regime names while maintaining backward compatibility with any stored data using old names.
3. **Test full pipeline**: Verify data-fetch → RegimeEngine → market_regime → Strategy/Scenario/AI → DB → API/OUPUT is deterministic and correct.
4. **Add integration/regression tests**: Verify that equivalent regime inputs produce equivalent outputs across old and new names.
5. **Only then consider historical regime validation**.

### Target architecture (per user):
```
Market Data
    ↓
RegimeEngine
    ↓
market_regime
    ↓
[StrategyEngine + ScenarioEngine + AIOutlookEngine] ← UPDATE INTERFACE
    ↓
Bias / Confidence / Range / Key Levels / Verdict
    ↓
build_outlook() compatibility layer ← UNTOUCHED
    ↓
Options Intelligence / UI
```

---

## 8. Design Decisions Required Before Implementation

| # | Question | Recommendation |
|---|---|---|
| 1 | Should StrategyEngine accept both old and new regime names? | Yes — backward compat with stored data |
| 2 | Should ScenarioEngine accept both? | Yes |
| 3 | Should AIOutlookEngine._rule_based() accept both? | Yes |
| 4 | Should ai_outlook.py LLM prompt be updated? | Yes — to reflect new regime names |
| 5 | Should alert.py handle regime name transitions? | Yes — normalize before comparison |
| 6 | Should daily_page.py use REGIME_MAP? | Optional — currently displays raw regime name |

---

## 9. Proposed STEP 3 Design (For User Review)

### 9a. Interface Layer — Regime Name Normalization

Add a shared normalization function that maps both old and new regime names to a canonical form before passing to StrategyEngine, ScenarioEngine, and AIOutlookEngine:

```python
REGIME_ALIASES = {
    "TRENDING_BULLISH": "BULLISH",
    "BULLISH": "BULLISH",
    "TRENDING_BEARISH": "BEARISH",
    "BEARISH": "BEARISH",
    "RANGE_BOUND": "SIDEWAYS",
    "SIDEWAYS": "SIDEWAYS",
    "HIGH_VOLATILITY": "HIGH_VOLATILITY",
}
```

This preserves backward compatibility with any stored data using old names while accepting new names from RegimeEngine.

### 9b. StrategyEngine.update

- Add regime name normalization at entry point
- Add BULLISH/BEARISH/SIDEWAYS cases mirroring the old TRENDING_BULLISH/TRENDING_BEARISH/RANGE_BOUND cases
- Keep HIGH_VOLATILITY case as-is
- Expected: existing tests pass; new tests cover new regime names

### 9c. ScenarioEngine.update

- Add regime name normalization at entry point
- Add BULLISH/BEARISH/SIDEWAYS cases mirroring old logic
- Keep HIGH_VOLATILITY case as-is

### 9d. AIOutlookEngine._rule_based_outlook() Update

- Add regime name normalization
- Add BULLISH/BEARISH cases mirroring TRENDING_BULLISH/TRENDING_BEARISH
- Update LLM prompt to use new regime names

### 9e. AIOutlookEngine LLM prompt update

- Line 35: Update regime options to: BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY/UNCONFIRMED

### 9f. alert.py Normalization

- Before comparing prev/curr regime strings, normalize both through REGIME_ALIASES
- Prevents false regime change alerts on old→new transitions

### 9g. Integration Tests

1. **Full pipeline test**: Mock market data → RegimeEngine.evaluate → store_regime_and_strategies → verify strategies/scenarios/ai_outlooks tables populated correctly
2. **build_outlook regression**: Verify build_outlook() produces identical output for equivalent regime inputs (BULLISH vs old TRENDING_BULLISH)
3. **StrategyEngine compatibility**: Verify BULLISH produces same strategies as old TRENDING_BULLISH, BEARISH = TRENDING_BEARISH, SIDEWAYS = RANGE_BOUND
4. **ScenarioEngine compatibility**: Same as above for probabilities
5. **AIOutlookEngine compatibility**: Same for bias/confidence/structure

### 9h. Regression Tests

1. **Regime name agnosticism**: Verify all engines produce equivalent output for both old and new regime names
2. **Determinism**: Same inputs → identical outputs across multiple runs
3. **No-LLM verification**: Confirm no LLM calls in rule-based paths
4. **API contract**: /api/regime, /api/market-outlook, /api/strategy, /api/scenarios all return valid responses

---

## 10. Summary

| Component | Regression-Safe? | Action Required |
|---|---|---|
| build_outlook() | **YES** | None |
| REGIME_MAP | **YES** | None |
| _bias(), _strategies(), verdict | **YES** | None |
| Historical fallback | **YES** | None |
| StrategyEngine.select() | **NO** | Add new regime names + normalization |
| ScenarioEngine.generate() | **NO** | Add new regime names + normalization |
| AIOutlookEngine._rule_based() | **NO** | Add new regime names + normalization |
| AIOutlookEngine LLM prompt | **INCONSISTENT** | Update to new regime names |
| alert.py | **RISK** | Add regime name normalization |
| API endpoints | **YES** | None |
| Backtest | **YES** | None |

**Conclusion**: build_outlook() is verified regression-safe with no changes required. STEP 3 requires updating StrategyEngine, ScenarioEngine, and AIOutlookEngine rule-based path to accept new regime names from RegimeEngine, plus integration/regression tests. The user explicitly confirmed build_outlook() should NOT be replaced.
