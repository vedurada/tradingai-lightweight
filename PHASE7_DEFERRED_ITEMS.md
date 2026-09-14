# Phase 7 — Deferred Follow-ups (logged at Track B LIVE acceptance)

Neither item reopens Track A/B freezes. Both need separate authorization.

## D1 — Market-page trust-header coverage

`ops/inject_trust_headers.py` targets `market/outlook-*.html` + `queries/index.html`.
The `market/nifty-close-*.html` family (daily_page output) is not covered.
Options when authorized: extend injector glob + tests, or scoped one-shot patch.
No production modification until then.

## D2 — `deploy-vm.sh` cron-generation bug (line 64)
Rebuild filter omits `cleanup.sh`/headers (duplicates accumulate) and a missing
separator glues the aggregate-sweep echo onto the self-heal line. VM crontab is
currently correct (26 lines, backup `/tmp/crontab.bak.20260914` preserved through
verification window); the *source* fix is deferred so the Track B release stays
reproducible. Do not silently fix during future deployments — separate commit.

## D3 — FINNIFTY empty outlook (Track C S5 diagnosis, 2026-09-14)

`/api/outlook/FINNIFTY` serves `"outlook":"{}"` from table `ai_outlooks`
(LLM-summary layer), whose latest FINNIFTY rows have length 2 while all other
symbols carry full payloads. The deterministic generator table
(`market_outlooks`) DOES hold full FINNIFTY outlooks (incl. today: ~5KB, regime
NEUTRAL/RANGE) — but only 8 FINNIFTY rows vs 2612 for NIFTY (scheduling skew).
So: generator output exists, summarizer output is empty, API serves the latter.
Any fix touches frozen backend/generator → requires a separate boundary-change
audit. Track C only improves the empty-state presentation (S3/S4 guards).
