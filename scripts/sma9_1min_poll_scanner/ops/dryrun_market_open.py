#!/usr/bin/env python3
"""Market-open dry run for the DEPLOYED sma9_1min_poll live runner.

What it proves
--------------
The exact deployed file
/opt/tradingai/sma9_1min_poll_scanner/app/live_sma9_1min_poll_scanner.py
is driven through the same branches its main loop uses, with a fake clock and
a fake Kite feed:

  08:55  pre-market branch  -> writes heartbeat, no scan
  09:00  scanner starts     -> resolves spot/ATM/expiry/contracts, no entry
  09:20  entry window       -> BUY at live LTP, 5% stop available
  09:20  same candle again  -> no duplicate entry
  09:22  LTP below 5% stop  -> STOP_LOSS_5PCT at the theoretical stop
  09:25  next candle        -> re-entry
  restart                   -> open position + trail state recovered

It also checks that the poll is minute-aligned and reports 60 seconds.

No network, no broker, no writes to the live DB: SMA9_1MIN_POLL_DB_PATH points
at a throw-away file.  Exit code 0 only if every assertion passes.
"""

import importlib.util
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DRY_DB = "/tmp/dryrun_sma9_1min_poll.db"
RUNNER = ("/opt/tradingai/sma9_1min_poll_scanner/app/"
          "live_sma9_1min_poll_scanner.py")

for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(DRY_DB + suffix)
    except FileNotFoundError:
        pass
os.environ["SMA9_1MIN_POLL_DB_PATH"] = DRY_DB
sys.path.insert(0, "/opt/tradingai/sma9_1min_poll_scanner")

