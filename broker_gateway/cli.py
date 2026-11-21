#!/usr/bin/env python3
"""Manage broker selection without touching scanner code."""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.environ.get("BROKER_GATEWAY_ROOT", "/opt/tradingai"))

from broker_gateway import __version__
from broker_gateway.adapters import available_brokers, get_adapter
from broker_gateway.config import config_path, load_config, save_config

SCANNER_SCRIPTS = {
    "sma9": "live_sma9_scanner.py",
    "sma9_atr": "live_sma9_atr_scanner.py",
    "sma9_high": "live_sma9_high_scanner.py",
    "sma9_1min_poll": "live_sma9_1min_poll_scanner.py",
    "sma9_trail": "live_sma9_trail_scanner.py",
    "sma9_high_trail": "live_sma9_high_trail_scanner.py",
    "sma9_5s_atr": "live_sma9_5s_atr_scanner.py",
    "pattern": "pattern_scanner_live.py",
}


def _resolve_scanner(value: str) -> str:
    if value in SCANNER_SCRIPTS:
        return SCANNER_SCRIPTS[value]
    return value


def _status() -> int:
    config = load_config()
    print(f"config: {config_path()}")
    print(f"default: {config.get('default')}")
    print("scanners:")
    for scanner in sorted(SCANNER_SCRIPTS.values()):
        print(f"  {scanner}: {config['scanners'].get(scanner, config['default'])}")
    return 0


def _use(scanner: str, broker: str) -> int:
    if broker not in available_brokers():
        print(
            f"ERROR: unknown broker {broker!r}; available: {', '.join(available_brokers())}",
            file=sys.stderr,
        )
        return 2
    config = load_config()
    key = _resolve_scanner(scanner)
    config["scanners"][key] = broker
    save_config(config)
    print(f"{key} -> {broker}")
    print("Restart only that scanner to activate the change.")
    return 0


def _adapters() -> int:
    for broker in available_brokers():
        print(broker)
    return 0


def _probe(broker: str) -> int:
    if broker not in available_brokers():
        print(f"ERROR: unknown broker {broker!r}", file=sys.stderr)
        return 2
    adapter = get_adapter(broker)
    print(f"broker: {broker}")
    try:
        profile = adapter.profile()
        print(f"profile: {profile.get('broker')} ok")
    except Exception as exc:
        print(f"profile: FAILED ({type(exc).__name__}: {exc})")
        return 1
    try:
        instruments = adapter.instruments("NFO")
        print(f"instruments(NFO): {len(instruments)}")
    except Exception as exc:
        print(f"instruments(NFO): FAILED ({type(exc).__name__}: {exc})")
        return 1
    try:
        quotes = adapter.quote(["NSE:NIFTY 50"])
        item = quotes.get("NSE:NIFTY 50") or {}
        print("quote(NSE:NIFTY 50): ok" if "last_price" in item else "quote: missing")
    except Exception as exc:
        print(f"quote: FAILED ({type(exc).__name__}: {exc})")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show broker selection")
    sub.add_parser("adapters", help="list installed broker adapters")

    use = sub.add_parser("use", help="select broker for a scanner")
    use.add_argument("--scanner", required=True)
    use.add_argument("--broker", required=True)

    probe = sub.add_parser("probe", help="read-only broker connectivity probe")
    probe.add_argument("--broker", required=True)

    args = parser.parse_args()
    if args.command == "status":
        return _status()
    if args.command == "adapters":
        return _adapters()
    if args.command == "use":
        if os.geteuid() != 0:
            print("ERROR: run with sudo", file=sys.stderr)
            return 2
        return _use(args.scanner, args.broker)
    if args.command == "probe":
        if os.geteuid() != 0:
            print("ERROR: run with sudo (probe reads broker secrets)", file=sys.stderr)
            return 2
        return _probe(args.broker)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
