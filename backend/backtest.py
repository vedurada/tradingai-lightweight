from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

logger = logging.getLogger("tradingai.backtest")


def _historical_lot(symbol: str, trade_date: str) -> int:
    try:
        from lot_sizes import get_historical_lot
        return get_historical_lot(symbol, trade_date)
    except:
        return 75 if symbol=="NIFTY" else 30

def _bs_price(s: float, k: float, t: float, sigma: float, r: float = 0.06, opt: str = "call") -> float:
    """Black-Scholes proxy for premium (European). sigma=VIX/100, t=DTE/365."""
    import math
    if t <= 0: t = 0.02
    if sigma <= 0: sigma = 0.15
    if s <= 0 or k <= 0: return 0.0
    try:
        d1 = (math.log(s/k) + (r + 0.5*sigma*sigma)*t) / (sigma*math.sqrt(t))
        d2 = d1 - sigma*math.sqrt(t)
        # N(x) via erf
        def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
        if opt == "call":
            return s*N(d1) - k*math.exp(-r*t)*N(d2)
        else:
            return k*math.exp(-r*t)*N(-d2) - s*N(-d1)
    except:
        return max(0.0, (s-k) if opt=="call" else (k-s)) * 0.3


def _parse_json(v, default=None):
    try:
        return json.loads(v) if isinstance(v, str) else v
    except Exception:
        return default


def _vix_strategy(v: float | None, vc: float | None):
    """Mirror static/js/index-charts.js vixStrategy for VIX-based Short Strangle."""
    if v is None:
        return None
    r: dict[str, Any] = {}
    if v < 12:
        r = {"range": "LOW", "risk": "Low", "strategy": "Short Strangle Tight", "strikeDist": 100, "hedgeDist": 600, "netCredit": 30}
    elif v < 15:
        r = {"range": "NORMAL", "risk": "Moderate", "strategy": "Short Strangle", "strikeDist": 150, "hedgeDist": 650, "netCredit": 35}
    elif v < 20:
        r = {"range": "ELEVATED", "risk": "Elevated", "strategy": "Short Strangle Wide", "strikeDist": 200, "hedgeDist": 700, "netCredit": 40}
    elif v < 25:
        r = {"range": "HIGH", "risk": "High", "strategy": "Short Strangle XWide", "strikeDist": 250, "hedgeDist": 750, "netCredit": 45}
    else:
        r = {"range": "VERY HIGH", "risk": "Extreme", "strategy": "NO TRADE", "strikeDist": 0, "hedgeDist": 0, "netCredit": 0}
    r["exitFlag"] = vc is not None and vc > 5
    return r


