#!/usr/bin/env python3
"""Pattern Scanner live runner — VM deployment.

Connects through the read-only broker gateway (Kite-compatible facade) for
NIFTY spot prices, resolves ATM CE/PE option symbols, and feeds completed
5-minute option OHLC bars to the
PatternScanner engine. Polls once per aligned 5-minute bar, matching the 5m
backtest replay; this scanner does not use a 5-second loop.

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

# Pattern scanner is intentionally aligned with the 5m backtest replay:
# one poll per completed 5-minute bar, a few seconds after the boundary so
# the exchange has published that bar. Other scanners keep their 5s cadence.
POLL_INTERVAL_SEC = 300
POLL_OFFSET_SEC = 10

VM_ROOT = os.environ.get("TRADINGAI_BASE", "/opt/tradingai")
STATUS_FILE = os.path.join(VM_ROOT, "data", "pattern_scanner_status.json")
sys.path.insert(0, VM_ROOT)
sys.path.insert(0, os.path.join(VM_ROOT, "app"))

from app.research.pattern_scanner import (  # noqa: E402
    PatternScanner, floor_5min, is_market_open, now_ist, round_to_strike,
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


def _as_ist_datetime(value):
    """Normalise a Kite/gateway bar timestamp to IST."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


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
        # The full NFO dump (~94k dicts) is only needed while building the
        # filtered NIFTY CE/PE index. Retaining it just to flag "loaded" costs
        # >100 MB per process, so keep only a flag and the compact index.
        self.nfo_loaded = False
        self.nfo_rows = 0
        self.nfo_index = {}
        self.option_tokens: dict[str, int] = {}
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
            return self.nfo_index
        if self.nfo_loaded and self.nfo_loaded_at and now - self.nfo_loaded_at < max_age:
            return self.nfo_index
        if now < self.nfo_retry_at:
            return self.nfo_index
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
                if inst.get("instrument_token") and inst.get("tradingsymbol"):
                    self.option_tokens[inst["tradingsymbol"]] = int(
                        inst["instrument_token"])
                expiries.add(expiry)
            self.nfo_rows = len(data)
            self.nfo_index = index
            self.nfo_expiries = sorted(expiries)
            self.nfo_loaded = True
            self.nfo_loaded_at = now
            self.nfo_retry_at = 0.0
            # `data` goes out of scope here: only the filtered NIFTY CE/PE
            # entries referenced by index stay in memory.
            print(f"[ps-live] NFO instruments indexed: {len(data)} rows, "
                  f"{len(expiries)} NIFTY expiries")
        except Exception as e:
            self.nfo_retry_at = now + 60
            print(f"[ps-live] NFO instruments load error (retry in 60s): {e}")
        return self.nfo_index

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

    def option_token(self, symbol: str):
        """Instrument token for a cached NIFTY option tradingsymbol."""
        self.get_nfo_instruments()
        return self.option_tokens.get(symbol)

    def completed_5m_bar(self, symbol: str, expected_start):
        """Return the completed 5m OHLC bar for `symbol`, or None.

        One read-only historical_data call per option per 5-minute poll. The
        expected start is the previous 5m boundary; a forming/mismatched bar
        is never returned.
        """
        if not self.available or not self.kite:
            return None
        token = self.option_token(symbol)
        if not token:
            return None
        expected_start = _as_ist_datetime(expected_start)
        end = expected_start + timedelta(minutes=5)
        try:
            raw = self.kite.historical_data(token, expected_start, end, "5minute")
        except Exception as e:
            print(f"[ps-live] historical error for {symbol}: {e}")
            return None
        for row in raw or []:
            try:
                start = _as_ist_datetime(row["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if start != expected_start:
                continue
            return {
                "start": start,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
            }
        return None

    def last_closed_nifty_bar(self, now):
        """Latest completed NIFTY 50 index 5m bar from mStock token 26000."""
        if not self.available or not self.kite:
            return None
        cutoff = floor_5min(now)
        start = _as_ist_datetime(now) - timedelta(days=7)
        try:
            raw = self.kite.historical_data(26000, start, now, "5minute")
        except Exception as e:
            print(f"[ps-live] NIFTY index history error: {e}")
            return None
        latest = None
        for row in raw or []:
            try:
                bar_start = _as_ist_datetime(row["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if bar_start >= cutoff:
                continue
            if latest is None or bar_start > latest["start"]:
                latest = {"start": bar_start, "close": float(row["close"])}
        return latest

    def last_closed_5m_bar(self, symbol: str, now):
        """Latest completed 5m OHLC bar for `symbol`, or None.

        Used when index history is unavailable: the latest CE/PE bar pair gives
        the last completed NIFTY spot close via strike + CE - PE parity.
        """
        if not self.available or not self.kite:
            return None
        token = self.option_token(symbol)
        if not token:
            return None
        cutoff = floor_5min(now)
        start = _as_ist_datetime(now) - timedelta(days=5)
        try:
            raw = self.kite.historical_data(token, start, now, "5minute")
        except Exception as e:
            print(f"[ps-live] historical error for {symbol}: {e}")
            return None
        latest = None
        for row in raw or []:
            try:
                bar_start = _as_ist_datetime(row["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if bar_start >= cutoff:
                continue
            if latest is None or bar_start > latest["start"]:
                latest = {
                    "start": bar_start,
                    "close": float(row["close"]),
                }
        return latest

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

    def completed_5m_bar(self, symbol, expected_start):
        return None


class PatternScannerLive:
    def __init__(self):
        self.ps = PatternScanner(get_conn)
        self.feed = KiteOptionFeed() if KITE_AVAILABLE else MockFeed()
        # A MockFeed has no option prices and may replay stale spot from the DB.
        # Never advertise it as a healthy RUNNING live scanner: downstream
        # operators/read the status to decide whether prices can be trusted.
        self.live_feed_ok = bool(
            self.feed is not None
            and not isinstance(self.feed, MockFeed)
            and getattr(self.feed, "available", False)
        )
        if not self.live_feed_ok:
            print("[ps-live] WARNING: no live Kite feed; status will report "
                  "NO_LIVE_FEED (mock fallback has no option prices)")
            self.feed = MockFeed()
        self.running = False
        self.thread = None
        self.poll = POLL_INTERVAL_SEC  # aligned 5m cadence, not 5s
        # A completed 5m bar whose historical fetch failed on its own poll is
        # retried on the next aligned poll so a transient gateway error cannot
        # silently lose that bar's premium exit.
        self._pending_bars: dict[str, datetime] = {}
        self._failed_bar_symbols: set[str] = set()

    @staticmethod
    def next_poll_time(now: datetime) -> datetime:
        """Next aligned 5m poll: boundary + small publication offset."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        candidate = now.replace(
            minute=(now.minute // 5) * 5,
            second=POLL_OFFSET_SEC,
            microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(minutes=5)
        return candidate.astimezone(IST)

    def _sleep_until_next_poll(self):
        delay = (self.next_poll_time(now_ist()) - now_ist()).total_seconds()
        if delay > 0:
            time_module.sleep(delay)

    def _fetch_completed_bars(self, symbols, now):
        """Fetch each symbol's previous completed 5m bar, retrying a failure.

        A bar that failed on its own poll is retried exactly once, on the next
        poll and before the newly completed bar, so a transient gateway error
        cannot silently lose an exit without breaking chronological evaluation.
        """
        if not hasattr(self.feed, "completed_5m_bar"):
            return
        target = floor_5min(now) - timedelta(minutes=5)
        for sym in symbols:
            pending = self._pending_bars.pop(sym, None)
            starts = []
            if pending is not None and pending < target:
                starts.append(pending)
            starts.append(target)
            for start in starts:
                bar = self.feed.completed_5m_bar(sym, start)
                if not bar:
                    self._failed_bar_symbols.add(sym)
                    if start == target:
                        self._pending_bars[sym] = start
                    continue
                self.ps.on_option_bar(sym, bar, now)

    def _refresh_last_closed_spot(self, now):
        """Fill last completed 5m spot from the real NIFTY index bar.

        Option CE/PE parity was unreliable: frozen zero-volume option bars can
        imply a spot hundreds of points away from the index close. The NIFTY
        index history on token 26000 is authoritative.
        """
        if not hasattr(self.feed, "last_closed_nifty_bar"):
            return
        try:
            bar = self.feed.last_closed_nifty_bar(now)
            if not bar:
                return
            spot = float(bar["close"])
            self.ps.last_closed_spot = round(spot, 2)
            self.ps.last_closed_atm_strike = float(round(spot / 50.0) * 50)
            self.ps.last_closed_candle_start = bar["start"].isoformat()
            self.ps.last_closed_ce_close = None
            self.ps.last_closed_pe_close = None
            self.ps.last_closed_spot_source = "nifty_index_5m_close"
        except Exception as e:
            print(f"[ps-live] last-closed spot error: {e}")

    def _status_snapshot(self) -> dict:
        """Status with explicit feed-health fields for the API/dashboard."""
        status = self.ps.get_status()
        status["spot_source"] = getattr(self.ps, "spot_source", "broker_quote")
        live = bool(self.live_feed_ok and getattr(self.feed, "available", False))
        failed_bars = sorted(getattr(self, "_failed_bar_symbols", set()))
        status["data_available"] = live
        status["exit_data_available"] = live and not failed_bars
        status["feed"] = "live" if live else "mock"
        status["poll_interval_sec"] = int(getattr(self, "poll", POLL_INTERVAL_SEC))
        status["poll_alignment"] = "5m_boundary_plus_10s"
        status["exit_data"] = "completed_5m_option_ohlc"
        errors = list(status.get("errors") or [])
        if not live:
            msg = ("no live broker feed; mock fallback has no option prices "
                   "(market data unavailable)")
            if msg not in errors:
                errors.append(msg)
            if status.get("status") == "RUNNING":
                status["status"] = "NO_LIVE_FEED"
        if failed_bars and live:
            msg = ("completed 5m option bar unavailable for: "
                   + ", ".join(failed_bars))
            if msg not in errors:
                errors.append(msg)
            if status.get("status") == "RUNNING":
                status["status"] = "NO_OPTION_DATA"
        status["errors"] = errors
        return status

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
            self._sleep_until_next_poll()

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
        self._failed_bar_symbols.clear()
        if not is_market_open(now):
            self.ps.status = "MARKET_CLOSED"
            # Positions are held across candles/overnight: no time-based exit.
            # Still fetch spot price for dashboard display
            spot = self.feed.quote_spot()
            if spot is not None:
                self.ps.last_spot = spot
                self.ps.spot_source = "broker_quote"
                self.ps.last_update = now.isoformat()
                if hasattr(self.feed, "kite") and self.feed.kite:
                    ce_sym, pe_sym, atm, expiry = self._resolve_option_symbols(spot)
                    if ce_sym and pe_sym:
                        self.ps.set_option_instruments(ce_sym, pe_sym, atm, expiry)
                        self._refresh_last_closed_spot(now)
                if self.ps.last_closed_spot is not None:
                    if (self.ps.last_spot is None
                            or abs(float(self.ps.last_spot) - self.ps.last_closed_spot) > 50):
                        self.ps.last_spot = self.ps.last_closed_spot
                        self.ps.spot_source = "index_close_fallback"
                        self.ps.current_atm_strike = int(
                            round(float(self.ps.last_closed_spot) / 50.0) * 50
                        )
            try:
                os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
                status = self._status_snapshot()
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

        # 2. One batched Kite quote call for spot + all option symbols. The
        #    LTP is the entry price at the spot candle-close poll; exits use
        #    the completed 5m OHLC bar fetched below.
        if hasattr(self.feed, "quote_snapshot"):
            spot, prices = self.feed.quote_snapshot(symbols)
        else:
            spot = self.feed.quote_spot()
            prices = {}
            for sym in symbols:
                px = self.feed.quote_option(sym)
                if px is not None:
                    prices[sym] = px

        for sym, price in prices.items():
            self.ps.record_quote(sym, price, now)

        # 3. Completed 5m option bars: feed each symbol's bar into its buffer
        #    and evaluate premium ATR exits with the backtest's OHLC rules.
        #    A bar that failed on its own poll is retried before the new one.
        self._fetch_completed_bars(symbols, now)

        # 4. Spot tick completes the 5m spot candle and detects entries using
        #    this poll's option quotes and freshly appended option bars.
        if spot is not None:
            # Resolve/set ATM BEFORE detection so a reband poll cannot enter at
            # the previous strike with a fresh quote for the old option.
            if hasattr(self.feed, "kite") and self.feed.kite:
                ce_sym, pe_sym, atm, expiry = self._resolve_option_symbols(spot)
                if ce_sym and pe_sym:
                    self.ps.set_option_instruments(ce_sym, pe_sym, atm, expiry)
            self.ps.spot_source = "broker_quote"
            self.ps.on_tick("NIFTY_SPOT", spot, now)
        if self.ps.last_closed_spot is None:
            self._refresh_last_closed_spot(now)
        if not is_market_open(now) and self.ps.last_closed_spot is not None:
            if (self.ps.last_spot is None
                    or abs(float(self.ps.last_spot) - self.ps.last_closed_spot) > 50):
                self.ps.last_spot = self.ps.last_closed_spot
                self.ps.spot_source = "index_close_fallback"

        # Write status to file for API to read
        try:
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            status = self._status_snapshot()
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
        return self._status_snapshot()


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
