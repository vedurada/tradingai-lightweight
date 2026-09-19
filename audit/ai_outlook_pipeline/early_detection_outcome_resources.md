# Early Detection, Outcome Linkage & Resources Audit

Date: 2026-09-18

## Early Detection (Section 16)

### Current State

The early detection concept is NOT implemented in the current codebase. There is no mechanism to:
1. Detect emerging trends before they materialize
2. Predict regime changes ahead of time
3. Flag "early warning" conditions
4. Provide anticipatory signals

### What Exists That Could Support Early Detection

- `market_change.py` `is_material_change()` — detects material changes AFTER they happen
- `outlook_change_detector.evaluate()` — evaluates current state vs previous
- `outlook_scheduler.needs_ai_outlook()` — checks if AI outlook is needed based on age/changes
- `outlook_change_detector.should_regenerate_ai()` — determines if AI should regenerate

### What's Missing

- No predictive model for regime changes
- No "trending toward" signals
- No early warning system for breakout/breakdown
- No confidence momentum tracking (confidence trend over time)
- No multi-timeframe confirmation

### Recommended Implementation

Early detection could be built on top of existing change detection:
1. Track confidence trend over last N candles
2. Monitor regime confidence approaching thresholds
3. Watch for VIX/RSI divergences
4. Track multi-timeframe alignment

## Outcome Linkage (Section 17)

### ai_outcome_predictions Table (EXISTS — EMPTY)

**Schema**: (id, outlook_id, symbol, entry_price, reference_price, horizon_minutes, future_return_pct, correct, mfe_pct, mae_pct, bias, recorded_at, evaluated_at, status)

**Current**: 0 rows — no predictions have been tracked.

### Purpose

Track whether AI outlook predictions were correct:
- `correct`: Whether the prediction was right
- `mfe_pct`: Maximum favorable excursion
- `mae_pct`: Maximum adverse excursion
- `status`: PENDING, EVALUATED, EXPIRED

### Evaluation Path (NOT IMPLEMENTED)

There is no code that:
1. Takes a generated AI outlook
2. Waits for the predicted horizon (30 minutes)
3. Checks if price moved as predicted
4. Records the result in ai_outcome_predictions

### Research Outcome Tracking (POPULATED)

**Table**: research_outcome_tracking — 61,672 rows

This table tracks paper trade outcomes, NOT AI outlook outcomes. It's a different concept:
- Research: Did paper trades make money?
- AI Outlook: Was the AI's prediction correct?

### Recommendation

1. Create evaluation job that runs after each AI outlook horizon expires
2. Link ai_outlooks_5m.outlook_id → ai_outcome_predictions.outlook_id
3. Evaluate bias correctness (was the directional bias correct?)
4. Evaluate confidence calibration (were high-confidence outlooks more accurate?)
5. Track MFE/MAE for each outlook

## Resource Usage (Section 18)

### CPU/Memory

**AI Outlook Generation**:
- AIOutlookEngine uses LLM API calls (Groq/Gemini/DeepSeek)
- Each LLM call: ~1-5 seconds latency, ~100-500 tokens
- Twice daily per symbol (4 symbols × 2 = 8 LLM calls per day)
- Estimated: ~40 tokens × 8 = 320 tokens/day per symbol
- Total: 320 × 41 symbols = ~13,120 tokens/day for legacy path

**5m Path** (if running):
- Would run every 5 minutes during market (78 candles/day × 4 symbols = 312 potential calls)
- But rate-limited: MAX_AI_OUTLOOKS_PER_SESSION = 200, MIN_AI_INTERVAL = 120s
- Realistic: ~78 AI calls per primary symbol × 2 = 156 LLM calls per day
- That's 156 × 40 tokens = ~6,240 tokens/day for primary only

### Resource Constraints on VM

**VM Specs**: Ubuntu 22.04, 2 CPU, 956MB RAM (564MB available), 45GB disk
**Current load**: Gunicorn (3 workers, ~56MB each = ~168MB) + data processes

**AI generation resource concern**: 5m pipeline would generate 156+ LLM calls per day during market hours. Each call takes ~1-5 seconds. Total: 156 × 3s = ~8 minutes of LLM time per day. This is manageable IF sequential.

### API Key / Rate Limit Management

- GROQ API key stored at /etc/tradingai/groq.env (mode 600)
- LLM provider selection: FREE_PROVIDERS = ["gemini", "groq", "deepseek", "openrouter", "ollama"]
- Round-robin through providers
- No rate limiting observed on AI generation side (would need to be added for 5m pipeline)

### Database Resource Impact

- ai_outlooks_5m would grow by ~312 rows/day × 4 symbols = ~1,248 rows/day
- At 30 days: ~37,000 rows — manageable
- Indexes: idx_ai5m_instrument_ts, idx_ai5m_generated — efficient queries

### Swap/Memory Concern

**VM has only 564MB RAM available**. If data_fetcher_db.py + monitor.py + gunicorn + other processes are running simultaneously, adding AI generation could cause memory pressure. The 5m generator creates AIOutlookEngine instances (with in-memory cache) which adds overhead.
