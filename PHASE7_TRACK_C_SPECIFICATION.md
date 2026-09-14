# PHASE 7 Track C — Specification (Intelligence Presentation)

**Status**: 🟡 SPECIFICATION — implementation NOT authorized.

**Baseline**: Track B LIVE `578384f` + P1 `5280b03f` 🔒. Audit: `PHASE7_TRACK_C_AUDIT.md`.
**Boundary**: presentation/webroot/nginx/frontend/SEO only. Zero changes to
`backend/*.py`, APIs, Track A/B engines, confidence math, thresholds, strategy or
options logic, backtest. FINNIFTY starvation (S5): diagnose only — any generator
change needs a separate boundary-change audit. Order: S1 → S3 → S4 → S6 → S7 →
S2 → S8 → S9, S5 independent.

---

## S1 — Soft-404 for unmatched `.html` (HIGH)

- `ops/nginx-tradingai.conf`: add above `location /` (exact-match ghost guard at
  `= /indices/market.html` keeps precedence — verify in test):
  `location ~* \.html$ { try_files $uri =404; <same no-store + headers + snippet> }`
  plus `error_page 404 /404.html;` in the 443 server block.
- New webroot `404.html`: branded "Page not found", links (Home/Market/Learn/Contact),
  site search hint if present, NO market numbers, NO ad-slot stuffing, returns 404.
- Keep: ghost 301, extensionless fallback, `/` → 200.
- Acceptance: `/no-such.html` → 404 + 404.html body; `/indices/market.html` → 301;
  every sitemap URL still 200; `nginx -t` passes (test asserts config text + live codes post-deploy).

## S2 — Pre-rendered first paint (HIGH)

- New `ops/prerender_snapshot.py` (stdlib; idempotent; `--dry-run`): fetches local
  `/api/market` (+ quote endpoints already used by pages) and injects values into
  known snapshot ids (`s-{nifty,banknifty,sensex,finnifty}-{price,trend,vix}`,
  `market-grid` server fallback block, `outlook-content` summary) with a
  `data-prerendered="{ts}"` marker + visible "Data as of … IST" stamp.
- Run at deploy (extend webroot sync step, append-only lines) + weekdaily cron AFTER
  outlook generation (same pattern as trust injector).
- JS keeps live-refreshing on top; if fetch fails, prerendered values stay (never
  blank to N/A on failure — show staleness stamp instead).
- Acceptance: raw HTML of index/market contains digits (not `—`/`N/A`) in snapshot
  ids; `data-prerendered` present; JS-overwrite still works (existing tests + new asserts).

## S3 — `{}` empty-payload guard (HIGH)

- `static/js/ai-outlook.js`: add `isEmptyOutlook(o)` — true when o is falsy,
  `o.error`, empty string, `"{}"`, or parsed object with zero keys; route all three
  cases into the existing red no-data branch ("No AI Market Outlook data available
  for X"). Apply at every outlook-consumer branch in the file (audit lists one;
  implementation must cover all fetchers in the bundle).
- Acceptance: Node DOM-stub harness executes accept/empty/invalid cases
  (pattern proven in Track B review); FINNIFTY tab shows the no-data message
  instead of empty sections.

## S4 — FINNIFTY presentation parity (presentation only)

- `index.html`: add static FINNIFTY snapshot card mirroring the NIFTY/BANKNIFTY/SENSEX
  trio (`s-finnifty-price/trend/vix`), fed by S2 prerender + existing dashboard path
  (`/api/market` instruments already include FINNIFTY — verified live).
- If the outlook payload is empty, the card/tab shows DATA UNAVAILABLE state —
  never fabricated values.
- Acceptance: card present in raw HTML; populated post-hydration; empty-state path
  covered by S3 tests.

## S5 — FINNIFTY starvation diagnosis (DIAGNOSE ONLY)

Read-only: row counts per symbol, generator logs (`logs/outlook.log`), input
availability (options chain/indicators for FINNIFTY), generation path for the 8 rows.
Deliverable: diagnosis note. 🛑 No backend/generator/cron-query changes.

## S6 — Max Pain rewrite (editorial, index.html:221)

Replace the causal sentence with observational framing:
"Max Pain is a theoretical expiry reference derived from option open interest.
Some traders watch it as a possible magnet level, but there is no reliable
evidence that price converges to it; treat it as context, not a forecast."
Acceptance: grep-assert new wording, no "gravitate … hedge" remains.

## S7 — Canonical single-source (lock-in)

Verified live: `/` and `/index.html` both canonicalize to `https://tradingai.in/`.
No change needed — add regression test asserting both canonical targets (fail on drift).

## S8 — Mobile acceptance criteria (spec + test only here)

Real-device validation required at implementation review: 360×640 + 390×844 +
tablet widths; no horizontal scroll; tap targets ≥44px on CTAs/nav/tabs;
consent banner usable without covering CTAs; snapshot cards stack legibly;
ad slots never overlap interactive elements. Criteria live here; verdict at review.

## S9 — Visual hierarchy (presentation-only)

Order enforced on outlook sections: regime → confidence → key levels → options
intelligence → strategy → AI explanation → invalidation (always visible, never
below fold-dependent lazy blocks). No numbers/logic changes — DOM order + CSS only.

## Cross-cutting guards

- Touch list: `index.html`, other webroot HTML (S2 markers/S4 card), `static/js/*.js`
  (presentation only), `ops/prerender_snapshot.py` + `ops/AD_*`-style docs (new),
  `404.html` (new), `ops/nginx-tradingai.conf` (S1 only), deploy sync/cron appends.
- Forbidden: `backend/**`, API semantics, Track A/B logic, AdSense/consent behavior
  changes (S8/S9 must not move ad or consent controls).
- Tests: extend `tests/test_phase7_track_*.py` family with `test_phase7_track_c.py` —
  raw-HTML asserts, nginx-config asserts, Node harness for S3, canonical lock,
  model-hash guard (`outlook.py` + 0/8 diff, same as Track B).

---

🛑 **STOP — specification complete. Implementation NOT authorized; awaiting GO-AHEAD.**
