# PHASE 29 — API Endpoint Dependency Map

Created: 16 September 2026
Companion to: docs/PHASE29_FUNCTIONAL_AUDIT.md

Purpose: Map every frontend page to its exact API endpoint dependencies,
so VM verification can test each chain end-to-end.

---

## Global API Routing

All frontend JS uses `fetch('/api/...')` (absolute path).
Nginx routes `/api/` → proxy to `http://127.0.0.1:8000` (Flask/Gunicorn).
Nginx serves HTML from `/var/www/tradingai.in/html/` (webroot).

If nginx is not serving pages OR gunicorn is not running, ALL dynamic content fails.

### Critical nginx behavior

| URL pattern | nginx location | Behavior |
|-------------|---------------|----------|
| `/*.html` | `~* \.html$` | `try_files $uri =404` — file must exist exactly |
| `/` | `location /` | `try_files $uri $uri/ /index.html` |
| `/today/` | `location /` | `$uri/` → serves `/today/index.html` via directory index |
| `/today/index.html` | `~* \.html$` | `try_files $uri =404` — file must exist exactly |
| `/api/...` | `location /api/` | Proxy to gunicorn on :8000 |
| `/data/...` | `location /data/` | Serve from webroot (static) |

**IMPORTANT**: `.html` files do NOT fall through to index.html SPA fallback.
Every `.html` URL must match an actual file in the webroot.

---

## P0 — Homepage (/)

### HTML file served
`/var/www/tradingai.in/html/index.html`

### Static inline scripts (no JS execution needed for structure)
- Breadth bar: inline `fetch('/api/index-breadth')` → `/api/index-breadth`
- Market status bar: inline `fetch('/api/market')` → `/api/market`
- Index prices (NIFTY/BANKNIFTY/SENSEX/FINNIFTY): inline `fetch('/api/price/'+sym)` → `/api/price/{SYM}`
- Options (PCR/MaxPain/OI): inline `fetch('/api/pcr')`, `fetch('/api/maxpain')`, `fetch('/api/oi-top?symbol=NIFTY')` → `/api/pcr`, `/api/maxpain`, `/api/oi-top`

### External JS (execution required)
- `static/js/ai-outlook.js` → calls `/api/market-outlook`, `/api/nifty`, `/api/vix`, `/api/breadth`
- `static/js/api.js` → used by market.js pattern (verify loaded)

### API chain for homepage

```
Browser → /api/index-breadth → nginx → gunicorn → api_server.py → DB
Browser → /api/market → nginx → gunicorn → api_server.py → DB (_MARKET cache)
Browser → /api/price/NIFTY → nginx → gunicorn → api_server.py → DB
Browser → /api/price/BANKNIFTY → nginx → gunicorn → api_server.py → DB
Browser → /api/price/SENSEX → nginx → gunicorn → api_server.py → DB
Browser → /api/price/FINNIFTY → nginx → gunicorn → api_server.py → DB
Browser → /api/market-outlook?symbol=NIFTY → nginx → gunicorn → market_outlooks table
Browser → /api/nifty → nginx → gunicorn → symbol_data("NIFTY") → DB
Browser → /api/vix → nginx → gunicorn → api_server.py → DB
Browser → /api/breadth → nginx → gunicorn → market_breadth table
```

### Expected responses (from AGENTS.md DB state)
| Endpoint | Expected | Status |
|----------|----------|--------|
| `/api/market` | 200, data_quality GOOD | ✅ Per AGENTS.md |
| `/api/price/NIFTY` | 200, price ~23118 | ✅ Per AGENTS.md |
| `/api/vix` | 200, ~13.27 | ✅ Per AGENTS.md |
| `/api/nifty` | 200, all data_completeness true | ✅ Per AGENTS.md |
| `/api/breadth` | 200, data | ⚠️ Not confirmed |
| `/api/index-breadth` | 200, array | ⚠️ Not confirmed |
| `/api/market-outlook?symbol=NIFTY` | 200, outlook payload | ⚠️ Not confirmed |
| `/api/health` | 200, ok, ready true | ✅ Per AGENTS.md |

### Failure trace if homepage shows Loading…/—

