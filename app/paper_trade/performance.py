"""Live paper-trade performance ledger for TradingAI.

R-DEFINITION MAP (canonical = app/research/backtest.py true multiple):
- CANONICAL R = signed move_pts / risk_pts (unit-consistent points/points).
- This module converts: R=(exit-entry)*dir/risk_pts, pnl=R*risk_rs-fees.
  Previously stored raw point difference as both realized_R and pnl.
- qualification risk_reward (reward_pct/risk_pct) equals canonical R for spot.
- options economics risk_reward (reward/risk) equals canonical R at max outcome.

AUTHORITATIVE SOURCE (2026-10-18): the live paper ledger is `paper_trades`,
written by the live watcher (scripts/tg_alerts.py --watch) via
PaperTradeEngine.create_paper_trade. Performance is computed directly from
`paper_trades` CLOSED rows and NEVER from the non-existent
`live_trade_performance` table (removed 2026-10-18). Rows that were not
written by the live watcher (qualification_evidence.origin != 'live-watch',
e.g. historical test fixtures) are EXCLUDED and reported as
`excluded_test_records` so they can never be counted as genuine trades.

Monitoring calls do NOT create duplicate records.
"""
import logging, sqlite3, json
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


def _is_live(evidence):
    """True when a paper_trades row was written by the live watcher.

    Kept identical to app.paper_trade.engine.LIVE_ORIGIN ('live-watch')."""
    try:
        ev = json.loads(evidence or '{}') or {}
    except (TypeError, ValueError):
        return False
    return ev.get('origin') == 'live-watch'


def _realized_r(row):
    """Canonical realised R from the recorded fill = signed_move_pts/risk_pts."""
    sign = _direction_sign(row.get('direction'))
    try:
        entry = float(row.get('entry'))
        stop = float(row.get('stop'))
        exit_px = float(row.get('exit_price'))
        move_pts = (exit_px - entry) * sign
        risk_pts = abs(entry - stop)
    except (TypeError, ValueError):
        return 0.0
    return round(move_pts / risk_pts, 4) if risk_pts > 0 else 0.0


