"""Load the installed kiteconnect package even when our shim shadows it."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import pathlib
import sys
import threading

_CACHE: object | None = None
_LOCK = threading.Lock()


def load_real_kite_connect():
    """Return the real KiteConnect class from the installed distribution."""
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE

        try:
            dist = importlib.metadata.distribution("kiteconnect")
            root = pathlib.Path(str(dist.locate_file("kiteconnect")))
        except Exception as exc:  # pragma: no cover - depends on host install
            raise RuntimeError(f"installed kiteconnect package not found: {exc}") from exc

        init = root / "__init__.py"
        if not init.exists():
            raise RuntimeError(f"kiteconnect package missing __init__.py at {root}")

        name = "_broker_gateway_real_kiteconnect"
        spec = importlib.util.spec_from_file_location(
            name, str(init), submodule_search_locations=[str(root)]
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot construct real kiteconnect import spec")

        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _CACHE = module.KiteConnect
        return _CACHE
