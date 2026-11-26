#!/usr/bin/env bash
# Install and enable the SMA9 HIGH code-integrity timer (runs every 15 minutes).
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run with sudo: sudo $0" >&2
  exit 1
fi

cat > /etc/systemd/system/tradingai-sma9-high-integrity.service <<'EOF'
[Unit]
Description=TradingAI SMA9 HIGH code integrity check
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/tradingai/sma9_high_scanner/ops/verify_integrity.sh
StandardOutput=append:/opt/tradingai/logs/sma9_high_integrity.log
StandardError=append:/opt/tradingai/logs/sma9_high_integrity.log
EOF

cat > /etc/systemd/system/tradingai-sma9-high-integrity.timer <<'EOF'
[Unit]
Description=Run the SMA9 HIGH code integrity check every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Unit=tradingai-sma9-high-integrity.service
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now tradingai-sma9-high-integrity.timer
systemctl start tradingai-sma9-high-integrity.service
systemctl --no-pager status tradingai-sma9-high-integrity.timer | sed -n '1,12p'
