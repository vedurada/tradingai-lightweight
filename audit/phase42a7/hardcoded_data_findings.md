# Hardcoded Data Findings

Date: 2026-09-19
Classification: READ-ONLY AUDIT

## Summary

Scanned all retained public HTML pages for hardcoded market data values.

## Critical Findings

### 1. Homepage Pre-Rendered Market Data (STALE)

**File:** `/index.html` (homepage)  
**Severity:** MEDIUM  
**Location:** Multiple `<span>` elements with `data-prerendered` attribute

| Element | Hardcoded Value | Timestamp | Staleness |
|---------|----------------|-----------|-----------|
| #s-nifty-price | 23,346.40 | 18 Sep 2026, 22:11 IST | ~20+ hours stale at audit time |
| #s-banknifty-price | 56,358.70 | 18 Sep 2026, 22:11 IST | ~20+ hours stale |
| #s-sensex-price | 74,294.96 | 18 Sep 2026, 22:11 IST | ~20+ hours stale |
| #s-finnifty-price | 25,510.00 | 18 Sep 2026, 22:11 IST | ~20+ hours stale |
| #s-vix-price | 11.39 | 18 Sep 2026, 22:11 IST | ~20+ hours stale |
| #s-vix-change | -7.36% | 18 Sep 2026, 22:11 IST | ~20+ hours stale |
| #home-data-age | "18 Sep 2026" | Hardcoded date | Does not update dynamically |

**Impact:** Users see stale market data if JavaScript fails or is blocked. The pre-rendered values are approximately 20+ hours old at audit time.

**Recommendation:** Add `data-prerendered` timestamp check. If older than 30 minutes, display "STALE" or "Market closed" instead of the pre-rendered value.

### 2. FINNIFTY Stale-Price Magic Number (CRITICAL)

**File:** `/indices/finnifty.html`  
**Severity:** CRITICAL  
**Location:** JavaScript — checks `if(spot.textContent.trim()==='25,262.40')`

**Description:** FINNIFTY page has a hardcoded magic number check for stale yfinance data. When the spot price equals exactly "25,262.40", it shows a "Stale: last known price from yfinance" tooltip. This is fragile — it only works for one specific price value. If the price changes, the stale warning disappears.

**Recommendation:** Replace magic number check with proper staleness detection (e.g., compare data timestamp to current time, or check data source flag).

### 3. SENSEX Missing Stale-Data Handling

**File:** `/indices/sensex.html`  
**Severity:** MEDIUM  
**Description:** FINNIFTY has stale-price detection but SENSEX does not. If SENSEX also uses yfinance fallback, stale data would be displayed without warning.

**Recommendation:** Add same stale-data handling as FINNIFTY, or verify SENSEX always has live NSE data.

## Allowed Hardcoded Values (No Issues)

The following hardcoded values are acceptable per Phase 42A.7 rules:

- Static page titles (e.g., "NIFTY 50 – AI Market Outlook")
- Navigation labels (e.g., "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")
- Educational text and methodology explanations
- Default empty states ("Loading...", "Loading market data...")
- Session state labels ("MARKET OPEN", "MARKET CLOSED")
- Footer text and legal disclaimers
- Index selector links (correct symbolic references)

## Not Found

- No hardcoded AI outputs found on any page
- No hardcoded strategy recommendations found
- No hardcoded OI/PCR/IV values found
- No hardcoded timestamps (except pre-rendered market data on homepage)
- No hardcoded market states (except session clock labels)
