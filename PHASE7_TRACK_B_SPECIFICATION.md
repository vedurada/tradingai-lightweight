# PHASE 7 Track B — Specification (Product / AdSense Readiness)

**Status**: 🟡 SPECIFICATION — implementation NOT authorized.

**Baseline**: Track A frozen `3d4f7ca` 🔒. Approved scope: B-G1…B-G7 (audit).
**Boundary**: 0/8 model files byte-identical; no signal/strategy/confidence/backtest changes.
If any item below requires touching a model file → STOP, request boundary-change audit.

**Publisher ID**: `ca-pub-2262405054444130` (already deployed site-wide via auto-ads).

---

## B1 — `ads.txt` (B-G1)

- New file `ads.txt` at webroot root with single line:
  `google.com, pub-2262405054444130, DIRECT, f08c47fec0942fa0`
- Acceptance: `https://tradingai.in/ads.txt` returns 200 text/plain with that line;
  no nginx rule blocks it (confirm no `location` intercept; static serve like `robots.txt`).
- Verify: curl status + body match; AdSense account "Sites → ads.txt status" when available.

## B2 — Cookie consent (B-G2)

- New lightweight first-party banner (`assets/js/consent.js` + inline CSS in a shared
  footer include or per-page snippet): on first visit shows Accept / Reject / (link to privacy).
- Consent stored in `localStorage` (`tai_consent` = `granted|denied` + timestamp);
  banner hidden on subsequent loads; "Cookie settings" link in footer re-opens it.
- On `denied`: request non-personalised ads (`(adsbygoogle=window.adsbygoogle||[]).requestNonPersonalizedAds=1`
  before ad calls) and set Google consent-mode defaults to denied
  (`gtag('consent','default',{ad_storage:'denied',analytics_storage:'denied'})` if gtag present).
- No third-party CMP dependency; no cookies set by the banner itself.
- Acceptance: fresh-profile load shows banner; Accept/Reject persists across reload;
  denied mode sets the non-personalised flag (assertable in DOM/unit test via jsdom-less string checks).

## B3 — Privacy disclosure (B-G3)

- Edit `privacy.html` only:
  - Replace the false statement "No ad partner is currently active on the site"
    with active-voice disclosure: Google AdSense IS serving ads (pub-2262405054444130),
    uses cookies/device identifiers, personalised vs non-personalised per consent region,
    links to Google Privacy Policy + Ads Settings + "About Google ads" opt-out.
  - Add explicit "Google advertising cookies (_gads/_gac/DART-related)" subsection.
- Acceptance: no remaining "no ad partner" wording; AdSense + pub-ID + cookie names +
  opt-out links all present (grep-asserted in tests).

## B4 — Navigation consistency (B-G4)

- Edit `strategies.html` footer only: add the standard link row used by `index.html`:
  About · Contact · Privacy · Terms · Disclaimer · Sitemap (same hrefs).
- Acceptance: `strategies.html` contains `contact.html` link; footer link-set identical
  (modulo page-specific extra links) across all root pages — test loops all `*.html`.

## B5 — Ad-placement guardrails (B-G5)

- New doc `ops/AD_PLACEMENT_POLICY.md`: auto-ads only; forbidden zones —
  within 150px of trade CTAs / chat send / strategy "Open" buttons; no ads inside
  `<form>`, no sticky bottom on screens with fixed CTA bars; layout-shift budget noted.
- Technical: add `data-adbreak-test` free CSS guard — `ins.adsbygoogle` gets
  `margin-top:24px` separation from `.cta-row` / `button` via one shared rule in the
  existing site stylesheet (no new render-blocking file).
- Acceptance: policy doc exists; separation rule present; manual screenshot check deferred
  to VM validation (noted, not automated).

## B6 — Content trust headers (B-G6)

- **Constraint**: `backend/outlook.py` is FROZEN — generator untouched.
- New injector `ops/inject_trust_headers.py` (stdlib only): for each
  `market/outlook-*.html` + `queries/index.html`, inserts (if absent) into `<head>`/body-top:
  `<meta name="author" content="TradingAI.in">`, visible byline block with
  publication date (parsed from filename/title), "Updated" stamp, and the standard
  educational-purpose disclaimer paragraph. Idempotent; dry-run mode; logs patched files.
- Run injector over existing generated pages as part of implementation; wire into the
  daily outlook cron AFTER generation (crontab line append, generation command unchanged).
- Acceptance: every `market/outlook-*.html` contains author meta + byline + date +
  disclaimer (test scans files); `backend/outlook.py` byte-identical to freeze (hash check in test).

## B7 — Ownership / author identity (B-G7)

- Edit `about.html` only: add named operator/editor block (name, role, contact email
  matching `contact.html`), "How content is produced" paragraph (data sources → engine →
  human review note), last-reviewed date.
- Edit `contact.html` only if email missing: ensure a reachable address is present.
- Acceptance: about page contains operator name + email + methodology paragraph (grep-asserted).

## Cross-cutting guards

- Files touched: `ads.txt` (new), `privacy.html`, `strategies.html`, `about.html`,
  (`contact.html` if needed), `ops/inject_trust_headers.py` + `ops/AD_PLACEMENT_POLICY.md`
  (new), shared CSS rule, `assets/js/consent.js` (new), `ops/crontab.txt` (one append line).
- Forbidden: any `backend/*.py` except NONE (injector lives in `ops/`); no API changes;
  no nginx changes expected (verify ads.txt serves under existing static handling).
- Tests: new `tests/test_phase7_track_b.py` — file/content assertions only (no engine tests);
  full suite must remain 483 + new B tests green; model-hash guard for `outlook.py` + 0/8 diff check.

---

🛑 **STOP — specification complete. Implementation NOT authorized; awaiting GO-AHEAD.**
