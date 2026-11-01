# Phase 5.21 — Production Path Findings

## Running Process

- Gunicorn PIDs: 802784, 824977, 829484 (started before Phase 5.20)
- These processes loaded OLD code (HLC unconditionally, no flag)
- Source file on disk has NEW code (with flag, defaulting to HLC)
- **Running process has NOT loaded Phase 5.20 change**

## Environment

- HLC_ONLY_MODE: not in environment variables
- HLC_ONLY_MODE: not in config/settings.json
- Gunicorn environ: HLC_ONLY_MODE not present

## Production Behavior

- Running process: HLC (old code, no flag)
- Source on disk: HLC by default (new code, flag defaults to True)
- **Production behavior unchanged (HLC in both cases)**

## Service/Job Bypass

- No service or scheduled job bypasses the flag
- paper_scalp_live.py: uses HLC directly (does not use LiveEngine.evaluate)
- tg_alerts.py: does not use the flag
- Flag is only in LiveEngine.evaluate()

## Conclusion

Production behavior is unchanged (HLC). The running process uses old code. The source on disk has new code with a design mismatch (default HLC instead of CPR). No safety violation occurred, but the implementation does not match the approved fail-safe design.
