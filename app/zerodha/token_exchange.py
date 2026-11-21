#!/usr/bin/env python3
"""Official Kite Connect token exchange - server-side only.

Reads exactly one request token from /tmp/request_token.txt, exchanges it with
the official SDK, verifies the returned session with a read-only profile call,
and only then persists the token atomically through the canonical credential
module. Never prints request tokens, access tokens, secrets, or headers.
"""

import sys

if "/opt/tradingai" not in sys.path:
    sys.path.insert(0, "/opt/tradingai")

from zerodha_credentials import (  # noqa: E402
    ACCESS_TOKEN,
    API_KEY,
    API_SECRET,
    CredentialError,
    clear_request_token,
    load_credentials,
    persist_access_token,
)
from broker_gateway.real_kite import load_real_kite_connect  # noqa: E402

REQUEST_TOKEN_FILE = "/tmp/request_token.txt"


def read_request_token(path: str = REQUEST_TOKEN_FILE) -> str:
    """Read and validate the single-use request token from disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
    except FileNotFoundError as exc:
        raise CredentialError(
            f"request token file missing: {path} "
            "(complete the browser login first)"
        ) from exc
    if not token:
        raise CredentialError("request token file is empty")
    if "=" in token or any(ch.isspace() for ch in token):
        raise CredentialError(
            "request token must be the raw value, not key=value text"
        )
    return token


def verify_returned_token(api_key: str, access_token: str) -> dict:
    """TEST A: authenticate a fresh client with the just-returned token."""
    # Session exchange is an auth operation run only as root by refresh_token.sh.
    # Use the real SDK: the installed `kiteconnect` name is the gateway's
    # read-only scanner shim, which deliberately has no generate_session.
    KiteConnect = load_real_kite_connect()

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite.profile()


def main() -> int:
    try:
        cfg = load_credentials(required=(API_KEY, API_SECRET))
        request_token = read_request_token()
    except CredentialError as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        KiteConnect = load_real_kite_connect()

        kite = KiteConnect(api_key=cfg[API_KEY])
        data = kite.generate_session(
            request_token, api_secret=cfg[API_SECRET]
        )
    except Exception as exc:  # classify only, never echo secrets
        detail = type(exc).__name__
        message = str(exc).strip().replace("\n", " ")[:200]
        if message:
            print(f"ERROR: generate_session failed ({detail}): {message}")
        else:
            print(f"ERROR: generate_session failed ({detail})")
        return 1

    returned = data.get("access_token")
    if not returned:
        fields = ",".join(sorted(data.keys())) if isinstance(data, dict) else "?"
        print(
            "ERROR: exchange response contained no access token "
            f"(response fields: {fields})"
        )
        return 1

    response_key = data.get("api_key")
    if response_key and response_key != cfg[API_KEY]:
        print(
            "ERROR: exchange API key does not match the canonical API key; "
            "token was not stored"
        )
        return 1

    try:
        profile = verify_returned_token(cfg[API_KEY], returned)
    except Exception as exc:
        print(
            "TEST A FAIL: immediate profile failed "
            f"({type(exc).__name__}); token was not stored"
        )
        return 1

    user_id = profile.get("user_id")
    print(f"TEST A PASS: immediate profile authenticated user_id={user_id}")
    if not response_key:
        print(
            "NOTE: exchange response did not include api_key; "
            "key/token pairing verified by the profile call"
        )

    try:
        persist_access_token(returned, expected_api_key=cfg[API_KEY])
    except CredentialError as exc:
        print(f"ERROR: token not persisted: {exc}")
        return 1

    reloaded = load_credentials()
    identity_match = reloaded[ACCESS_TOKEN] == returned
    print(f"Persisted token identity match: {identity_match}")
    if not identity_match:
        print("ERROR: persisted token does not match the returned session")
        return 1

    clear_request_token()
    print("OK: verified access token persisted atomically (value hidden)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
