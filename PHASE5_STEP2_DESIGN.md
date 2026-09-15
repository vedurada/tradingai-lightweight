# PHASE 5 STEP 2 — Market Regime Engine: Design Audit

## 1. Audit Findings

### 1.1 Existing `market_regime` table (db_schema.py:280)

| Column | Type | Currently Populated? | Source |
|--------|------|---------------------|--------|
| `regime` | TEXT | YES | data_fetcher_db.py:518 |
| `confidence` | REAL | YES | data_fetcher_db.py:518 |
| `trend` | TEXT | YES | data_fetcher_db.py:518 |
| `momentum` | TEXT | YES | data_fetcher_db.py:518 |
| `volatility` | TEXT | YES | data_fetcher_db.py:518 |
| `breadth` | TEXT | **NO** | column exists, never written |
| `vix_regime` | TEXT | **NO** | column exists, never written |
| `evidence` | TEXT | YES (empty string) | data_fetcher_db.py:518 |

**Finding**: Table already supports all 5 component columns (`trend`, `momentum`, `volatility`, `breadth`, `vix_regime`). No schema changes required for component storage.

### 1.2 Existing `regime.py` RegimeEngine

- `evaluate()` takes: price, vwap, prev_close, rsi, macd, adx, vix_price, bollinger, pivot, support_resistance, pcr, volume, avg_volume
- Returns: regime (TRENDING_BULLISH/TRENDING_BEARISH/RANGE_BOUND/HIGH_VOLATILITY), confidence, reasons, scores, timestamp
- **Problem**: Uses old regime names (TRENDING_BULLISH etc.), not the user's proposed BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY
- **Problem**: Has cache infrastructure (`_cache`, `_cache_time`, `_cache_ttl`, `_cached()`) — same dead-code pattern cleaned up in STEP 1A
- **Problem**: Hour-based weighting (`_hour_factor()`) introduces time-dependent non-determinism for same-input scenarios
- **Problem**: No standalone tests exist

### 1.3 Data Sources Available

| Component | Source | Table/Location | Key Fields |
|-----------|--------|---------------|------------|
| **Trend** | price_1d + indicators | price_1d, indicators | close, sma20, sma50, prev_day_close |
| **Momentum** | indicators | indicators | rsi, macd_histogram, adx |
| **VIX** | vix_data | vix_data | close, change_pct |
| **Breadth** | market_breadth | market_breadth | advances, declines, advance_decline_ratio, pct_above_ema20 |
| **Options** | option_chain + oi_top_strikes | option_chain, oi_top_strikes | pcr (calculated), call_oi, put_oi |

### 1.4 `build_outlook()` relationship (outlook.py:336)

- `build_outlook(conn, symbol, date)` reads `market_regime` at line 339
- Uses `reg.get("regime")` and `reg.get("confidence")` at lines 479-482
- **Must remain UNTOUCHED** per audit directive
- New RegimeEngine output must be backward-compatible with existing consumers

### 1.5 Population Gap

`data_fetcher_db.py:518` inserts into `market_regime` with columns: regime, confidence, evidence, trend, momentum, volatility. It does **not** populate `breadth` or `vix_regime` even though they exist in the table. Post-STEP 2, the new RegimeEngine should populate all component columns.

---

## 2. RegimeEngine Contract

### 2.1 Class Definition

```python
class RegimeEngine:
    def evaluate(self, market: dict, options: dict) -> dict:
        ...
```

### 2.2 Input Schema

```python
market = {
    "symbol": str,                    # e.g. "NIFTY"
    "price": Optional[float],         # current close from price_1d/live_quotes
    "sma20": Optional[float],         # from indicators table or computed from price_1d
    "sma50": Optional[float],         # from indicators table or computed from price_1d
    "prev_close": Optional[float],    # previous session close
    "rsi": Optional[float],           # from indicators (0-100)
    "macd_histogram": Optional[float], # from indicators
    "adx": Optional[float],           # from indicators (0-100)
    "vix_close": Optional[float],     # from vix_data
    "vix_change_pct": Optional[float],# from vix_data
    "advances": Optional[int],        # from market_breadth
    "declines": Optional[int],        # from market_breadth
    "advance_decline_ratio": Optional[float], # from market_breadth
    "pct_above_ema20": Optional[float],       # from market_breadth
}

options = {
    "pcr": Optional[float],           # put/call ratio, 3 decimals
    "call_oi": Optional[float],       # total CE OI
    "put_oi": Optional[float],        # total PE OI
}
```

