# Phase 40 — AI Integration Document

## 1. Evidence → AI Pipeline

```text
MARKET SNAPSHOT (Phase 39)
        ↓
MARKET EVIDENCE ENGINE (Phase 40)
        ↓
Structured evidence (6 groups + overall + conflict)
        ↓
AI OUTLOOK GENERATOR (ai_outlook_5m.py)
        ↓
Validated AI outlook (Phase 39 schema)
```

### Integration Point

In `ai_outlook_5m.py`:

```python
def generate(self, symbol, market_state, material_changes=None, evidence=None):
    prompt = self._build_prompt(symbol, market_state, changes, evidence)
    ai_response = self._call_llm(prompt)
```

The `_build_prompt` method now includes the structured evidence JSON before the market state:

```python
def _build_prompt(self, symbol, state, changes, evidence):
    state_json = json.dumps(state, indent=2, default=str)
    evidence_json = json.dumps(evidence, indent=2, default=str) if evidence else "{}"
    return AI_OUTLOOK_PROMPT + f"\n\nCurrent state:\n{state_json}\n\nEvidence:\n{evidence_json}\n\nRecent changes:\n{changes_json}"
```

## 2. AI Outlook Schema (Updated)

### Input to AI

The AI receives:
1. Current market snapshot (all indicators)
2. Deterministic market state (regime, trend, vwap, etc.)
3. Structured evidence (6 groups with signals, rules, data_used)
4. Overall evidence summary (signal, strength, conflict)
5. Material changes from previous outlook
6. Data availability per group

### Output from AI (Validated Schema)

```json
{
  "instrument": "NIFTY",
  "timestamp": "ISO timestamp",
  "bias": "BULLISH|BEARISH|RANGE|MIXED",
  "confidence": 0-100,
  "market_regime": "BULLISH|BEARISH|RANGE|MIXED",
  "summary": "1-2 sentence factual outlook",
  "evidence": ["factual factors from evidence"],
  "conflicting_evidence": ["conflicting factors if any"],
  "watch_levels": ["key levels to monitor"],
  "confirmation_conditions": ["what confirms this view"],
  "invalidation_conditions": ["what invalidates this view"],
  "risk_conditions": ["risk factors"],
  "trade_state": "TRADE|WAIT|NO_TRADE",
  "strategy_context": null,
  "expected_horizon_minutes": 30,
  "data_availability": {
    "trend": "LIVE|DELAYED|UNAVAILABLE",
    "options": "LIVE|DELAYED|UNAVAILABLE"
  }
}
```

## 3. Evidence Summary in Outlook Record

Every AI outlook now stores an `evidence_summary`:

```json
{
  "overall_signal": "BULLISH",
  "overall_strength": "MODERATE",
  "conflict_detected": false,
  "groups": {
    "trend": {"signal": "BULLISH", "strength": "STRONG", "availability": "LIVE"},
    "momentum": {"signal": "BULLISH", "strength": "MODERATE", "availability": "LIVE"},
    "structure": {"signal": "RANGE", "strength": "MODERATE", "availability": "LIVE"},
    "volatility": {"signal": "NORMAL", "strength": "MODERATE", "availability": "LIVE"},
    "options": {"signal": "NEUTRAL", "strength": "WEAK", "availability": "UNAVAILABLE"},
    "confirmation": {"signal": "BULLISH", "strength": "STRONG", "availability": "LIVE"}
  }
}
```

## 4. Confidence Semantics

`confidence: 72` means:
- **AI model interpretation confidence**
- NOT "72% probability of profit"
- The UI must display: "AI confidence: 72/100"
- Never: "72% probability of winning"

## 5. What Changed Since Phase 39

### ai_outlook_5m.py Changes
- `generate()` now accepts `evidence` parameter
- `_build_prompt()` now includes evidence JSON
- `_evidence_summary()` method added
- `data_state` now propagates from evidence
- `evidence_received` field in output
- `evidence_summary` field in output

### AI Prompt Changes
- Updated to reference "Structured market evidence"
- Added `conflicting_evidence` to required output
- Added `data_availability` to required output
- Added explicit instruction: "AI must NOT invent indicators"
- Added explicit instruction about confidence semantics

### ai_outlook_5m Table
New columns (in addition to Phase 39):
- `evidence_received` — whether evidence was provided to AI
- `evidence_summary` — compact evidence snapshot for reference

## 6. Previous Outlook Linking

The `outlook_change_detector.py` already tracks:
- Previous vs current bias
- Previous vs current regime
- Change trigger reason
- Material changes

Phase 40 adds evidence context to the "what changed" analysis:
- Which evidence groups changed signal
- Which rules newly triggered
- Whether conflict was introduced or resolved

## 7. AI Call Protection

Retained from Phase 39:
- Minimum 120 seconds between AI calls
- Maximum 200 per session
- Only on material change, max age, or first outlook
- Fallback on failure (previous valid outlook retained)

## 8. Reproducibility

Every outlook can be reproduced:
1. Retrieve `candle_timestamp` and `evidence_id` from `ai_outlooks_5m`
2. Fetch snapshot from `market_snapshots_5m` (candle_timestamp)
3. Fetch evidence from `market_evidence_5m` (evidence_id)
4. Run AI generation with same prompt version and model

This enables: "What did the system know at 10:25?" → Data → Evidence → AI Outlook.
