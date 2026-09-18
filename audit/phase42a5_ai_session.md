# Phase 42A.5 AI Session Architecture

## AI Model Configuration
- Provider: Groq (primary), with Ollama fallback
- Model: Configured via /etc/tradingai/groq.env
- Base URL: External (not localhost)

## AI Call Architecture

```
Every completed 5m candle (via generate_json.py or outlook.py):
   ↓
Market data + indicators + regime
   ↓
AIOutlookEngine.generate(symbol, data, use_llm=True)
   ↓
┌─────────────────────────────┐
│ _call_llm_chain(prompt, data)│
│  Try Groq → DeepSeek →     │
│  Gemini → OpenRouter →      │
│  Ollama (all in sequence)   │
│  If ALL fail:               │
│  → _rule_based_outlook()    │
└─────────────────────────────┘
   ↓
_rule_based_outlook(data)
   ↓
Deterministic outlook from market data
(uses ATR, VIX, regime, price)
   ↓
Save to DB as immutable record
```

## AI Call Protection
- Minimum interval: Governed by 5m candle cycle
- Maximum calls/session: Governed by material-change triggers (not every 5m)
- Timeout: Provider-level (Groq has own timeout)
- Retry: Sequential provider fallback (3-5 providers)
- Backoff: Implicit (next provider in sequence)
- Duplicate prevention: Material-change detector prevents unnecessary calls

## AI Output Contract
- bias: BULLISH|BEARISH|RANGE|MIXED|UNAVAILABLE
- confidence: 0-100 integer
- regime: String (from RegimeEngine)
- summary: String
- evidence: Array
- trade_state: TRADE|WAIT|NO_TRADE
- expected_horizon_minutes: Integer
- outlook_change_reason: String (why this outlook was generated)
- engine_version: String

## AI Immutability
- Each AI outlook stored as NEW immutable record
- Never overwrite previous outlooks
- outlook_id: Unique identifier per generation
- Previous outlook IDs tracked for lineage

## AI Failure Behavior
When ALL providers fail:
1. _rule_based_outlook() generates deterministic outlook
2. Market data continues to display normally ✅
3. Evidence continues to display ✅
4. AI section shows: "AI outlook temporarily unavailable"
5. Trade qualification uses rule-based bias (NEUTRAL fallback)
6. No broker execution regardless of AI output ✅

## Full-Session Capability
- Pre-market: AI outlook shows "Awaiting market open"
- Market open: Initial outlook generated on first completed 5m candle
- During session: New outlook only on material change triggers
- Market close: Final outlook generated at 15:25-15:30

## Cost Safety
- Maximum calls/session: ~30 (one every 5m for 150min session)
- Actual expected: 3-10 (material change triggers)
- No unnecessary AI calls on browser refresh ✅
- No AI call on page load ✅
