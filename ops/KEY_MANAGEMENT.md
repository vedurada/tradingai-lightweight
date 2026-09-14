# TradingAI API Key Management (A6 runbook)

Keys gate portfolio endpoints and privileged chat kinds (`system`/`alert`).
There is intentionally **no HTTP surface** for key management — all operations run
locally on the VM as `ubuntu` via `backend/auth.py`. Only key *prefixes* are ever
listed; hashes never leave the database.

## Commands (run in `/opt/tradingai/backend`)

```bash
python3 auth.py list                                  # prefixes only
python3 auth.py issue --user-id 1 --label "owner"     # prints raw key ONCE
python3 auth.py revoke <key-prefix>                   # revoke by prefix
```

## Rotation procedure (dual-active grace, no downtime)

1. `issue` a new key with a distinct label; distribute it to the client.
2. Verify the new key: `curl -H "Authorization: Bearer <new>" http://127.0.0.1:8000/api/portfolio`.
3. `revoke <old-prefix>`; confirm the old key now returns 401.
4. Record the rotation (date, label, prefix) in the deploy log.

## Revocation on suspected compromise

`revoke <prefix>` immediately; compromised keys cannot be recovered, only replaced.
Check `last_used_at` via `list` to scope exposure.

## Notes

- Storage: SHA-256(salt+key) + per-key salt; only hash/salt/prefix persisted.
- No expiry/TTL by design (long-lived service keys); rotation is the control.
- Secrets (`groq.env`) are separate: `/etc/tradingai/groq.env`, mode 600, never in git.