spec = importlib.util.spec_from_file_location("live_sma9_1min_poll_scanner",
                                              RUNNER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

IST = ZoneInfo("Asia/Kolkata")
assert mod.DB_PATH == DRY_DB, f"refusing to run: DB_PATH={mod.DB_PATH}"

clock = {"now": datetime(2026, 11, 19, 8, 55, 0, tzinfo=IST)}
mod.now_ist = lambda: clock["now"]

FAILS = []


def at(h, m, s=0):
    clock["now"] = datetime(2026, 11, 19, h, m, s, tzinfo=IST)


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        print(f"  FAIL  {label}  [{detail}]")
        FAILS.append(label)


def loop_step(scanner):
    """Mirror of the branch selection inside main()."""
    now = mod.now_ist()
    if not mod.is_weekday(now):
        state = scanner.scan()
        state["errors"] = list(state.get("errors", [])) + ["weekend"]
        mod.save_scan_state(state)
        return "weekend", state
    if now.time() < mod.session_open_time(now):
        state = scanner._status(now, {}, errors=["pre-market"])
        mod.save_scan_state(state)
        return "pre-market", state
    if now.time() >= mod.session_close_time(now) and not any(
            s.position for s in scanner.states.values()):
        state = scanner._status(now, {}, errors=["market closed"])
        mod.save_scan_state(state)
        return "market closed", state
    state = scanner.scan()
    mod.save_scan_state(state)
    return "scan", state


def db_rows(sql, params=()):
    conn = sqlite3.connect(DRY_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


class FakeFeed:
    def __init__(self):
        self.instrument_refreshes = 0
        self.spot = 25237.5
        self.strike = 25250.0
        self.expiry = date(2026, 11, 23)
        self.ltp = {"CE": 122.0, "PE": 118.0}

    def refresh_instruments(self):
        self.instrument_refreshes += 1

    def nearest_expiry(self):
        return self.expiry

    def find_contract(self, strike, expiry, option_type):
        return {
            "tradingsymbol": f"NIFTY26NOV{int(strike)}{option_type}",
            "instrument_token": 1001 if option_type == "CE" else 1002,
            "strike": float(strike),
            "expiry": expiry,
        }

    def quote(self, symbols):
        out = {"NSE:NIFTY 50": {"last_price": self.spot}}
        for opt in ("CE", "PE"):
            sym = f"NFO:NIFTY26NOV{int(self.strike)}{opt}"
            if sym in symbols:
                out[sym] = {"last_price": self.ltp[opt]}
        return out

    def _rows(self, opt):
        start = mod.floor_5m(clock["now"])
        rows = []
        for i in range(20, 0, -1):
            ts = start - timedelta(minutes=5 * i)
            if opt == "CE":
                close = 100.0 + (20 - i)
                open_ = close - 1.0
            else:
                close = 140.0 - (20 - i)
                open_ = close + 1.0
            rows.append({"start": ts, "open": open_, "high": close + 1,
                         "low": open_ - 1, "close": close, "volume": 1000})
        if opt == "CE":
            rows.append({"start": start, "open": 122.0, "high": 123.0,
                         "low": 120.0, "close": 121.5, "volume": 500})
        else:
            rows.append({"start": start, "open": 118.0, "high": 119.0,
                         "low": 116.0, "close": 117.0, "volume": 500})
        return rows

    def candles(self, token, force=False):
        return self._rows("CE" if token == 1001 else "PE")

    def candle_at(self, token, candle_start, retries=1):
        for r in self.candles(token):
            if r["start"] == candle_start:
                return r
        return None


def main():
    print(f"runner : {RUNNER}")
    print(f"temp DB: {mod.DB_PATH}\n")

    mod.init_db()
    feed = FakeFeed()
    scanner = mod.Sma9OneMinPollLiveScanner(feed)

    # ---------------------------------------------------------------- poll
    print("[poll] 60-second minute-aligned sleep")
    at(9, 10, 5)
    sleeps = []
    real_sleep = mod.time.sleep
    mod.time.sleep = lambda s: sleeps.append(s)
    try:
        mod.sleep_to_next_tick()
    finally:
        mod.time.sleep = real_sleep
    check("poll constant is 60s", mod.POLL_SECONDS == 60, mod.POLL_SECONDS)
    check("sleep targets the next minute",
          len(sleeps) == 1 and abs(sleeps[0] - 55.0) < 0.01, sleeps)

    # ---------------------------------------------------------------- 08:55
    print("\n[08:55] pre-market (process already running since yesterday)")
    at(8, 55)
    branch, st = loop_step(scanner)
    check("pre-market branch selected", branch == "pre-market", branch)
    check("no scan attempted before open", st.get("last_scan_at") is None)
    state_rows = db_rows(
        "SELECT value FROM sma9_1min_poll_scan_state WHERE key='live_status'")
    check("heartbeat written", len(state_rows) == 1)
    check("market reported closed",
          json.loads(state_rows[0]["value"])["market_open"] is False)
    check("status reports 60s poll",
          json.loads(state_rows[0]["value"])["poll_seconds"] == 60)

    # ---------------------------------------------------------------- 09:00
    print("\n[09:00] scanner starts")
    at(9, 0, 5)
    branch, st = loop_step(scanner)
    check("scan branch selected", branch == "scan", branch)
    check("spot resolved", st.get("spot") == 25237.5, st.get("spot"))
    check("ATM strike resolved", st.get("atm_strike") == 25250.0,
          st.get("atm_strike"))
    check("nearest expiry resolved", st.get("expiry") == "2026-11-23",
          st.get("expiry"))
    check("CE contract resolved",
          st["options"]["CE"]["tradingsymbol"].endswith("25250CE"),
          st["options"]["CE"].get("tradingsymbol"))
    check("PE contract resolved",
          st["options"]["PE"]["tradingsymbol"].endswith("25250PE"),
          st["options"]["PE"].get("tradingsymbol"))
    check("09:00 scan is not tradable yet",
          not mod.entry_window_is_open(clock["now"]))
    check("no entry at 09:00",
          not any(s.position for s in scanner.states.values()))
    check("heartbeat has last_scan_at", st.get("last_scan_at") is not None)

    # ---------------------------------------------------------------- 09:20
    print("\n[09:20] entry window opens")
    at(9, 20, 5)
    branch, st = loop_step(scanner)
    ce = scanner.states["CE"].position
    check("scan branch selected", branch == "scan", branch)
    check("CE entered", ce is not None)
    check("PE stays flat (its SMA9 conditions are false)",
          scanner.states["PE"].position is None)
    if ce:
        check("entry price is the live LTP", ce.entry_price == 122.0,
              ce.entry_price)
        check("condition A recorded", ce.condition_a is True)
        check("condition B recorded", ce.condition_b is True)
        check("5% stop is 115.90",
              scanner.states["CE"].check_stop_loss(115.89) == 115.9,
              scanner.states["CE"].check_stop_loss(115.89))
        check("stop is not hit at entry",
              scanner.states["CE"].check_stop_loss(122.0) is None)
    open_rows = db_rows("SELECT * FROM sma9_1min_poll_open_positions")
    check("open position persisted",
          len(open_rows) == 1 and open_rows[0]["option_type"] == "CE")
    check("no closed trade yet",
          len(db_rows("SELECT * FROM sma9_1min_poll_trades")) == 0)
    check("live state exposes SMA9 signal",
          st["options"]["CE"].get("sma9") is not None
          and st["options"]["CE"].get("signal") is True,
          f"sma9={st['options']['CE'].get('sma9')}")

    # ---------------------------------------------------------------- 09:20:30
    print("\n[09:20:30] same 5m candle, poll again")
    at(9, 20, 30)
    loop_step(scanner)
    check("no duplicate entry on same candle",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 1)

    # ---------------------------------------------------------------- 09:22
    print("\n[09:22] LTP trades through the 5% stop")
    feed.ltp["CE"] = 114.9
    at(9, 22, 0)
    branch, st = loop_step(scanner)
    trades = db_rows("SELECT * FROM sma9_1min_poll_trades")
    check("trade closed", len(trades) == 1)
    if trades:
        t = trades[0]
        check("exit reason STOP_LOSS_5PCT",
              t["exit_reason"] == "STOP_LOSS_5PCT", t["exit_reason"])
        check("filled at the theoretical 5% stop", t["exit_price"] == 115.9,
              f"exit={t['exit_price']}")
        check("P&L reflects the stop fill",
              abs(t["pnl_points"] - (115.9 - 122.0)) < 0.01, t["pnl_points"])
        check("entry conditions persisted",
              t["condition_a"] == 1 and t["condition_b"] == 1)
    check("open position cleared",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 0)
    check("today stats count the stop",
          st["today"]["trades"] == 1 and st["today"]["losses"] == 1,
          st["today"])

    # ---------------------------------------------------------------- 09:25
    print("\n[09:25] next candle: re-entry allowed")
    feed.ltp["CE"] = 122.0
    at(9, 25, 5)
    loop_step(scanner)
    ce2 = scanner.states["CE"].position
    check("re-entry after stop", ce2 is not None)
    check("one entry per candle rule intact",
          ce2 is not None
          and ce2.entry_candle_start == mod.floor_5m(clock["now"]))
    check("one open-position row after re-entry",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 1)

    # Trail state before restart: +6 -> breakeven lock at entry + 2.
    if ce2:
        scanner.states["CE"].update_trail(128.0)
        check("breakeven lock before restart",
              ce2.stop == 124.0 and ce2.be_locked is True,
              f"stop={ce2.stop} be={ce2.be_locked}")

    # ---------------------------------------------------------------- 09:26
    print("\n[09:26] poll above the trail stop persists the ratchet")
    feed.ltp["CE"] = 130.0
    at(9, 26, 0)
    loop_step(scanner)
    if ce2:
        check("trail ratcheted to peak-5",
              ce2.stop == 125.0 and ce2.hwm == 130.0,
              f"stop={ce2.stop} hwm={ce2.hwm}")
        check("breakeven lock stays on", ce2.be_locked is True)
    check("still one open position after the poll",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 1)

    # ---------------------------------------------------------------- restart
    print("\n[09:27] scanner restart mid-position")
    saved = dict(vars(ce2)) if ce2 else {}
    scanner2 = mod.Sma9OneMinPollLiveScanner(FakeFeed())
    scanner2.recover_open_positions()
    ce3 = scanner2.states["CE"].position
    check("open position recovered", ce3 is not None)
    if ce3:
        check("same trade id", ce3.trade_id == saved["trade_id"])
        check("5% entry price preserved", ce3.entry_price == saved["entry_price"])
        check("trail stop preserved", ce3.stop == saved["stop"],
              f"{ce3.stop} vs {saved['stop']}")
        check("breakeven lock preserved", ce3.be_locked == saved["be_locked"])
        check("HWM preserved", ce3.hwm == saved["hwm"])
    check("recovered row still in DB",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 1)

    # ---------------------------------------------------------------- 09:31
    print("\n[09:31] restart after the entry candle ended (same session)")
    at(9, 31, 0)
    scanner3 = mod.Sma9OneMinPollLiveScanner(FakeFeed())
    scanner3.recover_open_positions()
    ce4 = scanner3.states["CE"].position
    check("position survives a candle boundary", ce4 is not None)
    check("trail stop still preserved", ce4 is not None and ce4.stop == 125.0,
          ce4.stop if ce4 else None)
    check("no candle-close exit was written",
          len(db_rows("SELECT * FROM sma9_1min_poll_trades")) == 1)

    # ------------------------------------------------------ stale (prior day)
    print("\n[09:32] stale position from a previous session")
    conn = sqlite3.connect(DRY_DB)
    conn.execute(
        "UPDATE sma9_1min_poll_open_positions SET entry_timestamp=?, "
        "entry_candle_start=?, entry_candle_end=? WHERE option_type='CE'",
        ("2026-11-18T09:25:05+05:30", "2026-11-18T09:25:00+05:30",
         "2026-11-18T09:30:00+05:30"))
    conn.commit()
    conn.close()
    at(9, 32, 0)
    scanner4 = mod.Sma9OneMinPollLiveScanner(FakeFeed())
    scanner4.recover_open_positions()
    check("stale position not carried", scanner4.states["CE"].position is None)
    trades = db_rows("SELECT * FROM sma9_1min_poll_trades "
                     "WHERE exit_reason='STALE_RECOVERY_EXIT'")
    check("stale position closed at LTP",
          len(trades) == 1 and trades[0]["exit_price"] == 122.0,
          trades[0]["exit_price"] if trades else None)
    check("stale open row removed",
          len(db_rows("SELECT * FROM sma9_1min_poll_open_positions")) == 0)

    # ---------------------------------------------------------------- summary
    print("\n" + "=" * 68)
    if FAILS:
        print(f"DRY RUN FAILED: {len(FAILS)} assertion(s): {FAILS}")
        return 1
    print("DRY RUN PASSED: deployed runner opens, enters, stops and recovers")
    print(f"temp DB left at {DRY_DB} (live DB untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
