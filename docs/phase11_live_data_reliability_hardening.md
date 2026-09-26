# Phase 11 — Live Data Reliability & Market Session Hardening

## 1. Current provider architecture (audited before change)

- yfinance `^NSEI` / `^NSEBANK`, fetched **on demand per API request**:
  `GET /summary` → `get_quote`, `GET /decision` → quote + candles via
  LiveEngine. No cache, no retry, no timeout (installed yfinance 0.2.66
  `history()` has no timeout parameter), failures → generic API_ERROR.
- Multiplication factor: 2 gunicorn workers × N browsers × (30s price +
  120s decision polls) = every poll hit yfinance independently.
- No collector daemon or cron fetcher exists (only a health-curl guard).

## 2. Fetch frequency

Unchanged call sites; upstream volume now bounded by the shared cache:
quotes ≤1 upstream hit / 45s / symbol across all workers+browsers; candles
≤1 / 90s / symbol. Cache is read-through SQLite (`provider_cache`), so it is
shared across workers (an in-process dict would not be).

## 3. Caching

`app/market/cache.py`: key `(symbol, kind)`; stores payload JSON + original
`data_ts` + `fetch_ts` + state. Hits return the stored payload with the
**original market-data timestamp preserved**; quote `age_seconds` is
recomputed at serve time, so cached data can never masquerade as fresh.
Freshness is always derived downstream from `data_ts`. TTLs: quote 45s,
candles 90s. No Redis/new infra.

## 4. Freshness

15-minute threshold preserved (`STALE_AFTER_MIN = 15`). Dead feed (today's
newest row older than 15 min) → `STALE`/`FEED_STALE`; absent data →
`NO_DATA`; neither carries a trade object. Stale is never coerced.

## 5. Candle completion

Unchanged Phase 9 contract: timestamp == candle OPEN (+05:30),
`completed(T) = floor_5m(T−5m)`; provider flags only fully-closed candles
`is_complete`. Forming candle never decision-eligible (double-gated).

## 6. Market calendar

`app/market/calendar.py`: explicit NSE 2026 weekday-holiday table (15 dates,
source NSE circular CMTR71775 + nseindia.com) + weekend rule, no new
dependency. Holiday in-hours without data → `MARKET_CLOSED` with
`HOLIDAY_<name>` reason (verified: 2026-09-14 Ganesh Chaturthi; dataset
consistently has no 09-14 candles). Weekends → distinct `WEEKEND` state.
Limitation: special sessions (Budget Sunday 2026-02-01, Muhurat) not modeled;
out-of-table years fall back to weekday rule, with absent data still gating
to NO_DATA/MARKET_CLOSED (never a trade).

## 7. Failure states

LIVE / STALE / NO_DATA / PREMARKET / MARKET_CLOSED / WEEKEND / NO_TRADE /
QUALIFIED (+ RATE_LIMITED/UNAVAILABLE/API_ERROR at provider level, all
mapping to no-trade). Per-instrument isolation: NIFTY data never substitutes
for BANKNIFTY. Retry: 12s executor timeout, exactly 1 retry, no sleep loops;
HTTP 429 → RATE_LIMITED. Final failure deterministic.

## 8. Concurrency

One-trade/day preserved (`instrument + trade_date`, DB UNIQUE). 8-thread
parallel claim test: ≤1 trade row, ≤1 lock row, losers get
`DAILY_TRADE_LIMIT_REACHED`, zero exceptions (sentinel day fully cleaned).

## 9. GET/POST separation

**Fixed the Phase 9 concern**: `GET /api/<sym>/decision` is now strictly
read-only (`dry_run=True`, zero DB writes — 5 rapid polls verified
(0,0,0)). `POST /api/<sym>/decision/claim` (5/min) is the sole explicit
state-changing operation, idempotent per day. The frontend polls GET only
and never claims. Full audit + test: `test_get_decision_read_only`.

## 10. Live dry-run

Sunday execution → `LIVE MARKET SESSION TEST = NOT AVAILABLE`. Deterministic
matrix instead (freshness/session/holiday/weekend probes all PASS) + real
dry-run binary (MARKET_CLOSED, zero writes, honest quote ages).

## 11. Resource usage

956MB VM; gunicorn ~100MB/worker; DB ~10.5MB + small cache table; logs
change-only (no 30s spam). No new services.

## 12. Limitations (carried + new)

No real options data; no cost model; fills unvalidated; 39-session sample;
non-Q3 regimes unvalidated; yfinance rate limits apply; special NSE sessions
unmodeled; no future-performance claims. PIT baselines unchanged: NIFTY
34/+16.21R, BANKNIFTY 31/+16.63R (regression-gated).
