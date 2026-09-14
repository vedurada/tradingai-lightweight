# PHASE 6B-3 Phase B.1 — Specification: CI/CD Foundation

**Status**: SPECIFICATION — AWAITING REVIEW

**Frozen commits**: `45f90fc` (analytical), `51c02f9` (6A), `63ab095` (6B-1), `8bbd4d7` (6B-2, FROZEN), `c39af34` (6B-3 Phase A, FROZEN)

**Regression baseline**: 298/298 passing
**Test command**: `python3 -m pytest tests/ -v`

---

## Scope Definition

Per user directive: B.1 is narrowly defined as:

> "Can we automatically prove that future infrastructure changes have not broken the currently frozen system?"

This covers findings 4.1, 4.2, 4.3, and assesses 4.4.

**Not in B.1**: B.2–B.5, all analytical/model work, VM provisioning, DevOps cleanup beyond the safety net.

---

## 4.1 Automated Regression Gates

**Finding**: No CI/CD pipeline exists. Tests run manually only.
**Severity**: CRITICAL
**Effort**: S

### Requirement

Create `.github/workflows/regression.yml` that:
1. Triggers on every push and pull request to main
2. Runs `python3 -m pytest tests/ -v`
3. Blocks merge if any test fails
4. Stores test results as workflow artifacts
5. Runs on the exact same Python version as production

### Implementation Boundary

- Must add: `.github/workflows/regression.yml`
- Must not modify: any source code, model logic, API responses
- Must preserve: all 298 existing tests

### Acceptance Criteria

| Criterion | Target |
|---|---|
| CI runs pytest on push | Yes |
| CI runs pytest on PR | Yes |
| PR merge blocked on test failure | Yes |
| Test results stored as artifacts | Yes |
| Python version matches production | Yes |
| All 298 tests pass in CI | Yes |
| Model files untouched | 0/8 modified |

### Test Plan

- Validate workflow YAML syntax
- Run pytest locally (already passing: 298/298)
- Verify no model files changed: `git diff --name-only` → 0 model files

---

## 4.2 Commit/PR Validation

**Finding**: No pre-commit hooks. Debug statements, bare excepts, TODOs can enter unchecked.
**Severity**: HIGH
**Effort**: S

### Requirement

Create `.pre-commit-config.yaml` with hooks for:
1. Python syntax check (`py_compile`)
2. Pytest execution
3. Forbidden pattern detection:
   - `except:` (bare except) in non-test files
   - `print(` in non-test, non-debug files
   - `TODO:` in non-test files
4. Basic linting (ruff or flake8)

### Implementation Boundary

- Must add: `.pre-commit-config.yaml`
- Must add: `.pre-commit-hooks.yaml` (custom hooks if needed)
- Must not modify: any source code logic, model logic
- Must preserve: all 298 existing tests

### Acceptance Criteria

| Criterion | Target |
|---|---|
| Pre-commit hooks run on every commit | Yes |
| Bare except in non-test code blocked | Yes |
| Print in non-test code blocked | Yes |
| Tests blocked by pre-commit | Yes |
| Hooks documented in config | Yes |
| Existing tests still pass | 298/298 |
| Model files untouched | 0/8 modified |

### Forbidden Pattern Rules

```python
# Blocked in ALL non-test files:
except:                    # bare except
print(                     # debug print
TODO:                      # unfinished work
```

Test files are exempt from print/TODO checks (tests may use both legitimately).

### Test Plan

- Test that pre-commit blocks a bare except in a temp file
- Test that pre-commit blocks a print in a temp non-test file
- Test that pre-commit allows print in test files
- Test that pre-commit allows existing code (no false positives)
- Verify all 298 tests still pass after hooks configured

---

## 4.3 Deployment Safety Check

**Finding**: `deploy-vm.sh` has `|| true` on health check, ignoring failures. No rollback script.
**Severity**: MEDIUM
**Effort**: S

### Requirement

1. Fix `deploy-vm.sh` health check: remove `|| true`
2. Add explicit health check assertion: response must contain `"status": "ok"`
3. Create `ops/rollback.sh`: `git checkout <prev> && pip install -r ops/requirements.txt && systemctl restart tradingai-api && curl /api/health`
4. Add pre-deploy health check: verify API is healthy before deploying

