# Live-Site Bug Audit — index.html (read-only, no changes made)

**Source**: fetched live HTML + live API probes + repo JS/backend reads. No production writes.

## P1 — OI support/resistance wording is reversed (copy only)

Live copy: *"marking support (call concentration) and resistance (put concentration)"*.
Standard interpretation (and the engine's own usage): heavy **Call** OI → resistance,
heavy **Put** OI → support. Verified the engine does NOT share this error —
`backend/outlook.py` reports raw `ce_wall` strikes + call/put OI with no
support/resistance labels (`grep support|resistance backend/options.py` → empty).
**Fix when authorized**: editorial, index.html only. Teaches the wrong lesson until fixed.

## P1 — Homepage shows N/A/— pre-hydration (SEO/AdSense quality)

Snapshot cards (`s-nifty-price` etc.), outlook, strategy, options sections all render
`—`/`N/A` in raw HTML; values hydrate via `dashboard.js` ← `/api/market` (verified
live, returning NIFTY data). Not a data outage — but crawlers, previews, no-JS and
slow clients see an empty intelligence page. Candidate fixes (SSR/pre-render or
server-filled snapshot) are post-freeze product work → Track C input.

## P2 — FINNIFTY gap is twofold

(a) No static FINNIFTY snapshot card (only NIFTY/BANKNIFTY/SENSEX); the tabbed
outlook section covers FINNIFTY via JS only. (b) Worse: live
`/api/outlook/FINNIFTY` returns `"outlook":"{}"` — EMPTY payload, quality GOOD.
DB: FINNIFTY has 8 outlook rows vs 2612 for NIFTY/BANKNIFTY/SENSEX; today's row
exists but is empty. Generator starvation — backend behavior, frozen, diagnose-only.
JS guard (`!outlook || outlook.error`) does NOT catch `"{}"` (truthy) → renders
empty sections instead of the no-data message.

## P2 — Max Pain wording overstates causality

*"tends to gravitate toward Max Pain near expiry as market makers hedge"* —
presents a contested heuristic as a causal tendency. Editorial review; soften to
observational framing.

## Non-issues cleared

- `/api/market`, `/api/outlook/<symbol>` (path-param form), `/api/strategies` all live.
- FINNIFTY mentions (6×) are meta/prose only — consistent with no-card finding.
- Consent/GA/ads.txt verified live in the deployment check.

---

🛑 **Audit only. No fixes applied. Recommend: P1 copy fix (index.html editorial) as
authorized micro-change; P1-hydration + P2-FINNIFTY-generator as Track C/D items.**
