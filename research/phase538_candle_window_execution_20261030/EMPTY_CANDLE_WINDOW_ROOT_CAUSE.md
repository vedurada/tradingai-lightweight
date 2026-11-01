# Phase 5.38 — Empty Candle Window Root Cause

## Error
- IndexError on empty candle window.

## Cause
- Entry candle lookup returned no candle, then index access on empty list.

## Fix
- Robust candle lookup with explicit empty-window handling.
