"""Zerodha paper-trading config — SHADOW enforced, no secrets committed."""
import os
BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "zerodha_execution.db")
MODE = "SHADOW"  # explicitly SHADOW; never PAPER/LIVE without auth
INSTRUMENT = "NIFTY"
# Security: no execution switch; no live mode without separate review
LIVE_EXECUTION_AUTHORIZED = False
STRATEGY_VERSION = "hlc_3bar_canonical_v1"
