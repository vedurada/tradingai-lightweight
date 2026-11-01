# Phase 5.7 — Data Source Options

## Current: yfinance (5-min polling)

| Property | Value |
|----------|-------|
| Provider | yfinance (Yahoo Finance) |
| Cadence | 5-min timer (RandomizedDelaySec=20) |
| Candle completion | Server-side (yfinance provides completed bars) |
| Ingestion delay | ~9s median, ~79s P95, ~86s max |
| Cost | Free |
| Historical consistency | Good (10-day backfill per run) |
| Failure behavior | Retry on next 5-min poll |
| Changes required | None |
| Guard enforcement | Unchanged (completed candles only) |

**Assessment:** Sufficient for 5-minute entry window. No change needed.

## Alternative 1: WebSocket (e.g., Zerodha Kite, Upstox)

| Property | Value |
|----------|-------|
| Expected freshness | ~1-3s |
| Candle trust | Medium (forming candles, must detect completion) |
| Historical consistency | Requires reconciliation with REST API |
| Failure behavior | Reconnect + backfill gap |
| Cost | Paid license (Zerodha: ~Rs 2000/month for API) |
| Changes required | Major: new provider, candle builder, completion detection |
| Guard enforcement | Must enforce candle completion (not forming) |

**Assessment:** Would improve latency but adds complexity. Not needed for current 5-min window. Requires licensing verification.

## Alternative 2: NSE Direct API

| Property | Value |
|----------|-------|
| Expected freshness | ~5-15s |
| Candle trust | High (completed only) |
| Historical consistency | Good |
| Failure behavior | Retry on next poll |
| Cost | Free (rate-limited) |
| Changes required | Moderate: new provider adapter |
| Guard enforcement | Unchanged |

**Assessment:** Marginal improvement over yfinance. NSE API rate limits may be restrictive. Requires verification of terms of use.

## Alternative 3: TradingView Webhook

| Property | Value |
|----------|-------|
| Expected freshness | ~1-5s |
| Candle trust | Medium (real-time, may include forming) |
| Historical consistency | Requires reconciliation |
| Failure behavior | Webhook reliability concerns |
| Cost | Paid (TradingView Premium) |
| Changes required | Major: webhook receiver, candle builder, infrastructure |
| Guard enforcement | Must enforce candle completion |

**Assessment:** Real-time but adds infrastructure complexity. Not needed for current requirements.

## Recommendation

**No change recommended.** Current yfinance provider achieves ~9s median, ~79s P95 ingestion delay, well within the 5-minute entry window. The cost and complexity of alternatives is not justified by the current requirements.

If sub-10-second latency becomes a requirement in the future, evaluate WebSocket (Alternative 1) with proper licensing verification.
