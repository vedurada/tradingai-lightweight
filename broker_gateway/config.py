"""Broker selection config (contains no secrets)."""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

DEFAULT_PATH = "/opt/tradingai/broker_gateway/config/scanners.json"
DEFAULT_CONFIG: dict[str, Any] = {
    "default": "zerodha",
    "scanners": {},
}


def config_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("BROKER_GATEWAY_CONFIG", DEFAULT_PATH))


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot read broker gateway config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"broker gateway config must be a JSON object: {path}")
    data.setdefault("default", "zerodha")
    data.setdefault("scanners", {})
    if not isinstance(data["scanners"], dict):
        raise RuntimeError(f"'scanners' must be an object: {path}")
    return data


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.chmod(0o644)
    os.replace(str(tmp), str(path))


def scanner_name() -> str:
    """Effective scanner key from env override or script filename."""
    import sys

    explicit = os.environ.get("BROKER_GATEWAY_SCANNER", "").strip()
    if explicit:
        return explicit
    return pathlib.Path(sys.argv[0]).name


def broker_for(scanner: str | None = None) -> str:
    """Resolve broker: env override > per-scanner config > default."""
    env_broker = os.environ.get("BROKER_GATEWAY_BROKER", "").strip()
    if env_broker:
        return env_broker
    data = load_config()
    key = scanner or scanner_name()
    return str(data["scanners"].get(key, data["default"]))