```
index.html static HTML → loads (✅)
  ↓
inline /api/price/* calls → nginx → gunicorn?
  ↓
  If gunicorn NOT running → 502 → Loading… → FAIL
  ↓
inline /api/market call → nginx → gunicorn?
  ↓
  If DB empty → STALE or UNAVAILABLE → still shows data
  ↓
ai-outlook.js loads → executes → fetch /api/market-outlook, /api/nifty, /api/vix, /api/breadth
  ↓
  If any 404/500 → Loading AI Market Outlook… → FAIL
```

---

## P0 — Today terminal (/today/index.html)

### HTML file served
`/var/www/tradingai.in/html/today/index.html`

### API dependencies
**This page has NO external JS file dependency.** All data comes from inline scripts (verify with browser DOM inspector).

Each section has a static loading placeholder + inline JS that fetches from `/api/`.

### API chain for today

| Section | API call | Backend function |
|---------|----------|------------------|
| Session status | Inline JS check | Date/time comparison |
| Market Snapshot | `fetch('/api/price/NIFTY')` etc | `/api/price/{symbol}` |
| AI Outlook | `fetch('/api/market-outlook?symbol=NIFTY')` | `/api/market-outlook` |
| Key Levels | `fetch('/api/nifty')` | `/api/nifty` (extract indicators/key_levels) |
| Options | `fetch('/api/pcr?symbols=NIFTY')` etc | `/api/pcr`, `/api/maxpain`, `/api/oi-top` |
| Breadth | `fetch('/api/index-breadth')` | `/api/index-breadth` |
| VIX | `fetch('/api/vix')` | `/api/vix` |
| Strategy | `fetch('/api/market-outlook?symbol=NIFTY')` | `/api/market-outlook` (strategies) |
| Timeline | Inline + `fetch('/api/market')` | `/api/market` |

### Public inspection result
Still showing "Loading today's session…" in public audit.

### Most likely cause
Either gunicorn not running (all `/api/` calls fail) or inline JS not executing properly.

---

## P0 — NIFTY deep dive (/indices/nifty.html)

### HTML file served
`/var/www/tradingai.in/html/indices/nifty.html`

### External JS
`static/js/ai-outlook.js` → calls 4 endpoints:
1. `/api/market-outlook?symbol=NIFTY` (main outlook payload)
2. `/api/nifty` (price, regime, indicators, strategy, scenarios)
3. `/api/vix` (VIX data)
4. `/api/breadth` (breadth data)

### Public inspection result
Crawler could not retrieve reliably.

### Verification needed
1. Does `/indices/nifty.html` return 200 from nginx?
2. Does `/api/market-outlook?symbol=NIFTY` return valid JSON from gunicorn?
3. Does `/api/nifty` return valid JSON?
4. Are all 4 fetches completing successfully in browser?

---

## P0 — BANKNIFTY, FINNIFTY, SENSEX (/indices/{sym}.html)

### Same template as NIFTY, different symbol parameter

Each page loads `ai-outlook.js` with `symbol={SYM}` config.
API calls change to:
1. `/api/market-outlook?symbol={SYM}`
2. `/api/{sym}` (nifty→/api/nifty, banknifty→/api/banknifty, etc.)
3. `/api/vix` (same)
4. `/api/breadth` (same)

---

## P0 — Options Intelligence (/options/pcr.html)

### HTML file served
`/var/www/tradingai.in/html/options/pcr.html`

### API dependencies
Uses `fetchJSON` with `/api/` prefix:
1. `/api/pcr?symbols=NIFTY` → `/api/pcr`
2. `/api/pcr?symbols=BANKNIFTY` → `/api/pcr`
3. `/api/maxpain?symbols=NIFTY` → `/api/maxpain`
4. `/api/maxpain?symbols=BANKNIFTY` → `/api/maxpain`
5. Index data: `/api/nifty`, `/api/banknifty` → `/api/{symbol}`
6. VIX: `/api/vix`

### Public inspection result
Crawler could not retrieve reliably.

---

## P1 — Strategies (/strategies.html)

### HTML file served
`/var/www/tradingai.in/html/strategies.html`

### API dependencies
`strategies.js` fetches:
1. `/api/nifty` → NIFTY strategy data
2. `/api/banknifty` → BANKNIFTY strategy data
3. `/api/sensex` → SENSEX strategy data

### Also uses inline scripts (verify with DOM):
- Market data, breadth: `/api/market`, `/api/index-breadth`
- AI outlook sections: likely `/api/market-outlook`

