# PHASE 7 — Scope Review / Production Readiness Gap Audit

**Status**: 🟡 REVIEW — read-only audit. No code changes made or authorized.

**Position**: `45f90fc` 🔒 → `d4990e4` 🔒 → `4b7260f` 🔒 → `8c9faff` 🔒 (469 tests, live-validated).

**Method**: three independent read-only audits (code remainder, security posture, product
surface) reconciled against B.1–B.6 evidence. Findings below are `file:line`-grounded.

---

## Q1 — Is TradingAI.in technically safe enough for sustained public usage?

**Verdict: YES, with bounded hardening recommended. Nothing requires rollback or downtime.**

- Reliability core (B.1–B.6) verified present: pooling, caching, breakers, timeouts (sync workers),
  deep health, backup verify, deploy gates. Live: `all_healthy: true`, public 200.
- Security controls verified present: rate limits, CORS allowlist, portfolio Bearer auth,
  input validation, sql_guard, 1MB body cap, security headers at server level.
- Residual risk concentrates in **missing/absorbed hardening** (HSTS, CSP, nginx header
  inheritance, chat alert-spoofing), not in structural flaws. All fixable without architecture change.

## Q2 — Remaining weaknesses that could materially affect users?

### 🔴 Genuine production risks

| # | Risk | Evidence | User impact |
|---|---|---|---|
| R1 | nginx `add_header` inheritance loss: API/cached/static responses ship **without** nosniff/SAMEORIGIN/Referrer-Policy | `ops/nginx-tradingai.conf:40-44,46-50,52-57,89-98,106-113` set their own headers | Weakened XSS/clickjacking posture on exactly the public paths |
| R2 | Unauthenticated chat alert/system spoofing: anyone can POST `kind:"alert"` rows surfaced as "AI ALERT" toasts | `api_server.py:2391-2393,2405,2437-2443`, `static/js/chat.js:159-175` | Phishing/scare content under product branding |
| R3 | No HSTS | absent from `ops/nginx-tradingai.conf` | First-visit SSL-strip despite the http→https redirect |
| R4 | Silent-staleness misread: prolonged outage serves days-old data with correct-but-subtle flags; no max-age cutoff, no STALE banner in UI, crawlers see `—` | `api_server.py:592-609`, `ai-outlook.js:539-545` | Users may act on stale intelligence believing it live |
| R5 | Options-intelligence confirmation from defaults: `mkt_bias/conf` defaults survive `except: pass`, emitting CONFIRMED/DIVERGENCE from a synthetic side | `api_server.py:1541-1542,1552-1553` | False analytical confidence signal — the single most user-harmful code finding |

### 🟠 Useful improvements (real value, not urgent)

- Options-intel uncached N+1 per-expiry loops (`api_server.py:1429-1482`); `/api/global` has no fallback (`2173-2175`); expiry-parse 500 on third date format (`options.py:158-161`); error-500s uncached → thundering-herd on outage (`cache_page:470,475`).
- Fetcher retries missing for bhavcopy/nse_fo/fo_fetcher (transient NSE blip = lost EOD day).
- `/api/metrics` limiter-exempt + verbose (recon aid); CORS methods omit DELETE while `supports_credentials` + permissive defaults ship to prod.
- Key lifecycle: no rotation/expiry/revocation API; `verify_api_key` full-table scan.
- SEO: `sitemap.xml` stale (37 vs 41 URLs, no `<lastmod>`); indexnow never fired from cron; no `og:image`; `Article` missing dates; duplicate daily slug series (`daily_page` vs `outlook.py`).
- AdSense: `ads.txt` missing (blocker); zero reserved slots; loader fires on legal pages; `privacy §3` disclosure false once ads ship; thin publisher identity for YMYL.
- UX: no age-threshold STALE banner; weekend renders honest-but-empty; fully client-rendered (crawlers see `—`).

### 🟢 Already solved (no action)

Pooling/caching/async-backtest/breakers/sync timeouts/deep health/backup verify/deploy gates (B.1–B.6);
portfolio auth + validation; VIX/options isolation; WAL; logrotate; CORS allowlist; rate limits;
robots/sitemap base, meta/OG/canonical, JSON-LD base, legal pages real (not stubs), mobile/responsive,
cron freshness loop.

### ⏸️ Intentionally deferred (stay deferred)

CSRF tokens (honest residual LOW — Bearer headers aren't auto-sent; no cookies/sessions exist);
staging VM, Sentry, second provider (infra/vendor decisions); request queuing, `_symbol_data`
purity (complexity without production need); secrets vault (600-perms sufficient single-VM).

## Q3 — Highest product value per engineering risk?

1. **Security-hardening batch (R1, R2, R3 + metrics lockdown)** — config + tiny code, S. Fixes the only HIGH-adjacent items. R2 needs a product call: auth-gate alert/system kinds vs remove the kind field.
2. **AdSense unblock (ads.txt + reserved slots + legal-page suppression + privacy correction)** — S, revenue-gating.
3. **Staleness honesty (STALE banner + `Data as of` + max-age cutoff policy)** — S/M, directly serves trustworthiness.
4. **Options-intel correctness (R5 defaults + caching + expiry-parse guard)** — S/M, removes false-confidence signal. NOTE: touches `options.py`/`api_server.py` only — analytical engines stay frozen, but needs explicit model-boundary wording in spec (no threshold/confidence changes).
5. **Discoverability (sitemap resync + indexnow cron hook + og:image + slug dedup)** — S.
6. **Fetcher retries + `/api/global` fallback + cache error-shape** — S/M reliability.

---

## Recommended Phase 7 shape (for approval, not authorization)

**PHASE 7 — Trust & Product Readiness**: three tracks, each independently shippable,
each ≤ B.5-sized, all subject to the usual 0/8-model boundary:

- **Track A — Security hardening** (R1 header inheritance, R2 chat spoofing, R3 HSTS,
  metrics lockdown, CORS tightening, key-lifecycle docs/endpoints).
- **Track B — Product readiness** (ads.txt/slots/legal, sitemap+indexnow, og:image/dates,
  slug dedup, STALE banner + as-of, publisher identity).
- **Track C — Intelligence reliability** (R5 defaults fix, options-intel cache + parse guard,
  fetcher retries, global fallback, thundering-herd cache rule).

**Needed first**: your approval of (a) whether Phase 7 proceeds at all, (b) track selection
(all three vs subset), (c) the R2 product call (auth-gate vs remove-kind), (d) confirmation
that Track C's options-intel work may touch `options.py`/`api_server.py` presentation paths
under the frozen-engine boundary.

## Protected boundaries (any Phase 7 must preserve)

`45f90fc` · `d4990e4` · `4b7260f` · `8c9faff` · 0/8 model files · no Regime/Strategy/Options
engine changes · no confidence/threshold/backtest/analytical-output changes · degradation
semantics preserved · 469-test baseline green throughout.

## Lifecycle

Audit (this doc) → **STOP → Approval of scope/tracks** → Specification → STOP →
Authorization → Implementation → Acceptance → Independent Review → Freeze.

---

🛑 **STOP — audit complete. No specification, no implementation. Awaiting your decisions
on Phase 7 necessity, track selection, the R2 product call, and the Track C boundary confirmation.**
