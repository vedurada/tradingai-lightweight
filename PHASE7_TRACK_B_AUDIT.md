# PHASE 7 Track B — Audit (Product / AdSense Readiness)

**Status**: 🟡 AUDIT COMPLETE — awaiting scope approval. No code/content changes made.

**Baseline**: Track A frozen `3d4f7ca` 🔒. Engines frozen (0/8 model files untouchable).

**Method**: static inventory of the webroot served at `/var/www/tradingai.in/html`
against Google AdSense program policies + publisher best practice.

---

## Present ✅

| Item | Evidence |
|---|---|
| AdSense auto-ads script, all pages | `adsbygoogle.js?client=ca-pub-2262405054444130` on every HTML page (0 pages missing) |
| Privacy / Terms / Disclaimer / About / Contact | `privacy.html`, `terms.html`, `disclaimer.html`, `about.html`, `contact.html` exist |
| Financial disclaimers | "Educational purposes only — not investment advice" + risks section present |
| Sitemap / robots | `sitemap.xml` 37 URLs; `robots.txt` allows `/`, disallows `/api/`, `/data/` |
| Mobile viewport | `viewport` meta on sampled pages |
| Footer + contact linkage | mostly consistent |

## Gaps ❌ (candidate Track B scope)

| # | Gap | Risk |
|---|---|---|
| B-G1 | **No `ads.txt`** at webroot | AdSense verification / sellers.json fails; revenue + approval risk |
| B-G2 | **No cookie-consent mechanism** (privacy mentions cookies, no banner/choice) | GDPR/DPDP exposure; AdSense consent-mode expectation (EU/UK traffic) |
| B-G3 | Privacy page may not disclose **Google advertising cookies** explicitly | AdSense policy requires this disclosure verbatim-ish |
| B-G4 | Nav inconsistency: `strategies.html` has **0 links to contact.html** | Crawlability + policy "contactable publisher" signal |
| B-G5 | No documented **ad-placement guardrails** (auto-ads only; layout-shift / accidental-click risk near CTAs) | Policy violation risk on accidental clicks |
| B-G6 | Thin/auto-generated pages (`market/outlook-*.html`, `queries/`) lack visible authorship/date/disclosure headers | "Thin content / no value-add" rejection risk |
| B-G7 | No verified **ownership/author identity** signal beyond contact page | Trust signal for YMYL-adjacent financial content |

## Explicitly out of scope (engines frozen)

`backend/regime.py`, `strategies.py`, `outlook.py`, `scenarios.py`, `options.py`,
`ai_outlook.py`, `backtest.py`, `indicators.py` — zero changes. No signal math,
no strategy suggestions, no confidence/threshold changes. Track B touches
**webroot content + policies + ads plumbing only**.

---

🛑 **STOP — audit complete. Awaiting scope approval before specification.**
Proposed scope: B-G1…B-G7 above, webroot-only, engines frozen.
