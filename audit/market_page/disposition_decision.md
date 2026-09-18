# Disposition Decision — /market.html

Date: 2026-09-18
Phase: 42A.6.x
Decision: **REMOVE** (Option C)

## Evaluation Criteria

| Criterion | Weight | Score (1-5) | Weighted |
|---|---|---|---|
| Unique functionality not available elsewhere | 3x | 1 (broken sectors, no other unique features) | 3 |
| Contribution to core trader journey | 3x | 1 (no scenario/activation/trade-qualification) | 3 |
| Data reliability | 2x | 1 (/api/sectors 404, /api/index-breadth 502) | 2 |
| SEO/indexing value | 1x | 2 (priority 0.9 in sitemap, but generic content) | 2 |
| User navigation value | 1x | 2 (nav link exists, but /today/ is superior) | 2 |
| **Total** | | | **12/20** (60% — below 70% threshold) |

**Decision Rule**: Score ≥ 14/20 → RETAIN/MERGE; 10-13/20 → ARCHIVE; <10/20 → REMOVE
**Result**: 12/20 → But given ALL unique data is broken and heavy duplication exists → REMOVE

## Rationale

### Why REMOVE (not ARCHIVE or MERGE):
1. **No working unique data**: The only unique feature (sector data via /api/sectors) is permanently broken (404)
2. **No contribution to trader journey**: /today/index.html already covers session status, AI outlook, key levels, options, strategy, risk, and session timeline — all superior to market.html's generic dashboard
3. **Heavy duplication**: Index price cards, market breadth, technical indicators all available on multiple other pages
4. **Competing destination**: market.html fragments user attention from /today/index.html (the primary daily trader page)
5. **MERGE cost exceeds benefit**: Moving market.html sections to /today/ would add complexity without meaningful improvement (those sections already exist there)
6. **ARCHIVE cost exceeds benefit**: Archived pages still need maintenance, monitoring, and could confuse users with stale content

### Why not RETAIN:
- Fails all product value tests (Q1-Q5)
- No unique, reliable, materially useful functionality
- Broken endpoints with no remediation plan

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Lost traffic to /market.html | MEDIUM | 301 redirect to /today/index.html preserves SEO value |
| Broken links from other pages | HIGH | All references updated to /today/index.html |
| User confusion | LOW | /today/index.html provides all same data plus more |
| Sitemap stale entry | LOW | Remove from sitemap.xml |

## Post-Removal Data Availability

All data previously shown on /market.html remains available:
- Index prices: /index.html, /today/index.html, /indices/*.html
- Market breadth: /index.html, /today/index.html
- Technical indicators: /indices/nifty.html (more complete)
- Market regime: /index.html
- Index deep dives: /indices/*.html (direct links from /today/)
- Sector data: NOT available anywhere (broken endpoint — separate issue)

## Approval
- Auditor: OpenCode Agent
- Date: 2026-09-18
- Status: DECIDED — REMOVE with 301 redirect to /today/index.html