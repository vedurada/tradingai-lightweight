"""Paper-trade engine (spot-proxy fills with next-bar, no-lookahead exits).

R-DEFINITION MAP (see also app/research/backtest.py — canonical):
- backtest R_multiple (CANONICAL true multiple) = signed move_pts / risk_pts.
- qualification risk_reward = reward_pct / risk_pct (percent ratio; equals
  canonical R for spot trades since both legs scale with entry).
- options economics risk_reward/reward_risk = max_reward / max_risk
  (standardized reward/risk; equals canonical R at max outcome).
- performance realized_R = canonical R (converted here); pnl = R * risk_rs - fees.
This module persists legs JSON and exits on candles strictly AFTER entry
(entry_bar < t <= exit_bar) with STOP-first tie-break, matching backtest.
"""
import uuid, json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

# NSE lots effective 30-Dec-2025 (fixes stale lot 50).
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
BROKERAGE_RS = 40.0  # round-trip retail estimate
SLIPPAGE_PTS = 0.5  # per fill


def _lot(instrument):
    return LOT_SIZES.get((instrument or "").upper(), 65)


def _direction_sign(direction):
    d = (direction or "").upper()
    if d in ("SHORT", "BEARISH", "BEAR", "BEARISH"):
        return -1
    return 1  # LONG / BULLISH / BULL default


class PaperTradeEngine:
    def __init__(self):
        self.conn = get_conn()

    def create_paper_trade(self, qualified_trade):
        trade_id = f'PT-{str(uuid.uuid4())[:8].upper()}'
        legs = qualified_trade.get('legs') or []
        # Persist legs JSON (previously dropped as None). strikes/expiry
        # derived from legs when present for auditability.
        try:
            legs_json = json.dumps(legs)
        except (TypeError, ValueError):
            legs_json = "[]"
        strikes = None
        expiry = None
        try:
            if isinstance(legs, list) and legs:
                strikes = json.dumps([l.get("strike") for l in legs if isinstance(l, dict)])
                exps = {l.get("expiry") for l in legs if isinstance(l, dict) and l.get("expiry")}
                expiry = next(iter(exps)) if len(exps) == 1 else None
        except Exception:
            pass
        # Fall back to explicit fields if caller supplied them.
        if qualified_trade.get('strikes') and not strikes:
            strikes = qualified_trade.get('strikes') if isinstance(qualified_trade.get('strikes'), str) else json.dumps(qualified_trade.get('strikes'))
        if qualified_trade.get('expiry'):
            expiry = qualified_trade.get('expiry')
        self.conn.execute('''INSERT INTO paper_trades (trade_id, instrument_id, scenario, strategy, objective, direction, legs, strikes, expiry, entry, stop, target, max_risk, expected_reward, entry_time, status, qualification_evidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (trade_id, qualified_trade.get('instrument_id'), qualified_trade.get('scenario'), qualified_trade.get('strategy'), qualified_trade.get('objective'), qualified_trade.get('direction'), legs_json, strikes, expiry, qualified_trade.get('entry'), qualified_trade.get('stop'), qualified_trade.get('target'), qualified_trade.get('max_risk'), qualified_trade.get('expected_reward'), datetime.now(_IST).isoformat(), 'ACTIVE', json.dumps(qualified_trade, default=str), datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
        self.conn.commit()
        return trade_id

    def monitor(self, instrument_id):
        """Next-bar, no-lookahead monitor.

        For each ACTIVE/OPEN trade, evaluate 5m candles with
        timestamp STRICTLY AFTER entry_time (entry<t<=exit). STOP is
        checked before TARGET on the same bar (conservative tie-break,
        matching IntradayExitEngine). Falls back to the latest snapshot
        price only when no post-entry candles exist (no fill on entry bar).
        """
        trades = self.conn.execute('SELECT * FROM paper_trades WHERE instrument_id=? AND status IN ("ACTIVE", "OPEN")', (instrument_id,)).fetchall()
        results = []
        for t in trades:
            t = dict(t)
            entry_time = t.get('entry_time') or ""
            direction = t.get('direction') or "LONG"
            sign = _direction_sign(direction)
            entry = t.get('entry') or 0
            stop = t.get('stop') or 0
            target = t.get('target') or 0
            # Post-entry candles only: entry_bar < t (no entry-bar lookahead).
            try:
                candles = self.conn.execute(
                    'SELECT timestamp, open, high, low, close FROM market_candles_5m WHERE instrument_id=? AND timestamp > ? ORDER BY timestamp',
                    (instrument_id, entry_time)).fetchall()
            except Exception:
                candles = []
            filled = False
            current_price = None
            # Track latest price for reporting.
            try:
                snap = self.conn.execute('SELECT price FROM market_snapshots WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1', (instrument_id,)).fetchone()
                current_price = snap['price'] if snap else None
            except Exception:
                pass
            for c in candles:
                try:
                    cd = dict(c)
                    hi, lo = float(cd['high']), float(cd['low'])
                except (KeyError, TypeError, ValueError):
                    continue
                if sign > 0:  # LONG
                    stop_hit = lo <= stop
                    tgt_hit = hi >= target
                else:  # SHORT
                    stop_hit = hi >= stop
                    tgt_hit = lo <= target
                # Tie-break: STOP before TARGET on same bar (against trade).
                if stop_hit and tgt_hit:
                    self._exit_trade(t['trade_id'], stop, 'STOP', entry, direction, instrument_id)
                    filled = True
                    break
                if stop_hit:
                    self._exit_trade(t['trade_id'], stop, 'STOP', entry, direction, instrument_id)
                    filled = True
                    break
                if tgt_hit:
                    self._exit_trade(t['trade_id'], target, 'TARGET', entry, direction, instrument_id)
                    filled = True
                    break
            results.append({**t, 'current_price': current_price, 'filled': filled})
        return results

    def _exit_trade(self, trade_id, exit_price, reason, entry_price=None, direction=None, instrument_id=None):
        """PnL = (exit-entry)*lot*dir - costs (fixes stop-fill using current price).

        entry_price/direction/instrument resolved from DB when not passed
        (backward-compatible with old 4-arg calls).
        """
        entry = entry_price
        direction = direction or "LONG"
        instrument = instrument_id
        if entry is None or instrument is None:
            try:
                row = self.conn.execute('SELECT entry, direction, instrument_id FROM paper_trades WHERE trade_id=?', (trade_id,)).fetchone()
                if row:
                    rd = dict(row)
                    if entry is None:
                        entry = rd.get('entry') or 0
                    if direction is None or direction == "LONG":
                        direction = rd.get('direction') or direction or "LONG"
                    if instrument is None:
                        instrument = rd.get('instrument_id')
            except Exception:
                pass
        entry = entry or 0
        lot = _lot(instrument)
        sign = _direction_sign(direction)
        try:
            signed_pts = (float(exit_price) - float(entry)) * sign
        except (TypeError, ValueError):
            signed_pts = 0.0
        costs = BROKERAGE_RS + SLIPPAGE_PTS * lot
        pnl = round(signed_pts * lot - costs, 2)
        self.conn.execute('UPDATE paper_trades SET exit_price=?, exit_reason=?, exit_time=?, status=?, paper_pnl=?, updated_at=? WHERE trade_id=?',
            (exit_price, reason, datetime.now(_IST).isoformat(), 'CLOSED', pnl, datetime.now(_IST).isoformat(), trade_id))
        self.conn.commit()