### 2.3 Output Schema

```python
{
    "regime": str,                    # BULLISH | BEARISH | SIDEWAYS | HIGH_VOLATILITY
    "confidence": int,                # 0-100, integer
    "components": {
        "trend": str,                 # BULLISH | BEARISH | NEUTRAL | UNAVAILABLE
        "momentum": str,              # BULLISH | BEARISH | NEUTRAL | UNAVAILABLE
        "vix": str,                   # EXTREME | HIGH | ELEVATED | NORMAL | LOW | VERY_LOW | UNAVAILABLE
        "breadth": str,               # POSITIVE | NEGATIVE | NEUTRAL | UNAVAILABLE
        "options": str,               # BULLISH | BEARISH | NEUTRAL | UNAVAILABLE
    },
    "reasons": list[str],             # human-readable explanations
    "data_quality": str,              # LIVE | PARTIAL | UNAVAILABLE
    "timestamp": str,                 # ISO timestamp
}
```

### 2.4 Determinism Guarantee

- No cache, no time-based weighting, no randomness
- Same `market` + `options` dicts → identical output always
- `timestamp` is the only non-deterministic field (set after evaluation)

---

## 3. Component Classification Rules

### 3.1 Trend Component

Based on price vs SMA20/SMA50 (price/trend evidence):

| Condition | Classification |
|-----------|---------------|
| price > sma20 AND (sma50 is None OR sma20 > sma50) | **BULLISH** |
| price < sma20 AND (sma50 is None OR sma20 < sma50) | **BEARISH** |
| price > sma20 AND sma50 exists AND sma20 <= sma50 | NEUTRAL |
| price < sma20 AND sma50 exists AND sma20 >= sma50 | NEUTRAL |
| sma20 is None | **UNAVAILABLE** |

Reason strings:
- `"Price {price:.2f} above SMA20 {sma20:.2f}"`
- `"Price {price:.2f} below SMA20 {sma20:.2f}"`
- `"SMA20/SMA50 alignment confirms trend"` (when both available and aligned)
- `"SMA20 unavailable — trend classification unavailable"` (fallback)

### 3.2 Momentum Component

Based on RSI and MACD histogram (momentum direction + acceleration):

| Condition | Classification |
|-----------|---------------|
| rsi >= 50 AND (macd_histogram is None OR macd_histogram >= 0) | **BULLISH** |
| rsi < 50 AND macd_histogram is not None AND macd_histogram < 0 | **BEARISH** |
| rsi >= 50 AND macd_histogram is not None AND macd_histogram < 0 | NEUTRAL (conflict) |
| rsi < 50 AND (macd_histogram is None OR macd_histogram >= 0) | NEUTRAL (conflict) |
| rsi is None AND macd_histogram is None | **UNAVAILABLE** |
| rsi is None AND macd_histogram is not None | Use macd_histogram alone |

Reason strings:
- `"RSI {rsi:.1f} supports bullish momentum"`
- `"RSI {rsi:.1f} supports bearish momentum"`
- `"MACD histogram {macd_histogram:+.2f} confirms direction"`
- `"RSI and MACD conflict — momentum neutral"`

### 3.3 VIX Component (Volatility Regime)

Based on absolute VIX level (same thresholds as existing `_vix_regime()` in outlook.py:124):

| VIX Close | Classification |
|-----------|---------------|
| >= 25 | **EXTREME** |
| >= 20 | **HIGH** |
| >= 16 | **ELEVATED** |
| >= 13 | **NORMAL** |
| >= 11 | **LOW** |
| < 11 | **VERY_LOW** |
| None | **UNAVAILABLE** |

Reason strings:
- `"VIX {vix_close:.2f} — extreme volatility"`
- `"VIX {vix_close:.2f} — high volatility"`
- `"VIX {vix_close:.2f} — normal range"`
- etc.

### 3.4 Breadth Component

Based on advance/decline ratio:

