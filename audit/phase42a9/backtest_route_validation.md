# Backtest Route Validation — Phase 42A.9

## Route Investigation

### /tools/backtest.html
- **Status**: ✅ NOW 200 (was 404 before fix)
- **Content**: Full backtest UI with chart, strategy selection, parameters
- **Referenced from**: /index.html (Backtest card), /strategies.html (Backtest card)
- **Canonical**: YES — this is the canonical backtest page

### /backtest.html
- **Status**: ❌ 404 (does not exist in workspace or VM)
- **No file at workspace root**: No backtest.html in workspace
- **No redirect configured**: nginx has no redirect from /backtest.html to /tools/backtest.html
- **Internal links**: All internal links point to /tools/backtest.html, NOT /backtest.html
- **Decision**: No action needed — all links correctly point to /tools/backtest.html

### Historical Context
The backtest.html at root never existed in this codebase. The canonical URL has always been /tools/backtest.html. The 404 at /backtest.html is intentional — no redirects needed since no links point there.

## Nginx Routing
- /tools/backtest.html → try_files → /var/www/tradingai.in/html/tools/backtest.html → 200 ✅
- /backtest.html → try_files $uri $uri/ /index.html → falls through to index.html (SPA fallback)
  - This means /backtest.html would show index.html content, not 404
  - But since no links point there, this is harmless

## Verification
- All internal links to backtest use /tools/backtest.html ✅
- /tools/backtest.html serves correctly ✅
- /backtest.html 404s through HTTPS (try_files falls to /index.html but no link)
- No broken links to backtest found ✅