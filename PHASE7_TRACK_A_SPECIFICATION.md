# PHASE 7 Track A — Specification (Security Hardening)

**Status**: 🟡 SPECIFICATION — no implementation authorized.

**Baseline**: `8c9faff` 🔒. Authorization: `PHASE7_AUTHORIZATION.md` (Track A scope only).

**Global constraints**: 0/8 model files · no engine/confidence/threshold/backtest changes ·
degradation semantics preserved · 469-test baseline green throughout.

---

## A1 — Nginx security-header inheritance (R1)

**Current state**: server block sets 4 headers (`ops/nginx-tradingai.conf:31-34`); five
locations define their own `add_header` (`:40-44, :46-50, :52-57, :89-98, :99-113`) and therefore
drop all four server-level headers on API/cached/static responses.

**Change**:
1. New `ops/nginx-snippets/tradingai-security-headers.conf` containing exactly the four
   header lines (nosniff, SAMEORIGIN, XSS-Protection, Referrer-Policy).
2. Server block: replace the four inline lines with `include snippets/tradingai-security-headers.conf;`.
3. Every location block that defines its own `add_header` gains the same `include` line.
4. Deploy: copy the snippet to `/etc/nginx/snippets/` before the existing nginx-guard
   sync; guard unchanged otherwise (`nginx -t` stays loud).

**Files**: `ops/nginx-tradingai.conf`, `ops/nginx-snippets/tradingai-security-headers.conf` (new), `deploy-vm.sh` (snippet install).

**Tests** (2): snippet included in server block + every self-headered location (config-content test);
`nginx -T` dump contains all four headers per location (VM validation, documented).

## A2 — Chat alert auth-gating (R2)

**Current state**: `POST` chat handler (`api_server.py:2385+`) accepts `kind` in
(`user`,`system`,`alert`) from anyone; `kind:"alert"` rows render as AI ALERT toasts.

**Change**: after kind validation, if `kind in ("system", "alert")`, require the same
`_check_auth()` Bearer check as portfolio endpoints; failure → identical 401 envelope
(no new error shapes). `kind:"user"` stays unauthenticated (existing 8/min limiter unchanged).
Field preserved per authorization (legitimate authenticated use retained).

**Files**: `backend/api_server.py` (handler only).

**Tests** (3): unauthenticated `alert` → 401; authenticated `alert` → stored; unauthenticated
`user` → stored (no regression).

## A3 — HSTS (R3)

**Current state**: http→https redirect present; no `Strict-Transport-Security` anywhere.

**Change**: add `add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;`
to the 443 server block **via the A1 snippet mechanism** (so it inherits into locations correctly
and never touches the port-80 block). Also add `server_tokens off;` to the 443 server block.
Explicitly out: CSP (needs product-side inline-script audit — not authorized here).

**Files**: `ops/nginx-snippets/tradingai-security-headers.conf`, `ops/nginx-tradingai.conf`.

**Tests** (1): config-content test for HSTS line + 443-only placement.

## A4 — Metrics lockdown

**Current state**: `/api/metrics` (`api_server.py:249`) is limiter-exempt and public, exposing
counts/latency/breaker state (recon aid).

**Change**: localhost (`127.0.0.1`, `::1`) stays open (self-heal/monitor/scripts); any other
`remote_addr` must pass `_check_auth()` (same 401 envelope). Limiter-exempt retained for
local observers.

**Files**: `backend/api_server.py` (metrics handler only).

**Tests** (2): local 200; remote-without-key 401 (via `environ_base REMOTE_ADDR`).

## A5 — CORS tightening

**Current state**: methods omit DELETE (legit cross-origin portfolio DELETE preflights fail);
prod runs localhost-inclusive defaults because the unit sets no `TRADINGAI_CORS_ORIGINS`.

**Change**: methods += `DELETE`; systemd unit sets
`TRADINGAI_CORS_ORIGINS=https://tradingai.in,https://www.tradingai.in`; implementation must
first verify no frontend `fetch(..., {credentials:...})` relies on `supports_credentials`
(chat.js/portfolio calls) — if clean, set `supports_credentials=False`, else keep True with
a code comment and defer to Track B product work.

**Files**: `backend/api_server.py` (methods flag), `ops/systemd/tradingai-api.service` (env).

**Tests** (2): DELETE in methods list; unit file pins prod origins.

## A6 — Key-lifecycle operability

**Current state**: issuance/verify/revoke exist in `backend/auth.py` (local-call only); no CLI,
no documented rotation.

**Change**: `python3 backend/auth.py` CLI with `list` (prefix-only output, never hashes),
`revoke <key-prefix>`, plus `ops/KEY_MANAGEMENT.md` documenting issue → distribute →
rotate (dual-active grace: issue new, verify, revoke old) → revoke. No new HTTP endpoints
(no new attack surface).

**Files**: `backend/auth.py` (CLI only), `ops/KEY_MANAGEMENT.md` (new).

**Tests** (2): CLI issue→verify→revoke round-trip on temp DB; prefix-only listing leaks no hash.

---

## Test & acceptance plan

- New tests: ~14. Total target ≈ 483 green locally + full VM suite green after deploy.
- Live VM validation: header presence per path (`curl -sI`), HSTS on 443 only, metrics 401
  remotely, chat spoof blocked, `nginx -t` clean, public 200.
- Boundaries verified: 0/8 model files vs `8c9faff`/`45f90fc`; degradation-label tests green.

## Explicit non-goals

CSP · CSRF tokens (residual LOW, no sessions) · Sentry · staging · vault · any new endpoint
beyond none (A6 is CLI/docs only) · any model/analytical change.

---

🛑 **STOP — Specification complete. No implementation authorized. Next: Track A Authorization.**
