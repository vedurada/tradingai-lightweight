# Integration into the existing deployment

This orphan branch intentionally contains only new files. The following small
edits were applied to the already-deployed live-only tree on the VM. They are
recorded here so the branch can be replayed onto a fresh checkout without
copying large existing files.

## 1. API blueprint

`app/api/app.py`:

```python
from app.api.sma9_short_api import bp as sma9_short_bp
...
app.register_blueprint(sma9_short_bp)
```

## 2. Performance report

`app/api/performance_api.py` — add this entry at the start of `SCANNERS`:

```python
{
    "key": "sma9_short",
    "label": "SMA9 SHORT",
    "db": "sma9_short.db",
    "table": "sma9_short_trades",
    "date_col": "trade_date",
    "where": "status = 'CLOSED'",
    "open_table": "sma9_short_open_positions",
    "min_date": "2026-11-25",
},
```

## 3. Live ATM offsets

`app/api/live_atm_api.py`:

- Add `SCANNER_STRIKE_OFFSETS = {"sma9-short": {"CE": 200.0, "PE": -200.0}}`.
- Allow `_instrument_master_contracts`, `_heartbeat_contracts`, and
  `_derived_contracts` to accept explicit per-leg `strikes`.
- When `?scanner=sma9-short` is supplied, target `ATM+200` for CE and `ATM−200`
  for PE.
- Include `strike_offsets` in the response.
- Heartbeat contracts are accepted only when their strike matches the target;
  the instrument master is used only to fill missing legs.

## 4. Broker identity

`broker_gateway/config/scanners.json`:

```json
"sma9_short": "mstock",
"live_sma9_short_scanner.py": "mstock"
```

## 5. Scalp launcher

`frontend/live/scalp/index.html`:

```html
<button class="scanner-btn short" type="button"
        data-key="sma9-short"
        data-src="/live/sma9-short/"
        aria-pressed="false">SMA9 SHORT</button>
```

## 6. Strategy rules (display only)

`frontend/live/strategy_rules.json` — add a `scanners["sma9-short"]` object
describing the paper-only entry, stop, trail, and scope rules shown in
`README.md`.

## 7. Service

Install `systemd/tradingai-sma9-short-scanner.service` as
`/etc/systemd/system/tradingai-sma9-short-scanner.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tradingai-sma9-short-scanner.service
sudo systemctl restart tradingai-broker-gateway.service
sudo systemctl restart tradingai-api.service
```

The deployment used backups under
`/opt/tradingai/archives/sma9_short_deploy_*` before replacing existing files.
