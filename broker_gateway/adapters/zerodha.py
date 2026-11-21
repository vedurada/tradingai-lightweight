"""Zerodha adapter. Preserves the existing scanner feed exactly."""
from __future__ import annotations

import os
import pathlib
import threading

from broker_gateway.base import BrokerAdapter
from broker_gateway.real_kite import load_real_kite_connect

DEFAULT_CREDENTIALS = "/opt/tradingai/.env.zerodha"


def _load_credentials() -> dict[str, str]:
    path = pathlib.Path(os.environ.get("ZERODHA_CREDENTIALS_FILE", DEFAULT_CREDENTIALS))
    creds: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            creds[key.strip()] = value.strip().strip("\"'")
    return creds


class ZerodhaAdapter(BrokerAdapter):
    name = "zerodha"

    def __init__(self) -> None:
        self._cred_path = pathlib.Path(
            os.environ.get("ZERODHA_CREDENTIALS_FILE", DEFAULT_CREDENTIALS)
        )
        self._cred_lock = threading.Lock()
        self._signature: tuple[int, int] | None = None
        # Capture the signature before reading so a concurrent refresh cannot
        # pair this snapshot with a newer signature (TOCTOU).
        stamp = self._current_signature()
        creds = _load_credentials()
        api_key = creds.get("KITE_API_KEY")
        token = creds.get("KITE_ACCESS_TOKEN")
        if not api_key or not token:
            raise RuntimeError("Zerodha credentials are incomplete")
        self._signature = stamp
        self.kite = self._build(api_key, token)

    @staticmethod
    def _build(api_key: str, token: str):
        KiteConnect = load_real_kite_connect()
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(token)
        return kite

    def _current_signature(self) -> tuple[int, int] | None:
        try:
            stat = self._cred_path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    # -- gateway freshness contract --------------------------------------
    def credential_signature(self):
        return self._current_signature()

    def refresh_credentials_if_changed(self) -> None:
        signature = self._current_signature()
        if signature is None or signature == self._signature:
            return
        with self._cred_lock:
            signature = self._current_signature()
            if signature is None or signature == self._signature:
                return
            creds = _load_credentials()
            api_key = creds.get("KITE_API_KEY", "")
            token = creds.get("KITE_ACCESS_TOKEN", "")
            if not api_key or not token:
                return
            self.kite = self._build(api_key, token)
            self._signature = signature

    def validate_credentials(self) -> None:
        self.profile()

    # -- Kite-shaped methods ---------------------------------------------
    def instruments(self, exchange: str) -> list[dict]:
        return self.kite.instruments(exchange)

    def quote(self, symbols: list[str]) -> dict[str, dict]:
        return self.kite.quote(symbols)

    def historical_data(self, token: int, start, end, interval: str) -> list[dict]:
        return self.kite.historical_data(token, start, end, interval)

    def profile(self) -> dict:
        data = self.kite.profile()
        return {
            "broker": self.name,
            "user_id": data.get("user_id") if isinstance(data, dict) else None,
        }
