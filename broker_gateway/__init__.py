"""Broker-agnostic market-data gateway for TradingAI scanners.

Scanners keep using the KiteConnect interface. The gateway translates those
read-only calls to any configured broker adapter, without scanner code changes.
"""

__version__ = "1.0.0"
