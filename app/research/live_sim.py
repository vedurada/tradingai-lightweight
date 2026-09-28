"""Simulated live decision path (research-only, no broker, no live writes).

Feeds historical candles one at a time through the same decision pathway used
by live mode: the same QualificationEngine.qualify gate, the same daily lock
(keyed to the candle's trade_date, never wall-clock), and the same market
state construction as the batch backtest. The only deliberate difference from
live is research=True (no writes to qualified_trades / daily_trade_locks) and
as_of=candle timestamp, which is exactly what a live engine would know at that
moment (scenario state known at T, no future rows).

Phase 8 parity requirement: SimulatedLive decisions == SequentialReplay traces.
"""
from app.core.db import get_conn
from app.core.qualification import QualificationEngine

DECISION_SOURCE = 'simulated_live'


def build_market_state(candle):
    # FIXALL: no hardcoded BULLISH template; NEUTRAL-or-NO_DATA fail-closed.
    price = candle.get('close')
    if not isinstance(price, (int, float)) or not (price and price > 0):
        return {'trend': 'NO_DATA', 'price': price}
    return {'trend': 'NEUTRAL', 'vwap_relation': 'UNKNOWN', 'momentum': 'UNKNOWN',
            'volatility': 'UNKNOWN', 'price': price}


class SimulatedLive:
    def __init__(self):
        self.conn = get_conn()
        self.qualification = QualificationEngine()

    def run(self, instrument, date_start, date_end):
        """Return per-candle decisions in chronological order."""
        self.qualification.reset_research_locks()
        candles = [dict(c) for c in self.conn.execute(
            'SELECT * FROM market_candles_5m WHERE instrument_id=? AND timestamp BETWEEN ? AND ? AND is_complete=1 ORDER BY timestamp LIMIT 5000',
            (instrument, date_start, date_end)).fetchall()]
        out = []
        for c in candles:
            day = c['timestamp'][:10]
            lock_before = (instrument, day) in self.qualification.research_daily_locks
            # SPOT-R LIMITATION: no historical options chain; research forces
            # options_valid=True as spot-proxy. Live must compute via
            # app.options.engine.is_options_data_valid.
            d = self.qualification.qualify(
                instrument, build_market_state(c), options_valid=True,
                research=True, trade_date=day, as_of=c['timestamp'])
            out.append({
                'instrument': instrument, 'trade_date': day, 'timestamp': c['timestamp'],
                'price': c['close'], 'qualification': d['decision'],
                'reasons': list(d.get('reasons', [])),
                'lock_before': lock_before,
                'lock_after': (instrument, day) in self.qualification.research_daily_locks,
                'decision_source': DECISION_SOURCE})
        return {'decisions': out}
