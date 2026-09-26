# Deployment

## Prerequisites
- Python 3.10+
- pip
- nginx (optional, for public serving)

## Installation

```bash
cd /opt/tradingai_new
pip install -r requirements.txt
```

## Running the API

### Direct (development)
```bash
cd /opt/tradingai_new
python3 app/api/app.py
```

### Production (gunicorn)
```bash
cd /opt/tradingai_new
gunicorn -w 2 --threads 2 --bind 127.0.0.1:8000 app.api.app:app
```

### With systemd (recommended)
```bash
sudo cp /opt/tradingai_new/deploy/tradingai-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tradingai-api
sudo systemctl start tradingai-api
```

## Nginx Configuration

```nginx
server {
    listen 443 ssl;
    server_name tradingai.in www.tradingai.in;
    root /opt/tradingai_new/frontend;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

## Scheduled Jobs (Cron)

```bash
# Market data fetch (during market hours)
*/5 9-15 * * 1-5 cd /opt/tradingai_new && python3 scripts/fetch_market_data.py

# Health check
*/2 * * * * curl -sf http://127.0.0.1:8000/api/health > /dev/null || systemctl restart tradingai-api

# Health JSON generation
0 * * * * cd /opt/tradingai_new && python3 scripts/health_check.py

# Frontend JSON generation
30 * * * * cd /opt/tradingai_new && python3 scripts/generate_frontend_json.py
```

## Rollback

Legacy system archived at `/opt/tradingai_legacy_archive/legacy_full_backup_20260919_190535.tar.gz`.

To rollback:
1. Stop tradingai-api service
2. Extract backup to `/opt/tradingai/`
3. Restart legacy service