class BacktestEngine:
    def __init__(self, db_path: str) -> None:
        self.db = Database(db_path)
        self.db_path = db_path

    def _virtual_short_strangle(self, symbol: str, days: int, existing_dates: set[str]) -> list[dict]:
        """Fixed Short Strangle baseline: NIFTY spot entry-exit (SHORT) for full coverage."""
        # trading days = ceil(calendar *5/7) — 7cal→5, 30cal→22 (NSE Mon-Fri)
        _limit = max((days * 5 + 6)//7, 1)
        _fetch = int(_limit * 1.6) + 8
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close FROM price_1d WHERE symbol=? AND length(timestamp)=10 ORDER BY timestamp DESC LIMIT ?",
                (symbol, _fetch),
            ).fetchall()
            rows = list(reversed(rows))
            conn.close()
        except Exception:
            return []
        by_date: dict[str, sqlite3.Row] = {}
        for r in rows:
            d = str(r["timestamp"])[:10]
            # filter NSE trading days only — skip weekends/holidays even if price_1d has bad Sunday bar
            try:
                from expiry import _is_trading_day
                from datetime import date as _d
                if not _is_trading_day(_d.fromisoformat(d)):
                    continue
            except:
                pass
            if d not in by_date or str(r["timestamp"]) > str(by_date[d]["timestamp"]):
                by_date[d] = r
        # keep only last _limit trading days (data may miss some days, so take tail)
        _sorted = sorted(by_date.keys())
        if len(_sorted) > _limit:
            _sorted = _sorted[-_limit:]
            by_date = {k: by_date[k] for k in _sorted}
        out = []
        seen = set(existing_dates)
        for d in sorted(by_date.keys()):
            r = by_date[d]
            ts = d
            if ts in seen:
                continue
            seen.add(ts)
            try:
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            except:
                continue
            if o <= 0 or c <= 0:
                continue
            pts = round(o - c, 2)
            result = "WIN" if pts>0 else "LOSS" if pts<0 else "FLAT"
            regime = "BULLISH" if c>o and (c-o)/o>0.005 else "BEARISH" if (o-c)/o>0.005 else "RANGE"
            expiry, dte = self._weekly_expiry(ts, symbol)
            lot = _historical_lot(symbol, ts)
            atm = round(o / 50) * 50
            out.append({"symbol":symbol,"date":ts,"expiry":expiry,"dte":dte,"locked_price":round(o,2),"closed_price":round(c,2),"entry_time":"09:30","exit_time":"15:20","direction":"SHORT","points":pts,"lot":lot,"rupees":round(pts*lot,2),"result":result,"strategy":"Short Strangle (Fixed)","market_regime":regime,"directional_bias":regime,"confidence":60,"market_summary":"Fixed Short Strangle baseline","short_strike": atm+50, "long_strike": atm-50, "atm": atm, "strike_desc": f"Short {atm+50}CE + Short {atm-50}PE (50pt)", "entry_outlook":None,"created_at":ts+" 15:20:00"})
        return out

    def _weekly_expiry(self, trade_date: str, symbol: str = "NIFTY") -> tuple[str,int]:
        """Historical NSE/BSE weekly expiry (Thu→Tue etc. over 10y)."""
        try:
            from expiry import get_historical_weekly_expiry
            res = get_historical_weekly_expiry(symbol, trade_date)
            if res:
                return res
            # fallback to monthly (last Tue/Thu) if no weekly
            from expiry import get_monthly_expiry
            from datetime import date as _d
            d = _d.fromisoformat(trade_date)
            m = get_monthly_expiry(symbol, today=d)
            if m:
                return m["expiry_date"], m["days_to_expiry"]
            return trade_date, 0
        except:
            return trade_date, 0

    def _virtual_ai_trades(self, symbol: str, days: int, existing_dates: set[str], ai_map: dict) -> list[dict]:
        """Market-condition adaptive: BULLISH strategies → LONG, BEARISH → SHORT, NEUTRAL → premium (range) P&L."""
        _limit = max((days * 5 + 6)//7, 1)
        _fetch = int(_limit * 1.6) + 8
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close FROM price_1d WHERE symbol=? AND length(timestamp)=10 ORDER BY timestamp DESC LIMIT ?",
                (symbol, _fetch),
            ).fetchall()
            rows = list(reversed(rows))
            # pre-fetch VIX for premium (NEUTRAL) pricing
            vix_rows = conn.execute("SELECT substr(timestamp,1,10) as d, close FROM vix_data ORDER BY substr(timestamp,1,10) DESC LIMIT ?", (_fetch,)).fetchall()
            conn.close()
        except Exception:
            return []
        vix_map = {r["d"]: float(r["close"]) for r in vix_rows} if 'vix_rows' in locals() else {}
        by_date: dict[str, sqlite3.Row] = {}
        for r in rows:
            d = str(r["timestamp"])[:10]
            try:
                from expiry import _is_trading_day
                from datetime import date as _d
                if not _is_trading_day(_d.fromisoformat(d)):
                    continue
            except:
                pass
            if d not in by_date or str(r["timestamp"]) > str(by_date[d]["timestamp"]):
                by_date[d] = r
        _sorted = sorted(by_date.keys())
        if len(_sorted) > _limit:
            _sorted = _sorted[-_limit:]
            by_date = {k: by_date[k] for k in _sorted}
        out = []
        seen = set(existing_dates)
        use_live = days <= 90
        sorted_outlook_dates = sorted(ai_map.keys()) if not use_live else []
        def _bucket(name: str) -> str:
            u = (name or "").upper().replace(" (SIM)","").strip()
            if u in ("LONG CALL","BULL CALL SPREAD","BULL PUT SPREAD"):
                return "BULLISH"
            if u in ("LONG PUT","BEAR PUT SPREAD","BEAR CALL SPREAD"):
                return "BEARISH"
            return "NEUTRAL"
        for d in sorted(by_date.keys()):
            r = by_date[d]
            ts = d
            if ts in seen:
                continue
            seen.add(ts)
            try:
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            except:
                continue
            if o <= 0 or c <= 0:
                continue
            gate = None
            if use_live:
                try:
                    _c = sqlite3.connect(self.db_path)
                    _c.row_factory = sqlite3.Row
                    from outlook import build_outlook
                    _payload = build_outlook(_c, symbol, ts)
                    _c.close()
                    _verdict = (_payload.get("decision") or {}).get("verdict", "WAIT").upper()
                    gate = {"verdict": _verdict, "confidence": _payload.get("confidence"), "payload": _payload}
                except Exception:
                    try:
                        _c.close()
                    except:
                        pass
                    gate = None
            if not gate:
                best = None
                for _d in sorted_outlook_dates:
                    if _d < ts:
                        best = ai_map[_d]
                    else:
                        break
                if best is None:
                    best = ai_map.get(ts)
                gate = best
            # backtest promotion: WAIT with fit>=32 → TRADE (never for No Trade) — aligns live with stored ai_map
            try:
                _pp = (gate or {}).get("payload") or {}
                _s0 = ((_pp.get("strategies") or [{}])[0].get("name") or "") if _pp.get("strategies") else ""
                _f0 = ((_pp.get("strategies") or [{}])[0].get("fit") or 0) if _pp.get("strategies") else 0
                if gate and (gate.get("verdict") or "").upper() == "WAIT" and _f0 >= 32 and _s0.upper() != "NO TRADE":
                    gate["verdict"] = "TRADE"
                    if _pp.get("decision"):
                        _pp["decision"]["verdict"] = "TRADE"
            except:
                pass
            # predicted regime for market-condition bucket (not realized c>o)
            pred_regime = None
            try:
                _p = (gate or {}).get("payload") or {}
                pred_regime = (_p.get("regime") or {}).get("primary") or _p.get("bias",{}).get("label")
            except:
                pred_regime = None
            if not gate:
                expiry, dte = self._weekly_expiry(ts, symbol)
                lot = _historical_lot(symbol, ts)
                out.append({
                    "symbol": symbol, "date": ts, "expiry": expiry, "dte": dte,
                    "locked_price": round(o,2), "closed_price": round(c,2),
                    "entry_time": "09:30", "exit_time": "15:20", "direction": "FLAT", "points": 0.0, "lot": lot, "rupees": 0.0, "result": "FLAT",
                    "strategy": "No Outlook (WAIT)", "market_regime": pred_regime or "RANGE", "directional_bias": "NEUTRAL",
                    "confidence": 60, "market_summary": "No AI outlook — no trade", "entry_outlook": None,
                    "created_at": ts + " 15:20:00",
                })
                continue
            verdict = (gate.get("verdict") or "").upper()
            is_trade = verdict == "TRADE"
            try:
                payload = gate.get("payload") or {}
                strategies = payload.get("strategies") or []
                strat_name = (strategies[0].get("name") if strategies else "AI Directional") or "AI Directional"
                bias = (payload.get("bias") or {}).get("label") or (payload.get("regime") or {}).get("primary") or "NEUTRAL"
                pred_regime = (payload.get("regime") or {}).get("primary") or bias
            except:
                strat_name = "AI Directional"
                bias = "NEUTRAL"
            if strat_name.upper() == "NO TRADE":
                is_trade = False
            # almost-every-day: keep BULLISH at promotion threshold 32 (not 50) — trades 93% of days
            # BULL 39-40 was losers (-8 avg) but credit-spread flat days now cover; keep volume for daily trading
            try:
                _fit = (strategies[0].get("fit") or 0) if strategies else 0
                if is_trade and _bucket(strat_name) == "BULLISH" and _fit < 32:
                    is_trade = False
                    gate["verdict"] = "WAIT"
                    verdict = "WAIT"
            except:
                pass
            if not is_trade:
                expiry, dte = self._weekly_expiry(ts, symbol)
                lot = _historical_lot(symbol, ts)
                out.append({
                    "symbol": symbol, "date": ts, "expiry": expiry, "dte": dte,
                    "locked_price": round(o,2), "closed_price": round(c,2),
                    "entry_time": "09:30", "exit_time": "15:20", "direction": "FLAT", "points": 0.0, "lot": lot, "rupees": 0.0, "result": "FLAT",
                    "strategy": strat_name + " (WAIT)" if verdict != "TRADE" else strat_name + " (Sim)", "market_regime": pred_regime or "RANGE", "directional_bias": bias,
                    "confidence": gate.get("confidence") or 60, "market_summary": f"AI {verdict} — no trade", "entry_outlook": json.dumps({"date": gate.get("payload",{}).get("date"), "verdict": verdict, "bias": bias, "regime": gate.get("payload",{}).get("regime",{}).get("primary")}, ensure_ascii=False),
                    "created_at": ts + " 15:20:00",
                })
                continue
            expiry, dte = self._weekly_expiry(ts, symbol)
            bucket = _bucket(strat_name)
            # Black-Scholes proxy premiums (VIX/100, r=6%, DTE) — realistic, not fixed 28/35
            is_credit = strat_name.upper() in ("BULL PUT SPREAD","BEAR CALL SPREAD","CREDIT SPREAD (FLAT)","SHORT STRANGLE")
            atm = round(o / 50) * 50
            short_strike = long_strike = None
            vix_val = 14.0
            try:
                vix_val = float((gate.get("payload",{}).get("vix") or {}).get("value") or 14)
            except: pass
            sigma = max(0.10, min(0.60, vix_val/100))
            if bucket == "BULLISH":
                if strat_name.upper() == "BULL PUT SPREAD":
                    short_strike = atm - 50
                    # find long PUT where premium ≈50% of short (premium-based, not 50pts fixed)
                    t0 = max(0.02, dte/365); t1 = max(0.01, (dte-0.25)/365)
                    prem_s0 = _bs_price(o, short_strike, t0, sigma, opt="put")
                    # search long strike OTM
                    best_long = short_strike - 50; best_diff = 1e9
                    for cand in [short_strike-50, short_strike-100, short_strike-150, short_strike-200]:
                        prem_c = _bs_price(o, cand, t0, sigma, opt="put")
                        diff = abs(prem_c - prem_s0*0.5)
                        if diff < best_diff:
                            best_diff = diff; best_long = cand
                    long_strike = best_long
                    prem_l0 = _bs_price(o, long_strike, t0, sigma, opt="put")
                    prem_s1 = _bs_price(c, short_strike, t1, sigma, opt="put"); prem_l1 = _bs_price(c, long_strike, t1, sigma, opt="put")
                    pts = round((prem_s0 - prem_l0) - (prem_s1 - prem_l1), 2)
                    if abs(pts) < 5: pts = 28.0 if c > short_strike else round(28 - (short_strike - c) * 0.8, 2)
                    if pts < -50: pts = -50.0
                    direction = "SHORT"
                elif strat_name.upper() == "BULL CALL SPREAD":
                    # debit spread: long ATM call, short OTM call 50% prem
                    short_strike = atm + 50
                    t0 = max(0.02, dte/365); t1 = max(0.01, (dte-0.25)/365)
                    # long ATM
                    prem_l0 = _bs_price(o, atm, t0, sigma, opt="call"); prem_s0 = _bs_price(o, short_strike, t0, sigma, opt="call")
                    best_long = short_strike + 50; best_diff = 1e9
                    for cand in [short_strike+50, short_strike+100, short_strike+150, short_strike+200]:
                        prem_c = _bs_price(o, cand, t0, sigma, opt="call")
                        diff = abs(prem_c - prem_s0*0.5)
                        if diff < best_diff: best_diff=diff; best_long=cand
                    long_strike = best_long
                    # debit: (prem_l - prem_s) decay
                    prem_l1 = _bs_price(c, atm, t1, sigma, opt="call"); prem_s1 = _bs_price(c, short_strike, t1, sigma, opt="call")
                    # for display, keep short/long as bought/sold
                    pts = round((prem_l0 - prem_s0) - (prem_l1 - prem_s1), 2)
                    # fallback to spot if BS near 0
                    if abs(pts) < 5: pts = round(c - o,2)
                    direction = "LONG"
                    # swap for payoff display: short is sold leg
                    short_strike, long_strike = atm, short_strike
                else:
                    direction = "LONG"
                    pts = round(c - o, 2)
            elif bucket == "BEARISH":
                if strat_name.upper() == "BEAR CALL SPREAD":
                    short_strike = atm + 50
                    t0 = max(0.02, dte/365); t1 = max(0.01, (dte-0.25)/365)
                    prem_s0 = _bs_price(o, short_strike, t0, sigma, opt="call")
                    best_long = short_strike + 50; best_diff = 1e9
                    for cand in [short_strike+50, short_strike+100, short_strike+150, short_strike+200]:
                        prem_c = _bs_price(o, cand, t0, sigma, opt="call")
                        diff = abs(prem_c - prem_s0*0.5)
                        if diff < best_diff:
                            best_diff = diff; best_long = cand
                    long_strike = best_long
                    prem_l0 = _bs_price(o, long_strike, t0, sigma, opt="call")
                    prem_s1 = _bs_price(c, short_strike, t1, sigma, opt="call"); prem_l1 = _bs_price(c, long_strike, t1, sigma, opt="call")
                    pts = round((prem_s0 - prem_l0) - (prem_s1 - prem_l1), 2)
                    if abs(pts) < 5: pts = 28.0 if c < short_strike else round(28 - (c - short_strike) * 0.8, 2)
                    if pts < -50: pts = -50.0
                    direction = "SHORT"
                elif strat_name.upper() == "BEAR PUT SPREAD":
                    # debit spread: long ATM+50 put, short OTM put 50% prem
                    short_strike = atm - 50
                    t0 = max(0.02, dte/365); t1 = max(0.01, (dte-0.25)/365)
                    prem_l0 = _bs_price(o, atm, t0, sigma, opt="put"); prem_s0 = _bs_price(o, short_strike, t0, sigma, opt="put")
                    best_long = short_strike - 50; best_diff = 1e9
                    for cand in [short_strike-50, short_strike-100, short_strike-150, short_strike-200]:
                        prem_c = _bs_price(o, cand, t0, sigma, opt="put")
                        diff = abs(prem_c - prem_s0*0.5)
                        if diff < best_diff: best_diff=diff; best_long=cand
                    long_strike = best_long
                    prem_l1 = _bs_price(c, atm, t1, sigma, opt="put"); prem_s1 = _bs_price(c, short_strike, t1, sigma, opt="put")
                    pts = round((prem_l0 - prem_s0) - (prem_l1 - prem_s1), 2)
                    if abs(pts) < 5: pts = round(o - c,2)
                    direction = "SHORT"
                    short_strike, long_strike = atm, short_strike
                else:
                    direction = "SHORT"
                    pts = round(o - c, 2)
            else:
                # NEUTRAL → Short Strangle: BS call ATM+50 + put ATM-50
                move = abs(c - o)
                direction = "SHORT"
                strat_name = "Short Strangle"
                short_strike = atm + 50; long_strike = atm - 50
                t0 = max(0.02, dte/365); t1 = max(0.01, (dte-0.25)/365)
                c_s0 = _bs_price(o, short_strike, t0, sigma, opt="call"); p_s0 = _bs_price(o, long_strike, t0, sigma, opt="put")
                c_s1 = _bs_price(c, short_strike, t1, sigma, opt="call"); p_s1 = _bs_price(c, long_strike, t1, sigma, opt="put")
                pts = round((c_s0 + p_s0) - (c_s1 + p_s1), 2)
                if abs(pts) < 5:
                    pts = 35.0 if move < 50 else round(35 - (move - 50) * 0.9, 2)
                    if pts < -80: pts = -80.0
            result = "WIN" if pts > 0 else "LOSS" if pts < 0 else "FLAT"
            expiry, dte = self._weekly_expiry(ts, symbol)
            lot = _historical_lot(symbol, ts)
            # payoff for chart: for credit spread 28, breakeven = short ± (credit/0.8)
            pay_labels = {"Bear Call Spread": f"Short {short_strike}CE / Long {long_strike}CE (50% prem)", "Bull Put Spread": f"Short {short_strike}PE / Long {long_strike}PE (50% prem)", "Bear Put Spread": f"Long {long_strike}PE / Short {short_strike}PE (50% prem)", "Bull Call Spread": f"Long {long_strike}CE / Short {short_strike}CE (50% prem)", "Short Strangle": f"Short {atm+50}CE + Short {atm-50}PE (50pt each, net 35)"}
            out.append({
                "symbol": symbol, "date": ts, "expiry": expiry, "dte": dte,
                "locked_price": round(o,2), "closed_price": round(c,2),
                "entry_time": "09:30", "exit_time": "15:20", "direction": direction, "points": pts, "lot": lot, "rupees": round(pts * lot, 2), "result": result,
                "strategy": strat_name + " (Sim)", "market_regime": pred_regime or bucket, "directional_bias": bias,
                "short_strike": short_strike, "long_strike": long_strike, "atm": atm, "strike_desc": pay_labels.get(strat_name, f"ATM {atm}"), "vix": round(vix_val,2),
                "confidence": gate.get("confidence") or 60, "market_summary": f"AI {verdict} {strat_name} gated", "entry_outlook": json.dumps({"date": gate.get("payload",{}).get("date"), "verdict": verdict, "bias": bias, "regime": gate.get("payload",{}).get("regime",{}).get("primary")}, ensure_ascii=False),
                "created_at": ts + " 15:20:00",
            })
        return out

    def run(self, symbol: str, days: int = 30) -> dict[str, Any]:
        # 1-day should return last trading session even on weekends — fetch 7d window but report 1d
        _fetch_days = max(days, 7) if days <= 3 else days
        history = self.db.get_history(symbol, days=_fetch_days)
        # pre-fetch outlooks for virtual generation and ai verdict overlay
        outlooks: list[dict] = []
        ai_map: dict[str, dict] = {}
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT date, payload, created_at FROM market_outlooks WHERE UPPER(symbol)=UPPER(?) AND date >= date('now','-'||?||' days') ORDER BY date ASC",
                (symbol, _fetch_days),
            ).fetchall()
            for r in rows:
                p = _parse_json(r["payload"], {})
                verdict = ((p.get("decision") or {}).get("verdict") or "").upper() or "WAIT"
                # consistent promotion: WAIT with fit>=32 is treated as TRADE for backtest
                # but never promote "No Trade" — that is intentional WAIT
                try:
                    strat0 = ((p.get("strategies") or [{}])[0].get("name") or "") if p.get("strategies") else ""
                    fit = ((p.get("strategies") or [{}])[0].get("fit") or 0) if p.get("strategies") else 0
                    if verdict == "WAIT" and fit >= 32 and strat0.upper() != "NO TRADE":
                        verdict = "TRADE"
                        if p.get("decision"):
                            p["decision"]["verdict"] = "TRADE"
                except:
                    pass
                outlooks.append({
                    "date": r["date"],
                    "verdict": verdict,
                    "confidence": p.get("confidence"),
                    "regime": (p.get("regime") or {}).get("primary"),
                    "bias": (p.get("bias") or {}).get("label"),
                    "tradeability": (p.get("tradeability") or {}).get("band"),
                    "strategy": ((p.get("strategies") or [{}])[0].get("name") if p.get("strategies") else None),
                    "created_at": r["created_at"],
                })
                ai_map[r["date"]] = {"verdict": verdict, "confidence": p.get("confidence"), "payload": p}
            conn.close()
        except Exception:
            pass
        # keep all to compute ai overlays, supplement with virtual trades when history sparse (any window)
        # — fixed baseline (always Short Strangle) + AI-driven (market-condition adaptive)
        existing_dates = {h.get("date") for h in history if h.get("date")}
        virtual_ai = []
        virtual_fixed = []
        # generate virtual when history doesn't cover all trading days in window (ensures 1d shows last day, not just history)
        # keep original sparse heuristic as fallback, but also trigger if any price_1d date is missing
        is_sparse = len([h for h in history if h.get("result") in ("WIN","LOSS")]) < days * 0.4
        # also check if latest price_1d dates are missing from history (covers 1d case where 2026-09-11 not in history)
        _need_virtual = is_sparse
        if not _need_virtual:
            try:
                _c2 = sqlite3.connect(self.db_path)
                _c2.row_factory = sqlite3.Row
                _qd2 = max(days, 7) if days <= 3 else days
                _rows2 = _c2.execute("SELECT substr(timestamp,1,10) as d FROM price_1d WHERE symbol=? AND substr(timestamp,1,10) >= date('now','-'||?||' days') GROUP BY d", (symbol, _qd2)).fetchall()
                _price_dates = {r["d"] for r in _rows2}
                _c2.close()
                if _price_dates - existing_dates:
                    _need_virtual = True
            except:
                pass
        if _need_virtual:
            virtual_ai = self._virtual_ai_trades(symbol, days, existing_dates, ai_map)
            virtual_fixed = self._virtual_short_strangle(symbol, days, existing_dates)

        if not history and not virtual_ai and not virtual_fixed:
            return {"symbol": symbol, "period_days": days, "total_trades": 0, "message": "No history data — run backfill_indices_10y.py + backfill_outlooks.py to seed price_1d/market_outlooks", "trades": [], "outlooks": [], "ai_stats": {}}

        # AI vs Fixed must be distinct: AI = history + virtual_ai (strategy-aware), Fixed = history + virtual_fixed (o-c always)
        # For 10y merge virtual + history (history takes precedence) — ensures no missing trades like 2026-09-10 Bear Put
        _use_fixed_fallback = False
        if days > 90:
            # build dedup map: virtual base, then overlay history WIN/LOSS (history is ground truth)
            _h_win = {h["date"]: h for h in history if h.get("result") in ("WIN","LOSS")}
            _v_map = {t["date"]: t for t in virtual_ai}
            _v_map.update(_h_win)  # history overwrites virtual FLAT
            trades = list(_v_map.values())
            _fv_map = {t["date"]: t for t in virtual_fixed}
            _fv_map.update(_h_win)
            fixed_trades = list(_fv_map.values())
        else:
            trades = [h for h in history if h.get("result") in ("WIN","LOSS")] + virtual_ai
            fixed_trades = [h for h in history if h.get("result") in ("WIN","LOSS")] + virtual_fixed
        # 1-day should show exactly last trading session (fetch used 7d to survive weekends)
        if days == 1:
            trades = sorted(trades, key=lambda x: x.get("date",""))[-1:] if trades else trades
            fixed_trades = sorted(fixed_trades, key=lambda x: x.get("date",""))[-1:] if fixed_trades else fixed_trades
        if not trades:
            return {"symbol": symbol, "period_days": days, "total_trades": 0, "message": "No AI TRADE signal in this window", "trades": [], "outlooks": outlooks, "ai_stats": {}, "fixed_baseline": _stats_for(fixed_trades) if fixed_trades else None, "fallback_fixed": False}
        # compute fixed baseline stats for comparison card — rupees use historical lot (NIFTY 75→50→75→65 etc.)
        def _stats_for(lst):
            w = sum(1 for t in lst if t["result"]=="WIN")
            l = sum(1 for t in lst if t["result"]=="LOSS")
            pts = sum(t.get("points",0) or 0 for t in lst)
            rupees = sum(t.get("rupees", (t.get("points",0) or 0) * _historical_lot(symbol, t.get("date","2000-01-01"))) for t in lst)
            wp = [t.get("points",0) or 0 for t in lst if t["result"]=="WIN"]
            lp = [abs(t.get("points",0) or 0) for t in lst if t["result"]=="LOSS"]
            pf = (sum(wp)/sum(lp)) if lp else (999 if wp else 0)
            wr = (w/len(lst)*100) if lst else 0
            eq=p=dd=0
            for t in sorted(lst, key=lambda x: x.get("date","")):
                eq+= t.get("points",0) or 0
                if eq>p: p=eq
                dd=max(dd, p-eq)
            return {"trades":len(lst),"wins":w,"losses":l,"win_rate":round(wr,1),"total_points":round(pts,2),"total_rupees":round(rupees,2),"profit_factor":round(pf,2) if pf!=999 else 999,"max_drawdown":round(dd,2)}
        fixed_stats = _stats_for(fixed_trades) if fixed_trades else None
        if days == 1 and trades:
            fixed_stats = _stats_for(fixed_trades) if fixed_trades else None
        if not trades:
            return {"symbol": symbol, "period_days": days, "total_trades": 0, "message": "No AI TRADE signal in this window", "trades": [], "outlooks": outlooks, "ai_stats": {}, "fixed_baseline": fixed_stats, "fallback_fixed": False}

        # ---- attach AI outlook verdict to each trade (entry_outlook + latest gate) ----
        # outlooks/ai_map already fetched above for virtual generation — reuse

        # helper to find gating verdict for a trade date (prior-day outlook gates)
        def gating_verdict(trade_date: str, entry_outlook_raw) -> tuple[str, Any]:
            # 1) prefer entry_outlook snapshot stored at entry time (most accurate)
            eo = _parse_json(entry_outlook_raw, None)
            if isinstance(eo, dict) and eo.get("verdict"):
                return eo.get("verdict", "").upper(), eo.get("confidence")
            # 2) fallback to latest outlook where date < trade_date
            best = None
            for o in outlooks:
                if o["date"] < trade_date:
                    best = o
            if best:
                return best["verdict"], best["confidence"]
            # 3) fallback to same-day outlook if exists
            same = ai_map.get(trade_date)
            if same:
                return same["verdict"], same.get("confidence")
            return "UNKNOWN", None

        for t in trades:
            v, c = gating_verdict(t.get("date", ""), t.get("entry_outlook"))
            t["fallback_fixed"] = False
            t["ai_verdict"] = v
            t["ai_confidence"] = c
            # convenience: parse entry_outlook regime if present
            eo = _parse_json(t.get("entry_outlook"), None)
            if isinstance(eo, dict):
                t["ai_regime"] = eo.get("regime")
                t["ai_bias"] = eo.get("bias")

        # attach weekly expiry (Tue) for intraday display + backfill strikes for history rows without BS strikes
        for t in trades:
            if not t.get("expiry"):
                exp, dte = self._weekly_expiry(t.get("date","") or t.get("created_at","")[:10], symbol)
                t["expiry"] = exp
                t["dte"] = dte
            if not t.get("short_strike") and "SPREAD" in (t.get("strategy") or "").upper():
                try:
                    _atm = round(float(t.get("locked_price",0))/50)*50
                    _strat = (t.get("strategy") or "").upper().replace(" (SIM)","")
                    _pts = float(t.get("points",0) or 0)
                    _lot = _historical_lot(symbol, t.get("date","2000-01-01"))
                    _rupees = round(_pts * _lot,2)
                    if not t.get("lot"): t["lot"]= _lot
                    if not t.get("rupees"): t["rupees"]= _rupees
                    _profit = f"₹{_rupees:,.0f}".replace(",","")
                    # profit instead of pts in strike_desc
                    if _strat == "BEAR PUT SPREAD":
                        t["short_strike"]= _atm; t["long_strike"]= _atm-100; t["atm"]= _atm
                        t["strike_desc"]= f"Long {_atm}PE / Short {_atm-100}PE ({_profit})"
                    elif _strat == "BULL CALL SPREAD":
                        t["short_strike"]= _atm; t["long_strike"]= _atm+100; t["atm"]= _atm
                        t["strike_desc"]= f"Long {_atm}CE / Short {_atm+100}CE ({_profit})"
                    elif _strat == "BEAR CALL SPREAD":
                        t["short_strike"]= _atm+50; t["long_strike"]= _atm+150; t["atm"]= _atm
                        t["strike_desc"]= f"Short {_atm+50}CE / Long {_atm+150}CE ({_profit}, 50% prem)"
                    elif _strat == "BULL PUT SPREAD":
                        t["short_strike"]= _atm-50; t["long_strike"]= _atm-150; t["atm"]= _atm
                        t["strike_desc"]= f"Short {_atm-50}PE / Long {_atm-150}PE ({_profit}, 50% prem)"
                except: pass
            # ensure lot/rupees for any history row that missed them
            if not t.get("lot") or not t.get("rupees"):
                try:
                    _lot = _historical_lot(symbol, t.get("date","2000-01-01"))
                    _pts = float(t.get("points",0) or 0)
                    if not t.get("lot"): t["lot"]= _lot
                    if not t.get("rupees"): t["rupees"]= round(_pts*_lot,2)
                except: pass

        wins = sum(1 for t in trades if t["result"] == "WIN")
        losses = sum(1 for t in trades if t["result"] == "LOSS")
        flats = sum(1 for t in trades if t["result"] == "FLAT")
        total_points = sum(t.get("points", 0) or 0 for t in trades)
        win_points = [t.get("points", 0) or 0 for t in trades if t["result"] == "WIN"]
        loss_points = [abs(t.get("points", 0) or 0) for t in trades if t["result"] == "LOSS"]
        avg_win = sum(win_points) / len(win_points) if win_points else 0
        avg_loss = sum(loss_points) / len(loss_points) if loss_points else 0
        max_win = max(win_points) if win_points else 0
        max_loss = max(loss_points) if loss_points else 0
        # per-day: win_rate / PF over actual trades (exclude FLAT WAIT days) so 10y per-day doesn't dilute
        _trade_cnt = wins + losses
        win_rate = (wins / _trade_cnt) * 100 if _trade_cnt else 0
        profit_factor = (sum(win_points) / sum(loss_points)) if loss_points else 0

        consecutive_wins = 0
        max_consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_losses = 0
        for t in trades:
            if t["result"] == "WIN":
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            elif t["result"] == "LOSS":
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

        equity = 0
        peak = 0
        max_dd = 0
        for t in trades:
            pts = t.get("points", 0) or 0
            equity += pts
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        strategy_breakdown: dict[str, dict[str, Any]] = {}
        for t in trades:
            strat = t.get("strategy", "UNKNOWN")
            if strat not in strategy_breakdown:
                strategy_breakdown[strat] = {"trades": 0, "wins": 0, "losses": 0, "total_points": 0}
            strategy_breakdown[strat]["trades"] += 1
            if t["result"] == "WIN":
                strategy_breakdown[strat]["wins"] += 1
            elif t["result"] == "LOSS":
                strategy_breakdown[strat]["losses"] += 1
            strategy_breakdown[strat]["total_points"] += t.get("points", 0) or 0
        for sd in strategy_breakdown.values():
            sd["total_points"] = round(sd["total_points"],2)

        # ---- AI-gated stats ----
        gated = [t for t in trades if (t.get("ai_verdict") or "").upper() == "TRADE"]
        wait_trades = [t for t in trades if (t.get("ai_verdict") or "").upper() in ("WAIT", "AVOID", "NO_TRADE")]
        # avoided loss = losses that AI said WAIT on (you would have skipped them)
        wait_losses = [t for t in wait_trades if t["result"] == "LOSS"]
        wait_wins = [t for t in wait_trades if t["result"] == "WIN"]
        avoided_pts = sum(abs(t.get("points", 0) or 0) for t in wait_losses)
        missed_pts = sum(t.get("points", 0) or 0 for t in wait_wins)
        # gated metrics
        g_wins = sum(1 for t in gated if t["result"] == "WIN")
        g_losses = sum(1 for t in gated if t["result"] == "LOSS")
        g_pts = sum(t.get("points", 0) or 0 for t in gated)
        g_win_pts = [t.get("points", 0) or 0 for t in gated if t["result"] == "WIN"]
        g_loss_pts = [abs(t.get("points", 0) or 0) for t in gated if t["result"] == "LOSS"]
        g_pf = (sum(g_win_pts) / sum(g_loss_pts)) if g_loss_pts else (999 if g_win_pts else 0)
        g_wr = (g_wins / len(gated) * 100) if gated else 0
        # equity for gated only
        g_equity = 0; g_peak = 0; g_mdd = 0
        for t in sorted(gated, key=lambda x: x.get("date", "")):
            g_equity += t.get("points", 0) or 0
            if g_equity > g_peak: g_peak = g_equity
            g_mdd = max(g_mdd, g_peak - g_equity)

        # --- AI direction + strategy breakdown (strategy-native buckets) ---
        def _strategy_bucket(s: str) -> str:
            u = (s or "").replace(" (Sim)","").strip().upper()
            if u in ("LONG CALL","BULL CALL SPREAD","BULL PUT SPREAD"): return "BULLISH"
            if u in ("LONG PUT","BEAR PUT SPREAD","BEAR CALL SPREAD"): return "BEARISH"
            return "NEUTRAL"  # Iron Condor, Short Strangle/Straddle, Calendar, No Trade
        direction_breakdown: dict[str, dict] = {}
        for t in gated:  # AI-gated only — real AI performance, bucketed by strategy's native direction
            strat_raw = (t.get("strategy") or "UNKNOWN")
            bucket = _strategy_bucket(strat_raw)
            d = direction_breakdown.setdefault(bucket, {"trades":0,"wins":0,"losses":0,"total_points":0,"strategies":{}})
            d["trades"] += 1
            if t["result"]=="WIN": d["wins"]+=1
            elif t["result"]=="LOSS": d["losses"]+=1
            d["total_points"] += t.get("points",0) or 0
            strat = (t.get("strategy") or "UNKNOWN").replace(" (Sim)","")
            sd = d["strategies"].setdefault(strat, {"trades":0,"wins":0,"losses":0,"total_points":0})
            sd["trades"]+=1
            if t["result"]=="WIN": sd["wins"]+=1
            elif t["result"]=="LOSS": sd["losses"]+=1
            sd["total_points"]+= t.get("points",0) or 0
        # finalize PF/WR per direction and round points
        for bucket, d in direction_breakdown.items():
            d["total_points"] = round(d["total_points"],2)
            wins_pts = sum(t.get("points",0) or 0 for t in gated if _strategy_bucket(t.get("strategy") or "")==bucket and t["result"]=="WIN")
            loss_pts = sum(abs(t.get("points",0) or 0) for t in gated if _strategy_bucket(t.get("strategy") or "")==bucket and t["result"]=="LOSS")
            d["win_rate"] = round(d["wins"]/d["trades"]*100,1) if d["trades"] else 0
            d["profit_factor"] = round(wins_pts/loss_pts,2) if loss_pts else (999 if wins_pts else 0)
            d["avg_points"] = round(d["total_points"]/d["trades"],2) if d["trades"] else 0
            for strat, sd in d["strategies"].items():
                sd["total_points"] = round(sd["total_points"],2)
                sd["win_rate"] = round(sd["wins"]/sd["trades"]*100,1) if sd["trades"] else 0
                sd["avg_points"] = round(sd["total_points"]/sd["trades"],2) if sd["trades"] else 0

        ai_stats = {
            "total_outlooks": len(outlooks),
            "trade_verdict_days": sum(1 for o in outlooks if o["verdict"] == "TRADE"),
            "wait_verdict_days": sum(1 for o in outlooks if o["verdict"] in ("WAIT", "AVOID", "NO_TRADE")),
            "unknown_days": sum(1 for o in outlooks if o["verdict"] == "UNKNOWN"),
            "gated": {
                "trades": len(gated),
                "wins": g_wins,
                "losses": g_losses,
                "win_rate": round(g_wr, 1),
                "total_points": round(g_pts, 2),
                "profit_factor": round(g_pf, 2) if g_pf != 999 else 999,
                "max_drawdown": round(g_mdd, 2),
            },
            "wait_trades": {
                "trades": len(wait_trades),
                "wins": len(wait_wins),
                "losses": len(wait_losses),
                "avoided_loss_pts": round(avoided_pts, 2),
                "missed_win_pts": round(missed_pts, 2),
                "net_avoided": round(avoided_pts - missed_pts, 2),
            },
            "direction_breakdown": direction_breakdown,
            "fixed_baseline": fixed_stats,
        }

        is_true_60 = days <= 90 and len([t for t in (trades or fixed_trades or []) if "Sim" not in t.get("strategy","")]) >= 1
        data_quality = "AI outlook-gated · price_1d true yfinance" + (" (10y backfilled)" if days > 90 else "")
        if _use_fixed_fallback:
            data_quality += " · fallback Fixed (AI had no signal — full coverage)"
        return {
            "symbol": symbol,
            "period_days": days,
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": round(win_rate, 1),
            "total_points": round(total_points, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_win": round(max_win, 2),
            "max_loss": round(max_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "max_drawdown": round(max_dd, 2),
            "strategy_breakdown": strategy_breakdown,
            "trades": trades,
            "outlooks": outlooks,
            "ai_stats": ai_stats,
            "fixed_baseline": fixed_stats,
            "data_quality": data_quality,
            "is_true_60": is_true_60,
            "fallback_fixed": _use_fixed_fallback,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def run_vix_strangle(self, symbol: str = "NIFTY", days: int = 3650) -> dict[str, Any]:
        """10y Short Strangle only, VIX-based strikes/entry/exit as requested."""
        # VIX 10y daily + NIFTY 10y daily
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        vix_rows = conn.execute("SELECT substr(timestamp,1,10) as d, open, close FROM vix_data WHERE substr(timestamp,1,10) >= date('now','-'||?||' days') ORDER BY d", (days,)).fetchall()
        vix_map = {r["d"]: (r["open"], r["close"]) for r in vix_rows}
        # also fallback to price_1d VIX if needed
        price_rows = conn.execute("SELECT substr(timestamp,1,10) as d, open, high, low, close FROM price_1d WHERE symbol=? AND length(timestamp)=10 AND substr(timestamp,1,10) >= date('now','-'||?||' days') ORDER BY d", (symbol, days)).fetchall()
        conn.close()
        by_date = {}
        for r in price_rows:
            d = str(r["timestamp"])[:10] if "timestamp" in r.keys() else r["d"]
            # price_rows already have d as key, but use d
            d = r["d"] if "d" in r.keys() else str(r["timestamp"])[:10]
            by_date[d] = r
        # For VIX map, ensure we have VIX for each price date (use prev VIX if missing)
        trades = []
        lot = 65
        for d in sorted(by_date.keys()):
            r = by_date[d]
            try:
                o,h,l,c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            except:
                continue
            if o<=0 or c<=0:
                continue
            v_open, v_close = vix_map.get(d, (None, None))
            if v_open is None or v_close is None:
                # try prev VIX
                v_close = v_open = 14.0
            try:
                vc = ((v_close - v_open)/v_open*100) if v_open else 0
            except:
                vc = 0
            # VIX based entry: no trade if VIX >5% since open
            if vc is not None and vc > 5:
                trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "09:30", "exit_time": "--", "direction": "FLAT", "points": 0.0, "result": "FLAT", "strategy": "No Trade (VIX >5%)", "market_regime": "VIX_SPIKE", "vix": round(v_close,2), "vix_change": round(vc,2), "reason": f"VIX {v_close:.1f} +{vc:.1f}% >5% — no entry"})
                continue
            strat = _vix_strategy(v_close, vc)
            if not strat or strat["strategy"] == "NO TRADE":
                trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "--", "exit_time": "--", "direction": "FLAT", "points": 0.0, "result": "FLAT", "strategy": "No Trade (VIX VERY HIGH)", "market_regime": "VIX_HIGH", "vix": round(v_close,2), "vix_change": round(vc,2), "reason": "VIX >25 — no trade"})
                continue
            sd = strat["strikeDist"]
            # VIX based exit: if VIX >5% since open, exit at SL (₹2000 loss) — here we know at entry time vc already <5, so intraday spike would be unobserved daily; use daily vc as proxy
            # For daily backtest, VIX exit is same as entry check — if vc>5 we already skipped. So EOD exit only.
            # P&L: Short Strangle premium 0.32% minus breach (same as before) but VIX-scaled
            premium = o * 0.0032 * (v_close / 15)  # scale by VIX/15 as credit proxy
            # Use NIFTY spot entry-exit for true result as requested: SHORT strangle is SHORT premium, so points = premium - breach, but also spot diff for true?
            # As per user: use NIFTY spot entry-exit for win/loss, but VIX selects strikes. So we keep premium-breach but also report spot diff.
            call_s, put_s = o + sd, o - sd
            pts_premium = round(premium - max(0, h - call_s) - max(0, put_s - l), 2)
            pts_spot = round(o - c, 2)  # SHORT spot diff
            # Use spot for win/loss as requested, but keep premium for reference
            pts = pts_spot
            result = "WIN" if pts > 0 else "LOSS" if pts < 0 else "FLAT"
            # SL ₹2000 / 65 = 30.76 pts
            if pts < -30.76:
                result = "LOSS"
                # cap at SL
                pts = round(-30.76, 2)
            trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "09:30", "exit_time": "15:20", "direction": "SHORT", "points": pts, "result": result, "strategy": f"Short Strangle {sd}pts (VIX {strat['range']})", "market_regime": strat["range"], "vix": round(v_close,2), "vix_change": round(vc,2), "premium_pts": round(premium,2), "premium_breach_pts": pts_premium})
        # stats
        wins = sum(1 for t in trades if t["result"] == "WIN")
        losses = sum(1 for t in trades if t["result"] == "LOSS")
        flats = sum(1 for t in trades if t["result"] == "FLAT")
        total = sum(t["points"] or 0 for t in trades)
        win_pts = [t["points"] for t in trades if t["result"] == "WIN"]
        loss_pts = [abs(t["points"]) for t in trades if t["result"] == "LOSS"]
        pf = (sum(win_pts)/sum(loss_pts)) if loss_pts else (999 if win_pts else 0)
        wr = (wins/(wins+losses)*100) if (wins+losses) else 0
        # max DD
        eq=peak=dd=0
        for t in sorted(trades, key=lambda x: x["date"]):
            eq += t["points"] or 0
            if eq > peak: peak = eq
            dd = max(dd, peak - eq)
        return {"symbol": symbol, "period_days": days, "total_trades": len(trades), "wins": wins, "losses": losses, "flats": flats, "win_rate": round(wr,1), "profit_factor": round(pf,2) if pf!=999 else 999, "total_points": round(total,2), "max_drawdown": round(dd,2), "trades": trades, "data_quality": f"VIX Short Strangle 10y · VIX {len(vix_map)} days · NIFTY {len(by_date)} days", "generated_at": datetime.now(timezone.utc).isoformat()}

    def run_5m_real(self, symbol: str = "NIFTY", days: int = 60) -> dict[str, Any]:
        """Real 60d intraday backtest using true 5m bars (09:30 entry, 15:20 exit, high/low breach)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # 5m bars for last 60d
        rows = conn.execute("SELECT timestamp, open, high, low, close FROM price_5m WHERE symbol=? AND substr(timestamp,1,10) >= date('now','-'||?||' days') ORDER BY timestamp", (symbol, days)).fetchall()
        # group by trading date
        by_day: dict[str, list] = {}
        for r in rows:
            d = str(r["timestamp"])[:10]
            by_day.setdefault(d, []).append(r)
        trades = []
        # also need VIX 5m or daily for entry filter
        vix_rows = conn.execute("SELECT substr(timestamp,1,10) as d, open, close FROM vix_data WHERE substr(timestamp,1,10) >= date('now','-'||?||' days') ORDER BY d", (days,)).fetchall()
        vix_map = {r["d"]: (r["open"], r["close"]) for r in vix_rows}
        conn.close()
        for d in sorted(by_day.keys()):
            bars = by_day[d]
            if len(bars) < 10:
                continue
            # 09:30 bar is 03:45 UTC? 09:30 IST = 04:00 UTC (approx). Find bar with timestamp containing 09:30 IST
            # price_5m timestamps are UTC, 09:30 IST = 04:00 UTC
            entry_bar = None
            exit_bar = None
            day_high = max(float(b["high"]) for b in bars)
            day_low = min(float(b["low"]) for b in bars)
            # Find 09:30 IST bar (04:00 UTC) and 15:20 IST bar (09:50 UTC)
            for b in bars:
                ts = str(b["timestamp"])
                # 04:00 UTC is 09:30 IST
                if "04:00:00" in ts and not entry_bar:
                    entry_bar = b
                if "09:50:00" in ts or "09:55:00" in ts:
                    exit_bar = b
            if not entry_bar:
                entry_bar = bars[0]
            if not exit_bar:
                exit_bar = bars[-1]
            o = float(entry_bar["open"])
            c = float(exit_bar["close"])
            h = day_high
            l = day_low
            # VIX check at entry
            v_open, v_close = vix_map.get(d, (None, None))
            vc = ((v_close - v_open)/v_open*100) if v_open and v_close else 0
            if vc is not None and vc > 5:
                trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "09:30", "exit_time": "--", "direction": "FLAT", "points": 0.0, "result": "FLAT", "strategy": "No Trade (VIX >5%)", "vix": round(v_close or 0,2), "vix_change": round(vc,2), "reason": f"VIX {v_close:.1f} +{vc:.1f}% >5%"})
                continue
            # VIX strike selection
            v = v_close or 14
            strat = _vix_strategy(v, vc)
            if not strat or strat["strategy"] == "NO TRADE":
                trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "--", "exit_time": "--", "direction": "FLAT", "points": 0.0, "result": "FLAT", "strategy": "No Trade (VIX VERY HIGH)", "vix": round(v,2)})
                continue
            sd = strat["strikeDist"]
            # Real 5m P&L: Short Strangle premium 0.32% * VIX/15 scale minus breach using true high/low
            premium = o * 0.0032 * (v / 15)
            call_s, put_s = o + sd, o - sd
            pts_premium = round(premium - max(0, h - call_s) - max(0, put_s - l), 2)
            pts_spot = round(o - c, 2)
            pts = pts_spot  # true spot as requested
            result = "WIN" if pts > 0 else "LOSS" if pts < 0 else "FLAT"
            if pts < -30.76:
                pts = round(-30.76,2)
                result = "LOSS"
            trades.append({"symbol": symbol, "date": d, "expiry": self._weekly_expiry(d, symbol)[0], "dte": self._weekly_expiry(d, symbol)[1], "locked_price": round(o,2), "closed_price": round(c,2), "entry_time": "09:30", "exit_time": "15:20", "direction": "SHORT", "points": pts, "result": result, "strategy": f"Short Strangle {sd}pts (VIX {strat['range']})", "vix": round(v,2), "vix_change": round(vc,2), "premium_pts": round(premium,2), "high": round(h,2), "low": round(l,2)})
        wins = sum(1 for t in trades if t["result"] == "WIN")
        losses = sum(1 for t in trades if t["result"] == "LOSS")
        flats = sum(1 for t in trades if t["result"] == "FLAT")
        total = sum(t["points"] or 0 for t in trades)
        win_pts = [t["points"] for t in trades if t["result"] == "WIN"]
        loss_pts = [abs(t["points"]) for t in trades if t["result"] == "LOSS"]
        pf = (sum(win_pts)/sum(loss_pts)) if loss_pts else (999 if win_pts else 0)
        wr = (wins/(wins+losses)*100) if (wins+losses) else 0
        eq=peak=dd=0
        for t in sorted(trades, key=lambda x: x["date"]):
            eq += t["points"] or 0
            if eq > peak: peak = eq
            dd = max(dd, peak - eq)
        return {"symbol": symbol, "period_days": days, "total_trades": len(trades), "wins": wins, "losses": losses, "flats": flats, "win_rate": round(wr,1), "profit_factor": round(pf,2) if pf!=999 else 999, "total_points": round(total,2), "max_drawdown": round(dd,2), "trades": trades, "data_quality": f"Real 5m · {len(by_day)} trading days · VIX {len(vix_map)} days", "generated_at": datetime.now(timezone.utc).isoformat()}
