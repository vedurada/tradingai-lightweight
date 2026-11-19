#!/usr/bin/env python3
"""Pattern Scanner live runner — VM deployment.

Connects to Zerodha Kite Connect for NIFTY spot 5-minute ticks,
resolves ATM CE/PE option symbols, and feeds option prices to the
PatternScanner engine. Detects bullish patterns on ATM option candles.

Runs as a systemd service on the TradingAI VM.
No broker orders. Paper trading only.
"""

from __future__ import annotations

import os
import sys
import time as time_module
import json
import signal
import threading
from datetime import datetime, time, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)

VM_ROOT = os.environ.get("TRADINGAI_BASE", "/opt/tradingai")
STATUS_FILE = os.path.join(VM_ROOT, "data", "pattern_scanner_status.json")
sys.path.insert(0, VM_ROOT)
sys.path.insert(0, os.path.join(VM_ROOT, "app"))

from app.research.pattern_scanner import (  # noqa: E402
    PatternScanner, is_market_open, now_ist, round_to_strike,
)
from app.core.db import get_conn  # noqa: E402

# Optional Zerodha feed
KITE_AVAILABLE = False
try:
    from kiteconnect import KiteConnect  # type: ignore
    KITE_AVAILABLE = True
except Exception:
    KITE_AVAILABLE = False


def load_zerodha_credentials() -> dict:
    env_path = os.path.join(VM_ROOT, ".env.zerodha")
    creds = {}
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip()
    except Exception as e:
        print(f"[ps-live] Could not load credentials: {e}")
    return creds


