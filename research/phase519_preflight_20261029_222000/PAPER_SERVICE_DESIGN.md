# Phase 5.19 — Paper Service Design (Not Implemented)

## Proposed Systemd Unit

```ini
[Unit]
Description=TradingAI HLC Paper Trade Live Service
After=network-online.target tradingai-market-data.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/tradingai
ExecStart=/usr/bin/python3 /opt/tradingai/scripts/paper_scalp_live.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tradingai-paper-scalp-live
Environment=PYTHONPATH=/opt/tradingai

[Install]
WantedBy=multi-user.target
```

## Paper-Only Behavior
- No broker API calls
- Paper trades only (paper_trades table)
- No real-money execution
- No order placement

## Service User
- User: ubuntu
- Group: ubuntu
- Permissions: read/write to /opt/tradingai/database/, /opt/tradingai/logs/

## Logging
- stdout/stderr to journal
- SyslogIdentifier for filtering
- Log rotation via journald

## Restart Behavior
- Restart=on-failure
- RestartSec=10
- Duplicate process prevention via fcntl lock

## Idempotent Trade Creation
- Deterministic trade_id (SHA-1 of link_key)
- trade_id is PRIMARY KEY
- IntegrityError caught on duplicate

## Stop/Abort Procedure
- systemctl stop tradingai-paper-scalp-live
- Lock file released automatically
- Open positions remain in DB
- State file saved on last cycle

## Installation
- NOT installed in Phase 5.19
- Requires separate approval-gated phase
