import yfinance as yf
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json

_IST = ZoneInfo('Asia/Kolkata')

class MarketDataProvider:
    def __init__(self):
        self.sources = {'yfinance': yf.Ticker}
        self.active_provider = 'yfinance'

    def get_quote(self, symbol):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period='2d', interval='5m')
            if hist.empty:
                return {'state': 'UNAVAILABLE', 'source': 'yfinance'}
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            now_ist = datetime.now(_IST)
            return {
                'symbol': symbol,
                'price': float(latest['Close']),
                'change': float(latest['Close'] - prev['Close']),
                'change_pct': float((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] else 0,
                'timestamp': now_ist.isoformat(),
                'source': 'yfinance',
                'state': 'LIVE' if (now_ist - latest.name.to_pydatetime() if hasattr(latest, 'name') else now_ist).total_seconds() < 3600 else 'STALE'
            }
        except Exception as e:
            return {'state': 'API_ERROR', 'source': 'yfinance', 'error': str(e)}

    def get_5m_candles(self, symbol, periods=100):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period='10d', interval='5m')
            if hist.empty: return {'state': 'UNAVAILABLE'}
            candles = []
            for idx, row in hist.tail(periods).iterrows():
                candles.append({
                    'timestamp': idx.isoformat(), 'open': float(row['Open']),
                    'high': float(row['High']), 'low': float(row['Low']),
                    'close': float(row['Close']), 'volume': int(row['Volume']),
                    'is_complete': True
                })
            return {'candles': candles, 'source': 'yfinance', 'state': 'LIVE'}
        except Exception as e:
            return {'state': 'API_ERROR', 'error': str(e)}
