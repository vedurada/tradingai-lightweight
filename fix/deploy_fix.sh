#!/bin/bash
set -e

echo "=== Phase 42A.5 Deployment Fix ==="

# 1. Fix crontab
echo "Installing clean crontab..."
crontab /tmp/tradingai_crontab.txt
echo "Crontab installed: $(crontab -l | wc -l) lines"
echo "data_fetcher: $(crontab -l | grep -c data_fetcher)"
echo "aggregate: $(crontab -l | grep -c 'aggregate.py')"
echo "monitor: $(crontab -l | grep -c 'monitor.py')"
echo "self-heal: $(crontab -l | grep -c self-heal)"

# 2. Install monitor systemd service (oneshot)
echo "Installing monitor systemd service..."
sudo cp /tmp/monitor.service /etc/systemd/system/monitor.service
sudo systemctl daemon-reload
sudo systemctl enable monitor.service
echo "monitor service installed"

# 3. Install data-fetcher systemd service (oneshot)
echo "Installing data-fetcher systemd service..."
sudo cp /tmp/data-fetcher.service /etc/systemd/system/data-fetcher.service
sudo systemctl daemon-reload
sudo systemctl enable data-fetcher.service
echo "data-fetcher service installed"

# 4. Stop old monitor.service if it was crash-looping
echo "Clearing monitor crash state..."
sudo systemctl stop monitor.service 2>/dev/null || true
sudo systemctl reset-failed monitor.service 2>/dev/null || true

echo "=== Deployment Complete ==="