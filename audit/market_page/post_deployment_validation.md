# Post-Deployment Validation — /market.html Removal

Date: 2026-09-18
Status: TEMPLATE — fill after deployment

## Pre-Deployment Checklist
- [ ] All HTML files updated (nav links, CTA links, JS redirects)
- [ ] sitemap.xml updated (market.html entry removed)
- [ ] market.html archived
- [ ] nginx redirect config added to VM
- [ ] All changes deployed to VM

## Validation Tests

### 1. Redirect Tests (run on VM after deploy)
```bash
# Test 301 redirect
curl -I https://tradingai.in/market.html 2>&1 | grep "301\|Location"
# Expected: HTTP/2 301, Location: /today/index.html

# Test ghost-path redirect
curl -I https://tradingai.in/indices/market.html 2>&1 | grep "301\|Location"
# Expected: HTTP/2 301, Location: /today/index.html

# Test /today/index.html still works
curl -I https://tradingai.in/today/index.html 2>&1 | grep "200"
# Expected: HTTP/2 200
```

### 2. Content Tests
```bash
# Verify /today/index.html renders correctly
curl -s https://tradingai.in/today/index.html | grep -c "NIFTY"
# Expected: multiple matches (NIFTY appears in snapshot, outlook, etc.)

# Verify no market.html references in served HTML
curl -s https://tradingai.in/index.html | grep -c "market\.html"
# Expected: 0 (nav link removed)
```

### 3. Sitemap Validation
```bash
# Verify market.html not in sitemap
curl -s https://tradingai.in/sitemap.xml | grep -c "market.html"
# Expected: 0
```

### 4. Link Integrity
```bash
# Check all pages no longer link to /market.html
for page in /index.html /today/index.html /about.html /contact.html; do
  echo "=== $page ==="
  curl -s https://tradingai.in$page | grep -c "market\.html"
done
# Expected: 0 for all pages
```

### 5. Test Suite
```bash
cd /opt/tradingai/backend
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -20
# All tests should pass
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
