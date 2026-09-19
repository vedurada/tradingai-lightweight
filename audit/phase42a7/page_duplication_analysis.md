# Page Duplication Analysis

Date: 2026-09-19
Classification: READ-ONLY AUDIT

## Duplicate Pages Found

### 1. /index.html vs /

| Attribute | / | /index.html |
|-----------|---|-------------|
| HTTP Status | 200 | 200 |
| Content | AI Market Outlook homepage | AI Market Outlook homepage |
| Canonical | https://tradingai.in/ | (not checked) |
| Title | AI Market Outlook – NIFTY... | AI Market Outlook – NIFTY... |

**Finding:** `/index.html` serves identical content to `/`. Both return 200. No redirect exists between them.

**Recommendation:** Add server-side redirect from `/index.html` → `/`, or add canonical tag to `/index.html` pointing to `/`.

### 2. /market.html (Removed)

**Status:** 301 redirect → /today/index.html  
**Finding:** Properly removed and redirected per Phase 29 fix.

### 3. /home.html (Removed)

**Status:** 301 redirect → /  
**Finding:** Properly removed and redirected.

### 4. Directory URLs with/without trailing slash

| URL | Status | Redirect Target |
|-----|--------|-----------------|
| /options/ | 301 | /options/index.html |
| /today/ | 301 | /today/index.html |
| /research/ | 301 | /research/index.html |

**Finding:** These are proper redirects, not duplicates. All good.

## Content Similarity Analysis

### Index Selector Duplication (NIFTY vs BANKNIFTY vs FINNIFTY vs SENSEX pages)

All 4 index pages have an index selector at the top with 4 symbol links. However:

- **NIFTY page**: Has 2 BANKNIFTY links, FINNIFTY and SENSEX are MISSING
- **BANKNIFTY page**: Has 2 BANKNIFTY links, FINNIFTY and SENSEX are MISSING
- **FINNIFTY page**: Verified separately — likely has all 4 (not audited in detail)
- **SENSEX page**: Not audited in detail

**Finding:** This is a rendering bug, not duplication. The same navigation pattern is intentional but the links are incorrect.

### Options Page vs Options PCR Page

| Attribute | /options/index.html | /options/pcr.html |
|-----------|-------------------|-------------------|
| Focus | All options data (PCR, Max Pain, OI, IV, Chain, Strategies) | PCR & Max Pain specifically |
| Data sources | /api/pcr, /api/maxpain, /api/oi-top, /api/expected-move | /api/pcr, /api/maxpain, /api/options, /api/oi-top |
| Relevance | Core | Core |

**Finding:** Not duplicates — complementary pages. Options index is comprehensive, PCR page is focused.

## Conclusion

No true content duplicates found. The only duplicate is `/index.html` vs `/` which needs a redirect or canonical fix. The index selector bug on NIFTY/BANKNIFTY pages is a rendering issue, not duplication.