def record_performance(trade_id):
    """Record a closed live paper trade once (idempotent).

    Derived from the authoritative `paper_trades` row:
    R = signed_move_pts / risk_pts; pnl = R * risk_rs - fees. The derived
    record is appended once to `paper_trade_events` under a deterministic
    event_id (so a repeat call is a no-op). Returns the stable event id, or
    None when the trade is unknown. NO dependency on live_trade_performance.
    """
    conn = get_conn()
    try:
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
        event_id = 'PERF-' + str(trade_id)
        existing = conn.execute(
            'SELECT event_id FROM paper_trade_events WHERE event_id=?',
            (event_id,)).fetchone()
        if existing:
            log.info('performance trade_id=%s already recorded', trade_id)
            return event_id
        cur = conn.execute('''INSERT INTO paper_trade_events
            (event_id, trade_id, timestamp, event_type, price, evidence, created_at)
            VALUES (?,?,?,?,?,?,?)''',
            (event_id, t['trade_id'], datetime.now(_IST).isoformat(),
             'PERFORMANCE_RECORDED', exit_px,
             json.dumps({'realized_R': realized_r, 'pnl': pnl,
                         'instrument': t.get('instrument_id'),
                         'direction': direction}),
             datetime.now(_IST).isoformat()))
        # Fetch lastrowid BEFORE close (fixes use-after-close).
        new_id = cur.lastrowid
        conn.commit()
        log.info('performance recorded trade_id=%s instrument=%s R=%s pnl=%s',
                 trade_id, t.get('instrument_id'), realized_r, pnl)
        return event_id
    except Exception as e:
        log.error('performance error trade_id=%s err=%s', trade_id, str(e)[:160])
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_performance(instrument_id=None, start=None, end=None):
    """Aggregate LIVE paper-trade performance from `paper_trades`.

    Authoritative source: CLOSED `paper_trades` rows written by the live
    watcher (qualification_evidence.origin == 'live-watch'). Historical test
    fixtures / unmarked rows are EXCLUDED and reported as `excluded_test_records`.

    Definitions (see module docstring):
      realized_R  = (exit-entry)*dir / |entry-stop|        (canonical points/points)
      pnl         = stored paper_pnl (rupees, net of brokerage+slippage*lot)
      win/loss    = pnl > 0 / pnl < 0
      win_rate    = wins / closed
      total_r     = sum(realized_R);  average_r = total_r / closed
      profit_factor = gross_profit / gross_loss (None when no losses)
      max_drawdown_r = min cumulative realized_R over exit_time order

    Always returns a dict (explicit empty result when nothing is eligible).
    Raises RuntimeError on a database error — never silently returns None.
    """
    conn = None
    try:
        conn = get_conn()
        closed = [dict(r) for r in conn.execute(
            'SELECT * FROM paper_trades WHERE status="CLOSED"').fetchall()]
        opens = [dict(r) for r in conn.execute(
            'SELECT trade_id, instrument_id, qualification_evidence FROM paper_trades '
            'WHERE status IN ("ACTIVE", "OPEN")').fetchall()]
    except Exception as e:
        raise RuntimeError('performance query failed: %s' % str(e)[:160])
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    inst = (instrument_id or '').upper() or None

    def _keep(r):
        if not _is_live(r.get('qualification_evidence')):
            return False
        if inst and (r.get('instrument_id') or '').upper() != inst:
            return False
        d = (r.get('entry_time') or '')[:10]
        if start and d and d < start:
            return False
        if end and d and d > end:
            return False
        return True

    all_closed = closed
    rows = [r for r in all_closed if _keep(r)]
    excluded = len(all_closed) - len([r for r in all_closed
                                      if _is_live(r.get('qualification_evidence'))])
    open_n = sum(1 for r in opens if _is_live(r.get('qualification_evidence'))
                 and (not inst or (r.get('instrument_id') or '').upper() == inst))

    if not rows:
        return {
            'instrument': instrument_id or 'ALL',
            'total_trades': 0, 'wins': 0, 'losses': 0,
            'win_rate': None, 'total_r': 0, 'average_r': None,
            'profit_factor': None, 'max_drawdown_r': 0,
            'open_trades': open_n, 'closed_trades': 0,
            'excluded_test_records': excluded,
            'definitions': 'realized_R=(exit-entry)*dir/|entry-stop|; '
                           'pnl=paper_pnl (net of fees); win=pnl>0',
            'note': 'NO LIVE PAPER TRADES YET'
        }

    wins = sum(1 for r in rows if (r.get('paper_pnl') or 0) > 0)
    losses = sum(1 for r in rows if (r.get('paper_pnl') or 0) < 0)
    rs = [_realized_r(r) for r in rows]
    total_r = sum(rs)
    avg_r = total_r / len(rows) if rows else 0
    cum = 0
    max_dd = 0
    for r in sorted(rows, key=lambda x: x.get('exit_time') or ''):
        cum += _realized_r(r)
        if cum < max_dd:
            max_dd = cum
    gross_profit = sum((r.get('paper_pnl') or 0) for r in rows if (r.get('paper_pnl') or 0) > 0)
    gross_loss = abs(sum((r.get('paper_pnl') or 0) for r in rows if (r.get('paper_pnl') or 0) < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else None
    return {
        'instrument': instrument_id or 'ALL',
        'total_trades': len(rows),
        'wins': wins, 'losses': losses,
        'win_rate': wins / len(rows) if rows else 0,
        'total_r': round(total_r, 4),
        'average_r': round(avg_r, 4) if rows else 0,
        'profit_factor': round(pf, 4) if pf else None,
        'max_drawdown_r': round(max_dd, 4),
        'open_trades': open_n,
        'closed_trades': len(rows),
        'excluded_test_records': excluded,
        'definitions': 'realized_R=(exit-entry)*dir/|entry-stop|; '
                       'pnl=paper_pnl (net of fees); win=pnl>0',
        'note': None
    }
