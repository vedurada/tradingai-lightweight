"""Live paper-trade performance ledger for TradingAI.

R-DEFINITION MAP (canonical = app/research/backtest.py true multiple):
- CANONICAL R = signed move_pts / risk_pts (unit-consistent points/points).
- This module converts: R=(exit-entry)*dir/risk_pts, pnl=R*risk_rs-fees.
  Previously stored raw point difference as both realized_R and pnl.
- qualification risk_reward (reward_pct/risk_pct) equals canonical R for spot.
- options economics risk_reward (reward/risk) equals canonical R at max outcome.

Records completed paper trades exactly once when they close.
Monitoring calls do NOT create duplicate records.
"""
import logging, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')
log = logging.getLogger('tradingai.performance')

# NSE lots effective 30-Dec-2025 (fixes stale lot 50).
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
BROKERAGE_RS = 40.0  # round-trip retail estimate
SLIPPAGE_PTS = 0.5
# NOTE: STT varies by venue/leg; modelled inside flat brokerage estimate.
# Gross pnl = move_pts * lot; net pnl = gross - (brokerage + slippage*lot).


def _lot(instrument):
    return LOT_SIZES.get((instrument or "").upper(), 65)


def _direction_sign(direction):
    d = (direction or "").upper()
    if d in ("SHORT", "BEARISH", "BEAR"):
        return -1
    return 1


def record_performance(trade_id):
    """Record a closed paper trade in the performance ledger.

    Idempotent: if a record already exists for this trade_id,
    it is NOT updated and NOT duplicated. Returns the record id.
    R = signed_move_pts / risk_pts; pnl = R * risk_rs - fees.
    """
    conn = get_conn()
    try:
        existing = conn.execute(
            'SELECT id FROM live_trade_performance WHERE trade_id=?',
            (trade_id,)).fetchone()
        if existing:
            log.info('performance trade_id=%s already recorded', trade_id)
            return existing['id']

        trade = conn.execute(
            'SELECT * FROM paper_trades WHERE trade_id=?', (trade_id,)).fetchone()
        if not trade:
            log.warning('performance trade_id=%s not found in paper_trades', trade_id)
            return None

        t = dict(trade)
        entry = t.get('entry', 0) or 0
        stop = t.get('stop', 0) or 0
        exit_px = t.get('exit_price', 0) or 0
        direction = t.get('direction') or 'LONG'
        sign = _direction_sign(direction)
        lot = _lot(t.get('instrument_id'))
        try:
            risk_pts = abs(float(entry) - float(stop))
        except (TypeError, ValueError):
            risk_pts = 0.0
        try:
            move_pts = (float(exit_px) - float(entry)) * sign
        except (TypeError, ValueError):
            move_pts = 0.0
        # Canonical true-multiple R (fixes raw-points-as-R).
        realized_r = round(move_pts / risk_pts, 4) if risk_pts > 0 else 0.0
        risk_rs = risk_pts * lot
        fees = BROKERAGE_RS + SLIPPAGE_PTS * lot
        pnl = round(realized_r * risk_rs - fees, 2) if risk_pts > 0 else round(move_pts * lot - fees, 2)
        cur = conn.execute('''INSERT INTO live_trade_performance
            (trade_id, instrument_id, trade_date, scenario, strategy, objective,
             direction, entry_time, entry_price, stop_price, target_price,
             exit_time, exit_price, exit_reason, status, risk_amount,
             reward_amount, realized_R, pnl, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                t['trade_id'], t['instrument_id'],
                (t.get('entry_time') or '')[:10],
                t.get('scenario'), t.get('strategy'), t.get('objective'),
                t.get('direction'), t.get('entry_time'), t.get('entry'),
                t.get('stop'), t.get('target'),
                t.get('exit_time'), t.get('exit_price'), t.get('exit_reason'),
                t.get('status'),
                t.get('max_risk', 0) or 0,
                t.get('expected_reward', 0) or 0,
                realized_r, pnl,
                datetime.now(_IST).isoformat(),
                datetime.now(_IST).isoformat(),
            ))
        # Fetch lastrowid BEFORE close (fixes use-after-close).
        new_id = cur.lastrowid
        conn.commit()
        log.info('performance recorded trade_id=%s instrument=%s R=%s pnl=%s', trade_id, t.get('instrument_id'), realized_r, pnl)
        try:
            conn.close()
        except Exception:
            pass
        return new_id
    except Exception as e:
        log.error('performance error trade_id=%s err=%s', trade_id, str(e)[:160])
        try:
            conn.close()
        except Exception:
            pass
        return None


def get_performance(instrument_id=None):
    """Aggregate live performance. Returns dict with metrics."""
    conn = get_conn()
    try:
        if instrument_id:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM live_trade_performance WHERE instrument_id=? AND status="CLOSED"',
                (instrument_id,)).fetchall()]
        else:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM live_trade_performance WHERE status="CLOSED"').fetchall()]

        if not rows:
            return {
                'instrument': instrument_id or 'ALL',
                'total_trades': 0, 'wins': 0, 'losses': 0,
                'win_rate': None, 'total_r': 0, 'average_r': None,
                'profit_factor': None, 'max_drawdown_r': 0,
                'open_trades': 0, 'closed_trades': 0,
                'note': 'NO LIVE TRADES YET'
            }

        wins = sum(1 for r in rows if r.get('pnl', 0) > 0)
        losses = sum(1 for r in rows if r.get('pnl', 0) < 0)
        total_r = sum(r.get('realized_R', 0) for r in rows) or 0
        avg_r = total_r / len(rows) if rows else 0
        cum = 0
        max_dd = 0
        for r in sorted(rows, key=lambda x: x.get('exit_time', '')):
            cum += r.get('realized_R', 0) or 0
            if cum < max_dd:
                max_dd = cum
        gross_profit = sum(r.get('pnl', 0) for r in rows if r.get('pnl', 0) > 0) or 0
        gross_loss = abs(sum(r.get('pnl', 0) for r in rows if r.get('pnl', 0) < 0) or 0)
        pf = gross_profit / gross_loss if gross_loss > 0 else None
        open_t = 0
        if instrument_id:
            open_t = conn.execute(
                'SELECT COUNT(*) FROM paper_trades WHERE instrument_id=? AND status IN ("ACTIVE","OPEN")',
                (instrument_id,)).fetchone()[0]
        try:
            conn.close()
        except Exception:
            pass
        return {
            'instrument': instrument_id or 'ALL',
            'total_trades': len(rows),
            'wins': wins, 'losses': losses,
            'win_rate': wins / len(rows) if rows else 0,
            'total_r': round(total_r, 4),
            'average_r': round(avg_r, 4) if rows else 0,
            'profit_factor': round(pf, 4) if pf else None,
            'max_drawdown_r': round(max_dd, 4),
            'open_trades': open_t,
            'closed_trades': len(rows),
            'note': None
        }
    except Exception as e:
        log.error('performance get error instrument=%s err=%s', instrument_id, str(e)[:160])
        try:
            conn.close()
        except Exception:
            pass
        return None