| Condition | Classification |
|-----------|---------------|
| advance_decline_ratio is not None AND ratio > 1.0 | **POSITIVE** |
| advance_decline_ratio is not None AND ratio < 0.8 | **NEGATIVE** |
| advance_decline_ratio is not None AND 0.8 <= ratio <= 1.0 | NEUTRAL |
| advances is not None AND declines is not None | Use (advances - declines) sign |
| None of the above | **UNAVAILABLE** |

Reason strings:
- `"Breadth positive: advances {advances} vs declines {declines}"`
- `"Breadth negative: advances {advances} vs declines {declines}"`
- `"Breadth balanced"`
- `"Breadth data unavailable"`

### 3.5 Options Component (Confirmation Only)

Based on PCR (put/call ratio). Per user directive: "Options should initially be confirmation, not allowed to completely override price/trend evidence."

| PCR Value | Classification |
|-----------|---------------|
| pcr is None | **UNAVAILABLE** |
| pcr < 0.7 | **BULLISH** (put protection thin, bullish positioning) |
| 0.7 <= pcr <= 1.5 | NEUTRAL |
| pcr > 1.5 | **BEARISH** (put heavy, bearish positioning) |

Reason strings:
- `"Options confirm bullish: PCR {pcr:.3f}"`
- `"Options confirm bearish: PCR {pcr:.3f}"`
- `"Options neutral: PCR {pcr:.3f}"`
- `"Options data unavailable"`

---

## 4. Regime Classification Rules

### 4.1 Primary Decision: HIGH_VOLATILITY vs Directional

HIGH_VOLATILITY is a regime, not a VIX flag. It is triggered when volatility conditions make directional classification unreliable.

| Condition | Regime |
|-----------|--------|
| VIX = EXTREME (>= 25) | **HIGH_VOLATILITY** |
| VIX = HIGH (>= 20) AND trend ≠ momentum (conflict) | **HIGH_VOLATILITY** |
| VIX = HIGH (>= 20) AND all directional components agree | HIGH_VOLATILITY (with directional caveat in reasons) |
| Otherwise | directional regime (BULLISH/BEARISH/SIDEWAYS) |

**Rationale**: When VIX is HIGH or EXTREME, normal directional calls should be treated cautiously. Even if trend and momentum agree, the regime is HIGH_VOLATILITY because volatility is dominant enough to warrant caution.

### 4.2 Directional Regime (when VIX < 20 or as fallback)

