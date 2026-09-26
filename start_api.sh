#!/bin/bash
mkdir -p /opt/tradingai/logs
cd /opt/tradingai
if ! pgrep -f "gunicorn.*app.api" > /dev/null; then
    /usr/local/bin/gunicorn -D -w 2 --threads 2 --worker-class gthread --bind 127.0.0.1:8000 --timeout 90 --graceful-timeout 15 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile /opt/tradingai/logs/gunicorn-access.log --error-logfile /opt/tradingai/logs/gunicorn-error.log app.api.app:app
    echo "API started at $(date)"
else
    echo "API already running"
fi
