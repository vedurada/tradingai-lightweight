# Phase 5.20 — Rollback Instructions

## To Roll Back the Feature Flag

1. Restore the original file from snapshot:
   cp /opt/tradingai/research/phase520_feature_flag_20261029_223000/source_snapshots/engine.py.before /opt/tradingai/app/live/engine.py

2. Verify hash matches original:
   sha256sum /opt/tradingai/app/live/engine.py
   # Should be: b06dac4f01a0a1e111556f47df0ec2e5034c0d6e04406f2131279a0309167542

3. No services need restart (flag is read at evaluation time)
4. No database changes needed
5. No configuration changes needed

## To Disable HLC (Roll Back to CPR)

Set HLC_ONLY_MODE=false in environment or config/settings.json, then restart gunicorn.

## Note

The feature flag defaults to HLC (current behavior). Setting to false rolls back to CPR. No production behavior changed by this implementation.
