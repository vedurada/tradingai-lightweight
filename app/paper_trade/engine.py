import uuid, json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

class PaperTradeEngine:
    def __init__(self):
        self.conn = get_conn()

    def create_paper_trade(self, qualified_trade):
        trade_id = f'PT-{str(uuid.uuid4())[:8].upper()}'
        self.conn.execute('''INSERT INTO paper_trades (trade_id, instrument_id, scenario, strategy, objective, direction, legs, strikes, expiry, entry, stop, target, max_risk, expected_reward, entry_time, status, qualification_evidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (trade_id, qualified_trade.get('instrument_id'), qualified_trade.get('scenario'), qualified_trade.get('strategy'), qualified_trade.get('objective'), qualified_trade.get('direction'), None, None, None, qualified_trade.get('entry'), qualified_trade.get('stop'), qualified_trade.get('target'), qualified_trade.get('max_risk'), qualified_trade.get('expected_reward'), datetime.now(_IST).isoformat(), 'ACTIVE', json.dumps(qualified_trade), datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
        self.conn.commit()
        return trade_id

    def monitor(self, instrument_id):
        trades = self.conn.execute('SELECT * FROM paper_trades WHERE instrument_id=? AND status IN ("ACTIVE", "OPEN")', (instrument_id,)).fetchall()
        results = []
        for t in trades:
            t = dict(t)
            current = self.conn.execute('SELECT price FROM market_snapshots WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1', (instrument_id,)).fetchone()
            if not current: continue
            current_price = current['price']
            if current_price <= t['stop']:
                self._exit_trade(t['trade_id'], t['stop'], 'STOP', current_price)
            elif current_price >= t['target']:
                self._exit_trade(t['trade_id'], t['target'], 'TARGET', current_price)
            results.append({**t, 'current_price': current_price})
        return results

    def _exit_trade(self, trade_id, exit_price, reason, price):
        self.conn.execute('UPDATE paper_trades SET exit_price=?, exit_reason=?, exit_time=?, status=?, paper_pnl=?, updated_at=? WHERE trade_id=?',
            (exit_price, reason, datetime.now(_IST).isoformat(), 'CLOSED', round((exit_price - price) * 50, 2), datetime.now(_IST).isoformat(), trade_id))
        self.conn.commit()
