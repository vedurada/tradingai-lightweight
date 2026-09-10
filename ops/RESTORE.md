# TradingAI Disaster Recovery Runbook

Goal: from a dead/lost VM to a fully working tradingai.in with **zero data loss**.

## How backups work

- **Daily 18:30 IST cron** on the VM runs `ops/vm-backup.sh`.
- It snapshots the **live** SQLite DB with the online-backup API (never a raw file copy),
  integrity-checks it (`PRAGMA integrity_check` + row counts), and aborts loudly on any failure.
- Snapshot + `data/*.json` + `config/` + `backend/` + pages + `ops/` are committed to the
  **`vm-backup` branch** of this same repo (code `main` stays clean) and the push is verified.
- Check health any time: `tail /opt/tradingai/logs/backup.log` on the VM — every run ends
  with either `backup pushed OK` or `FATAL` with the exact fix.

## One-time setup (backup push auth)

The VM needs write access to GitHub (read-only deploy from Mac is not enough for pushes):

```bash
ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81 \
  "ssh-keygen -t ed25519 -f ~/.ssh/github_backup -N '' && cat ~/.ssh/github_backup.pub"
```

Add the printed key as a **write** deploy key at
`github.com/vedurada/tradingai-lightweight/settings/keys` (title: `vm-backup`).
Then trigger one backup manually to confirm:

```bash
ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81 "/opt/tradingai/ops/vm-backup.sh"
```

## Full rebuild on a new VM (Ubuntu 22.04, ports 80+443 open)

1. Point DNS `tradingai.in` + `www` at the new VM IP and wait for propagation.
2. From your Mac:
   ```bash
   NEW_VM_IP=<new-ip> bash ops/setup-new-vm.sh
   ```
   This installs everything (apt, pip, nginx, certbot), syncs the repo, **restores
   `database/tradingai.db` from the `vm-backup` branch**, installs nginx + cron,
   issues the HTTPS cert, runs the first fetch, and starts the API.
3. Verify: site loads with trusted cert, `/api/health` → ok, `crontab -l` complete,
   `history.html` shows past P&L (proof the DB restore worked).
4. Add the `github_backup` deploy key (section above) so daily backups resume.

## What is NOT in git (by design)

- `~/.ssh/*` keys, letsencrypt account keys — re-created per machine.
- `logs/` — ephemeral; recreated automatically.
- LetsEncrypt certs are re-issued by `setup-new-vm.sh` (needs DNS first).

## Layout reference

| Path (VM) | Source of truth |
|---|---|
| `/opt/tradingai` | repo `main` via `deploy-vm.sh` rsync (no `.git`, no DB) |
| `/var/www/tradingai.in/html` | synced from `/opt/tradingai` by deploy script |
| `/opt/tradingai/database/tradingai.db` | live DB; backed up from `vm-backup` branch on rebuild |
| `/opt/tradingai-backup` | git workdir for the `vm-backup` branch (backup script only) |
| `/etc/nginx/sites-enabled/tradingai` | `ops/nginx-tradingai.conf` in repo |
| crontab | `ops/crontab.txt` in repo |
