#!/usr/bin/env python3
"""Market-open dry run for the DEPLOYED sma9_atr live runner.

What it proves
--------------
The exact deployed file /opt/tradingai/sma9_atr_scanner/app/live_sma9_atr_scanner.py
is driven through the same branches its main loop uses, with a fake clock and
a fake Kite feed:

  08:55  pre-market branch  -> writes heartbeat, no scan
  09:00  scanner starts     -> resolves spot/ATM/expiry/contracts, no entry
  09:20  entry window       -> BUY at live LTP, ATR stop persisted
  09:20  same candle again  -> no duplicate entry
  09:22  LTP below stop     -> STOP_LOSS_ATR filled at the actual LTP
  09:25  next candle        -> re-entry
  restart                   -> open position + ATR stop recovered

No network, no broker, no writes to the live DB: SMA9_ATR_DB_PATH points at a
throw-away file.  Exit code 0 only if every assertion passes.
"""

import importlib.util
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DRY_DB = "/tmp/dryrun_sma9_atr.db"
RUNNER = "/opt/tradingai/sma9_atr_scanner/app/live_sma9_atr_scanner.py"

for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(DRY_DB + suffix)
    except FileNotFoundError:
        pass
os.environ["SMA9_ATR_DB_PATH"] = DRY_DB
sys.path.insert(0, "/opt/tradingai/sma9_atr_scanner")

spec = importlib.util.spec_from_file_location("live_sma9_atr_scanner", RUNNER)
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
    scanner = mod.Sma9AtrLiveScanner(feed)

    # ---------------------------------------------------------------- 08:55
    print("[08:55] pre-market (process already running since yesterday)")
    at(8, 55)
    branch, st = loop_step(scanner)
    check("pre-market branch selected", branch == "pre-market", branch)
    check("no scan attempted before open", st.get("last_scan_at") is None)
    state_rows = db_rows("SELECT value FROM sma9_atr_scan_state WHERE key='live_status'")
    check("heartbeat written", len(state_rows) == 1)
    check("market reported closed", json.loads(state_rows[0]["value"])["market_open"] is False)

    # ---------------------------------------------------------------- 09:00
    print("\n[09:00] scanner starts")
    at(9, 0, 5)
    branch, st = loop_step(scanner)
    check("scan branch selected", branch == "scan", branch)
    check("spot resolved", st.get("spot") == 25237.5, st.get("spot"))
    check("ATM strike resolved", st.get("atm_strike") == 25250.0, st.get("atm_strike"))
    check("nearest expiry resolved", st.get("expiry") == "2026-11-23", st.get("expiry"))
    check("CE contract resolved", st["options"]["CE"]["tradingsymbol"].endswith("25250CE"),
          st["options"]["CE"].get("tradingsymbol"))
    check("PE contract resolved", st["options"]["PE"]["tradingsymbol"].endswith("25250PE"),
          st["options"]["PE"].get("tradingsymbol"))
    check("09:00 scan is not tradable yet", not mod.entry_window_is_open(clock["now"]))
    check("no entry at 09:00", not any(s.position for s in scanner.states.values()))
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
        check("entry price is the live LTP", ce.entry_price == 122.0, ce.entry_price)
        check("ATR captured at entry", ce.atr_at_entry is not None, ce.atr_at_entry)
        check("ATR stop below entry", ce.stop_price < ce.entry_price,
              f"stop={ce.stop_price} entry={ce.entry_price}")
        check("stop distance within 5%-30%",
              0.05 - 1e-9 <= ce.stop_distance_pct <= 0.30 + 1e-9,
              round(ce.stop_distance_pct * 100, 2))
        check("stop source recorded", ce.stop_source in ("atr", "fallback_pct"),
              ce.stop_source)
    open_rows = db_rows("SELECT * FROM sma9_atr_open_positions")
    check("open position persisted", len(open_rows) == 1 and open_rows[0]["option_type"] == "CE")
    if open_rows:
        check("DB has atr_at_entry", open_rows[0]["atr_at_entry"] is not None,
              open_rows[0]["atr_at_entry"])
        check("DB has stop_price", open_rows[0]["stop_price"] is not None,
              open_rows[0]["stop_price"])
    check("no closed trade yet", len(db_rows("SELECT * FROM sma9_atr_trades")) == 0)
    check("live state exposes ATR + stop preview",
          st["options"]["CE"].get("atr") is not None
          and st["options"]["CE"].get("stop_preview") is not None,
          f"atr={st['options']['CE'].get('atr')} preview={st['options']['CE'].get('stop_preview')}")

    # ---------------------------------------------------------------- 09:20:15
    print("\n[09:20:15] same 5m candle, poll again")
    at(9, 20, 15)
    loop_step(scanner)
    check("no duplicate entry on same candle",
          len(db_rows("SELECT * FROM sma9_atr_open_positions")) == 1)

    # ---------------------------------------------------------------- 09:22
    print("\n[09:22] LTP trades through the stop")
    stop = scanner.states["CE"].position.stop_price
    feed.ltp["CE"] = round(stop - 1.0, 2)
    at(9, 22, 0)
    branch, st = loop_step(scanner)
    trades = db_rows("SELECT * FROM sma9_atr_trades")
    check("trade closed", len(trades) == 1)
    if trades:
        t = trades[0]
        check("exit reason STOP_LOSS_ATR", t["exit_reason"] == "STOP_LOSS_ATR", t["exit_reason"])
        check("filled at actual LTP (not theoretical stop)",
              t["exit_price"] == round(stop - 1.0, 2),
              f"exit={t['exit_price']} stop={stop}")
        check("P&L reflects the LTP fill",
              abs(t["pnl_points"] - round(t["exit_price"] - t["entry_price"], 2)) < 0.01,
              t["pnl_points"])
        check("ATR/stop persisted on the trade",
              t["atr_at_entry"] is not None and t["stop_price"] == stop)
    check("open position cleared",
          len(db_rows("SELECT * FROM sma9_atr_open_positions")) == 0)
    check("today stats count the stop",
          st["today"]["trades"] == 1 and st["today"]["stop_outs"] == 1, st["today"])

    # ---------------------------------------------------------------- 09:25
    print("\n[09:25] next candle: re-entry allowed")
    feed.ltp["CE"] = 122.0
    at(9, 25, 5)
    loop_step(scanner)
    ce2 = scanner.states["CE"].position
    check("re-entry after stop", ce2 is not None)
    check("one entry per candle rule intact",
          ce2 is not None and ce2.entry_candle_start == mod.floor_5m(clock["now"]))
    check("two open-position rows total after re-entry",
          len(db_rows("SELECT * FROM sma9_atr_open_positions")) == 1)

    # ---------------------------------------------------------------- restart
    print("\n[09:26] scanner restart mid-position")
    saved = {k: v for k, v in vars(ce2).items()}
    scanner2 = mod.Sma9AtrLiveScanner(FakeFeed())
    scanner2.recover_open_positions()
    ce3 = scanner2.states["CE"].position
    check("open position recovered", ce3 is not None)
    if ce3:
        check("same trade id", ce3.trade_id == saved["trade_id"])
        check("ATR stop preserved", ce3.stop_price == saved["stop_price"],
              f"{ce3.stop_price} vs {saved['stop_price']}")
        check("ATR preserved", ce3.atr_at_entry == saved["atr_at_entry"])
        check("HWM preserved", ce3.hwm == saved["hwm"])
    check("recovered row still in DB",
          len(db_rows("SELECT * FROM sma9_atr_open_positions")) == 1)

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
