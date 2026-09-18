# Phase 42A.5 Nginx Validation

## Nginx Status
- Service: ACTIVE ✅
- Config test: PASSED ✅
- Config file: /etc/nginx/sites-enabled/tradingai

## Configuration Summary

### Server Blocks
1. **Port 80**: Redirects HTTP → HTTPS (301)
2. **Port 443**: Main server with SSL

### Key Locations
| Location | Behavior | Cache |
|---|---|---|
| `/data/` | Static files, no proxy | no-store |
| `/api/` | Proxy to gunicorn:8000 | 10s cache |
| `/api/chat/` | Proxy with 2s cache | 2s cache |
| `/api/portfolio` | Proxy, no cache | no-store |
| `/api/metrics` | Deny all | - |
| `/*.html` | try_files $uri $uri/ /index.html | no-store |
| `/` | SPA fallback | no-store |
| Static assets | Static files | 1h cache |

### Security
- SSL: TLSv1.2, TLSv1.3
- HSTS: Enabled via snippet
- Server tokens: Off
- Limit req: 60r/m for API

### Ghost Path Guards
- `/indices/market.html` → 301 /market.html ✅
- `/home.html` → 301 / ✅
- `/stocks.html` → 301 /scanner.html ✅
- `/fixed-loss-options.html` → 301 /options/pcr.html ✅

## Data Serving Verification

### Before Fix
```
curl https://tradingai.in/data/nifty.json → 404 Not Found
curl https://tradingai.in/data/banknifty.json → 404 Not Found
```

### After Fix
```
curl https://tradingai.in/data/nifty.json → 200 OK (7,132 bytes)
curl https://tradingai.in/data/banknifty.json → 200 OK (7,159 bytes)
curl https://tradingai.in/data/sensex.json → 200 OK (7,157 bytes)
curl https://tradingai.in/data/finnifty.json → 200 OK (4,547 bytes)
curl https://tradingai.in/data/health.json → 200 OK (268 bytes)
```

### Symlink
`/var/www/tradingai.in/html/data → /opt/tradingai/data` ✅

### No Caching Issues
- /data/ has `no-store, no-cache, must-revalidate` ✅
- /api/ has 10s cache (acceptable for market data) ✅
- Static assets have 1h cache (versioned) ✅
- HTML pages have no-store ✅
