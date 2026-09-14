# Card / Price / Link Audit — TradingAI.in

Run: 2026-09-14

## 1. Broken Links Found

### CSS/JS paths (relative, break on subdirectory pages)
| Page | Line | Resource | Current | Fix |
|------|------|----------|---------|-----|
| market.html | 40 | CSS | `assets/css/main.css` | `/assets/css/main.css` |
| market.html | 41 | JS | `assets/js/keep-scroll.js` | `/assets/js/keep-scroll.js` |
| market.html | 42 | JS | `assets/js/live-blink.js` | `/assets/js/live-blink.js` |
| market.html | 74 | Footer links | `about.html` etc | `/about.html` etc |
| scanner.html | 90 | Footer links | `about.html` etc | `/about.html` etc |
| scanner.html | 41-43 | CSS/JS | `assets/...` | `/assets/...` |

### Confirmed working
- index.html uses `/assets/...` and relative `about.html` (root-level ✅)
- indices/*.html uses `../assets/...` and `../about.html` (relative to /indices/ ✅)
- today/index.html uses `../assets/...` and `../about.html` (relative to /today/ ✅)

### `/indices/nifty.html` 404
File exists at workspace `indices/nifty.html`. Need to verify nginx config and deployment sync.

## 2. Cards NOT Clickable

### index.html — MARKET SNAPSHOT cards (lines 58-91)
- NIFTY 50 card (`s-nifty-price`) — NO onclick, NO link → NOT clickable
- BANKNIFTY card (`s-banknifty-price`) — NO onclick, NO link → NOT clickable
- SENSEX card (`s-sensex-price`) — NO onclick, NO link → NOT clickable
- FINNIFTY card (`s-finnifty-price`) — NO onclick, NO link → NOT clickable
- INDIA VIX card (`s-vix-price`) — NO onclick, NO link → NOT clickable
These are the MOST important cards on the site. Should link to their index pages.

### index.html — Backtest preview cards (lines 118-118)
- Generated dynamically, 4 cards — NOT clickable

### All pages — Market Grid CTA cards (lines 51/56/65-70 etc)
- Already have `<a class="cta cta-single" href="...">Open →</a>` → CLICKABLE ✅

### index.html — Dashboard cards (rendered by ai-outlook.js)
- Hero card, regime card, outlook bars, factors, key levels, options, strategies, decision, risk, trade record — Generated dynamically by ai-outlook.js
- No click handlers on these cards

## 3. Price Sources (INCONSISTENT)

| Page | Price Source | Endpoint |
|------|-------------|----------|
| index.html snapshot cards | prerender_snapshot.py | `/api/market` → instruments.NIFTY.quote.price |
| index.html dashboard | ai-outlook.js | `/api/nifty`, `/api/banknifty`, etc |
| market.html | loadMarket() | `/api/market` → instruments |
| scanner.html | loadScanner() | `/api/{symbol}` per instrument |
| today/index.html | loadToday() | `/api/nifty` |
| indices/nifty.html | ai-outlook.js | `/api/nifty`, `/api/vix`, `/api/breadth` |
| indices/banknifty.html | ai-outlook.js | `/api/banknifty`, `/api/vix`, `/api/breadth` |
| indices/sensex.html | ai-outlook.js | `/api/sensex`, `/api/vix`, `/api/breadth` |
| indices/finnifty.html | ai-outlook.js | `/api/finnifty`, `/api/vix`, `/api/breadth` |

**Key inconsistency:** index.html snapshot cards use `/api/market` data, but dashboard uses individual endpoints. Snapshots get stale; dashboard gets fresh. Prices may diverge.

## 4. Internal Navigation Gaps

- No navigation from index.html snapshot cards to detail pages
- No breadcrumb on any page (except JSON-LD)
- No "back to market overview" link on index detail pages
- No cross-links between related instruments
- No "view full outlook" link from market.html cards to index pages
