# Phase 41 AI Attribution Analysis
Generated: 2026-09-17

## Question: What in Phase 41 is AI vs Rules-Based?

## Answer: Phase 41 is 0% AI in decision-making. AI is INPUT ONLY.

### AI Involvement Matrix

| Component | AI Used? | Details |
|-----------|----------|---------|
| Evidence Engine | NO | EMA(9/20/50), RSI(14), VWAP proximity, ADX, CPR, VIX — all mathematical |
| Historical Evidence | NO | Regime/gap/price-location/RSI matching — deterministic |
| Walk-Forward | NO | Chronological window splitting — deterministic |
| Trade Qualification | NO | 6-layer boolean checks — deterministic |
| Strategy Selection | NO | 11 strategies, candidate pool/filter/select — deterministic |
| Paper Trade Execution | NO | Entry/exit/PnL simulation — deterministic |
| Performance Stats | NO | Win rate, PnL, PF, R-multiples — deterministic |
| AI Outlook (INPUT) | YES | Groq LLM generates bias/trade_state/confidence |
| AI Outlook (HISTORICAL) | YES | `/api/ai-outlook/historical` — Groq LLM |

### Phase 41 Backend Modules — AI Call Count

| Module | Functions | AI API Calls | Lines |
|--------|-----------|-------------|-------|
| trade_qualification_engine.py | 16 | 0 | 455 |
| strategy_selection.py | 6 | 0 | 248 |
| paper_trade_engine.py | 22 | 0 | 431 |
| replay_engine.py | 8 | 0 | ~350 |
| market_evidence_engine.py | 4 | 0 | ~200 |
| replay_runner.py (debug tool) | 0 | 0 | ~250 |

**Total AI API calls in Phase 41 trading pipeline: 0**

### Where AI IS Used (separate from Phase 41 engine)

1. **`/api/ai-outlook/5m`** — Generates 5-minute AI outlook using Groq LLM
   - Input: Market state, indicators, options data
   - Output: bias, trade_state, confidence, invalidation/confirmation conditions
   - Called BEFORE qualification as INPUT

2. **`/api/ai-outlook/historical`** — Generates historical AI outlook
   - Input: Date range, historical market data
   - Output: Per-day AI outlooks for historical backtesting
   - NOT used in replay_runner.py (replay uses deterministic signals)

3. **`/api/evidence/<symbol>/<date>`** — Historical evidence for a specific date
   - Returns BULLISH/BEARISH/MIXED/RANGE classification
   - **100% deterministic** — no AI, LLM, or model involved
   - Matching criteria: regime, gap direction, price location, RSI conditions

### AI Separation Guarantee

The Phase 41 engine enforces strict AI separation:
- AI outlook is INPUT to qualification, not computed by it
- `_check_ai_outlook()` validates AI fields exist but never generates them
- `ai_confidence_reviewed` check: `confidence={confidence} (not used for qualification)` — explicitly documented as non-influencing
- All 16 functions in qualification engine have 0 AI API calls
- Strategy selection: 0 AI API calls
- Paper trade: 0 AI API calls

### What AI Contributes vs What the Engine Does

| AI Contributes | Engine Does |
|----------------|-------------|
| Decides market bias (BULLISH/BEARISH) | Validates bias is valid |
| Sets trade_state (TRADE/WAIT/NO_TRADE) | Validates trade_state allows qualification |
| Provides confidence score | Logs but does NOT use confidence for qualification |
| Suggests invalidation/confirmation | Checks conditions are defined, not whether they're met |

### Replay Runner Specifics

The `replay_runner.py` does NOT call AI at all. It uses:
- Market Evidence Engine for signal generation (deterministic)
- Trade Qualification Engine for filtering (deterministic)
- Paper Trade Engine for simulation (deterministic)
- EMA crossover for trend proxy (mathematical, not AI)

This is by design: the replay tests the QUALIFICATION pipeline with real market data, not AI predictions.

### Implications for Phase 42

- Phase 42 can refine the rules-based pipeline without worrying about AI contamination
- Any performance improvement in Phase 42 is attributable to RULE CHANGES, not AI
- The 38.43% win rate and -130K PnL from the replay are PURE rules-based results
- AI outlook quality (bias/trade_state/confidence) was the limiting factor — AI was wrong often enough that 61% of signals were MIXED/RANGE

### Replay Results Attribution

From the 1,184 simulated trades:
- 38.43% win rate = RULE-BASED (no AI influence on entry/exit decisions)
- -130,391.72 net PnL = RULE-BASED (no AI influence on PnL calculation)
- 0.349 profit factor = RULE-BASED (no AI influence on risk management)
- 45.54 trades/day = RULE-BASED (no AI filtering/suppression)
