# Phase 5.20 — Pre-Change Inspection

## Candidate Source Files

| File | Pre-Change Hash | Status |
|------|----------------|--------|
| app/live/engine.py | b06dac4f01a0a1e111556f47df0ec2e5034c0d6e04406f2131279a0309167542 | Verified |
| app/research/scalp_engine.py | 127c09d6dfcf4ac930d116d311d56b21005fff84acf40eab8aca01ba7aaf7e23 | Verified |
| app/strategies/scalp.py | 7711ad0683ebca88080e1ebbb5efcc3e8e61ba8a994f47282eb380de12f50c82 | Verified |

## Production Decision Path

Current: `_hlc_book_signal()` is called unconditionally in `evaluate()` (line 784).
CPR: `_cpr_book_signal()` exists but is never called in `evaluate()`.

## Configuration Loading

- `app/core/config.py` loads `config/settings.json`
- Environment variables: `TRADINGAI_BASE`, `TRADINGAI_DB_PATH`
- No existing HLC_ONLY_MODE setting

## Callers That Might Bypass Flag

- `evaluate()` is the only caller of `_hlc_book_signal` in production
- No other code path calls signal selection directly

## Broker Execution

- No broker API calls in app/live/engine.py
- No broker execution in paper_scalp_live.py
- No broker execution in tg_alerts.py