### Public inspection result
Crawler could not retrieve reliably.

### Key failure points
- If `/api/nifty`, `/api/banknifty`, or `/api/sensex` fail → strategies = Loading…
- The Strategy Analysis section may use different endpoint than strategy cards

---

## P1 — Market (/market.html)

### HTML file served
`/var/www/tradingai.in/html/market.html`

### API dependencies
`market.js` fetches:
1. `/api/market` → market grid (instruments)
2. `/api/vix` → VIX data

### Also uses inline scripts:
- `/api/market` (duplicate, for ticker)
- `/api/index-breadth` (breadth)

### Public inspection result
Crawler could not retrieve reliably.

### Key failure points
- If `/api/market` fails → grid = "Loading market pulse…"
- If `/api/vix` fails → VIX section empty

---

## P1 — Scanner (/scanner.html)

### HTML file served
`/var/www/tradingai.in/html/scanner.html`

### API dependencies
`scanner.js` fetches 12 symbols:
1. Index endpoints: `/api/nifty`, `/api/banknifty`, `/api/sensex`
2. Stock endpoints: `/api/reliance`, `/api/hdfcbank`, `/api/icicibank`, `/api/sbin`, `/api/infy`, `/api/tcs`, `/api/lt`, `/api/axisbank`, `/api/adanient`, `/api/bhartiartl`

### All stock endpoints go through `/api/<symbol>` generic route (line 778)
This route:
1. Checks if symbol is a reserved word (MARKET, HEALTH, etc.) → 404
2. Checks `symbols` table for known symbol → 404 if not found
3. Returns `_symbol_data(s)` if found

### Key failure points
- If any stock is NOT in `symbols` table → that scanner card is skipped (not loaded)
- If `/api/market` fails → no market data context
- If gunicorn is slow → 12 sequential fetches may timeout

---

## P2 — Mutual Funds (/mutual-funds/index.html)

### HTML file served
`/var/www/tradingai.in/html/mutual-funds/index.html`

### API dependencies
1. `/api/mf` → mutual fund data
2. `/api/market` (inline) → market context
3. `/api/index-breadth` (inline) → breadth context

### Key failure points
- `/api/mf` → queries `mf_schemes` and `mf_returns` tables
- If these tables are empty → "Loading mutual funds…"

---

## P2 — Strategy Builder (/strategy-builder.html)

### API dependencies
1. `/api/nifty` → index data for strategy builder
2. `/api/market` → market context (inline)
3. Payoff calculations are static (no API)

---

## P2 — Backtest (/tools/backtest.html)

### API dependencies
1. `/api/backtest` (when user clicks Run) → runs backtest
2. `/api/market` (inline) → market context

### Key observation
Backtest is interactive — empty until user clicks Run. Expected behavior.

---

## P2 — Position Size (/tools/position-size.html)

### API dependencies
1. `/api/market` (inline) → market context
2. Calculations are static (no API)

---

## Summary — Endpoint Risk Matrix

| Endpoint | Used By | Risk Level | Notes |
|----------|---------|------------|-------|
| `/api/market` | Homepage, Today, Market, Scanner, ALL pages | CRITICAL | Single point of failure for market data |
| `/api/price/{symbol}` | Homepage ticker, Today snapshot | CRITICAL | 4 endpoints (NIFTY/BANKNIFTY/SENSEX/FINNIFTY) |
| `/api/market-outlook` | Homepage, Today, NIFTY page | CRITICAL | Main AI outlook payload |
| `/api/nifty` | NIFTY page, strategies, options | HIGH | NIFTY-specific data |
| `/api/banknifty` | Options, strategies | HIGH | BANKNIFTY data |
| `/api/sensex` | Strategies | MEDIUM | SENSEX data |
| `/api/vix` | Homepage, Today, Market, NIFTY | HIGH | VIX data |
| `/api/breadth` | Homepage, Today, NIFTY | HIGH | Breadth data |
| `/api/index-breadth` | Homepage inline, Today | HIGH | Alternative breadth endpoint |
| `/api/pcr` | Options, Today, Homepage | HIGH | PCR data |
| `/api/maxpain` | Options, Today, Homepage | HIGH | Max Pain data |
| `/api/oi-top` | Homepage options cards | HIGH | OI data |
| `/api/mf` | Mutual funds | MEDIUM | MF data |
| `/api/{symbol}` (stock) | Scanner | HIGH | 12 stock symbols must be in DB |
| `/api/backtest` | Backtest tool | MEDIUM | Interactive only |

