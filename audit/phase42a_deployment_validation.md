# Phase 42A — Deployment Validation

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Principle**: HTTP 200 does NOT guarantee correct content is served

---

## Phase 41C Lesson

Phase 41C found that `/var/www/tradingai.in/html/index.html` had wrong content (today page instead of home page). HTTP 200 alone was insufficient to verify deployment correctness.

## Deployment Validation Steps

### Pre-Deployment Checklist

1. [ ] Run all tests (Phase 39, 40, 41, 42A)
2. [ ] Verify no production code modified
3. [ ] Verify schema migration is additive (no destructive changes)
4. [ ] Verify DB backup completed
5. [ ] Generate expected page identity manifest (hash each critical page)
6. [ ] Record file hashes for verification

### Deployment Verification

7. [ ] Deploy Phase 42A changes
8. [ ] Verify HTTP 200 for critical pages
9. [ ] Verify CONTENT IDENTITY for critical pages (not just HTTP 200)
10. [ ] Verify API health (/api/health)
11. [ ] Verify critical API endpoints return correct data
12. [ ] Verify frontend page markers (title, canonical, Phase 41 marker)
13. [ ] Verify no stale page served
14. [ ] Verify git/deployment state matches expected

### Post-Deployment Monitoring

15. [ ] Monitor API error rates (should not increase)
16. [ ] Monitor DB size growth (should be minimal)
17. [ ] Monitor memory usage (should not increase significantly)
18. [ ] Monitor research data collection rate (setup identities being recorded)
19. [ ] Verify research data tables are being populated

## Page Identity Verification

### Method

For each critical page, verify:
- Page-specific `<title>` content
- Canonical URL marker
- Unique page identifier
- Expected Phase 41 shell marker

### Pages to Verify

| Page | Expected Markers |
|------|-----------------|
| /index.html | TradingAI title, canonical, Phase 41 marker |
| /today/index.html | Today title, Phase 41 marker |
| /indices/nifty.html | NIFTY title, Phase 41 marker |
| /indices/banknifty.html | BANKNIFTY title, Phase 41 marker |

### Verification Process

1. Compute SHA-256 hash of each page BEFORE deployment
2. Deploy Phase 42A
3. Compute SHA-256 hash of each page AFTER deployment
4. Compare hashes — they should be IDENTICAL (Phase 42A doesn't change pages)
5. If any hash differs, STOP — investigate immediately

## Rollback Criteria

If any of the following occur, rollback immediately:
- Page content hash changed unexpectedly
- API health check fails
- Research data collection fails
- Trading behavior changes (qualification logic different)
- Any test regression not pre-existing
- Memory/CPU spike beyond baseline

## Tool: deploy_validator.py

The `deploy_validator.py` module provides:
- `generate_expected_manifest()` — Generate page hashes before deployment
- `validate_deployment()` — Verify deployment after deployment
- `PAGE_IDENTITY_MARKERS` — Expected page identity markers

## NOT IMPLEMENTED IN PHASE 42A

- Automated pre-deployment hash recording (manual step for now)
- Automated deployment verification (manual step for now)
- Monitoring dashboard (not required for Phase 42A)
