# AI Input Quality & LLM Logging Audit

Date: 2026-09-18

## AI Inputs Analysis

### For Legacy Path (outlook.py → ai_outlooks)

**Input data source**: AIOutlookEngine.generate(symbol, data, use_llm=True)

Input data is assembled in outlook.py refresh_ai_outlook():
```python
data = {
    "price": price,
    "previous_close": q.get("open", 0),
    "rsi": ind.get("rsi"),
    "macd": ...,
    "adx": ind.get("adx"),
    "atr": ind.get("atr"),
    "vwap": ind.get("vwap"),
    "pivot": ind.get("pivot"),
    "cpr": ind.get("cpr_classification", ""),
    "vix": (vix.get("close") or 0),
    "volume": q.get("volume", 0),
    "regime": (reg.get("regime") or "UNKNOWN"),
    "support_levels": ...,
    "resistance_levels": ...,
    "options_unavailable": True,
    "symbol": symbol,
    "data_quality": "GOOD",
}
```

**Input quality assessment**:
- Data is read from latest market_regime, indicators, vix_data, price_1m
- All these tables ARE populated (data_fetcher_db.py runs every minute)
- `options_unavailable: True` is hardcoded — options data is explicitly marked unavailable
- Data is timestamp-consistent (all from latest rows at time of generation)
- No validation that inputs are non-null/non-empty before LLM call

### For 5m Path (ai_outlook_5m.py → AIOutlookGenerator5m)

**Input**: `generate(symbol, market_state, material_changes, evidence)`
- market_state: Provided by create_snapshot() from market_snapshot.py
- material_changes: From outlook_change_detector.evaluate()
- evidence: From market_evidence_5m (EMPTY — never populated)

**Critical Bug**: `_call_llm()` ignores ALL inputs:
```python
result = self.engine.generate("NIFTY", {}, use_llm=True)  # Hardcoded, empty state
```
- Symbol hardcoded to "NIFTY" — all symbols generate NIFTY outlooks
- Market state is `{}` — no price, RSI, regime, VIX, or any actual data
- The built prompt (with symbol-specific state) is never used
- Evidence parameter is never passed

**Impact**: Even if scheduler ran, every symbol would generate identical NIFTY outlooks using no data.

## LLM Logging Analysis

### research_ai_call_log (EXISTS — EMPTY — 0 rows)

**Schema**: (id, call_timestamp, instrument, candle_timestamp, trigger, model, provider, prompt_version, success, latency_ms, token_usage, error, fallback_used, outlook_id, data_version, created_at)

**Purpose**: Log every AI/LLM call for outlook generation
**Expected data**: model, provider, prompt_version, latency, token usage, success/failure
**Actual**: 0 rows

### Why Is research_ai_call_log Empty?

1. **outlook.py**: Does NOT call record_ai_call() — it calls AIOutlookEngine directly
2. **data_fetcher_db.py**: Does NOT call record_ai_call() — uses _latest_ai_outlook() cache
3. **ai_outlook_5m.py**: Does NOT call record_ai_call() — uses AIOutlookEngine internally
4. **research_collector.record_ai_call()**: EXISTS but is NEVER called in production pipeline

### No Persistent LLM Prompt/Response Logging

- No table stores actual prompts sent to LLM
- No table stores LLM responses before normalization
- No way to audit LLM quality, drift, or errors
- research_ai_call_log would have been the place, but it's never populated

### AI Call Trace (If Working)

Expected flow:
```
OutlookScheduler._generate_ai_outlook()
  → AIOutlookGenerator5m._generate_ai_outlook()
    → AIOutlookGenerator5m._call_llm()
      → AIOutlookEngine._call_llm_chain()
        → LLM API call (Groq/Gemini/DeepSeek)
      → Returns dict
    → Returns validated dict
  → Should call ResearchCollector.record_ai_call() — NOT DONE
  → _store_outlook() → ai_outlooks_5m
```

### What Should Be Logged

Each AI call should record:
- call_timestamp: When the call was made
- instrument: Which symbol
- candle_timestamp: Which 5-minute candle
- trigger: Why was AI called (MATERIAL_CHANGE, SCHEDULED, etc.)
- model: Which model (groq/gemini/deepseek)
- provider: Which provider
- prompt_version: Which prompt template version
- success: 1/0
- latency_ms: Response time
- token_usage: Tokens consumed
- error: Error message if any
- fallback_used: Was fallback used?
- outlook_id: Generated outlook ID
- data_version: Database version at time of call

**None of this is currently logged.**
