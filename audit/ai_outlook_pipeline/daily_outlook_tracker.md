# Daily AI Outlook Tracker

Date: 2026-09-18

## Daily Outlook Tracker: outlook.py

| File | backend/outlook.py |
|------|-------------------|
| Purpose | Generate daily AI market outlook for 4 core indices |
| Schedule | 09:30 IST (morning), 19:00 IST (close) — weekdays only |
| Trigger | crontab: `30 9 * * 1-5` and `0 19 * * 1-5` |
| Output | market_outlooks table + market/nifty-outlook-<date>.html pages |
| LLM Usage | 4 calls per run (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) |
| Run count today | 1 of 2 (morning done at 09:30; close pending at 19:00) |

### How outlook.py Works

1. `main()` iterates over INDEX_SYMBOLS (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
2. For each symbol:
   a. Fetches data (indicators, regime, VIX, PCR/OI, price gaps, P&L)
   b. Builds data dict
   c. Calls `refresh_ai_outlook(conn, symbol)` which:
      - Checks INDEX_SYMBOLS (skips non-core indices)
      - Calls `AIOutlookEngine.generate(symbol, data)` with use_llm=True
      - Inserts into `ai_outlooks` table
      - Prints result
3. Also writes daily static pages: `market/nifty-outlook-<date>.html`

### Output Tables
| Table | Rows Added Per Run | Notes |
|-------|--------------------:|-------|
| ai_outlooks | 4 | One per index |
| market_outlooks | 1-4 | Depends on merge_llm_into_payload |

### Daily Pattern
```
09:30 IST (morning):
  NIFTY → outlook.py --symbol NIFTY → ai_outlooks + market_outlooks + market/nifty-outlook-YYYY-MM-DD.html
  BANKNIFTY → ...
  FINNIFTY → ...
  SENSEX → ...
  + inject_trust_headers.py + prerender_snapshot.py

19:00 IST (close):
  NIFTY → ...
  BANKNIFTY → ...
  FINNIFTY → ...
  SENSEX → ...
  + sitemap_gen.py + inject_trust_headers.py + prerender_snapshot.py
```

### Verification
- market_outlooks has 206 rows: 67 each for NIFTY, BANKNIFTY, SENSEX (Jun-Sep), 5 for FINNIFTY (Sep 14-18)
- ai_outlooks has 39,148 rows: ~1,295 per index (daily updates overwrite)
- Last NIFTY ai_outlook: 2026-09-18T16:40:20Z (from data_fetcher_db.py rule-based, overwritten frequently)
- OUTLOOK.PY runs at 09:30/19:00 → the AI outlook table is updated by data_fetcher_db.py every minute in between

### The Loop Problem

1. outlook.py runs at 09:30 → AIOutlookEngine(use_llm=True) → ai_outlooks (LLM quality)
2. data_fetcher_db.py runs every minute → AIOutlookEngine(use_llm=False) → ai_outlooks (rule-based, OVERWRITES)
3. This means the LLM quality outlook from 09:30 is overwritten within ~1 minute by the rule-based version

**Critical finding**: The twice-daily LLM outlook is overwritten almost immediately by the per-minute rule-based outlook. The ai_outlooks table effectively contains rule-based outlooks, not LLM-generated ones (after the first minute of each day).

### Cross-Validation

Can we verify the daily outlook is correct?
- market_outlooks table → used by /api/market-outlook endpoint
- Static pages → market/nifty-outlook-<date>.html
- ai_outlooks table → used by /api/ai-outlook endpoint (but overwritten)
- ai_outlooks_5m → empty (broken pipeline)

### Recommendations

1. Separate ai_outlooks (LLM) from ai_outlooks_template (rule-based) — don't overwrite
2. Add a generated_method field to distinguish LLM vs template
3. Make the daily tracker actually daily (not overwritten per minute)
4. Track which outlook was the "primary" LLM outlook vs template