class KiteOptionFeed:
    """Zerodha Kite Connect feed for NIFTY spot + ATM option prices.

    The NFO instrument dump is large and rate-limited, so it is fetched once
    and cached (not on every poll). Quotes for spot + all option symbols are
    batched into a single Kite quote call per poll.
    """

    # NIFTY 50 index token is stable; used as a fallback if the NSE lookup fails.
    NIFTY_SPOT_TOKEN = 256265

    def __init__(self):
        self.kite = None
        self.spot_token = self.NIFTY_SPOT_TOKEN
        self.available = False
        self.nfo_instruments = []
        self.nfo_index = {}
        self.nfo_expiries = []
        self.nfo_loaded_at = 0.0
        self.nfo_retry_at = 0.0
        self._load()

    def _load(self):
        creds = load_zerodha_credentials()
        if not creds.get("KITE_API_KEY") or not creds.get("KITE_ACCESS_TOKEN"):
            print("[ps-live] Kite credentials not set; running without live feed")
            return
        try:
            self.kite = KiteConnect(api_key=creds["KITE_API_KEY"])
            self.kite.set_access_token(creds["KITE_ACCESS_TOKEN"])
            self.kite.profile()  # verify
            self.available = True
            # Resolve NIFTY spot token (fallback stays 256265 if this fails).
            try:
                for inst in self.kite.instruments("NSE"):
                    if (inst.get("name") in ("NIFTY", "NIFTY 50")
                            and inst.get("instrument_type") in ("EQ", "INDEX")
                            and inst.get("segment") == "INDICES"):
                        self.spot_token = inst["instrument_token"]
                        break
            except Exception as e:
                print(f"[ps-live] NSE instrument lookup failed, using token "
                      f"{self.spot_token}: {e}")
            print(f"[ps-live] Kite connected. NIFTY spot token: {self.spot_token}")
        except Exception as e:
            print(f"[ps-live] Kite not available: {e}")

    def get_nfo_instruments(self, max_age=21600):
        """Return the cached NFO instrument dump (refresh at most every 6h).

        Never raises: on a Kite error it keeps the previous cache and waits
        60s before retrying, so a rate-limit window cannot kill the poll loop.
        """
        now = time_module.time()
        if not self.available or not self.kite:
            return self.nfo_instruments
        if (self.nfo_instruments
                and self.nfo_loaded_at
                and now - self.nfo_loaded_at < max_age):
            return self.nfo_instruments
        if now < self.nfo_retry_at:
            return self.nfo_instruments
        try:
            data = self.kite.instruments("NFO")
            index = {}
            expiries = set()
            for inst in data:
                if (inst.get("name") != "NIFTY"
                        or inst.get("instrument_type") not in ("CE", "PE")):
                    continue
                expiry = inst.get("expiry")
                strike = inst.get("strike")
                if expiry is None or strike is None:
                    continue
                key = (float(strike), expiry, inst["instrument_type"])
                index.setdefault(key, []).append(inst)
                expiries.add(expiry)
            self.nfo_instruments = data
            self.nfo_index = index
            self.nfo_expiries = sorted(expiries)
            self.nfo_loaded_at = now
            self.nfo_retry_at = 0.0
            print(f"[ps-live] NFO instruments cached: {len(data)} rows, "
                  f"{len(expiries)} NIFTY expiries")
        except Exception as e:
            self.nfo_retry_at = now + 60
            print(f"[ps-live] NFO instruments load error (retry in 60s): {e}")
        return self.nfo_instruments

    def nifty_expiries(self):
        self.get_nfo_instruments()
        return self.nfo_expiries

    def find_option(self, strike, expiry, option_type):
        self.get_nfo_instruments()
        matches = self.nfo_index.get((float(strike), expiry, option_type), [])
        if not matches:
            return None
        matches.sort(key=lambda i: i.get("instrument_token") or 0)
        return matches[0].get("tradingsymbol")

    def quote_snapshot(self, option_symbols):
        """One Kite quote call for spot + options.

        Returns (spot_ltp, {tradingsymbol: ltp}). Never raises.
        """
        if not self.available or not self.kite:
            return None, {}
        symbols = []
        for sym in option_symbols:
            if sym and sym not in symbols:
                symbols.append(sym)
        keys = []
        if self.spot_token:
            keys.append(str(self.spot_token))
        opt_keys = [f"NFO:{sym}" for sym in symbols]
        keys.extend(opt_keys)
        try:
            q = self.kite.quote(keys)
        except Exception as e:
            print(f"[ps-live] quote error: {e}")
            return None, {}
        spot = None
        if self.spot_token:
            try:
                spot = float(q[str(self.spot_token)]["last_price"])
            except Exception:
                pass
        prices = {}
        for sym, key in zip(symbols, opt_keys):
            data = q.get(key)
            if data:
                try:
                    prices[sym] = float(data["last_price"])
                except Exception:
                    pass
        return spot, prices

    def quote_spot(self) -> float | None:
        spot, _ = self.quote_snapshot([])
        return spot

    def quote_option(self, symbol: str) -> float | None:
        """Quote an option by tradingsymbol like 'NIFTY26N1725300CE'."""
        _, prices = self.quote_snapshot([symbol])
        return prices.get(symbol)


