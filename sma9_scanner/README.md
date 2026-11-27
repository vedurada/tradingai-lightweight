# SMA9 Scanner — Locked, Consolidated Source

This folder is the single source of truth for the SMA9 ATM CE/PE BUY-only
paper scanner. The code is **root-owned, read-only, and immutable**.

- Live entrypoint: `app/live_sma9_scanner.py`
- Strategy engine: `app/sma9_engine.py`
- Corrected historical audit: `app/sma9_historical_audit.py`
- Legacy signal-only package: `sma9_only/`
- Tests: `tests/`
- Lock / integrity / status tools: `ops/`
- Security and change-control guide: `docs/SECURITY_AND_OPERATIONS.md`

## Daily checks

```bash
sudo systemctl status tradingai-sma9-scanner.service
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
sudo /opt/tradingai/sma9_scanner/ops/status.sh
```

## Lock status

```bash
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
stat -c '%U:%G %a %n' /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
```

Expected: the `i` (immutable) flag is set, owner is `root`, mode is `444`.

## Approved changes only

```bash
sudo /opt/tradingai/sma9_scanner/ops/unlock_code.sh
# edit + test
sudo /opt/tradingai/sma9_scanner/ops/lock_code.sh
sudo systemctl restart tradingai-sma9-scanner.service
```

The scanner runs as the unprivileged `sma9` user with no sudo rights, inside a
systemd sandbox. See `docs/SECURITY_AND_OPERATIONS.md` for the full policy,
verification commands, and rollback steps.

## Exit policies and polling (local change)

The live scanner polls on exact wall-clock 5-second boundaries (`:00`, `:05`,
`:10`, ...); there is no poll offset or alignment field. Each open position
carries a persisted `exit_policy`:

- `SL_TARGET_1_2` (all new entries): the fixed 5% initial stop is saved as
  `initial_stop` and never ratcheted; `target_price` is entry + 2 × risk.
  The only exits are `STOP_LOSS_INITIAL` and `TARGET_1_2`, filled at those
  levels. No trailing stop, EOD flatten, restart same-candle recovery or
  stale-recovery exit applies.
- `LEGACY` (default for all pre-existing rows): the prior +5 trail/+2 lock,
  5% stop, entry-candle-close restart recovery and EOD behavior are unchanged.

These fields are stored on `sma9_open_positions` with backward-compatible
migrations, and are included in `Position.as_dict()`/`from_dict()` and the
per-option live status. This is a local source change only; no deploy,
service restart or order placement is part of it.
