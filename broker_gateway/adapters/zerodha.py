"""Zerodha adapter. Preserves the existing scanner feed exactly."""
from __future__ import annotations

import os
import pathlib

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
        creds = _load_credentials()
        api_key = creds.get("KITE_API_KEY")
        token = creds.get("KITE_ACCESS_TOKEN")
        if not api_key or not token:
            raise RuntimeError("Zerodha credentials are incomplete")
        KiteConnect = load_real_kite_connect()
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(token)

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
