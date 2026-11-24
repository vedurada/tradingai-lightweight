#!/usr/bin/env bash
# Rotate the mStock Type A API key stored on this VM.
#
# This script does NOT generate or revoke the key at mStock. Do that first in
# the mStock portal (trade.mstock.com -> Trading APIs -> Generate New API Key).
# It only replaces the local root-only secret file. No secret is accepted as a
# command-line argument, echoed, or written to a backup.
#
# Usage:
#   sudo /usr/local/sbin/rotate_mstock_key.sh
#   MSTOCK_SECRET_FILE=/path/to/secret sudo /usr/local/sbin/rotate_mstock_key.sh

set -euo pipefail
umask 077

SECRET_FILE="${MSTOCK_SECRET_FILE:-/opt/tradingai/secrets/mstock.env}"
SECRET_DIR="$(dirname "$SECRET_FILE")"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

read_hidden() {
    local prompt="$1"
    printf '%s' "$prompt" >&2
    IFS= read -r -s READ_VALUE || die "input cancelled"
    printf '\n' >&2
    [[ -n "$READ_VALUE" ]] || die "empty value: $prompt"
}

read_hidden_optional() {
    local prompt="$1"
    printf '%s' "$prompt" >&2
    IFS= read -r -s READ_VALUE || die "input cancelled"
    printf '\n' >&2
}

read_visible_with_default() {
    local prompt="$1" default="$2"
    printf '%s' "$prompt" >&2
    IFS= read -r READ_VALUE || die "input cancelled"
    if [[ -z "$READ_VALUE" ]]; then
        READ_VALUE="$default"
    fi
}

current_client_id=""
if [[ -f "$SECRET_FILE" ]]; then
    current_client_id="$(python3 - "$SECRET_FILE" <<'PY'
import pathlib, shlex, sys
path = pathlib.Path(sys.argv[1])
for line in path.read_text().splitlines():
    if line.startswith("MSTOCK_CLIENT_ID="):
        print(shlex.split(line, posix=True)[0].split("=", 1)[1])
        break
PY
)"
fi

[[ $EUID -eq 0 ]] || die "run with sudo (root is required)"
[[ -t 0 ]] || die "run interactively; hidden input needs a TTY"
command -v python3 >/dev/null || die "python3 is required"

printf 'mStock API key rotation\n' >&2
printf 'Secret file: %s\n\n' "$SECRET_FILE" >&2

read_hidden "New API key (hidden): "            # -> READ_VALUE
export MSTOCK_NEW_API_KEY="$READ_VALUE"

read_visible_with_default "Client ID [${current_client_id:-<none>}]: " "$current_client_id"
export MSTOCK_NEW_CLIENT_ID="$READ_VALUE"

read_hidden_optional "Trading password (hidden, press Enter to keep current): "
export MSTOCK_NEW_PASSWORD="$READ_VALUE"

printf 'Checksum [L]: ' >&2
IFS= read -r READ_VALUE || die "input cancelled"
export MSTOCK_NEW_CHECKSUM="${READ_VALUE:-L}"

printf 'Access token (hidden, press Enter to keep current / leave unset): ' >&2
IFS= read -r -s READ_VALUE || die "input cancelled"
printf '\n' >&2
export MSTOCK_NEW_ACCESS_TOKEN="$READ_VALUE"

install -d -m 700 -o root -g root "$SECRET_DIR"

python3 - "$SECRET_FILE" <<'PY'
import os
import pathlib
import shlex
import sys

path = pathlib.Path(sys.argv[1])
old = {}

if path.exists():
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        old[key.strip()] = value.strip()

# One-time values must never survive a rotation.
for transient in ("MSTOCK_OTP", "MSTOCK_TOTP", "MSTOCK_REQUEST_TOKEN"):
    old.pop(transient, None)

updates = {
    "MSTOCK_API_KEY": os.environ["MSTOCK_NEW_API_KEY"],
    "MSTOCK_CLIENT_ID": os.environ["MSTOCK_NEW_CLIENT_ID"],
    "MSTOCK_CHECKSUM": os.environ.get("MSTOCK_NEW_CHECKSUM") or "L",
    "MSTOCK_WEBSOCKET_URL": "wss://ws.mstock.trade",
}
password = os.environ.get("MSTOCK_NEW_PASSWORD", "")
if password:
    updates["MSTOCK_PASSWORD"] = password
access_token = os.environ.get("MSTOCK_NEW_ACCESS_TOKEN", "")
if access_token:
    updates["MSTOCK_ACCESS_TOKEN"] = access_token
old.update(updates)

tmp = path.with_name(path.name + ".tmp")
fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
try:
    os.fchmod(fd, 0o600)
    os.fchown(fd, 0, 0)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("# Managed by rotate_mstock_key.sh - root only, mode 0600\n")
        for key in sorted(old):
            handle.write(f"{key}={shlex.quote(old[key])}\n")
        handle.flush()
        os.fsync(handle.fileno())
except Exception:
    try:
        os.unlink(str(tmp))
    except FileNotFoundError:
        pass
    raise

os.replace(str(tmp), str(path))
os.chmod(str(path), 0o600)
os.chown(str(path), 0, 0)
PY

unset MSTOCK_NEW_API_KEY MSTOCK_NEW_CLIENT_ID MSTOCK_NEW_PASSWORD \
      MSTOCK_NEW_CHECKSUM MSTOCK_NEW_ACCESS_TOKEN

printf '\nUpdated: ' >&2
stat -c '%a %U:%G %n' "$SECRET_FILE" >&2
printf 'Old key was not backed up. Revoke it in the mStock portal if you have not already.\n' >&2
printf 'Next: regenerate the daily session with the new API key (OTP or TOTP).\n' >&2