class MockFeed:
    """Fallback feed that replays from DB candle cache or returns None."""

    def __init__(self):
        self.available = True
        print("[ps-live] Mock feed active (no live market data)")

    def quote_spot(self) -> float | None:
        try:
            conn = get_conn()
            row = conn.execute(
                "SELECT close FROM market_candles_5m "
                "WHERE instrument_id='NIFTY' ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                return float(row[0])
        except Exception:
            pass
        return None

    def quote_option(self, symbol: str) -> float | None:
        return None

    def quote_snapshot(self, option_symbols):
        return self.quote_spot(), {}


class PatternScannerLive:
    def __init__(self):
        self.ps = PatternScanner(get_conn)
        self.feed = KiteOptionFeed() if KITE_AVAILABLE else MockFeed()
        if not self.feed.available:
            self.feed = MockFeed()
        self.running = False
        self.thread = None
        self.poll = 5.0  # seconds

    def start(self):
        self.running = True
        self.ps.status = "RUNNING"
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[ps-live] Pattern Scanner live runner started")

    def _loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                print(f"[ps-live] loop error: {e}")
            time_module.sleep(self.poll)

    def _resolve_option_symbols(self, spot):
        """Resolve ATM CE/PE from the cached NFO instrument index.

        No per-poll instrument download: the dump is cached by the feed.
        """
        atm = round_to_strike(spot)
        today = now_ist().date()
        if not hasattr(self.feed, "nifty_expiries"):
            return None, None, atm, None
        expiries = [e for e in self.feed.nifty_expiries()
                    if e is not None and e >= today]
        if not expiries:
            return None, None, atm, None
        expiry = expiries[0]
        ce_sym = self.feed.find_option(atm, expiry, "CE")
        pe_sym = self.feed.find_option(atm, expiry, "PE")
        return ce_sym, pe_sym, atm, expiry

    def _tick(self):
        now = now_ist()
        if not is_market_open(now):
            self.ps.status = "MARKET_CLOSED"
            # Positions are held across candles/overnight: no time-based exit.
            # Still fetch spot price for dashboard display
            spot = self.feed.quote_spot()
            if spot is not None:
                self.ps.last_spot = spot
                self.ps.last_update = now.isoformat()
                if hasattr(self.feed, "kite") and self.feed.kite:
                    ce_sym, pe_sym, atm, expiry = self._resolve_option_symbols(spot)
                    if ce_sym and pe_sym:
                        self.ps.set_option_instruments(ce_sym, pe_sym, atm, expiry)
            try:
                os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
                status = self.ps.get_status()
                with open(STATUS_FILE, "w") as f:
                    json.dump(status, f)
            except Exception:
                pass
            return
        self.ps.status = "RUNNING"

        # 1. Instruments we need prices for: current ATM CE/PE plus every
        #    instrument with an active position (the ATM band may have moved).
        symbols = []
        for sym in (self.ps.ce_symbol, self.ps.pe_symbol):
            if sym and sym not in symbols:
                symbols.append(sym)
        for pos in list(self.ps.positions.values()):
            if pos.instrument and pos.instrument not in symbols:
                symbols.append(pos.instrument)

        # 2. One batched Kite quote call for spot + all option symbols.
        if hasattr(self.feed, "quote_snapshot"):
            spot, prices = self.feed.quote_snapshot(symbols)
        else:
            spot = self.feed.quote_spot()
            prices = {}
            for sym in symbols:
                px = self.feed.quote_option(sym)
                if px is not None:
                    prices[sym] = px

        # Feed the quoted option prices FIRST, so the spot tick below manages
        # exits and detects new entries with this poll's quotes. Previously the
        # spot tick ran first and used the previous poll's (possibly minutes
        # old) option price.
        for sym, price in prices.items():
            self.ps.on_tick(sym, price, now)

        if spot is not None:
            self.ps.on_tick("NIFTY_SPOT", spot, now)
            # Resolve ATM from the cached instrument index (no download).
            if hasattr(self.feed, "kite") and self.feed.kite:
                ce_sym, pe_sym, atm, expiry = self._resolve_option_symbols(spot)
                if ce_sym and pe_sym:
                    self.ps.set_option_instruments(ce_sym, pe_sym, atm, expiry)

        # Write status to file for API to read
        try:
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            status = self.ps.get_status()
            with open(STATUS_FILE, "w") as f:
                json.dump(status, f)
        except Exception as e:
            print(f"[ps-live] status write error: {e}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.ps.stop()
        print("[ps-live] Pattern Scanner live runner stopped")

    def get_status(self):
        return self.ps.get_status()


# Global instance
scanner = None


def handle_signal(signum, frame):
    global scanner
    if scanner:
        scanner.stop()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    scanner = PatternScannerLive()
    scanner.start()
    try:
        while True:
            time_module.sleep(2)
    except KeyboardInterrupt:
        scanner.stop()
