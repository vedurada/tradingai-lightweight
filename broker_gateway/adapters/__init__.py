"""Broker adapter registry. Add a new broker by adding one module here."""
from __future__ import annotations

from broker_gateway.errors import BrokerNotAvailable

_ADAPTERS: dict[str, str] = {
    "mstock": "broker_gateway.adapters.mstock:MStockAdapter",
}


def available_brokers() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(name: str):
    name = (name or "").strip().lower()
    target = _ADAPTERS.get(name)
    if not target:
        raise BrokerNotAvailable(
            f"unknown broker {name!r}; available: {', '.join(available_brokers())}"
        )
    module_name, class_name = target.split(":", 1)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)()
