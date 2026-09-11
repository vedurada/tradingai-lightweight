#!/usr/bin/env bash
# Ping IndexNow (Bing/Yandex/Seznam) with the full sitemap URL.
# Run after any deploy. Key file lives at /var/www/tradingai.in/html/<key>.txt.
set -euo pipefail
HOST="tradingai.in"
KEY=$(find /var/www/tradingai.in/html -maxdepth 1 -name "*.txt" -not -name "robots.txt" -size +15c -size -60c | head -1)
if [ -z "$KEY" ]; then
  echo "no indexnow key file found" >&2; exit 1
fi
K=$(basename "$KEY" .txt)
curl -s -o /dev/null -w "indexnow ping: %{http_code}\n" \
  "https://api.indexnow.org/indexnow?url=https%3A%2F%2F${HOST}%2Fsitemap.xml&key=${K}"