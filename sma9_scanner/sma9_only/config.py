#!/usr/bin/env python3
"""SMA9 Scanner Configuration - BUY ONLY.

Both ATM CE and ATM PE use the same long-only rule set:

Qualification at a 5-minute candle boundary (per option, from its own candles):
  A) previous completed candle CLOSE > SMA9 of the 9 completed candles
     ending at that previous candle
  OR
  B) current forming candle OPEN > the same SMA9

Execution confirmation:
  live option LTP > the same SMA9

Entry: paper BUY immediately when qualified and confirmed.
Exit:  at the CLOSE of the entry 5-minute candle (no carry forward).

SMA9 is always computed from completed candles only; the current candle's
close is never used.  There is no PE-short / bearish branch.
"""

from dataclasses import dataclass
from typing import List

STRATEGY_ID = "sma9_only"
STRATEGY_NAME = "SMA9 Only - ATM Option Strike (BUY ONLY)"
STRATEGY_VERSION = "2.0.0"
STRATEGY_TYPE = "SMA9_BUY_ONLY"
INSTRUMENT = "NIFTY"
TIMEFRAME = "5m"
MARKET_SESSION = "REGULAR"

# SMA parameters
SMA_PERIOD = 9
# Fallback strike used by the offline package only.  The live scanner derives
# the ATM strike from the current NIFTY spot on every poll.
ATM_STRIKE = 22950
OPTION_TYPES = ["CE", "PE"]

# Entry rules (identical for CE and PE):
#   A) previous completed candle CLOSE > SMA9  OR
#   B) current forming candle OPEN > SMA9
#   Confirmation: live LTP > SMA9
# Both options are BUY-only.  Never short an option.

# Exit rules
# Same-candle exit at CLOSE.  The last tradable candle starts at 15:25 and
# closes at 15:30 IST.
SESSION_EXIT_TIME = "15:30"
NO_OVERNIGHT = True

# Risk
# Independent CE and PE state machines may each hold one position, so the
# portfolio can hold at most two simultaneous long option positions.
MAX_POSITIONS = 2


@dataclass
class ScannerConfig:
    scanner_id: str = STRATEGY_ID
    scanner_name: str = STRATEGY_NAME
    scanner_version: str = STRATEGY_VERSION
    strategy_type: str = STRATEGY_TYPE
    instrument: str = INSTRUMENT
    timeframe: str = TIMEFRAME
    market_session: str = MARKET_SESSION
    sma_period: int = SMA_PERIOD
    atm_strike: int = ATM_STRIKE
    option_types: List[str] = None  # type: ignore
    max_positions: int = MAX_POSITIONS
    no_overnight: bool = NO_OVERNIGHT
    session_exit_time: str = SESSION_EXIT_TIME

    def __post_init__(self):
        if self.option_types is None:
            self.option_types = OPTION_TYPES
