# Post-Deployment Validation — /market.html Removal

Date: 2026-09-18
Status: TEMPLATE — fill after deployment

## Pre-Deployment Checklist
- [ ] All HTML files updated (nav links, CTA links, JS redirects)
- [ ] sitemap.xml updated (market.html entry removed)
- [ ] market.html archived
- [ ] nginx redirect config added to VM
- [ ] All changes deployed to VM

## Validation Results (2026-09-18)

### 1. Redirect Tests ✅
```
curl -I https://tradingai.in/market.html
→ HTTP/1.1 301 Moved Permanently
→ Location: https://tradingai.in/today/index.html

curl -I https://tradingai.in/indices/market.html
→ HTTP/1.1 301 Moved Permanently
→ Location: https://tradingai.in/today/index.html

curl -L https://tradingai.in/market.html
→ HTTP/2 200 (follows redirect to /today/index.html)
```

### 2. Content Tests ✅
```
curl -s https://tradingai.in/index.html | grep -c "market\.html"
→ 0 (no references)

curl -s https://tradingai.in/today/index.html | grep -c "market\.html"  
→ 0 (no URL references; "pre_market" text not counted)

curl -s https://tradingai.in/about.html | grep -c "market\.html"
→ 0
```

### 3. Sitemap Validation ✅
```
curl -s https://tradingai.in/sitemap.xml | grep -c "market.html"
→ 0
```

### 4. Test Suite (workspace)
```
pytest tests/test_live_pages.py tests/test_deploy.py tests/test_phase42a5d.py 
tests/test_phase33_7_production_validation.py tests/test_phase7_track_c.py 
tests/test_data_integrity.py tests/test_phase7_track_b.py
→ 125 passed, 2 pre-existing failures (MaxPain wording + consent check)
```

### 5. Deployment Verification
```
- Git commit: f184739
- Git push: origin/html/h31-shell-core-pages
- VM webroot: market.html deleted
- VM nginx: redirect config deployed and reloaded
- VM audit/: synced
```

## Post-Deployment Metrics to Monitor
- /today/index.html traffic (should increase as redirected traffic arrives)
- 404 errors (should not increase — all links updated)
- Search Console indexing (verify /market.html de-indexes, /today/ re-indexes)

## Rollback Procedure
If issues found:
1. Remove nginx redirect: `location = /market.html { return 301 /today/index.html; }`
2. Restore archived market.html from /opt/tradingai/audit/market_page/archive/
3. Revert HTML changes (git checkout)
4. Re-add sitemap entry
5. Restart nginx and gunicorn
