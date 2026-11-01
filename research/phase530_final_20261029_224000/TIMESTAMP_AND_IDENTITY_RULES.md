# Phase 5.30 — Timestamp and Identity Rules

## Matching Rules (Documented)

1. EXACT_MATCH: instrument + entry_time + direction all match
2. PROBABLE_MATCH: same day + instrument + direction, but entry_time differs
3. DATABASE_ONLY: paper trade exists, no replay trade
4. REPLAY_ONLY: replay trade exists, no paper trade
5. CONFLICTING: apparent match but different material fields
6. UNCLASSIFIABLE: insufficient evidence

## Promotion Rules

- PROBABLE → EXACT only when ALL required identity fields agree (instrument, entry_time, direction, entry_price)
- Same day/instrument/direction alone is NOT sufficient for EXACT_MATCH
- No forced matches

## Timestamp Normalization

- All timestamps in ISO 8601 with +05:30 (Asia/Kolkata)
- No UTC conversion for matching
- Entry time = next candle's open timestamp
- Signal time = 3rd confirming candle's open timestamp
