#!/usr/bin/env python3
"""Create or verify an mStock Type A session without exposing secrets.

Reads /opt/tradingai/secrets/mstock.env (root-only 0600), performs the Type A
login/session flow, and stores the returned daily tokens back into the same
file. OTP/TOTP is prompted for but never stored or printed.

Usage:
    sudo /usr/local/sbin/mstock_session.py --mode otp     # SMS OTP flow
    sudo /usr/local/sbin/mstock_session.py --mode totp    # authenticator flow
    sudo /usr/local/sbin/mstock_session.py --check        # verify stored token
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import pathlib
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request

SECRET_FILE = pathlib.Path(
    os.environ.get("MSTOCK_SECRET_FILE", "/opt/tradingai/secrets/mstock.env")
)
BASE = "https://api.mstock.trade/openapi/typea"
TIMEOUT = 30


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config() -> dict[str, str]:
    if not SECRET_FILE.exists():
        die(f"missing secret file: {SECRET_FILE}")
    config: dict[str, str] = {}
    for raw in SECRET_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            config[key.strip()] = shlex.split(value, posix=True)[0]
        except (ValueError, IndexError):
            config[key.strip()] = value.strip().strip("\"'")
    return config


def save_config(config: dict[str, str]) -> None:
    for transient in ("MSTOCK_OTP", "MSTOCK_TOTP", "MSTOCK_REQUEST_TOKEN"):
        config.pop(transient, None)

    tmp = SECRET_FILE.with_name(SECRET_FILE.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, 0, 0)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("# Managed by rotate_mstock_key.sh - root only, mode 0600\n")
            for key in sorted(config):
                handle.write(f"{key}={shlex.quote(config[key])}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(str(tmp))
        except FileNotFoundError:
            pass
        raise

    os.replace(str(tmp), str(SECRET_FILE))
    os.chmod(str(SECRET_FILE), 0o600)
    os.chown(str(SECRET_FILE), 0, 0)


def api_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except Exception:
        return f"HTTP {exc.code}"
    message = payload.get("message") or payload.get("error_type") or "request failed"
    return f"HTTP {exc.code}: {message}"


def request_json(
    path: str,
    fields: dict[str, str] | None = None,
    api_key: str | None = None,
    access_token: str | None = None,
    method: str = "POST",
) -> dict:
    headers = {"X-Mirae-Version": "1"}
    data = None
    if fields is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(fields).encode("utf-8")
    if api_key:
        headers["X-PrivateKey"] = api_key
    if access_token:
        if not api_key:
            die("api_key is required with access_token")
        headers["Authorization"] = f"token {api_key}:{access_token}"

    req = urllib.request.Request(
        BASE + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        die(api_error(exc))
    except Exception as exc:
        die(f"network error: {type(exc).__name__}")

    if not isinstance(payload, dict):
        die("unexpected response shape")
    if payload.get("status") != "success":
        die(str(payload.get("message") or payload.get("error_type") or "login failed"))
    return payload


def require(config: dict[str, str], key: str) -> str:
    value = config.get(key, "").strip()
    if not value:
        die(f"{key} is not set in {SECRET_FILE}")
    return value


def store_session(config: dict[str, str], data: dict) -> None:
    mapping = {
        "access_token": "MSTOCK_ACCESS_TOKEN",
        "public_token": "MSTOCK_PUBLIC_TOKEN",
        "enctoken": "MSTOCK_ENCTOKEN",
        "refresh_token": "MSTOCK_REFRESH_TOKEN",
    }
    for source, target in mapping.items():
        value = data.get(source)
        if value:
            config[target] = str(value)

    save_config(config)

    print("session: success")
    print(f"user_id: {data.get('user_id', '--')}")
    print(f"login_time: {data.get('login_time', '--')}")
    for source, target in mapping.items():
        if target in config:
            print(f"{target}_len: {len(config[target])}")
    print(f"secret_file: {SECRET_FILE} (600 root:root)")


def new_session(config: dict[str, str], mode: str) -> None:
    api_key = require(config, "MSTOCK_API_KEY")
    checksum = config.get("MSTOCK_CHECKSUM", "L").strip() or "L"

    if mode == "otp":
        username = require(config, "MSTOCK_CLIENT_ID")
        password = require(config, "MSTOCK_PASSWORD")
        request_json(
            "/connect/login",
            fields={"username": username, "password": password},
        )
        otp = getpass.getpass("OTP sent to registered mobile (hidden): ").strip()
        if not otp:
            die("empty OTP")
        payload = request_json(
            "/session/token",
            fields={
                "api_key": api_key,
                "request_token": otp,
                "checksum": checksum,
            },
        )
    else:
        totp = getpass.getpass("Authenticator TOTP (hidden): ").strip()
        if not totp:
            die("empty TOTP")
        payload = request_json(
            "/session/verifytotp",
            fields={"api_key": api_key, "totp": totp},
        )

    store_session(config, payload["data"])


def check_session(config: dict[str, str]) -> None:
    api_key = require(config, "MSTOCK_API_KEY")
    access_token = require(config, "MSTOCK_ACCESS_TOKEN")
    payload = request_json(
        "/user/fundsummary",
        api_key=api_key,
        access_token=access_token,
        method="GET",
    )
    print("session: valid")
    print(f"fundsummary_rows: {len(payload.get('data') or [])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mode", choices=("otp", "totp"))
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        die("run with sudo")
    if not sys.stdin.isatty():
        die("run interactively; hidden input needs a TTY")

    config = load_config()
    if args.check:
        check_session(config)
    else:
        new_session(config, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
