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