Count directional components (BULLISH or BEARISH only; NEUTRAL and UNAVAILABLE don't count):

| Calculation | Rule |
|-------------|------|
| bullish_count | number of components == BULLISH in {trend, momentum, options} |
| bearish_count | number of components == BEARISH in {trend, momentum, options} |
| If bullish_count > bearish_count + 1 | **BULLISH** |
| If bearish_count > bullish_count + 1 | **BEARISH** |
| Otherwise | **SIDEWAYS** |

Options counts as 0.5 weight (confirmation only). So:
- effective_bullish = bullish_count + 0.5 * options_bullish_flag (1 if options == BULLISH else 0)
- effective_bearish = bearish_count + 0.5 * options_bearish_flag (1 if options == BEARISH else 0)
- Threshold difference for BULLISH/BEARISH: > 0.5

### 4.3 Confidence Calculation

```
confidence = 50 (base)

+15 for each directional component matching the regime
    (trend, momentum, options count as 15; breadth counts as 10; VIX component does NOT add)
-10 if VIX is ELEVATED, HIGH, or EXTREME (volatility reduces directional confidence)
-10 for each UNAVAILABLE component
+5 if ADX >= 25 (trending market, higher confidence in directional call)

Clamp to [15, 100]
```

Special case: HIGH_VOLATILITY regime always gets confidence = min(computed, 60) even if components align. This reflects that high volatility reduces confidence in directional accuracy.

### 4.4 Data Quality

| Condition | Data Quality |
|-----------|-------------|
| All 5 components available | LIVE |
| 3-4 components available | PARTIAL |
| 1-2 components available | PARTIAL |
| 0 components available | UNAVAILABLE |

---

## 5. Schema Impact

### 5.1 No Schema Changes Required

The existing `market_regime` table already has all necessary columns:

```sql
CREATE TABLE IF NOT EXISTS market_regime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    regime TEXT,           -- will store BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY
    confidence REAL,        -- will store 0-100 integer
    trend TEXT,             -- component classification
    momentum TEXT,          -- component classification
    volatility TEXT,        -- component classification (VIX level)
    breadth TEXT,           -- component classification (was never populated, now will be)
    vix_regime TEXT,        -- component classification (was never populated, now will be)
    evidence TEXT,
    UNIQUE(symbol, timestamp)
);
```

### 5.2 Backward Compatibility

- Old regime names (TRENDING_BULLISH etc.) are not used by the new engine
- `build_outlook()` reads `reg.get("regime")` and `reg.get("confidence")` — both still present in new output
- Existing consumers of `market_regime` table that query by `regime` column need to handle new values
- The `trend` and `momentum` columns now store component classifications (BULLISH/BEARISH/NEUTRAL/UNAVAILABLE) instead of old formatted strings — consumers that parse these should be updated

### 5.3 Required: Populate All Columns

When storing regime results to `market_regime`, populate ALL component columns:

```sql
INSERT OR REPLACE INTO market_regime
    (symbol, timestamp, regime, confidence, evidence, trend, momentum, volatility, breadth, vix_regime)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

---

## 6. Test Matrix

### 6.1 Required Test Cases

| # | Scenario | Market Input | Options Input | Expected Regime | Confidence |
|---|----------|-------------|---------------|-----------------|------------|
| 1 | Clear bullish | price > sma20 > sma50, RSI 60, MACD+ | pcr 0.5, advances > declines | BULLISH | High (75-90) |
| 2 | Clear bearish | price < sma20 < sma50, RSI 35, MACD- | pcr 2.0, advances < declines | BEARISH | High (75-90) |
| 3 | Sideways | price near sma20, RSI 50, MACD ~0 | pcr 1.0, breadth balanced | SIDEWAYS | Medium (35-55) |
| 4 | High volatility | VIX 28 | Any | HIGH_VOLATILITY | ≤ 60 |
| 5 | High volatility + directional | VIX 22, trend and momentum agree | Any | HIGH_VOLATILITY | ≤ 60 |
| 6 | Missing VIX | VIX None | Any | directional regime | Reduced by 10 |
| 7 | Missing breadth | breadth None | Any | directional regime | Reduced by 10 |
| 8 | Missing options | PCR None | — | directional regime | Reduced by 10 |
| 9 | Missing all optional | All None | — | UNAVAILABLE | 15 |
| 10 | Conflicting indicators | trend BULLISH, momentum BEARISH | NEUTRAL | SIDEWAYS | Medium |
| 11 | VIX boundary (exactly 20) | VIX 20.0 | — | HIGH_VOLATILITY | ≤ 60 |
| 12 | VIX boundary (19.99) | VIX 19.99 | — | directional | — |
| 13 | RSI boundary (exactly 50) | RSI 50.0 | — | momentum NEUTRAL | — |
| 14 | PCR boundary (exactly 0.7) | PCR 0.7 | — | options NEUTRAL | — |
| 15 | PCR boundary (exactly 1.5) | PCR 1.5 | — | options NEUTRAL | — |
| 16 | Deterministic repeat | Same input twice | Same options twice | Identical | Identical |
| 17 | ADX >= 25 boost | trend BULLISH, ADX 30 | pcr 0.6 | BULLISH | Higher (+5) |
| 18 | Partial data: trend only | sma20 available, rest None | None | directional from trend | Reduced |

### 6.2 Determinism Test

```python
def test_deterministic_same_inputs():
    engine = RegimeEngine()
    result1 = engine.evaluate(market, options)
    result2 = engine.evaluate(market, options)
    assert result1["regime"] == result2["regime"]
    assert result1["confidence"] == result2["confidence"]
    assert result1["reasons"] == result2["reasons"]
    assert result1["components"] == result2["components"]
```

### 6.3 No-LLM Test

```python
def test_no_llm_or_randomness():
    engine = RegimeEngine()
    # Verify no LLM calls, no random seeds, no time-based logic
    import inspect
    source = inspect.getsource(engine.evaluate)
    assert "random" not in source.lower() or "seed" not in source.lower()
    assert "llm" not in source.lower()
    assert "openai" not in source.lower()
```

---

## 7. Implementation Notes

### 7.1 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `backend/regime.py` | **Rewrite** | New RegimeEngine with clean contract, no cache, no hour_factor |
| `tests/test_regime.py` | **Create** | All test cases from matrix above |
| `backend/db_schema.py` | No change | Table already supports all columns |
| `backend/data_fetcher_db.py` | **Modify** | Use new RegimeEngine, populate all 10 market_regime columns |
| `backend/outlook.py` | No change | build_outlook() untouched |

### 7.2 RegimeEngine Cleanup (from STEP 1A pattern)

The existing `regime.py` has dead code that should be removed:
- `_cache`, `_cache_time`, `_cache_ttl`, `_cached()` — same pattern cleaned in STEP 1A
- `_hour_factor()` — time-dependent, breaks determinism for same inputs
- Old regime names in `regime_map` — replace with new names

### 7.3 Boundary Definition

"Exactly at boundary" means:
- VIX = 20.0 → HIGH (since >= 20)
- RSI = 50.0 → BULLISH (since >= 50)
- PCR = 0.7 → NEUTRAL (since 0.7 <= pcr <= 1.5)
- PCR = 1.5 → NEUTRAL (since 0.7 <= pcr <= 1.5)

### 7.4 Options Weighting in Directional Decision

```python
directional_components = [trend, momentum]  # primary
options_weight = 0.5  # confirmation only

effective_bullish = (1 if trend == BULLISH else 0) + (1 if momentum == BULLISH else 0) + (0.5 if options == BULLISH else 0)
effective_bearish = (1 if trend == BEARISH else 0) + (1 if momentum == BEARISH else 0) + (0.5 if options == BEARISH else 0)

# BULLISH if effective_bullish > effective_bearish + 0.5
# BEARISH if effective_bearish > effective_bullish + 0.5
# SIDEWAYS otherwise
```

---

## 8. Regime Output Example

```python
# BULLISH example
{
    "regime": "BULLISH",
    "confidence": 78,
    "components": {
        "trend": "BULLISH",
        "momentum": "BULLISH",
        "vix": "NORMAL",
        "breadth": "POSITIVE",
        "options": "BULLISH"
    },
    "reasons": [
        "Price 24500.00 above SMA20 24350.00",
        "SMA20 24350.00 above SMA50 24100.00 — trend alignment confirmed",
        "RSI 58.5 supports bullish momentum",
        "MACD histogram +12.3 confirms direction",
        "VIX 14.2 — normal range",
        "Breadth positive: advances 2150 vs declines 1200",
        "Options confirm bullish: PCR 0.450"
    ],
    "data_quality": "LIVE",
    "timestamp": "2026-09-13T05:30:00+00:00"
}

# HIGH_VOLATILITY example
{
    "regime": "HIGH_VOLATILITY",
    "confidence": 45,
    "components": {
        "trend": "BEARISH",
        "momentum": "BEARISH",
        "vix": "EXTREME",
        "breadth": "NEGATIVE",
        "options": "BEARISH"
    },
    "reasons": [
        "Price 23800.00 below SMA20 24100.00",
        "RSI 38.2 supports bearish momentum",
        "VIX 28.5 — extreme volatility",
        "Breadth negative: advances 900 vs declines 2400",
        "Options confirm bearish: PCR 2.150"
    ],
    "data_quality": "LIVE",
    "timestamp": "2026-09-13T05:30:00+00:00"
}
```

---

## 9. Next Action

Await user approval of this design before implementing `backend/regime.py` (rewrite) and `tests/test_regime.py` (create).

Key open decisions:
1. Should HIGH_VOLATILITY always cap confidence at 60, or should it be computed normally? (Proposed: cap at 60 for HIGH_VOLATILITY)
2. Should VIX >= 20 with strong unidirectional components (trend+momentum+options all same direction) still trigger HIGH_VOLATILITY? (Proposed: Yes — volatility is dominant)
3. Should ADX boost apply only when regime is directional (not HIGH_VOLATILITY)? (Proposed: Yes)
