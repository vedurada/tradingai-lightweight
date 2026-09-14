# Track C — Audit (read-only, no fixes, no commits)

**Method**: live-URL probes (status/body), sitemap crawl (37 URLs, all 200),
55-link internal integrity check, inbound-link graph, per-familysnippet checks.
Local repo + VM untouched. Backend frozen, not examined beyond prior findings.

## C1 — Soft-404 (confirmed, site-wide)

`/{anything}.html` → **200 with full index content** (25,402 bytes) via
`try_files … /index.html`. Probed: no-such-page, foo/bar, old-page (all 200-as-index).
`indices/market.html` correctly 301s (ghost-path guard intact).
Impact: crawl-budget waste, soft-404 dilution, confusing AdSense review.
Fix direction: 404 status for unmatched `.html` (keep guard redirects).

## C2 — SSR/hydration placeholders (confirmed, all families)

Raw-HTML placeholder counts: backtest ~108, today ~29, scanner ~28,
strategies ~26, market/stock ~7. `/api/market`, `/api/outlook/<symbol>`,
`/api/strategies` all live — data exists, crawlers just never see it.
Fix direction: SSR/pre-render snapshot or server-filled first paint (Track C spec).

## C3 — `{}` empty-payload guard (confirmed gap)

Only `ai-outlook.js` has a no-data branch and it tests `!outlook || outlook.error`;
`"{}"` is truthy → renders empty sections. FINNIFTY live proof.
Fix direction: presentation-layer empty-object detection (no engine change).

## C4 — FINNIFTY presentation vs starvation (split confirmed)

Presentation (Track C): no static FINNIFTY snapshot card; JS tabs cover it.
Starvation (deferred engine diagnosis, NOT Track C): `/api/outlook/FINNIFTY` →
`"outlook":"{}"`, 8 rows vs 2612. Do not patch generator without boundary audit.

## C5 — Editorial: Max Pain (confirmed as quoted)

Causal "gravitate … as market makers hedge" framing stands as reported.
Fix direction: observational rewrite in Track C content pass.

## C6 — Canonical/duplicates (mostly healthy, one note)

37/37 sitemap URLs 200; 55/55 internal links resolve (earlier `/../` 400s were a
checker artifact — proper resolution passes). Titles/H1/meta-descriptions present
on all sampled pages. Canonical tags live site-wide. Note: `/` vs `/index.html`
duality — homepage canonical self-points to `/`; verify `/index.html` canonical
target in spec (single canonical preferred).

## C7 — FAQ staleness (uncorroborated)

No FAQ block found on 7 candidate live pages (index, guide, backtest, learn,
queries, history, portfolio) nor in repo. The reported 2026-05-08 FAQ does not
match current surfaces — could be stale cache or removed page. Recommend one
targeted re-check with URL before scoping content work.

## C8 — home.html (closed, superseded)

Does not exist (repo, webroot, disk). `/home.html` → byte-identical index
(md5 `c37c355f…`) via fallback. No legacy surface, no redirect needed.

## C9 — AdSense/consent/trust per family (healthy)

Spot-checked 5 families: AdSense + consent.js + GA + viewport on all;
disclaimers present (learn explicit educational; market/others risk-text in
footer; generated pages carry injected trust headers). No family missing the
Track B plumbing.

## C10 — Mobile (static signals only)

Viewport meta on all sampled pages; no blocking errors observable statically.
Real tap-target/responsive check needs device rendering — flag for spec stage.

## Proposed Track C scope (for approval, not started)

S1 soft-404 handling · S2 hydration/SSR-first-paint · S3 `{}` guards ·
S4 FINNIFTY presentation (not generator) · S5 Max Pain rewrite ·
S6 canonical `/` vs `/index.html` single-source · S7 FAQ re-check + freshness ·
S8 footer-disclaimer standardization · S9 mobile rendering pass.

---

🛑 **STOP — audit only. No fixes, no commits. Awaiting scope approval.**
