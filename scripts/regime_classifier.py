#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')

class RegimeClassifier:
    """Point-in-time market regime classification.
    
    Uses only data available at classification time.
    Regime is determined at session close using prior sessions.
    
    Categories:
    - UPTREND: Price > MA20 AND momentum positive AND volatility normal
    - DOWNTREND: Price < MA20 AND momentum negative AND volatility normal
    - RANGE: Price near MA20 AND volatility normal AND momentum weak
    - HIGH_VOLATILITY: ATR above threshold
    - LOW_VOLATILITY: ATR below threshold
    """
    
    def __init__(self, conn):
        self.conn = conn
    
    def classify_session(self, instrument_id, session_date):
        """Classify a session using only data available at session close."""
        # Get last 20 sessions before this date
        sessions = self.conn.execute(
            "SELECT DISTINCT substr(timestamp,1,10) as d FROM market_candles_5m "
            "WHERE instrument_id=? AND substr(timestamp,1,10) <= ? ORDER BY d DESC LIMIT 20",
            (instrument_id, session_date)
        ).fetchall()
        
        dates = [s[0] for s in sessions]
        if len(dates) < 5:
            return 'INSUFFICIENT_DATA'
        
        # Get daily close for each session
        closes = []
        for d in dates:
            c = self.conn.execute(
                "SELECT close FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1",
                (instrument_id, d)
            ).fetchone()
            if c:
                closes.append(c[0])
        
        if len(closes) < 5:
            return 'INSUFFICIENT_DATA'
        
        # MA20 (using available data)
        ma20 = sum(closes[:min(20, len(closes))]) / min(20, len(closes))
        current_close = closes[0]
        
        # Momentum: current close vs MA20
        momentum = (current_close - ma20) / ma20 * 100 if ma20 else 0
        
        # Volatility: range of last 5 sessions
        ranges = []
        for d in dates[:5]:
            hi = self.conn.execute(
                "SELECT MAX(high) FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=?",
                (instrument_id, d)
            ).fetchone()[0] or 0
            lo = self.conn.execute(
                "SELECT MIN(low) FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)=?",
                (instrument_id, d)
            ).fetchone()[0] or 0
            ranges.append(hi - lo)
        
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        
        # Classify
        if avg_range > 150:
            return 'HIGH_VOLATILITY'
        elif avg_range < 50:
            return 'LOW_VOLATILITY'
        elif momentum > 0.3:
            return 'UPTREND'
        elif momentum < -0.3:
            return 'DOWNTREND'
        else:
            return 'RANGE'
    
    def get_all_regimes(self, instrument_id):
        """Get regime for each session."""
        sessions = self.conn.execute(
            "SELECT DISTINCT substr(timestamp,1,10) as d FROM market_candles_5m WHERE instrument_id=? ORDER BY d",
            (instrument_id,)
        ).fetchall()
        
        results = {}
        for s in sessions:
            regime = self.classify_session(instrument_id, s[0])
            results[s[0]] = regime
        return results


if __name__ == '__main__':
    conn = get_conn()
    classifier = RegimeClassifier(conn)
    
    print("=" * 60)
    print("MARKET REGIME CLASSIFICATION")
    print("=" * 60)
    
    for inst in ['NIFTY', 'BANKNIFTY']:
        print(f"\n{inst}:")
        regimes = classifier.get_all_regimes(inst)
        counts = {}
        for d, r in regimes.items():
            counts[r] = counts.get(r, 0) + 1
        for r, c in sorted(counts.items()):
            print(f"  {r}: {c} sessions")
        
        # Regime by date
        print(f"  Dates:")
        for d, r in sorted(regimes.items()):
            print(f"    {d}: {r}")
    
    conn.close()