---

## Most Likely Single-Point Failures

If ALL P0 pages fail simultaneously, the most likely cause is:

1. **gunicorn not running** → ALL `/api/` calls fail → ALL dynamic content shows Loading…
2. **Nginx not running** → ALL pages 404 or 502
3. **DB empty** → API returns STALE or UNAVAILABLE → pages show "data unavailable"

If only SOME P0 pages fail:
1. **Specific endpoint returns 404** → check nginx route or backend route
2. **Specific endpoint returns empty data** → check DB table
3. **JS execution fails** → browser console check needed
4. **CORS issue** → check nginx CORS headers (AGENTS.md says CORS: tradingai.in only)

---

## VM Verification Checklist

When VM access available, run in this order:

```bash
# 1. Check services
sudo systemctl status nginx
sudo systemctl status tradingai-api
curl -s http://127.0.0.1:8000/api/health

# 2. Check key endpoints (all should return 200)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/market
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/price/NIFTY
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/vix
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/breadth
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/market-outlook?symbol=NIFTY
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/nifty
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/mf

# 3. Check nginx routes (all should return 200 or 301)
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/today/
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/market.html
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/indices/nifty.html
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/options/pcr.html
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/strategies.html
curl -s -o /dev/null -w "%{http_code}" https://tradingai.in/scanner.html

# 4. Check HTML files exist in webroot
ls /var/www/tradingai.in/html/index.html
ls /var/www/tradingai.in/html/today/index.html
ls /var/www/tradingai.in/html/market.html
ls /var/www/tradingai.in/html/indices/nifty.html
ls /var/www/tradingai.in/html/options/pcr.html
ls /var/www/tradingai.in/html/strategies.html
ls /var/www/tradingai.in/html/scanner.html
```

---

## Backend Endpoint Reference

Generated from backend/api_server.py (90 routes total).
Key routes for this audit (marked with section headers):

### Market data
- `/api/market` — Main market payload (instruments + ai_outlook)
- `/api/price/<symbol>` — Single symbol quote
- `/api/vix` — India VIX
- `/api/breadth` — Market breadth (advance/decline)
- `/api/index-breadth` — Index-level advances/declines
- `/api/snapshot` — Market snapshot

### Index data
- `/api/nifty`, `/api/banknifty`, `/api/sensex`, `/api/finnifty` — Per-index data
- `/api/<symbol>` — Generic symbol (checks symbols table)

### AI outlook
- `/api/market-outlook` — Latest outlook payload
- `/api/market-outlook/<date>` — Outlook for specific date
- `/api/outlook/<symbol>` — Per-symbol outlook

### Options
- `/api/pcr`, `/api/pcr?symbols=` — Put-call ratio
- `/api/maxpain`, `/api/maxpain?symbols=` — Max Pain
- `/api/oi-top`, `/api/oi-top?symbol=` — Open interest
- `/api/expected-move/<symbol>` — Expected move
- `/api/options/<symbol>` — Options chain
- `/api/options-intelligence/<symbol>` — Options intelligence

### Strategy & scenario
- `/api/strategy/<symbol>` — Per-symbol strategy
- `/api/strategies` — All strategies
- `/api/regime/<symbol>` — Per-symbol regime
- `/api/regimes` — All regimes
- `/api/scenarios/<symbol>` — Per-symbol scenarios

### Tools
- `/api/backtest`, `/api/backtest/vix-strangle`, `/api/backtest/5m-real` — Backtest
- `/api/walkforward/<symbol>/<start>/<end>` — Walk-forward
- `/api/evidence/<symbol>/<date>` — Historical evidence

### MF, News, ETF
- `/api/mf` — Mutual funds
- `/api/news`, `/api/news/<symbol>` — News
- `/api/etf`, `/api/etf-holdings` — ETF data
- `/api/fundamentals/<symbol>` — Fundamentals

### Journal & Intelligence
- `/api/journal` CRUD, `/api/journal/stats`, `/api/journal/feedback` — Trade journal
- `/api/intelligence/*` — Personal trading intelligence

---

**Generated from workspace analysis. Requires VM verification to confirm actual runtime behavior.**
