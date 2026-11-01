# Phase 5.22 — Rollback Instructions

## To Roll Back Source Code

1. Restore original file:
   cp /opt/tradingai/research/phase522_correction_20261029_225000/source_snapshots/engine.py.before /opt/tradingai/app/live/engine.py

2. Verify hash:
   sha256sum /opt/tradingai/app/live/engine.py
   # Should be: 4e4424fc040cb56dbbd327ae06dde13a816bfe48f2ea9ff1624721ff36420417

## To Roll Back Service Configuration

1. Restore original service file:
   sudo cp /opt/tradingai/research/phase522_correction_20261029_225000/source_snapshots/tradingai-api.service.before /etc/systemd/system/tradingai-api.service

2. Verify hash:
   sha256sum /etc/systemd/system/tradingai-api.service
   # Should be: a36884983f7e3030d332ab1f4bc6185d36fb5eca9b9dd809231ba32c278f4a11

## Note

No service restart needed for rollback (running process uses old code). Changes take effect only on next approved restart.
