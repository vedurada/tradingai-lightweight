"""Intrabar (real-time) entry + frozen-trade persistence.

- _select_entry: historical next-open vs live intrabar entry selection.
- _freeze_trade/_frozen_trade: one-trade-a-day freeze is idempotent and the
  served trade is stable across polls (what the alert exit-sweep relies on).
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import app.core.db as db
from app.live.engine import _select_entry, _freeze_trade, _frozen_trade

IST = ZoneInfo('Asia/Kolkata')


def _c(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': 10}


def test_select_entry_historical_next_open():
    feed = [_c('2026-09-16T09:15:00+05:30', 100, 101, 99, 100),
            _c('2026-09-16T09:20:00+05:30', 102, 103, 101, 102)]
    entry, nt, sig_ts = _select_entry(feed, None, 0, live_price=999.0, now=None)
    assert entry == 102.0
    assert nt == '2026-09-16T09:20:00+05:30'
    assert sig_ts == '2026-09-16T09:15:00+05:30'


def test_select_entry_intrabar_uses_live_price():
    feed = [_c('2026-09-16T09:15:00+05:30', 100, 101, 99, 100)]
    forming = _c('2026-09-16T09:20:00+05:30', 100, 102, 99, 101)
    now = datetime(2026, 9, 16, 9, 21, tzinfo=IST)
    entry, nt, sig_ts = _select_entry(feed, forming, 1, live_price=101.75, now=now)
    assert entry == 101.75
    assert nt == now.isoformat()
    assert sig_ts == forming['timestamp']


def test_select_entry_intrabar_falls_back_to_forming_close():
    feed = [_c('2026-09-16T09:15:00+05:30', 100, 101, 99, 100)]
    forming = _c('2026-09-16T09:20:00+05:30', 100, 102, 99, 100.5)
    now = datetime(2026, 9, 16, 9, 22, tzinfo=IST)
    entry, nt, sig_ts = _select_entry(feed, forming, 1, live_price=None, now=now)
    assert entry == 100.5
    assert sig_ts == forming['timestamp']


def test_select_entry_no_forming_is_pending():
    feed = [_c('2026-09-16T09:15:00+05:30', 100, 101, 99, 100)]
    assert _select_entry(feed, None, 0, live_price=100.0, now=None) is None


def _tmp_conn(monkeypatch, tmp_path):
    path = str(tmp_path / 't.db')

    def _new(*a, **k):
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    c0 = _new()
    c0.executescript(
        'CREATE TABLE daily_trade_locks (lock_id TEXT PRIMARY KEY, instrument_id TEXT,'
        ' date TEXT, status TEXT, trade_id TEXT, locked_at TEXT, consumed_at TEXT,'
        ' created_at TEXT, UNIQUE(instrument_id, date));'
        'CREATE TABLE qualified_trades (trade_id TEXT PRIMARY KEY, instrument_id TEXT,'
        ' date TEXT, timestamp TEXT, scenario TEXT, strategy TEXT, objective TEXT,'
        ' direction TEXT, entry REAL, stop REAL, target REAL, max_risk REAL,'
        ' expected_reward REAL, risk_reward REAL, qualification_evidence TEXT,'
        ' status TEXT, daily_lock_consumed INTEGER, created_at TEXT);')
    c0.commit()
    c0.close()
    monkeypatch.setattr(db, 'get_conn', _new)
    return path


def test_freeze_is_idempotent_and_stable(monkeypatch, tmp_path):
    _tmp_conn(monkeypatch, tmp_path)
    trade = {'entry': 23100.0, 'entry_time': '2026-09-16T09:21:00+05:30',
             'signal_time': '2026-09-16T09:15:00+05:30', 'stop': 23215.5,
             'target': 22638.0, 'max_risk': 0.5, 'expected_reward': 2.0,
             'strategy': 'Bear Call Spread', 'objective': 'DIRECTIONAL',
             'direction': 'BEAR', 'scenario': 'BELOW_CPR'}
    assert _freeze_trade('NIFTY', '2026-09-16', trade) is True
    assert _freeze_trade('NIFTY', '2026-09-16', trade) is False
    f = _frozen_trade('NIFTY', '2026-09-16')
    assert f is not None and f['entry'] == 23100.0 and f['frozen'] is True
    assert f['entry_time'] == '2026-09-16T09:21:00+05:30'
    assert f['signal_time'] == '2026-09-16T09:15:00+05:30'


def test_frozen_trade_absent_returns_none(monkeypatch, tmp_path):
    _tmp_conn(monkeypatch, tmp_path)
    assert _frozen_trade('NIFTY', '2026-09-16') is None
