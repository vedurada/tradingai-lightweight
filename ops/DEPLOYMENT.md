# TradingAI Deployment Guide

## Production Deployment

### Prerequisites
- VM at 129.159.224.81 (Ubuntu 22.04)
- SSH key at `~/.ssh/oci_key`
- Python 3.10+ on VM

### Deploy
```bash
./deploy-vm.sh
```

### Rollback
```bash
./ops/rollback.sh
```
Rolls back to previous commit, reinstalls dependencies, restarts API, verifies health. Completes in < 2 minutes.

## Staging Environment (B.4 — Future)

### Requirements
- Staging VM: same image as production, different IP
- Separate database (or copy of production DB)
- Isolated from production traffic

### Deploy to Staging
1. Modify deploy-vm.sh to accept target VM parameter
2. Deploy to staging VM first
3. Run regression tests against staging
4. Validate endpoints
5. Deploy to production

### Validation Checklist
- [ ] All 298 regression tests pass
- [ ] Health endpoint returns OK
- [ ] Critical endpoints respond (price, vix, market, strategy)
- [ ] No model file modifications
- [ ] No successful response changes

### Staging VM Specification
- Same OS image as production (Ubuntu 22.04)
- Same package versions
- Separate IP address
- Database: copy of production or fresh with same schema
- Network: isolated from production traffic

**Status**: Not yet authorized. Awaiting B.4 scope authorization.
