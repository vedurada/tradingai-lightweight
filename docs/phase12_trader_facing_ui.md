# Phase 12 — Trader-Facing NIFTY & BANKNIFTY Product UI

## Page architecture

`frontend/indices/nifty.html` and `frontend/indices/banknifty.html` rebuilt
from one template (identical structure, per-instrument `SYM` constant only).
Sections: header + state chips → primary decision card → price snapshot →
market structure → market intent/scenario → completed-5m table → data-health
`<details>` → disclaimer footer. ~14KB per page, self-contained inline
CSS/JS, no frameworks, no images, no external dependencies.

## API fields used (all pre-existing except `candles`)

summary/decision `data`: state, session, reasons, instrument, live_price,
change/change_pct (Phase 12 passthrough addition, display only),
quote_timestamp/quote_age_seconds/quote_state, completed_candle,
completed_age_minutes, decision_timestamp, market_state
(trend/volatility/momentum/vwap_relation), qualification, trade
(entry/stop/target/scenario/strategy/objective/direction), read_only.
New read-only `GET /api/<sym>/candles?n=`: completed candles only +
`forming_excluded` flag (reuses provider cache, zero DB writes).

## UI state mapping

QUALIFIED→green "QUALIFIED SETUP" + trade box; NO_TRADE→"NO TRADE — WAIT" +
backend reasons; PREMARKET/MARKET_CLOSED/WEEKEND/STALE/NO_DATA/RATE_LIMITED/
UNAVAILABLE→explicit headline + reasons. Text always accompanies color.
NO_TRADE is first-class, never a failure presentation.

## Refresh intervals

summary 30s (price + state), decision 120s, candles 120s — within Phase 11
cache TTLs. Decision polling is GET-only; pages never call
POST /decision/claim (statically asserted). Price blinks only when a fresh
(`quote_state==LIVE`, new timestamp) quote actually changed value.

## Mobile design

Single column, decision card above fold, 44px touch targets, tabular
numerals, 6-column candle table sized for 320px (no page-level horizontal
scroll), `@media(min-width:700px)` widening. Verified by markup contract
tests (viewport, breakpoints); device rendering limited to markup/CSS review
(no device lab on VM).

## NIFTY/BANKNIFTY isolation

Separate pages, separate `SYM`, all API URLs derived from `SYM`; backend
per-symbol feeds/locks verified independent (Phase 11 tests + Phase 12
API independence test).

## Options-data boundary

No strikes/premiums/IV/OI/PCR/expiry/legs anywhere (statically scanned).
Persistent notice: "Options data unavailable — any qualified setup above is
an index-price setup, not a validated options trade." Phase 12 explicitly
does NOT add real options data.

## Tests / validation

`tests/test_phase12.py` 18 tests (page contracts, isolation, read-only,
state coverage, no-fabrication, completed-candle endpoint, freshness
display, blink guards, nav, no-JS-business-logic). HTML parsed +
`node --check` clean. Full suite + PIT baselines + research isolation in the
Phase 12 validation pass. Production: webroot redeployed (backup taken),
HTTPS 200s, API live.

## Known limitations

No device-lab mobile screenshots; no console-error capture (no headless
browser on VM — mitigated by parse + syntax checks); structure section
limited to backend-provided fields (no VWAP/ATR/supports — not in live API);
special NSE sessions unmodeled (Phase 11); index/backtest/methodology pages
unchanged.