### Implementation Boundary

- Must modify: `deploy-vm.sh`, `ops/rollback.sh` (new)
- Must not modify: any Python source code, model logic
- Must preserve: all 298 existing tests

### Acceptance Criteria

| Criterion | Target |
|---|---|
| Deploy fails if health check fails | Yes (no `|| true`) |
| Health check asserts `"status": "ok"` | Yes |
| Pre-deploy health check exists | Yes |
| Rollback script exists | Yes |
| Rollback tested | Yes |
| Rollback completes <2 min | Yes (documented) |
| All 298 tests still pass | Yes |
| Model files untouched | 0/8 modified |

### Rollback Script

```bash
#!/bin/bash
# ops/rollback.sh — Fast rollback to previous commit
set -euo pipefail

PREV_COMMIT=$(git rev-parse HEAD~1)
echo "Rolling back to $PREV_COMMIT..."
git checkout "$PREV_COMMIT"
pip install -r ops/requirements.txt
systemctl restart tradingai-api
sleep 5
curl -sf http://127.0.0.1:8000/api/health | grep -q "ok" && echo "Rollback successful" || echo "Rollback FAILED — investigate"
```

### Test Plan

- Verify `deploy-vm.sh` exits non-zero when health check returns non-ok
- Verify rollback script syntax is valid (`bash -n ops/rollback.sh`)
- Verify all 298 tests still pass

---

## 4.4 Staging Environment

**Finding**: No staging VM. All changes tested directly on production.
**Severity**: MEDIUM
**Effort**: L

### Assessment

This finding requires VM provisioning (infrastructure, not code). It cannot be implemented in the repository alone.

### Recommendation

**Assess, don't implement in B.1.** Document requirements:
- Staging VM: same image as production, different IP
- Deploy workflow: deploy to staging first, validate, then production
- Validation checklist: documented

**Defer to B.4 (Operational Polish)** or a separate infrastructure authorization.

### In B.1 Only

Document staging requirements in `ops/DEPLOYMENT.md`:
- Staging VM specification
- Deploy-to-staging workflow
- Validation checklist

No code changes. No VM provisioning.

---

## B.1 Aggregate Summary

| Finding | Severity | Effort | Status |
|---|---|---|---|
| 4.1 Automated Regression Gates | CRITICAL | S | Implement |
| 4.2 Commit/PR Validation | HIGH | S | Implement |
| 4.3 Deployment Safety Check | MEDIUM | S | Implement |
| 4.4 Staging Environment | MEDIUM | L | Assess only (document) |

### Files to Create

| File | Purpose |
|---|---|
| `.github/workflows/regression.yml` | CI/CD pipeline |
| `.pre-commit-config.yaml` | Pre-commit hooks |
| `ops/rollback.sh` | Fast rollback script |
| `ops/DEPLOYMENT.md` | Staging requirements (4.4 documentation) |

### Files to Modify

| File | Change |
|---|---|
| `deploy-vm.sh` | Remove `|| true`, add health assertion |

### Files NOT Touched

- All Python source files (0 modifications)
- All model files (0 modifications)
- All API responses (0 modifications)
- All model logic (0 modifications)

### Tests

| Category | Count | Purpose |
|---|---|---|
| Regression (existing) | 298 | Baseline preservation |
| B.1 new | ~10-15 | CI config, hook validation, deploy/rollback |
| **Total** | ~310-315 | Full coverage |

### Model Boundary Protection

| Protection | Mechanism |
|---|---|
| File-level | `git diff --name-only` → 0 model files |
| Test gate | All 298 existing tests must pass |
| Pre-commit | Hooks run before any commit |
| CI gate | CI blocks merge on test failure |
| Independent review | Required before freeze |

### Sequence

```
Specification Review → Implementation → Gate Verification → Independent Review → Freeze B.1 🔒 → STOP
```

**B.1 is the ONLY authorized implementation. B.2–B.5 and all analytical work remain outside authorization.**
