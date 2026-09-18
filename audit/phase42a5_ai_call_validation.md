# Phase 42A.5 AI Call Validation

## AI Call Test Results

### Pre-Market AI Call
```
Symbol: NIFTY
Use LLM: True (if providers available)
Providers attempted: Groq → DeepSeek → Gemini → OpenRouter → Ollama
Result: Rule-based fallback (Ollama unavailable, external providers may timeout)
Fallback outlook: {bias: "UNAVAILABLE", confidence: 0, regime: "BEARISH", trade_state: "NO_TRADE"}
```

### AI Call Count (Expected)
| Scenario | Calls | Notes |
|---|---|---|
| Browser refresh | 0 | No AI call on refresh ✅ |
| Market open (first candle) | 1 | Initial outlook |
| No material change | 0 | Keep current outlook |
| Material change detected | 1 | New outlook generated |
| Session close | 1 | Final outlook |
| Max session | ~30 | Theoretical max (every 5m) |
| Actual expected | 3-10 | Material-change driven |

### AI Call Test: Rule-Based Fallback
When LLM unavailable, generate_json.py generates rule-based outlook:
```python
try:
    ai_outlook = ai_engine.generate(...)  # LLM call
except Exception:
    ai_outlook = {  # Fallback
        "bias": "UNAVAILABLE",
        "confidence": 0,
        "regime": regime.get("regime", "UNKNOWN"),
        "trade_state": "NO_TRADE",
        "summary": "AI outlook temporarily unavailable",
        ...
    }
```
Verified: ✅ Works - 43 instruments generated with rule-based fallback

### AI Call Test: Failure Isolation
- AI failure does NOT stop market data ✅
- AI failure does NOT stop research collection ✅
- AI failure does NOT stop paper trade monitoring ✅
- AI failure shows UNAVAILABLE, not LIVE ✅

### AI Call Logging
Each AI generation logged with:
- timestamp
- instrument
- trigger
- model/provider
- success/failure
- latency
- error (if any)
- outlook_id

Verified in: research_ai_call_log table

## No Fabricated AI Data
- AI outlooks are either: LLM-generated or rule-based fallback
- Never show stale data as AI output ✅
- Never generate AI from stale inputs ✅
- AI history is prospective only (not retroactive) ✅
