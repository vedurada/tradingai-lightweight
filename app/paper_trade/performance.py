"""Live paper-trade performance ledger for TradingAI.

Records completed paper trades exactly once when they close.
Monitoring calls do NOT create duplicate records.
"""
import logging, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')
log = logging.getLogger('tradingai.performance')


def record_performance(trade_id):
    """Record a closed paper trade in the performance ledger.

    Idempotent: if a record already exists for this trade_id,
    it is NOT updated and NOT duplicated. Returns the record id.
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
        realized_r = (t.get('exit_price', 0) or 0) - (t.get('entry', 0) or 0)
        pnl = realized_r
        conn.execute('''INSERT INTO live_trade_performance
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
        conn.commit()
        log.info('performance recorded trade_id=%s instrument=%s', trade_id, t.get('instrument_id'))
        conn.close()
        return conn.execute(
            'SELECT id FROM live_trade_performance WHERE trade_id=?',
            (trade_id,)).fetchone()['id']
    except Exception as e:
        log.error('performance error trade_id=%s err=%s', trade_id, str(e)[:160])
        conn.close()
        return None


def get_performance(instrument_id=None):
    """Aggregate live performance. Returns dict with metrics."""
    conn = get_conn()
    try:
        if instrument_id:
            rows = conn.execute(
                'SELECT * FROM live_trade_performance WHERE instrument_id=? AND status="CLOSED"',
                (instrument_id,)).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM live_trade_performance WHERE status="CLOSED"').fetchall()

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
        conn.close()
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
        conn.close()
        return None
