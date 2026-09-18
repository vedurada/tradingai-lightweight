# Phase 42A — Content Identity Validation

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Lesson from Phase 41C**: HTTP 200 + wrong page content = failure

---

## Validation Method

For each critical page, verify:
1. HTTP status = 200
2. Page-specific `<title>` contains expected text
3. Page contains Phase 41 shell marker
4. Content hash matches pre-deployment baseline

## Page Validation Results

### `/` (Home)

| Check | Result |
|-------|--------|
| HTTP 200 | TBD (verify on VM) |
| Title contains "TradingAI" | TBD |
| Phase 41 marker present | TBD |
| Content hash | TBD |

### `/today/`

| Check | Result |
|-------|--------|
| HTTP 200 | TBD |
| Title contains "Today" | TBD |
| Phase 41 marker present | TBD |
| Content hash | TBD |

### `/indices/nifty.html`

| Check | Result |
|-------|--------|
| HTTP 200 | TBD |
| Title contains "NIFTY" | TBD |
| Phase 41 marker present | TBD |
| Content hash | TBD |

### `/indices/banknifty.html`

| Check | Result |
|-------|--------|
| HTTP 200 | TBD |
| Title contains "BANKNIFTY" | TBD |
| Phase 41 marker present | TBD |
| Content hash | TBD |

## Validation Process

Content identity checks will be performed as part of deployment validation using deploy_validator.py. The expected page markers are defined in the module.

## Note

Since Phase 42A only adds backend modules and database schema (no frontend changes), page content hashes should be IDENTICAL before and after deployment. Any hash change indicates an unexpected modification.
